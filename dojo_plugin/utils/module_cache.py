import contextlib
import datetime
import logging
import threading
import time
from dataclasses import dataclass

import redis
from sqlalchemy import and_, or_, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from CTFd.models import db

from ..models import (
    DOJO_CACHE_REFRESH_GENERATION,
    DOJO_MODULE_CACHE_INVALIDATION_GENERATION,
    DojoCacheMigrations,
    DojoCacheRefreshes,
    DojoModuleCacheInvalidations,
    DojoModules,
    Dojos,
)
from .background_stats import get_cached_stat, get_redis_client, publish_stat_event


logger = logging.getLogger(__name__)

SCOREBOARD_DURATIONS = (0, 7, 30)
INVALIDATION_BATCH_SIZE = 500
INVALIDATION_MAX_BATCHES = 4
CACHE_REFRESH_BATCH_SIZE = 100
CACHE_REFRESH_RETRY_SECONDS = 30
CACHE_MAINTENANCE_ADVISORY_LOCK = 0x646F6A6F1097
LEGACY_MODULE_CACHE_MIGRATION = "legacy-module-cache-keys-v1"

_maintenance_lock_state = threading.local()


@dataclass(frozen=True)
class ModuleCacheTarget:
    dojo_id: int
    module_id: str
    cache_identity: str


@dataclass(frozen=True)
class CacheRefreshTarget:
    kind: str
    dojo_id: int
    module_id: str
    cache_identity: str
    generation: int


@contextlib.contextmanager
def module_cache_maintenance_lock(blocking=False):
    depth = getattr(_maintenance_lock_state, "depth", 0)
    if depth:
        _maintenance_lock_state.depth = depth + 1
        try:
            yield True
        finally:
            _maintenance_lock_state.depth -= 1
        return

    connection = db.engine.connect()
    transaction = None
    acquired = False
    try:
        transaction = connection.begin()
        lock_function = (
            db.func.pg_advisory_xact_lock
            if blocking
            else db.func.pg_try_advisory_xact_lock
        )
        result = connection.execute(db.select([
            lock_function(CACHE_MAINTENANCE_ADVISORY_LOCK)
        ])).scalar()
        acquired = True if blocking else bool(result)
        if acquired:
            _maintenance_lock_state.depth = 1
        yield acquired
    finally:
        if acquired:
            _maintenance_lock_state.depth = 0
        if transaction is not None:
            try:
                transaction.rollback()
            except SQLAlchemyError as error:
                logger.warning(
                    "Failed to roll back module cache maintenance lock: %s",
                    error,
                )
        connection.close()


def module_cache_target(module):
    return ModuleCacheTarget(module.dojo_id, module.id, module.cache_identity)


def lock_dojo_cache_target(dojo_id):
    return (
        Dojos.query
        .filter_by(dojo_id=dojo_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )


def module_cache_content_signature(module):
    def normalize_datetime(value):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return value

    challenges = []
    for challenge in module.challenges:
        challenge_id = challenge.challenge_id
        if challenge_id is None and challenge.challenge is not None:
            challenge_id = challenge.challenge.id
        visibility = challenge.visibility
        challenges.append((
            challenge.id,
            challenge.name,
            challenge_id,
            challenge.required if challenge.required is not None else True,
            normalize_datetime(visibility.start) if visibility else None,
            normalize_datetime(visibility.stop) if visibility else None,
        ))
    return tuple(challenges)


def lock_module_cache_target(target):
    module = (
        DojoModules.query
        .filter_by(dojo_id=target.dojo_id, id=target.module_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if module is None or module.cache_identity != target.cache_identity:
        return None
    return module


def module_scoreboard_cache_key(module, duration, kind="scoreboard"):
    return f"stats:{kind}:module:{module.dojo_id}:{module.cache_identity}:{duration}"


def module_challenge_solves_cache_key(module):
    return f"stats:challenge_solves:module:{module.dojo_id}:{module.cache_identity}"


def module_scores_cache_key(module):
    return f"stats:scores:module:{module.dojo_id}:{module.cache_identity}"


def dojo_scoreboard_cache_key(dojo_id, duration, kind="scoreboard"):
    return f"stats:{kind}:dojo:{dojo_id}:{duration}"


def dojo_stats_cache_key(dojo):
    return f"stats:dojo:{dojo.reference_id}"


def dojo_scores_cache_key(dojo_id):
    return f"stats:scores:dojo:{dojo_id}"


def dojo_aggregate_cache_keys(dojo):
    keys = {
        dojo_stats_cache_key(dojo),
        dojo_scores_cache_key(dojo.dojo_id),
    }
    for duration in SCOREBOARD_DURATIONS:
        keys.add(dojo_scoreboard_cache_key(dojo.dojo_id, duration))
        keys.add(dojo_scoreboard_cache_key(
            dojo.dojo_id,
            duration,
            "crews",
        ))
    return keys | {
        metadata_key
        for key in keys
        for metadata_key in (f"{key}:updated", f"{key}:version")
    }


def module_identity_cache_keys(dojo_id, cache_identity):
    target = ModuleCacheTarget(dojo_id, "", cache_identity)
    keys = {
        module_challenge_solves_cache_key(target),
        module_scores_cache_key(target),
    }
    for duration in SCOREBOARD_DURATIONS:
        keys.add(module_scoreboard_cache_key(target, duration))
        keys.add(module_scoreboard_cache_key(target, duration, "crews"))
    return keys | {
        metadata_key
        for key in keys
        for metadata_key in (f"{key}:updated", f"{key}:version")
    }


def legacy_module_cache_keys(dojo_id, module_index):
    keys = {
        f"stats:challenge_solves:module:{dojo_id}:{module_index}",
        f"stats:scores:module:{dojo_id}:{module_index}",
    }
    for duration in SCOREBOARD_DURATIONS:
        keys.add(f"stats:scoreboard:module:{dojo_id}:{module_index}:{duration}")
        keys.add(f"stats:crews:module:{dojo_id}:{module_index}:{duration}")
    return keys | {
        metadata_key
        for key in keys
        for metadata_key in (f"{key}:updated", f"{key}:version")
    }


def queue_dojo_stats_reference_retirement(reference_id):
    cache_key = f"stats:dojo:{reference_id}"
    cache_keys = {
        cache_key,
        f"{cache_key}:updated",
        f"{cache_key}:version",
    }
    queue_module_cache_invalidations(cache_keys)
    return cache_keys


def queue_dojo_module_cache_retirement(dojo):
    cache_keys = dojo_aggregate_cache_keys(dojo)
    for module in dojo.modules:
        cache_keys.update(
            module_identity_cache_keys(dojo.dojo_id, module.cache_identity)
        )
        cache_keys.update(
            legacy_module_cache_keys(dojo.dojo_id, module.module_index)
        )
    retire_dojo_cache_refreshes(dojo.dojo_id)
    queue_module_cache_invalidations(cache_keys)
    return cache_keys


def retire_dojo_cache_refreshes(dojo_id):
    table = DojoCacheRefreshes.__table__
    db.session.execute(table.delete().where(table.c.dojo_id == dojo_id))


def retire_module_cache_refreshes(module_targets):
    table = DojoCacheRefreshes.__table__
    refresh_keys = sorted({
        (target.dojo_id, target.module_id, target.cache_identity)
        for target in module_targets
    })
    for start in range(0, len(refresh_keys), CACHE_REFRESH_BATCH_SIZE):
        db.session.execute(table.delete().where(and_(
            table.c.kind == "module",
            tuple_(
                table.c.dojo_id,
                table.c.module_id,
                table.c.cache_identity,
            ).in_(refresh_keys[start:start + CACHE_REFRESH_BATCH_SIZE]),
        )))


def retire_stale_module_cache_refreshes(module_targets):
    table = DojoCacheRefreshes.__table__
    refresh_keys = sorted({
        (target.dojo_id, target.module_id, target.cache_identity)
        for target in module_targets
    })
    for start in range(0, len(refresh_keys), CACHE_REFRESH_BATCH_SIZE):
        batch = refresh_keys[start:start + CACHE_REFRESH_BATCH_SIZE]
        module_keys = [(dojo_id, module_id) for dojo_id, module_id, _ in batch]
        db.session.execute(table.delete().where(and_(
            table.c.kind == "module",
            tuple_(table.c.dojo_id, table.c.module_id).in_(module_keys),
            tuple_(
                table.c.dojo_id,
                table.c.module_id,
                table.c.cache_identity,
            ).notin_(batch),
        )))


def queue_module_cache_invalidations(cache_keys):
    table = DojoModuleCacheInvalidations.__table__
    keys = sorted(set(cache_keys))
    if not keys:
        return
    for start in range(0, len(keys), INVALIDATION_BATCH_SIZE):
        next_generation = DOJO_MODULE_CACHE_INVALIDATION_GENERATION.next_value()
        values = [
            {"cache_key": cache_key, "generation": next_generation}
            for cache_key in keys[start:start + INVALIDATION_BATCH_SIZE]
        ]
        statement = insert(table).values(values)
        db.session.execute(statement.on_conflict_do_update(
            index_elements=[table.c.cache_key],
            set_={"generation": statement.excluded.generation},
        ))


def queue_cache_refreshes(module_targets=(), dojo_ids=()):
    module_targets = tuple(module_targets)
    dojo_ids = set(dojo_ids)
    refreshes = {
        ("module", target.dojo_id, target.module_id, target.cache_identity)
        for target in module_targets
    }
    refreshes.update(
        ("dojo", dojo_id, "", "")
        for dojo_id in dojo_ids
    )
    if not refreshes:
        return

    retire_stale_module_cache_refreshes(module_targets)

    queue_module_cache_invalidations(set().union(*(
        module_identity_cache_keys(target.dojo_id, target.cache_identity)
        for target in module_targets
    )) if module_targets else set())

    if dojo_ids:
        dojos = Dojos.query.filter(Dojos.dojo_id.in_(dojo_ids)).all()
        queue_module_cache_invalidations(set().union(*(
            dojo_aggregate_cache_keys(dojo) for dojo in dojos
        )) if dojos else set())

    table = DojoCacheRefreshes.__table__
    refreshes = sorted(refreshes)
    for start in range(0, len(refreshes), CACHE_REFRESH_BATCH_SIZE):
        next_generation = DOJO_CACHE_REFRESH_GENERATION.next_value()
        values = [
            {
                "kind": kind,
                "dojo_id": dojo_id,
                "module_id": module_id,
                "cache_identity": cache_identity,
                "generation": next_generation,
                "published_at": None,
            }
            for kind, dojo_id, module_id, cache_identity
            in refreshes[start:start + CACHE_REFRESH_BATCH_SIZE]
        ]
        statement = insert(table).values(values)
        db.session.execute(statement.on_conflict_do_update(
            index_elements=[
                table.c.kind,
                table.c.dojo_id,
                table.c.module_id,
                table.c.cache_identity,
            ],
            set_={
                "generation": statement.excluded.generation,
                "published_at": None,
            },
        ))


def pending_cache_refreshes(
    limit=CACHE_REFRESH_BATCH_SIZE,
    retry_seconds=CACHE_REFRESH_RETRY_SECONDS,
    refresh_keys=None,
):
    table = DojoCacheRefreshes.__table__
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(
        seconds=retry_seconds
    )
    statement = db.select([
        table.c.kind,
        table.c.dojo_id,
        table.c.module_id,
        table.c.cache_identity,
        table.c.generation,
    ]).where(or_(
        table.c.published_at.is_(None),
        table.c.published_at <= cutoff,
    ))
    if refresh_keys is not None:
        keys = sorted(set(refresh_keys))
        if not keys:
            return []
        statement = statement.where(tuple_(
            table.c.kind,
            table.c.dojo_id,
            table.c.module_id,
            table.c.cache_identity,
        ).in_(keys))
    statement = statement.order_by(
        table.c.kind,
        table.c.dojo_id,
        table.c.module_id,
        table.c.cache_identity,
    ).limit(limit)
    with db.engine.connect() as connection:
        rows = connection.execute(statement).fetchall()
    return [
        CacheRefreshTarget(
            row.kind,
            row.dojo_id,
            row.module_id,
            row.cache_identity,
            row.generation,
        )
        for row in rows
    ]


def publish_pending_cache_refreshes(
    limit=CACHE_REFRESH_BATCH_SIZE,
    retry_seconds=CACHE_REFRESH_RETRY_SECONDS,
    refresh_keys=None,
):
    try:
        pending = pending_cache_refreshes(limit, retry_seconds, refresh_keys)
    except SQLAlchemyError as error:
        logger.warning("Failed to load pending cache refreshes: %s", error)
        return False

    all_published = True
    table = DojoCacheRefreshes.__table__
    for refresh in pending:
        payload = {
            "dojo_id": refresh.dojo_id,
            "generation": refresh.generation,
        }
        if refresh.kind == "module":
            payload.update({
                "module_id": refresh.module_id,
                "cache_identity": refresh.cache_identity,
            })
        try:
            message_id = publish_stat_event(
                f"{refresh.kind}_cache_refresh",
                payload,
            )
        except Exception as error:
            logger.warning(
                "Failed to publish %s cache refresh for dojo %s: %s",
                refresh.kind,
                refresh.dojo_id,
                error,
            )
            message_id = None
        if message_id is None:
            all_published = False
            continue

        try:
            with db.engine.begin() as connection:
                result = connection.execute(table.update().where(and_(
                    table.c.kind == refresh.kind,
                    table.c.dojo_id == refresh.dojo_id,
                    table.c.module_id == refresh.module_id,
                    table.c.cache_identity == refresh.cache_identity,
                    table.c.generation == refresh.generation,
                )).values(published_at=datetime.datetime.utcnow()))
        except SQLAlchemyError as error:
            logger.warning(
                "Failed to lease %s cache refresh for dojo %s: %s",
                refresh.kind,
                refresh.dojo_id,
                error,
            )
            all_published = False
            continue
        if result.rowcount != 1:
            all_published = False
    return all_published


def invalidate_module_cache_keys(cache_keys):
    keys = sorted(set(cache_keys))
    if not keys:
        return True
    last_error = None
    final_sweep_succeeded = False
    for attempt in range(3):
        try:
            client = get_redis_client()
            for start in range(0, len(keys), INVALIDATION_BATCH_SIZE):
                client.delete(*keys[start:start + INVALIDATION_BATCH_SIZE])
            final_sweep_succeeded = True
            last_error = None
        except (redis.RedisError, redis.ConnectionError, RuntimeError) as error:
            final_sweep_succeeded = False
            last_error = error
        if attempt < 2:
            time.sleep(0.05)
    if not final_sweep_succeeded:
        logger.warning("Failed to invalidate module caches: %s", last_error)
    return final_sweep_succeeded


def dojo_cache_refresh_pending(dojo_id):
    table = DojoCacheRefreshes.__table__
    statement = db.select([table.c.dojo_id]).where(and_(
        table.c.kind == "dojo",
        table.c.dojo_id == dojo_id,
    )).limit(1)
    try:
        with db.engine.connect() as connection:
            return connection.execute(statement).first() is not None
    except SQLAlchemyError as error:
        logger.warning(
            "Failed to check pending dojo cache refresh for dojo %s: %s",
            dojo_id,
            error,
        )
        return True


def module_cache_refresh_pending(target):
    table = DojoCacheRefreshes.__table__
    statement = db.select([table.c.dojo_id]).where(and_(
        table.c.kind == "module",
        table.c.dojo_id == target.dojo_id,
        table.c.module_id == target.module_id,
        table.c.cache_identity == target.cache_identity,
    )).limit(1)
    try:
        with db.engine.connect() as connection:
            return connection.execute(statement).first() is not None
    except SQLAlchemyError as error:
        logger.warning(
            "Failed to check pending module cache refresh for dojo %s: %s",
            target.dojo_id,
            error,
        )
        return True


def get_dojo_cached_stat(dojo_id, cache_key):
    if dojo_cache_refresh_pending(dojo_id):
        return None
    cache_keys = {
        cache_key,
        f"{cache_key}:updated",
        f"{cache_key}:version",
    }
    if not drain_module_cache_invalidations(cache_keys):
        return None
    cached = get_cached_stat(cache_key)
    if dojo_cache_refresh_pending(dojo_id):
        return None
    return cached


def _canonical_signed_integer(value, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if str(parsed) != value or not minimum <= parsed <= maximum:
        return None
    return parsed


def _legacy_module_cache_base(cache_key):
    if isinstance(cache_key, bytes):
        try:
            cache_key = cache_key.decode()
        except UnicodeDecodeError:
            return None
    base_key = cache_key
    for suffix in (":updated", ":version"):
        if base_key.endswith(suffix):
            base_key = base_key.removesuffix(suffix)
            break
    parts = base_key.split(":")
    if len(parts) not in (5, 6):
        return None
    if parts[0] != "stats" or parts[2] != "module":
        return None
    if _canonical_signed_integer(parts[3], -(2 ** 31), 2 ** 31 - 1) is None:
        return None
    if parts[1] not in {
        "scoreboard",
        "crews",
        "challenge_solves",
        "scores",
    }:
        return None
    if parts[1] in {"scoreboard", "crews"} and len(parts) != 6:
        return None
    if parts[1] in {"challenge_solves", "scores"} and len(parts) != 5:
        return None
    if len(parts) == 6 and parts[5] not in {
        str(duration) for duration in SCOREBOARD_DURATIONS
    }:
        return None
    module_selector = parts[4]
    if _canonical_signed_integer(module_selector, 0, 2 ** 31 - 1) is None:
        return None
    return base_key


def _discover_legacy_module_cache_keys():
    client = get_redis_client()
    cache_keys = set()
    for cache_key in client.scan_iter(match="stats:*:module:*", count=500):
        base_key = _legacy_module_cache_base(cache_key)
        if base_key is not None:
            cache_keys.update({
                base_key,
                f"{base_key}:updated",
                f"{base_key}:version",
            })
    return cache_keys


def _queue_live_module_cache_migration_refreshes():
    dojo_ids = [
        dojo_id
        for (dojo_id,) in db.session.query(Dojos.dojo_id)
        .order_by(Dojos.dojo_id)
        .all()
    ]
    db.session.rollback()
    for dojo_id in dojo_ids:
        dojo = lock_dojo_cache_target(dojo_id)
        if dojo is None:
            db.session.rollback()
            continue
        modules = (
            DojoModules.query
            .filter_by(dojo_id=dojo_id)
            .order_by(DojoModules.module_index)
            .populate_existing()
            .with_for_update()
            .all()
        )
        targets = []
        for module in modules:
            identity = module.cache_identity
            data = dict(module.data or {})
            if data.get("cache_identity") != identity:
                data["cache_identity"] = identity
            launched_at = module.cache_launched_at.isoformat()
            if data.get("cache_launched_at") != launched_at:
                data["cache_launched_at"] = launched_at
            if data != (module.data or {}):
                module.data = data
            targets.append(ModuleCacheTarget(dojo_id, module.id, identity))
        queue_cache_refreshes(module_targets=targets)
        db.session.commit()


def _legacy_module_cache_migration_completed():
    table = DojoCacheMigrations.__table__
    statement = db.select([table.c.name]).where(
        table.c.name == LEGACY_MODULE_CACHE_MIGRATION
    ).limit(1)
    with db.engine.connect() as connection:
        return connection.execute(statement).first() is not None


def migrate_legacy_module_caches():
    try:
        if _legacy_module_cache_migration_completed():
            return True
    except SQLAlchemyError as error:
        logger.warning("Failed to inspect legacy module cache migration: %s", error)
        return False

    try:
        _queue_live_module_cache_migration_refreshes()
    except SQLAlchemyError as error:
        db.session.rollback()
        logger.warning("Failed to backfill module cache identities: %s", error)
        return False
    try:
        legacy_keys = _discover_legacy_module_cache_keys()
    except (redis.RedisError, redis.ConnectionError, RuntimeError) as error:
        db.session.rollback()
        logger.warning("Failed to enumerate legacy module caches: %s", error)
        return False

    queue_module_cache_invalidations(legacy_keys)
    db.session.add(DojoCacheMigrations(
        name=LEGACY_MODULE_CACHE_MIGRATION,
        completed_at=datetime.datetime.utcnow(),
    ))
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        logger.warning("Failed to commit legacy module cache migration: %s", error)
        return False
    return True


def initialize_module_cache_migration():
    try:
        maintenance_lock = module_cache_maintenance_lock(blocking=True)
        acquired = maintenance_lock.__enter__()
    except SQLAlchemyError as error:
        logger.warning("Failed to acquire startup cache migration lock: %s", error)
        return False
    try:
        if not acquired or not migrate_legacy_module_caches():
            return False
        return drain_module_cache_invalidations()
    finally:
        maintenance_lock.__exit__(None, None, None)


def pending_module_cache_invalidations(limit=INVALIDATION_BATCH_SIZE, cache_keys=None):
    table = DojoModuleCacheInvalidations.__table__
    statement = db.select([table.c.cache_key, table.c.generation])
    if cache_keys is not None:
        keys = sorted(set(cache_keys))
        if not keys:
            return []
        statement = statement.where(table.c.cache_key.in_(keys))
    statement = statement.order_by(table.c.cache_key).limit(limit)
    with db.engine.connect() as connection:
        rows = connection.execute(statement).fetchall()
    return [(row.cache_key, row.generation) for row in rows]


def _drain_module_cache_invalidations(cache_keys=None):
    selected_keys = None if cache_keys is None else set(cache_keys)
    if selected_keys is not None and not selected_keys:
        return True
    if selected_keys is not None and len(selected_keys) > INVALIDATION_BATCH_SIZE:
        logger.warning("Refusing to drain %d selected module cache keys", len(selected_keys))
        return False

    for _ in range(INVALIDATION_MAX_BATCHES):
        try:
            pending = pending_module_cache_invalidations(cache_keys=selected_keys)
        except SQLAlchemyError as error:
            logger.warning("Failed to load pending module cache invalidations: %s", error)
            return False
        if not pending:
            return True
        keys = selected_keys or {cache_key for cache_key, _ in pending}
        if not invalidate_module_cache_keys(keys):
            return False
        table = DojoModuleCacheInvalidations.__table__
        try:
            with db.engine.begin() as connection:
                connection.execute(table.delete().where(
                    tuple_(table.c.cache_key, table.c.generation).in_(pending)
                ))
        except SQLAlchemyError as error:
            logger.warning("Failed to complete module cache invalidations: %s", error)
            return False

    try:
        return not pending_module_cache_invalidations(limit=1, cache_keys=selected_keys)
    except SQLAlchemyError as error:
        logger.warning("Failed to load pending module cache invalidations: %s", error)
        return False


def drain_module_cache_invalidations(cache_keys=None):
    try:
        with module_cache_maintenance_lock(blocking=True) as acquired:
            if not acquired:
                return False
            return _drain_module_cache_invalidations(cache_keys)
    except SQLAlchemyError as error:
        logger.warning(
            "Failed to acquire module cache invalidation lock: %s",
            error,
        )
        return False


def maintain_module_cache_outboxes(refresh_keys=None):
    try:
        maintenance_lock = module_cache_maintenance_lock()
        acquired = maintenance_lock.__enter__()
    except SQLAlchemyError as error:
        logger.warning("Failed to acquire module cache maintenance lock: %s", error)
        return False
    try:
        if not acquired:
            return False
        if not migrate_legacy_module_caches():
            return False
        if not drain_module_cache_invalidations():
            return False
        return publish_pending_cache_refreshes(refresh_keys=refresh_keys)
    finally:
        maintenance_lock.__exit__(None, None, None)


def get_module_cached_stat(module, cache_key):
    target = (
        module
        if isinstance(module, ModuleCacheTarget)
        else module_cache_target(module)
    )
    if module_cache_refresh_pending(target):
        return None
    cache_keys = {
        cache_key,
        f"{cache_key}:updated",
        f"{cache_key}:version",
    }
    if not drain_module_cache_invalidations(cache_keys):
        return None
    cached = get_cached_stat(cache_key)
    if module_cache_refresh_pending(target):
        return None
    return cached
