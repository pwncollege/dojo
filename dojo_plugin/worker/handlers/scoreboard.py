import logging
import datetime
from sqlalchemy import func

from CTFd.models import db, Solves, Users
from ...models import Dojos, DojoModules, DojoChallenges
from ...utils.background_stats import set_cached_stat
from . import register_handler

logger = logging.getLogger(__name__)

COMMON_DURATIONS = [0, 7, 30]

def calculate_scoreboard(model, duration):
    duration_filter = (
        Solves.date >= datetime.datetime.utcnow() - datetime.timedelta(days=duration)
        if duration else True
    )
    required_filter = DojoChallenges.required == True
    solves = func.count().label("solves")
    rank = (
        func.row_number()
        .over(order_by=(solves.desc(), func.max(Solves.id)))
        .label("rank")
    )
    user_entities = [Solves.user_id, Users.name, Users.email]
    query = (
        model.solves()
        .filter(duration_filter)
        .filter(required_filter)
        .group_by(*user_entities)
        .order_by(rank)
        .with_entities(rank, solves, *user_entities)
    )

    row_results = query.all()
    results = [{key: getattr(item, key) for key in item.keys()} for item in row_results]
    return results

@register_handler("scoreboard_update")
def handle_scoreboard_update(payload):
    model_type = payload.get("model_type")
    model_id = payload.get("model_id")

    if not model_type or model_id is None:
        logger.warning(f"scoreboard_update event missing model_type or model_id: {payload}")
        return

    logger.info(f"Handling scoreboard_update for {model_type} id={model_id}")

    db.session.expire_all()
    db.session.commit()

    if model_type == "dojo":
        model = Dojos.query.get(model_id)
        if not model:
            logger.info(f"Dojo not found for dojo_id {model_id} (may have been deleted)")
            return
        cache_prefix = f"stats:scoreboard:dojo:{model_id}"
    elif model_type == "module":
        if isinstance(model_id, dict):
            dojo_id = model_id.get("dojo_id")
            module_index = model_id.get("module_index")
            model = DojoModules.query.get((dojo_id, module_index))
        else:
            model = DojoModules.query.get(model_id)

        if not model:
            logger.info(f"Module not found for id {model_id} (may have been deleted)")
            return
        cache_prefix = f"stats:scoreboard:module:{model.dojo_id}:{model.module_index}"
    else:
        logger.warning(f"Unknown model_type: {model_type}")
        return

    for duration in COMMON_DURATIONS:
        try:
            logger.info(f"Calculating scoreboard for {model_type} {model_id}, duration={duration}...")
            scoreboard = calculate_scoreboard(model, duration)
            cache_key = f"{cache_prefix}:{duration}"
            set_cached_stat(cache_key, scoreboard)
            logger.info(f"Successfully updated scoreboard cache {cache_key} ({len(scoreboard)} entries)")
        except Exception as e:
            logger.error(f"Error calculating scoreboard for {model_type} {model_id}, duration={duration}: {e}", exc_info=True)

def initialize_all_scoreboards():
    db.session.expire_all()
    db.session.commit()

    dojos = Dojos.query.all()
    logger.info(f"Initializing scoreboards for {len(dojos)} dojos...")

    for dojo in dojos:
        for duration in COMMON_DURATIONS:
            try:
                scoreboard = calculate_scoreboard(dojo, duration)
                cache_key = f"stats:scoreboard:dojo:{dojo.dojo_id}:{duration}"
                set_cached_stat(cache_key, scoreboard)
                logger.info(f"Initialized scoreboard for dojo {dojo.reference_id} (id={dojo.dojo_id}), duration={duration}")
            except Exception as e:
                logger.error(f"Error initializing scoreboard for dojo {dojo.reference_id}, duration={duration}: {e}", exc_info=True)

    modules = DojoModules.query.all()
    logger.info(f"Initializing scoreboards for {len(modules)} modules...")

    for module in modules:
        for duration in COMMON_DURATIONS:
            try:
                scoreboard = calculate_scoreboard(module, duration)
                cache_key = f"stats:scoreboard:module:{module.dojo_id}:{module.module_index}:{duration}"
                set_cached_stat(cache_key, scoreboard)
                logger.info(f"Initialized scoreboard for module {module.dojo.reference_id}/{module.id} (dojo_id={module.dojo_id}, module_index={module.module_index}), duration={duration}")
            except Exception as e:
                logger.error(f"Error initializing scoreboard for module {module.dojo.reference_id}/{module.id}, duration={duration}: {e}", exc_info=True)
