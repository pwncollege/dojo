import logging

from CTFd.models import db, Solves

from ...models import Dojos, DojoChallenges, UserVisibilityUpdates
from ...utils.feed import remove_user_events
from ...utils.public_stats import (
    affected_public_cache_keys,
    capture_public_cache_revisions,
    complete_user_visibility_transition,
    public_stats_visibility_update,
    retry_user_visibility_transition,
)
from . import register_handler
from .awards import handle_belts_update, handle_emojis_update
from .dojo_stats import handle_dojo_stats_update
from .scoreboard import handle_scoreboard_update
from .scores import handle_scores_update


logger = logging.getLogger(__name__)


@register_handler("user_visibility_update")
def handle_user_visibility_update(payload, event_timestamp=None):
    user_id = payload.get("user_id")
    token = payload.get("token")
    if user_id is None or token is None:
        logger.warning(
            f"user_visibility_update event missing user_id or token: {payload}"
        )
        return

    db.session.expire_all()
    db.session.commit()
    transition = UserVisibilityUpdates.query.filter_by(
        user_id=user_id,
        token=token,
    ).first()
    if transition is None:
        return

    completed = False
    try:
        with public_stats_visibility_update() as connection:
            cache_keys = affected_public_cache_keys(connection, user_id)
            revisions = capture_public_cache_revisions(cache_keys)
            affected_modules = (
                db.session.query(
                    DojoChallenges.dojo_id,
                    DojoChallenges.module_index,
                )
                .join(Solves, Solves.challenge_id == DojoChallenges.challenge_id)
                .filter(
                    Solves.user_id == user_id,
                    Solves.type == Solves.__mapper__.polymorphic_identity,
                )
                .distinct()
                .all()
            )
            modules_by_dojo = {}
            for dojo_id, module_index in affected_modules:
                modules_by_dojo.setdefault(dojo_id, set()).add(module_index)

            for dojo_id, module_indices in modules_by_dojo.items():
                dojo = Dojos.query.get(dojo_id)
                if dojo is None:
                    continue
                handle_dojo_stats_update({"dojo_id": dojo_id})
                handle_scoreboard_update(
                    {"model_type": "dojo", "model_id": dojo_id}
                )
                for module_index in module_indices:
                    handle_scoreboard_update(
                        {
                            "model_type": "module",
                            "model_id": {
                                "dojo_id": dojo_id,
                                "module_index": module_index,
                            },
                        }
                    )
                if dojo.is_public_or_official:
                    handle_scores_update({"dojo_id": dojo_id})

            handle_belts_update({})
            handle_emojis_update({})
            remove_user_events(user_id)
            completed = complete_user_visibility_transition(
                connection,
                user_id,
                token,
                revisions,
            )
    finally:
        if not completed:
            retry_user_visibility_transition(user_id, token)
