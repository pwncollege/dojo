import logging

from sqlalchemy import event
from sqlalchemy.orm.session import Session
from CTFd.cache import cache
from CTFd.models import Users, Solves, Awards

from ..models import (
    Dojos, DojoChallenges, DojoUsers, DojoMembers, DojoAdmins,
    DojoStudents, DojoModules, DojoChallengeVisibilities, Belts, Emojis
)
from .events import (
    queue_stat_event,
    publish_dojo_stats_event,
    publish_scoreboard_event,
    publish_scores_event,
    publish_belts_event,
    publish_emojis_event,
    publish_activity_event,
    publish_challenge_solve_event,
)

logger = logging.getLogger(__name__)


def invalidate_scoreboard_cache():
    pass


# TODO: Consider deduplicating events when a single action triggers
# multiple updates (e.g., solve affecting multiple dojos). Currently
# acceptable but may need optimization at scale.


@event.listens_for(Dojos, 'after_insert', propagate=True)
@event.listens_for(Dojos, 'after_delete', propagate=True)
@event.listens_for(Solves, 'after_insert', propagate=True)
@event.listens_for(Solves, 'after_delete', propagate=True)
@event.listens_for(Awards, 'after_insert', propagate=True)
@event.listens_for(Awards, 'after_delete', propagate=True)
@event.listens_for(Belts, 'after_insert', propagate=True)
@event.listens_for(Belts, 'after_delete', propagate=True)
@event.listens_for(Emojis, 'after_insert', propagate=True)
@event.listens_for(Emojis, 'after_delete', propagate=True)
def hook_object_creation(mapper, connection, target):
    invalidate_scoreboard_cache()

    if isinstance(target, Solves):
        logger.info(f"Solve listener fired: challenge_id={target.challenge_id}, user_id={target.user_id}")
        queue_stat_event(lambda u_id=target.user_id, c_id=target.challenge_id, s_date=target.date: publish_challenge_solve_event(u_id, c_id, s_date))
    elif isinstance(target, Dojos):
        dojo_id = target.dojo_id
        queue_stat_event(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
        queue_stat_event(lambda d_id=dojo_id: publish_scoreboard_event("dojo", d_id))
        queue_stat_event(publish_scores_event)
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
    if Session.object_session(target).is_modified(target, include_collections=False):
        invalidate_scoreboard_cache()

        if isinstance(target, Dojos):
            dojo_id = target.dojo_id
            queue_stat_event(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
            queue_stat_event(lambda d_id=dojo_id: publish_scoreboard_event("dojo", d_id))
            queue_stat_event(publish_scores_event)
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
