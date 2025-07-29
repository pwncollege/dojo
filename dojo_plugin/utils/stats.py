from CTFd.cache import cache
from CTFd.models import Solves, Users
from datetime import datetime, timedelta
from sqlalchemy import func, desc

from . import force_cache_updates, get_all_containers, DojoChallenges
from ..models import UserPrivacySettings

@cache.memoize(timeout=1200, forced_update=force_cache_updates)
def get_container_stats():
    containers = get_all_containers()
    return [{attr: container.labels[f"dojo.{attr}_id"]
            for attr in ["dojo", "module", "challenge"]}
            for container in containers]

@cache.memoize(timeout=10, forced_update=force_cache_updates)
def get_challenge_active_users():
    containers = get_all_containers()
    challenge_users = {}
    
    for container in containers:
        try:
            challenge_id = container.labels.get("dojo.challenge_id")
            user_id = container.labels.get("dojo.user_id")
            
            if challenge_id and user_id:
                if challenge_id not in challenge_users:
                    challenge_users[challenge_id] = {}
                challenge_users[challenge_id][int(user_id)] = {
                    'container': container,
                    'started_at': container.attrs['State']['StartedAt']
                }
        except (KeyError, ValueError):
            continue
    
    # Convert to list of user data with names and durations
    result = {}
    for challenge_id, user_containers in challenge_users.items():
        users_data = []
        for user_id, container_info in user_containers.items():
            user = Users.query.filter_by(id=user_id).first()
            if user and not user.hidden:  # Respect basic privacy settings
                # Check if user allows username in activity display
                privacy_settings = UserPrivacySettings.get_or_create(user_id)
                if privacy_settings.show_username_in_activity:
                    # Calculate duration
                    from datetime import datetime
                    import dateutil.parser
                    
                    started_at = dateutil.parser.parse(container_info['started_at'])
                    now = datetime.now(started_at.tzinfo)
                    duration = now - started_at
                    
                    # Format duration
                    total_seconds = int(duration.total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    
                    if hours > 0:
                        duration_str = f"{hours}h {minutes}m"
                    else:
                        duration_str = f"{minutes}m"
                    
                    users_data.append({
                        'id': user.id,
                        'name': user.name,
                        'display_name': user.name,
                        'duration': duration_str
                    })
        result[challenge_id] = users_data
    
    return result

@cache.memoize(timeout=1200, forced_update=force_cache_updates)
def get_dojo_stats(dojo):
    now = datetime.now()
    solves_query = dojo.solves()

    total_challenges = len(dojo.challenges)
    visible_challenges = len([c for c in dojo.challenges if c.visible()])

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
