import logging

from sqlalchemy import event, inspect
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm.session import Session
from CTFd.models import Users, Solves, Awards

from ..models import (
    Dojos, DojoChallenges, DojoUsers, DojoMembers, DojoAdmins,
    DojoStudents, DojoModules, DojoChallengeVisibilities, Belts, Emojis,
    DojoStatsRevisions,
)
from .events import (
    queue_stat_event,
    publish_dojo_stats_event,
    publish_scoreboard_event,
    publish_scores_event,
    publish_belts_event,
    publish_emojis_event,
    publish_challenge_solve_event,
)

logger = logging.getLogger(__name__)


def invalidate_scoreboard_cache():
    pass


def next_stats_revision(connection):
    table = DojoStatsRevisions.__table__
    statement = insert(table).values(id=1, version=1)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.id],
        set_={"version": table.c.version + 1},
    ).returning(table.c.version)
    return connection.execute(statement).scalar()


@event.listens_for(Solves, 'after_insert', propagate=True)
@event.listens_for(Solves, 'after_delete', propagate=True)
def hook_solve_change(mapper, connection, target):
    invalidate_scoreboard_cache()
    revision = next_stats_revision(connection)
    logger.info(
        f"Solve listener fired: challenge_id={target.challenge_id}, "
        f"user_id={target.user_id}, revision={revision}"
    )
    queue_stat_event(
        lambda u_id=target.user_id,
        c_id=target.challenge_id,
        s_date=target.date,
        solve_id=target.id,
        version=revision: publish_challenge_solve_event(
            u_id,
            c_id,
            s_date,
            solve_id=solve_id,
            version=version,
        )
    )


def dojo_user_dojo_id(dojo_user):
    if dojo_user.dojo_id is not None:
        return dojo_user.dojo_id
    if dojo_user.dojo is not None:
        return dojo_user.dojo.dojo_id
    return None


@event.listens_for(Session, 'before_flush')
def queue_eligibility_cache_refreshes(session, flush_context, instances):
    new_or_deleted = session.new.union(session.deleted)
    transient_dojo_ids = {
        dojo.dojo_id
        for dojo in new_or_deleted
        if isinstance(dojo, Dojos)
    }
    dojo_ids = {
        dojo_id
        for dojo_user in new_or_deleted
        if isinstance(dojo_user, DojoUsers)
        for dojo_id in (dojo_user_dojo_id(dojo_user),)
        if dojo_id is not None
    }
    for target in session.dirty:
        state = inspect(target)
        if (
            isinstance(target, DojoUsers)
            and state.attrs.type.history.has_changes()
        ):
            dojo_id = dojo_user_dojo_id(target)
            if dojo_id is not None:
                dojo_ids.add(dojo_id)

    hidden_user_ids = {
        user.id
        for user in session.dirty
        if (
            isinstance(user, Users)
            and user.id is not None
            and inspect(user).attrs.hidden.history.has_changes()
        )
    }
    if hidden_user_ids:
        dojo_ids.update(
            dojo_id
            for (dojo_id,) in (
                session.query(DojoChallenges.dojo_id)
                .join(
                    Solves,
                    Solves.challenge_id == DojoChallenges.challenge_id,
                )
                .filter(Solves.user_id.in_(hidden_user_ids))
                .distinct()
                .all()
            )
        )

    dojo_ids.difference_update(transient_dojo_ids)

    if not dojo_ids:
        return

    from .module_cache import (
        ModuleCacheTarget,
        queue_cache_refreshes,
    )

    modules = (
        session.query(DojoModules)
        .filter(DojoModules.dojo_id.in_(dojo_ids))
        .all()
    )
    queue_cache_refreshes(
        module_targets=tuple(
            ModuleCacheTarget(
                module.dojo_id,
                module.id,
                module.cache_identity,
            )
            for module in modules
        ),
        dojo_ids=dojo_ids,
    )
    session.info['_maintain_module_cache_after_commit'] = True


@event.listens_for(Session, 'after_commit')
def mark_committed_cache_maintenance(session):
    if session.info.pop('_maintain_module_cache_after_commit', False):
        session.info['_run_committed_module_cache_maintenance'] = True


@event.listens_for(Session, 'after_rollback')
def clear_rolled_back_cache_maintenance(session):
    session.info.pop('_maintain_module_cache_after_commit', None)
    session.info.pop('_run_committed_module_cache_maintenance', None)


@event.listens_for(Session, 'after_transaction_end')
def run_committed_cache_maintenance(session, transaction):
    if getattr(transaction, 'parent', None) is not None:
        return
    if not session.info.pop(
        '_run_committed_module_cache_maintenance',
        False,
    ):
        return
    try:
        from .module_cache import maintain_module_cache_outboxes
        maintain_module_cache_outboxes()
    except Exception as error:
        logger.error(
            "Failed to maintain eligibility cache refreshes: %s",
            error,
            exc_info=True,
        )


# TODO: Consider deduplicating events when a single action triggers
# multiple updates (e.g., solve affecting multiple dojos). Currently
# acceptable but may need optimization at scale.


@event.listens_for(Dojos, 'after_insert', propagate=True)
@event.listens_for(Dojos, 'after_delete', propagate=True)
@event.listens_for(Awards, 'after_insert', propagate=True)
@event.listens_for(Awards, 'after_delete', propagate=True)
@event.listens_for(Belts, 'after_insert', propagate=True)
@event.listens_for(Belts, 'after_delete', propagate=True)
@event.listens_for(Emojis, 'after_insert', propagate=True)
@event.listens_for(Emojis, 'after_delete', propagate=True)
def hook_object_creation(mapper, connection, target):
    invalidate_scoreboard_cache()

    if isinstance(target, Dojos):
        dojo_id = target.dojo_id
        queue_stat_event(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
        queue_stat_event(lambda d_id=dojo_id: publish_scoreboard_event("dojo", d_id))
        queue_stat_event(lambda d_id=dojo_id: publish_scores_event(d_id))
    elif isinstance(target, Belts):
        queue_stat_event(publish_belts_event)
    elif isinstance(target, Emojis):
        queue_stat_event(publish_emojis_event)


@event.listens_for(Users, 'after_update', propagate=True)
@event.listens_for(Dojos, 'after_update', propagate=True)
@event.listens_for(DojoUsers, 'after_update', propagate=True)
@event.listens_for(DojoMembers, 'after_update', propagate=True)
@event.listens_for(DojoAdmins, 'after_update', propagate=True)
@event.listens_for(DojoStudents, 'after_update', propagate=True)
@event.listens_for(DojoModules, 'after_update', propagate=True)
@event.listens_for(DojoChallenges, 'after_update', propagate=True)
@event.listens_for(DojoChallengeVisibilities, 'after_update', propagate=True)
@event.listens_for(Belts, 'after_update', propagate=True)
@event.listens_for(Emojis, 'after_update', propagate=True)
def hook_object_update(mapper, connection, target):
    if isinstance(target, DojoModules):
        state = inspect(target)
        changed_columns = {
            attribute.key
            for attribute in state.mapper.column_attrs
            if state.attrs[attribute.key].history.has_changes()
        }
        if changed_columns == {"module_index"}:
            return
    if Session.object_session(target).is_modified(target, include_collections=False):
        invalidate_scoreboard_cache()

        if isinstance(target, Dojos):
            dojo_id = target.dojo_id
            queue_stat_event(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
            queue_stat_event(lambda d_id=dojo_id: publish_scoreboard_event("dojo", d_id))
            queue_stat_event(lambda d_id=dojo_id: publish_scores_event(d_id))
        elif isinstance(target, DojoChallenges):
            dojo_id = target.dojo.dojo_id
            module_id = {"dojo_id": target.dojo.dojo_id, "module_index": target.module.module_index}
            queue_stat_event(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
            queue_stat_event(lambda d_id=dojo_id: publish_scoreboard_event("dojo", d_id))
            queue_stat_event(lambda m_id=module_id: publish_scoreboard_event("module", m_id))
        elif isinstance(target, DojoModules):
            dojo_id = target.dojo.dojo_id
            module_id = {"dojo_id": target.dojo.dojo_id, "module_index": target.module_index}
            queue_stat_event(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
            queue_stat_event(lambda m_id=module_id: publish_scoreboard_event("module", m_id))
        elif isinstance(target, Belts):
            queue_stat_event(publish_belts_event)
        elif isinstance(target, Emojis):
            queue_stat_event(publish_emojis_event)
