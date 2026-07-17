import logging
import datetime
from sqlalchemy import func

from CTFd.models import db, Solves, Users
from ...models import Dojos, DojoModules, DojoChallenges
from ...utils.background_stats import (
    get_public_cached_stat as get_cached_stat,
    set_public_cached_stat as set_cached_stat,
    is_event_stale,
)
from ...utils.crews import aggregate_crews, member_challenges_from_crews, parse_crew_tag
from ...utils.public_stats import (
    SCOREBOARD_DURATIONS,
    capture_public_cache_revisions,
)
from . import register_handler

logger = logging.getLogger(__name__)

COMMON_DURATIONS = SCOREBOARD_DURATIONS


def duration_solves_filter(duration):
    if not duration:
        return True
    return Solves.date >= datetime.datetime.utcnow() - datetime.timedelta(days=duration)


def calculate_member_challenges(model, duration, scoreboard):
    tagged_user_ids = [entry["user_id"] for entry in scoreboard if parse_crew_tag(entry.get("name"))]
    result = {}
    for start in range(0, len(tagged_user_ids), 500):
        chunk = tagged_user_ids[start:start + 500]
        query = (
            model.solves()
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
        model.solves()
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
    revisions=None,
):
    crews_key = cache_key.replace("stats:scoreboard:", "stats:crews:", 1)
    revisions = revisions or capture_public_cache_revisions([cache_key, crews_key])
    set_cached_stat(cache_key, scoreboard, revision=revisions[cache_key])
    set_cached_stat(
        crews_key,
        aggregate_crews(scoreboard, member_challenges),
        revision=revisions[crews_key],
    )


def update_scoreboard_cache(
    model,
    cache_key,
    user_id,
    challenge_id,
    revisions=None,
):
    current_scoreboard = get_cached_stat(cache_key)
    crews_key = cache_key.replace("stats:scoreboard:", "stats:crews:", 1)
    current_crews = get_cached_stat(crews_key)
    if current_scoreboard is None or current_crews is None:
        logger.info(f"Incomplete public cache pair for {cache_key}, skipping incremental update")
        return False
    updated_scoreboard = update_scoreboard(current_scoreboard, user_id)
    member_challenges = member_challenges_from_crews(current_crews)
    entry = next((item for item in updated_scoreboard if item["user_id"] == user_id), None)
    if entry and parse_crew_tag(entry.get("name")):
        if user_id in member_challenges:
            member_challenges[user_id].add(challenge_id)
        else:
            duration = int(cache_key.rsplit(":", 1)[1])
            member_challenges[user_id] = user_challenges(model, duration, user_id)
    set_scoreboard_cache(
        cache_key,
        updated_scoreboard,
        member_challenges,
        revisions=revisions,
    )
    return True


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

def challenge_solves_cache_key(dojo_id, module_index):
    return f"stats:challenge_solves:module:{dojo_id}:{module_index}"


def calculate_challenge_solves(module):
    required_filter = DojoChallenges.required == True
    query = (
        module.solves()
        .filter(required_filter)
        .group_by(Solves.challenge_id)
        .with_entities(Solves.challenge_id, func.count().label("count"))
    )
    return {str(row.challenge_id): row.count for row in query.all()}


def update_challenge_solves(challenge_solves, challenge_id):
    result = dict(challenge_solves)
    key = str(challenge_id)
    result[key] = result.get(key, 0) + 1
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
def handle_scoreboard_update(payload, event_timestamp=None):
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

    cache_keys = []
    for duration in COMMON_DURATIONS:
        cache_key = f"{cache_prefix}:{duration}"
        cache_keys.extend(
            [
                cache_key,
                cache_key.replace("stats:scoreboard:", "stats:crews:", 1),
            ]
        )
    if model_type == "module":
        cache_keys.append(
            challenge_solves_cache_key(model.dojo_id, model.module_index)
        )
    revisions = capture_public_cache_revisions(cache_keys)

    for duration in COMMON_DURATIONS:
        try:
            cache_key = f"{cache_prefix}:{duration}"
            if event_timestamp and is_event_stale(cache_key, event_timestamp):
                continue
            crews_key = cache_key.replace("stats:scoreboard:", "stats:crews:", 1)
            logger.info(f"Calculating scoreboard for {model_type} {model_id}, duration={duration}...")
            scoreboard = calculate_scoreboard(model, duration)
            set_scoreboard_cache(
                cache_key,
                scoreboard,
                calculate_member_challenges(model, duration, scoreboard),
                revisions=revisions,
            )
            logger.info(f"Successfully updated scoreboard cache {cache_key} ({len(scoreboard)} entries)")
        except Exception as e:
            logger.error(f"Error calculating scoreboard for {model_type} {model_id}, duration={duration}: {e}", exc_info=True)

    if model_type == "module":
        try:
            logger.info(f"Calculating challenge_solves for module {model_id}...")
            cache_key = challenge_solves_cache_key(model.dojo_id, model.module_index)
            challenge_solves = calculate_challenge_solves(model)
            set_cached_stat(
                cache_key,
                challenge_solves,
                revision=revisions[cache_key],
            )
            logger.info(f"Successfully updated challenge_solves cache {cache_key} ({len(challenge_solves)} challenges)")
        except Exception as e:
            logger.error(f"Error calculating challenge_solves for module {model_id}: {e}", exc_info=True)


def initialize_all_scoreboards():
    dojos = Dojos.query.all()
    logger.info(f"Initializing scoreboards for {len(dojos)} dojos...")
    cache_keys = []
    for dojo in dojos:
        for duration in COMMON_DURATIONS:
            dojo_key = f"stats:scoreboard:dojo:{dojo.dojo_id}:{duration}"
            cache_keys.extend(
                [
                    dojo_key,
                    dojo_key.replace("stats:scoreboard:", "stats:crews:", 1),
                ]
            )
        for module in dojo.modules:
            for duration in COMMON_DURATIONS:
                module_key = f"stats:scoreboard:module:{module.dojo_id}:{module.module_index}:{duration}"
                cache_keys.extend(
                    [
                        module_key,
                        module_key.replace(
                            "stats:scoreboard:", "stats:crews:", 1
                        ),
                    ]
                )
            cache_keys.append(
                challenge_solves_cache_key(module.dojo_id, module.module_index)
            )
    revisions = capture_public_cache_revisions(cache_keys)

    for dojo in dojos:
        for duration in COMMON_DURATIONS:
            try:
                cache_key = f"stats:scoreboard:dojo:{dojo.dojo_id}:{duration}"
                crews_key = cache_key.replace("stats:scoreboard:", "stats:crews:", 1)
                scoreboard = calculate_scoreboard(dojo, duration)
                set_scoreboard_cache(
                    cache_key,
                    scoreboard,
                    calculate_member_challenges(dojo, duration, scoreboard),
                    revisions=revisions,
                )
                logger.info(f"Initialized scoreboard for dojo {dojo.reference_id} (id={dojo.dojo_id}), duration={duration}")
            except Exception as e:
                logger.error(f"Error initializing scoreboard for dojo {dojo.reference_id}, duration={duration}: {e}", exc_info=True)

        for module in dojo.modules:
            for duration in COMMON_DURATIONS:
                try:
                    cache_key = f"stats:scoreboard:module:{module.dojo_id}:{module.module_index}:{duration}"
                    crews_key = cache_key.replace("stats:scoreboard:", "stats:crews:", 1)
                    scoreboard = calculate_scoreboard(module, duration)
                    set_scoreboard_cache(
                        cache_key,
                        scoreboard,
                        calculate_member_challenges(module, duration, scoreboard),
                        revisions=revisions,
                    )
                    logger.info(f"Initialized scoreboard for module {dojo.reference_id}/{module.id} (dojo_id={module.dojo_id}, module_index={module.module_index}), duration={duration}")
                except Exception as e:
                    logger.error(f"Error initializing scoreboard for module {dojo.reference_id}/{module.id}, duration={duration}: {e}", exc_info=True)

            try:
                cache_key = challenge_solves_cache_key(module.dojo_id, module.module_index)
                challenge_solves = calculate_challenge_solves(module)
                set_cached_stat(
                    cache_key,
                    challenge_solves,
                    revision=revisions[cache_key],
                )
                logger.info(f"Initialized challenge_solves for module {dojo.reference_id}/{module.id} ({len(challenge_solves)} challenges)")
            except Exception as e:
                logger.error(f"Error initializing challenge_solves for module {dojo.reference_id}/{module.id}: {e}", exc_info=True)
