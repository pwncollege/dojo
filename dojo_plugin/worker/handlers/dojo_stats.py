import logging
from datetime import datetime, timedelta
from sqlalchemy import func, desc

from CTFd.models import db, Solves
from ...models import Dojos, DojoChallenges
from ...utils.background_stats import get_cached_stat, set_cached_stat
from . import register_handler

logger = logging.getLogger(__name__)

def calculate_dojo_stats(dojo):
    now = datetime.now()
    solves_query = dojo.solves()

    total_challenges = len(dojo.challenges)
    visible_challenges = sum(1 for c in dojo.challenges if c.visible())

    total_stats = solves_query.with_entities(
        func.count(Solves.id).label('total_solves'),
        func.count(func.distinct(Solves.user_id)).label('total_users')
    ).first()

    total_solves = total_stats.total_solves or 0
    total_users = total_stats.total_users or 0

    snapshot_days = [1, 7, 30, 60]
    chart_labels = ['Today', '1w ago', '1mo ago', '2mo ago']
    chart_solves = []
    chart_users = []

    for days_ago in snapshot_days:
        snapshot_date = now - timedelta(days=days_ago)
        day_start = snapshot_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        day_stats = solves_query.filter(
            Solves.date >= day_start,
            Solves.date < day_end
        ).with_entities(
            func.count(Solves.id).label('day_solves'),
            func.count(func.distinct(Solves.user_id)).label('day_users')
        ).first()

        chart_solves.append(day_stats.day_solves or 0)
        chart_users.append(day_stats.day_users or 0)

    basic_query = (
        solves_query
        .with_entities(
            Solves.date.label('date'),
            DojoChallenges.name.label('challenge_name')
        )
        .filter(Solves.date >= now - timedelta(days=7))
        .order_by(desc(Solves.date))
        .limit(5)
        .all()
    )

    recent_solves = [
        {
            'challenge_name': f'{solve.challenge_name}',
            'date': solve.date.isoformat() if solve.date else None,
            'date_display': solve.date.strftime('%m/%d/%y %I:%M %p') if solve.date else 'Unknown time'
        }
        for solve in basic_query
    ]

    def trend_calc(current, previous):
        if previous == 0:
            return 100 if current > 0 else 0
        change = ((current - previous) / previous) * 100
        return max(-99, min(999, round(change)))

    trends = {
        'solves': trend_calc(chart_solves[0], chart_solves[1]),
        'users': trend_calc(chart_users[0], chart_users[1]),
        'active': 0,
        'challenges': 0,
    }

    return {
        'users': total_users,
        'challenges': total_challenges,
        'visible_challenges': visible_challenges,
        'solves': total_solves,
        'recent_solves': recent_solves,
        'trends': trends,
        'chart_data': {
            'labels': chart_labels,
            'solves': chart_solves,
            'users': chart_users
        }
    }

@register_handler("dojo_stats_update")
def handle_dojo_stats_update(payload):
    dojo_id = payload.get("dojo_id")

    if not dojo_id:
        logger.warning("dojo_stats_update event missing dojo_id")
        return

    logger.info(f"Handling dojo_stats_update for dojo_id={dojo_id}")

    db.session.expire_all()
    db.session.commit()

    dojo = Dojos.query.get(dojo_id)

    if not dojo:
        logger.info(f"Dojo not found for dojo_id={dojo_id} (may have been deleted)")
        return

    try:
        logger.info(f"Calculating stats for dojo {dojo.reference_id} (dojo_id={dojo_id})...")
        stats = calculate_dojo_stats(dojo)
        cache_key = f"stats:dojo:{dojo.reference_id}"
        set_cached_stat(cache_key, stats)
        logger.info(f"Successfully updated and cached stats for dojo {dojo.reference_id} (solves: {stats['solves']}, users: {stats['users']})")
    except Exception as e:
        logger.error(f"Error calculating stats for dojo_id {dojo_id}: {e}", exc_info=True)


def update_dojo_stats(stats, challenge_name):
    now = datetime.now()
    result = {
        'users': stats.get('users', 0),
        'challenges': stats.get('challenges', 0),
        'visible_challenges': stats.get('visible_challenges', 0),
        'solves': stats.get('solves', 0) + 1,
        'recent_solves': list(stats.get('recent_solves', [])),
        'trends': dict(stats.get('trends', {})),
        'chart_data': {
            'labels': stats.get('chart_data', {}).get('labels', []),
            'solves': list(stats.get('chart_data', {}).get('solves', [])),
            'users': list(stats.get('chart_data', {}).get('users', []))
        }
    }

    new_solve = {
        'challenge_name': challenge_name,
        'date': now.isoformat(),
        'date_display': now.strftime('%m/%d/%y %I:%M %p')
    }
    result['recent_solves'].insert(0, new_solve)
    result['recent_solves'] = result['recent_solves'][:5]

    if result['chart_data']['solves']:
        result['chart_data']['solves'][0] += 1

    return result


@register_handler("dojo_stats_update_solve")
def handle_dojo_stats_update_solve(payload):
    dojo_reference_id = payload.get("dojo_reference_id")
    challenge_name = payload.get("challenge_name")

    if not dojo_reference_id or not challenge_name:
        logger.warning(f"dojo_stats_update_solve event missing required fields: {payload}")
        return

    logger.info(f"Handling dojo_stats_update_solve for dojo {dojo_reference_id}, challenge {challenge_name}")

    cache_key = f"stats:dojo:{dojo_reference_id}"
    current_stats = get_cached_stat(cache_key)

    if not current_stats:
        logger.warning(f"No cached stats for dojo {dojo_reference_id}, skipping incremental update")
        return

    try:
        updated_stats = update_dojo_stats(current_stats, challenge_name)
        set_cached_stat(cache_key, updated_stats)
        logger.info(f"Updated dojo stats for {dojo_reference_id} (solves: {updated_stats['solves']})")
    except Exception as e:
        logger.error(f"Error updating dojo stats for {dojo_reference_id}: {e}", exc_info=True)


def initialize_all_dojo_stats():
    dojos = Dojos.query.all()
    logger.info(f"Initializing stats for {len(dojos)} dojos...")

    for dojo in dojos:
        try:
            stats = calculate_dojo_stats(dojo)
            cache_key = f"stats:dojo:{dojo.reference_id}"
            set_cached_stat(cache_key, stats)
            logger.info(f"Initialized stats for dojo {dojo.reference_id}")
        except Exception as e:
            logger.error(f"Error initializing stats for dojo {dojo.reference_id}: {e}", exc_info=True)
