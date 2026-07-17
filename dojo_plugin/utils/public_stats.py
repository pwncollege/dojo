import uuid
from contextlib import contextmanager

from flask import g, has_request_context
import redis
from sqlalchemy.dialects.postgresql import insert

from CTFd.models import db, Solves

from ..models import (
    Dojos,
    DojoChallenges,
    PublicStatsCacheVersions,
    PublicStatsVisibilityGuard,
    UserVisibilityUpdates,
    UserVisibilityVersions,
)


SCOREBOARD_DURATIONS = (0, 7, 30)


def affected_public_cache_keys(connection, user_id):
    rows = connection.execute(
        db.select(
            [
                DojoChallenges.dojo_id,
                DojoChallenges.module_index,
                Dojos.id,
                Dojos.official,
                Dojos.data["type"].astext,
            ]
        )
        .select_from(
            DojoChallenges.__table__
            .join(
                Solves.__table__,
                Solves.challenge_id == DojoChallenges.challenge_id,
            )
            .join(Dojos.__table__, Dojos.dojo_id == DojoChallenges.dojo_id)
        )
        .where(
            Solves.user_id == user_id,
            Solves.type == Solves.__mapper__.polymorphic_identity,
        )
        .distinct()
    ).all()

    keys = {"stats:belts", "stats:emojis"}
    dojo_rows = {}
    for dojo_id, module_index, dojo_name, official, dojo_type in rows:
        dojo_rows.setdefault(
            dojo_id,
            {
                "reference_id": (
                    dojo_name
                    if official
                    else f"{dojo_name}~{dojo_id & 0xFFFFFFFF:08x}"
                ),
                "is_public": official or dojo_type == "public",
                "module_indices": set(),
            },
        )["module_indices"].add(module_index)

    for dojo_id, dojo_data in dojo_rows.items():
        keys.add(f"stats:dojo:{dojo_data['reference_id']}")
        if dojo_data["is_public"]:
            keys.add(f"stats:scores:dojo:{dojo_id}")
        for duration in SCOREBOARD_DURATIONS:
            keys.add(f"stats:scoreboard:dojo:{dojo_id}:{duration}")
            keys.add(f"stats:crews:dojo:{dojo_id}:{duration}")
        for module_index in dojo_data["module_indices"]:
            if dojo_data["is_public"]:
                keys.add(f"stats:scores:module:{dojo_id}:{module_index}")
            keys.add(f"stats:challenge_solves:module:{dojo_id}:{module_index}")
            for duration in SCOREBOARD_DURATIONS:
                keys.add(
                    f"stats:scoreboard:module:{dojo_id}:{module_index}:{duration}"
                )
                keys.add(f"stats:crews:module:{dojo_id}:{module_index}:{duration}")

    return keys


def mark_user_visibility_transition(connection, user_id):
    release_public_stats_visibility()
    if has_request_context():
        g.public_stats_visibility_transition = True
    guard_table = PublicStatsVisibilityGuard.__table__
    connection.execute(
        insert(guard_table)
        .values(id=1)
        .on_conflict_do_nothing(index_elements=[guard_table.c.id])
    )
    connection.execute(
        db.select([guard_table.c.id])
        .where(guard_table.c.id == 1)
        .with_for_update()
    ).scalar()

    cache_keys = sorted(affected_public_cache_keys(connection, user_id))
    versions_table = PublicStatsCacheVersions.__table__
    for start in range(0, len(cache_keys), 1000):
        chunk = cache_keys[start:start + 1000]
        statement = insert(versions_table).values(
            [
                {"cache_key": key, "revision": 1, "ready_revision": 0}
                for key in chunk
            ]
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[versions_table.c.cache_key],
                set_={"revision": versions_table.c.revision + 1},
            )
        )

    updates_table = UserVisibilityUpdates.__table__
    visibility_versions = UserVisibilityVersions.__table__
    connection.execute(
        insert(visibility_versions)
        .values(user_id=user_id, revision=1)
        .on_conflict_do_update(
            index_elements=[visibility_versions.c.user_id],
            set_={"revision": visibility_versions.c.revision + 1},
        )
    )
    token = uuid.uuid4().hex
    connection.execute(
        insert(updates_table)
        .values(user_id=user_id, token=token, published_at=None)
        .on_conflict_do_update(
            index_elements=[updates_table.c.user_id],
            set_={"token": token, "published_at": None},
        )
    )


def initialize_public_stats_state():
    table = PublicStatsVisibilityGuard.__table__
    db.session.execute(
        insert(table)
        .values(id=1)
        .on_conflict_do_nothing(index_elements=[table.c.id])
    )
    db.session.commit()


def lock_public_stats_visibility(*, persistent=False):
    visibility_lock = (
        getattr(g, "public_stats_visibility_lock", None)
        if has_request_context()
        else None
    )
    if (
        not has_request_context()
        or getattr(g, "public_stats_visibility_transition", False)
        or (
            visibility_lock is not None
            and not (persistent and visibility_lock == "session")
        )
    ):
        return
    if not persistent:
        PublicStatsVisibilityGuard.query.filter_by(id=1).with_for_update(
            read=True
        ).one()
        g.public_stats_visibility_lock = "session"
        return
    connection = db.engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            db.select([PublicStatsVisibilityGuard.__table__.c.id])
            .where(PublicStatsVisibilityGuard.__table__.c.id == 1)
            .with_for_update(read=True)
        ).scalar()
        g.public_stats_visibility_lock = (connection, transaction)
    except Exception:
        transaction.rollback()
        connection.close()
        raise


def release_public_stats_visibility():
    if not has_request_context():
        return
    visibility_lock = getattr(g, "public_stats_visibility_lock", None)
    if visibility_lock is None:
        return
    g.public_stats_visibility_lock = None
    if visibility_lock == "session":
        return
    connection, transaction = visibility_lock
    try:
        transaction.rollback()
    finally:
        connection.close()


def public_cache_revision(cache_key):
    row = PublicStatsCacheVersions.query.with_entities(
        PublicStatsCacheVersions.revision,
        PublicStatsCacheVersions.ready_revision,
    ).filter_by(cache_key=cache_key).first()
    if row is None or row.revision != row.ready_revision:
        return None
    return row.revision


def capture_public_cache_revisions(cache_keys):
    cache_keys = sorted(set(cache_keys))
    if not cache_keys:
        return {}

    table = PublicStatsCacheVersions.__table__
    for start in range(0, len(cache_keys), 1000):
        chunk = cache_keys[start:start + 1000]
        db.session.execute(
            insert(table)
            .values(
                [
                    {"cache_key": key, "revision": 0, "ready_revision": 0}
                    for key in chunk
                ]
            )
            .on_conflict_do_nothing(index_elements=[table.c.cache_key])
        )
    db.session.commit()
    revisions = {}
    for start in range(0, len(cache_keys), 1000):
        chunk = cache_keys[start:start + 1000]
        revisions.update(
            {
                cache_key: revision
                for cache_key, revision in PublicStatsCacheVersions.query.filter(
                    PublicStatsCacheVersions.cache_key.in_(chunk)
                ).with_entities(
                    PublicStatsCacheVersions.cache_key,
                    PublicStatsCacheVersions.revision,
                )
            }
        )
    return revisions


@contextmanager
def public_stats_visibility_read():
    guard = PublicStatsVisibilityGuard.__table__
    with db.engine.begin() as connection:
        connection.execute(
            db.select([guard.c.id])
            .where(guard.c.id == 1)
            .with_for_update(read=True)
        ).scalar()
        yield


@contextmanager
def public_stats_visibility_update():
    guard = PublicStatsVisibilityGuard.__table__
    with db.engine.begin() as connection:
        connection.execute(
            db.select([guard.c.id])
            .where(guard.c.id == 1)
            .with_for_update()
        ).scalar()
        yield connection


def complete_user_visibility_transition(
    connection,
    user_id,
    token,
    revisions,
):
    from .background_stats import get_redis_client

    versions = PublicStatsCacheVersions.__table__
    updates = UserVisibilityUpdates.__table__
    revisions = dict(revisions)
    cache_keys = list(revisions)

    try:
        transition = connection.execute(
            db.select([updates.c.user_id])
            .where(
                updates.c.user_id == user_id,
                updates.c.token == token,
                updates.c.published_at.isnot(None),
            )
            .with_for_update()
        ).scalar()
        if transition is None:
            return False

        for start in range(0, len(cache_keys), 1000):
            chunk = cache_keys[start:start + 1000]
            current = dict(
                connection.execute(
                    db.select([versions.c.cache_key, versions.c.revision])
                    .where(versions.c.cache_key.in_(chunk))
                ).all()
            )
            if any(current.get(key) != revisions[key] for key in chunk):
                return False

        redis_client = get_redis_client()
        for start in range(0, len(cache_keys), 500):
            chunk = cache_keys[start:start + 500]
            pipeline = redis_client.pipeline()
            for key in chunk:
                pipeline.get(key)
                pipeline.get(f"{key}:visibility")
            values = pipeline.execute()
            for index, key in enumerate(chunk):
                data = values[index * 2]
                cached_revision = values[index * 2 + 1]
                if (
                    data is None
                    or cached_revision is None
                    or int(cached_revision) != revisions[key]
                ):
                    return False

        keys_by_revision = {}
        for key, revision in revisions.items():
            keys_by_revision.setdefault(revision, []).append(key)
        for revision, revision_keys in keys_by_revision.items():
            for start in range(0, len(revision_keys), 1000):
                chunk = revision_keys[start:start + 1000]
                result = connection.execute(
                    versions.update()
                    .where(
                        versions.c.cache_key.in_(chunk),
                        versions.c.revision == revision,
                    )
                    .values(ready_revision=revision)
                )
                if result.rowcount != len(chunk):
                    raise RuntimeError("Public cache generation changed")

        result = connection.execute(
            updates.delete().where(
                updates.c.user_id == user_id,
                updates.c.token == token,
            )
        )
        if result.rowcount != 1:
            raise RuntimeError("User visibility transition changed")
        return True
    except (
        redis.RedisError,
        redis.ConnectionError,
        TypeError,
        ValueError,
    ):
        return False


def retry_user_visibility_transition(user_id, token):
    UserVisibilityUpdates.query.filter_by(user_id=user_id, token=token).update(
        {UserVisibilityUpdates.published_at: None},
        synchronize_session=False,
    )
    db.session.commit()
