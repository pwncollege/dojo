from CTFd.cache import cache
from CTFd.models import Solves
from datetime import datetime, timedelta
from sqlalchemy import func, desc

from . import force_cache_updates, get_all_containers, DojoChallenges

@cache.memoize(timeout=1200, forced_update=force_cache_updates)
def get_container_stats():
    containers = get_all_containers()
    return [{attr: container.labels[f"dojo.{attr}_id"]
            for attr in ["dojo", "module", "challenge"]}
            for container in containers]

@cache.memoize(timeout=1200, forced_update=force_cache_updates)
def get_dojo_stats(dojo):
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

    # chart data
    snapshot_days = [1, 7, 30, 60]
    chart_labels = ['Today', '1w ago', '1mo ago', '2mo ago']
    chart_solves = []
    chart_users = []

    return {
        'users': total_users,
        'challenges': total_challenges,
        'visible_challenges': visible_challenges,
        'solves': total_solves,
        'recent_solves': [],
        'trends': {
            'solves': 0,
            'users': 0,
            'active': 0,
            'challenges': 0,
        },
        'chart_data': {
            'labels': chart_labels,
            'solves': chart_solves,
            'users': chart_users
        }
    }

    for days_ago in snapshot_days:
        # get day given how many days ago
        snapshot_date = now - timedelta(days=days_ago)
        day_start = snapshot_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        # get day info
        day_stats = solves_query.filter(
            Solves.date >= day_start,
            Solves.date < day_end
        ).with_entities(
            func.count(Solves.id).label('day_solves'),
            func.count(func.distinct(Solves.user_id)).label('day_users')
        ).first()

        chart_solves.append(day_stats.day_solves or 0)
        chart_users.append(day_stats.day_users or 0)

    # recent solves data
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
            'date': solve.date,
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
