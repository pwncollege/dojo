import logging
import datetime
from sqlalchemy import func

from CTFd.models import db, Solves, Users
from ...models import Dojos, DojoModules, DojoChallenges
from ...utils.background_stats import calculate_authoritative_stat, get_cached_stat, get_cache_watermark, set_cached_stat, is_event_stale
from ...utils.crews import aggregate_crews, member_challenges_from_crews, parse_crew_tag
from ...utils.module_cache import SCOREBOARD_DURATIONS, drain_module_cache_invalidations, lock_dojo_cache_target, lock_module_cache_target, module_cache_target, module_challenge_solves_cache_key, module_scoreboard_cache_key
from . import register_handler

logger = logging.getLogger(__name__)

COMMON_DURATIONS = SCOREBOARD_DURATIONS


def duration_solves_filter(duration):
    if not duration:
        return True
    return Solves.date >= datetime.datetime.utcnow() - datetime.timedelta(days=duration)


def cache_solves(model):
    if isinstance(model, DojoModules):
        return model.cache_solves()
    return model.solves()


def calculate_member_challenges(model, duration, scoreboard):
    tagged_user_ids = [entry["user_id"] for entry in scoreboard if parse_crew_tag(entry.get("name"))]
    result = {}
    for start in range(0, len(tagged_user_ids), 500):
        chunk = tagged_user_ids[start:start + 500]
        query = (
            cache_solves(model)
            .filter(duration_solves_filter(duration))
            .filter(DojoChallenges.required == True)
            .filter(Solves.user_id.in_(chunk))
            .with_entities(Solves.user_id, Solves.challenge_id)
        )
        for user_id, challenge_id in query.all():
            result.setdefault(user_id, set()).add(challenge_id)
    return result


def user_challenges(model, duration, user_id):
    query = (
        cache_solves(model)
        .filter(duration_solves_filter(duration))
        .filter(DojoChallenges.required == True)
        .filter(Solves.user_id == user_id)
        .with_entities(Solves.challenge_id)
    )
    return set(challenge_id for (challenge_id,) in query.all())


def set_scoreboard_cache(
    cache_key,
    scoreboard,
    member_challenges,
    updated_at=None,
    version=None,
):
    if updated_at is None:
        updated_at = get_cache_watermark()
    scoreboard_cached = set_cached_stat(
        cache_key,
        scoreboard,
        updated_at=updated_at,
        version=version,
    )
    crews_cached = set_cached_stat(
        cache_key.replace("stats:scoreboard:", "stats:crews:", 1),
        aggregate_crews(scoreboard, member_challenges),
        updated_at=updated_at,
        version=version,
    )
    return scoreboard_cached and crews_cached


def update_scoreboard_cache(
    model,
    cache_key,
    user_id,
    challenge_id,
    solve_delta=1,
):
    current_scoreboard = get_cached_stat(cache_key) or []
    updated_scoreboard = update_scoreboard(
        current_scoreboard,
        user_id,
        solve_delta,
    )
    crews_key = cache_key.replace("stats:scoreboard:", "stats:crews:", 1)
    member_challenges = member_challenges_from_crews(get_cached_stat(crews_key) or [])
    entry = next((item for item in updated_scoreboard if item["user_id"] == user_id), None)
    if entry and parse_crew_tag(entry.get("name")):
        if user_id in member_challenges:
            member_challenges[user_id].add(challenge_id)
        else:
            duration = int(cache_key.rsplit(":", 1)[1])
            member_challenges[user_id] = user_challenges(model, duration, user_id)
    set_scoreboard_cache(cache_key, updated_scoreboard, member_challenges)


def update_scoreboard(scoreboard, user_id, solve_delta=1):
    result = [entry.copy() for entry in scoreboard]

    user_entry = None
    user_index = None
    for i, entry in enumerate(result):
        if entry["user_id"] == user_id:
            user_entry = entry
            user_index = i
            break

    if user_entry is None:
        user = Users.query.get(user_id)
        if user is None:
            return result
        user_entry = {
            "user_id": user_id,
            "name": user.name,
            "email": user.email,
            "solves": 0,
        }
    else:
        result.pop(user_index)

    user_entry["solves"] += solve_delta

    new_solves = user_entry["solves"]
    insert_pos = 0
    for i, entry in enumerate(result):
        if entry["solves"] >= new_solves:
            insert_pos = i + 1
        else:
            break

    result.insert(insert_pos, user_entry)

    for i, entry in enumerate(result):
        entry["rank"] = i + 1

    return result

def calculate_challenge_solves(module):
    required_filter = DojoChallenges.required == True
    query = (
        module.cache_solves()
        .filter(required_filter)
        .group_by(Solves.challenge_id)
        .with_entities(Solves.challenge_id, func.count().label("count"))
    )
    return {str(row.challenge_id): row.count for row in query.all()}


def update_challenge_solves(challenge_solves, challenge_id, solve_delta=1):
    result = dict(challenge_solves)
    key = str(challenge_id)
    result[key] = result.get(key, 0) + solve_delta
    return result


def calculate_scoreboard(model, duration):
    duration_filter = duration_solves_filter(duration)
    required_filter = DojoChallenges.required == True
    solves = func.count().label("solves")
    rank = (
        func.row_number()
        .over(order_by=(solves.desc(), func.max(Solves.id)))
        .label("rank")
    )
    user_entities = [Solves.user_id, Users.name, Users.email]
    query = (
        cache_solves(model)
        .filter(duration_filter)
        .filter(required_filter)
        .group_by(*user_entities)
        .order_by(rank)
        .with_entities(rank, solves, *user_entities)
    )

    row_results = query.all()
    results = [{key: getattr(item, key) for key in item.keys()} for item in row_results]
    return results


def populate_module_scoreboard_caches(target, event_timestamp=None):
    if not lock_dojo_cache_target(target.dojo_id):
        db.session.rollback()
        return False
    module = lock_module_cache_target(target)
    if not module:
        db.session.rollback()
        return False

    try:
        def calculate():
            scoreboards = []
            for duration in COMMON_DURATIONS:
                cache_key = module_scoreboard_cache_key(module, duration)
                if event_timestamp and is_event_stale(
                    cache_key,
                    event_timestamp,
                ):
                    continue
                scoreboard = calculate_scoreboard(module, duration)
                member_challenges = calculate_member_challenges(
                    module,
                    duration,
                    scoreboard,
                )
                scoreboards.append((
                    cache_key,
                    scoreboard,
                    member_challenges,
                ))
            return scoreboards, calculate_challenge_solves(module)

        (scoreboards, challenge_solves), version, calculated_at = (
            calculate_authoritative_stat(calculate)
        )
        updated_at = (
            event_timestamp
            if event_timestamp is not None
            else calculated_at
        )
        for cache_key, scoreboard, member_challenges in scoreboards:
            set_scoreboard_cache(
                cache_key,
                scoreboard,
                member_challenges,
                updated_at=updated_at,
                version=version,
            )
        set_cached_stat(
            module_challenge_solves_cache_key(module),
            challenge_solves,
            updated_at=updated_at,
            version=version,
        )
    except Exception as error:
        logger.error(
            f"Error calculating module caches for {target.module_id}: {error}",
            exc_info=True,
        )
    db.session.commit()
    return True


@register_handler("scoreboard_update")
def handle_scoreboard_update(payload, event_timestamp=None):
    model_type = payload.get("model_type")
    model_id = payload.get("model_id")

    if not model_type or model_id is None:
        logger.warning(f"scoreboard_update event missing model_type or model_id: {payload}")
        return

    logger.info(f"Handling scoreboard_update for {model_type} id={model_id}")

    db.session.expire_all()
    db.session.commit()
    if not drain_module_cache_invalidations():
        return False

    if model_type == "dojo":
        model = lock_dojo_cache_target(model_id)
        if not model:
            logger.info(f"Dojo not found for dojo_id {model_id} (may have been deleted)")
            db.session.rollback()
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
        target = module_cache_target(model)
        if not populate_module_scoreboard_caches(target, event_timestamp):
            logger.info(f"Module changed while handling id {model_id}")
        return True
    else:
        logger.warning(f"Unknown model_type: {model_type}")
        return

    try:
        def calculate():
            values = []
            for duration in COMMON_DURATIONS:
                cache_key = f"{cache_prefix}:{duration}"
                if event_timestamp and is_event_stale(
                    cache_key,
                    event_timestamp,
                ):
                    continue
                scoreboard = calculate_scoreboard(model, duration)
                values.append((
                    cache_key,
                    scoreboard,
                    calculate_member_challenges(
                        model,
                        duration,
                        scoreboard,
                    ),
                ))
            return values

        scoreboards, version, calculated_at = calculate_authoritative_stat(
            calculate
        )
        updated_at = (
            event_timestamp
            if event_timestamp is not None
            else calculated_at
        )
        for cache_key, scoreboard, member_challenges in scoreboards:
            set_scoreboard_cache(
                cache_key,
                scoreboard,
                member_challenges,
                updated_at=updated_at,
                version=version,
            )
            logger.info(
                f"Successfully updated scoreboard cache {cache_key} "
                f"({len(scoreboard)} entries)"
            )
    except Exception as error:
        logger.error(
            f"Error calculating scoreboard for {model_type} {model_id}: {error}",
            exc_info=True,
        )
    db.session.commit()
    return True

def initialize_all_scoreboards():
    db.session.expire_all()
    db.session.commit()
    if not drain_module_cache_invalidations():
        return False
    dojo_ids = [dojo_id for (dojo_id,) in db.session.query(Dojos.dojo_id).all()]
    db.session.rollback()
    logger.info(f"Initializing scoreboards for {len(dojo_ids)} dojos...")

    for dojo_id in dojo_ids:
        dojo = lock_dojo_cache_target(dojo_id)
        if not dojo:
            db.session.rollback()
            continue
        try:
            def calculate():
                values = []
                for duration in COMMON_DURATIONS:
                    scoreboard = calculate_scoreboard(dojo, duration)
                    values.append((
                        duration,
                        scoreboard,
                        calculate_member_challenges(
                            dojo,
                            duration,
                            scoreboard,
                        ),
                    ))
                return values

            scoreboards, version, calculated_at = (
                calculate_authoritative_stat(calculate)
            )
            for duration, scoreboard, member_challenges in scoreboards:
                cache_key = f"stats:scoreboard:dojo:{dojo.dojo_id}:{duration}"
                set_scoreboard_cache(
                    cache_key,
                    scoreboard,
                    member_challenges,
                    updated_at=calculated_at,
                    version=version,
                )
                logger.info(f"Initialized scoreboard for dojo {dojo.reference_id} (id={dojo.dojo_id}), duration={duration}")
        except Exception as e:
            logger.error(f"Error initializing scoreboard for dojo {dojo.reference_id}: {e}", exc_info=True)

        module_targets = [module_cache_target(module) for module in dojo.modules]
        db.session.commit()
        for target in module_targets:
            populate_module_scoreboard_caches(target)
    return True
