from CTFd.cache import cache
from CTFd.models import db
from sqlalchemy import text

from . import force_cache_updates, get_all_containers, DojoChallenges

@cache.memoize(timeout=1200, forced_update=force_cache_updates)
def get_container_stats():
    containers = get_all_containers()
    return [{attr: container.labels[f"dojo.{attr}_id"]
            for attr in ["dojo", "module", "challenge"]}
            for container in containers]

@cache.memoize(timeout=1200, forced_update=force_cache_updates)
def get_dojo_stats(dojo):
    
    challenge_ids = [c.challenge_id for c in dojo.challenges]

    stats = db.session.execute(
        text("""
            SELECT 
                COUNT(DISTINCT user_id) as total_users,
                COUNT(*) as total_solves
            FROM submissions
            WHERE type = 'correct'
                AND challenge_id = ANY(:challenge_ids)
        """),
        {"challenge_ids": challenge_ids}
    ).fetchone()

    recent = db.session.execute(
        text("""
            SELECT s.date, dc.name
            FROM submissions s
            INNER JOIN dojo_challenges dc ON dc.challenge_id = s.challenge_id
            WHERE s.type = 'correct'
                AND dc.dojo_id = :dojo_id
            ORDER BY s.date DESC
            LIMIT 7
        """),
        {"dojo_id": dojo.dojo_id}
    ).fetchall()

    recent_solves = [
        {
            'challenge_name': row.name,
            'date': row.date,
            'date_display': row.date.strftime('%m/%d/%y %I:%M %p') if row.date else 'Unknown time'
        }
        for row in recent
    ]

    return {
        'users': stats.total_users or 0,
        'challenges': dojo.challenges_count,
        'solves': stats.total_solves or 0,
        'recent_solves': recent_solves,
        'active': 0,
    }
