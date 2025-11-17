from datetime import datetime
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
    stats = db.session.execute(
        text("""
            SELECT 
                COUNT(DISTINCT s.user_id) as total_users,
                COUNT(*) as total_solves
            FROM submissions s
            INNER JOIN dojo_challenges dc ON dc.challenge_id = s.challenge_id
            INNER JOIN challenges c ON c.id = s.challenge_id
            INNER JOIN users u ON u.id = s.user_id
            WHERE s.type = 'correct'
                AND dc.dojo_id = :dojo_id
                AND c.state = 'visible'
                AND u.type != 'admin'
                AND u.hidden = false
        """),
        {"dojo_id": dojo.dojo_id}
    ).fetchone()

    recent = db.session.execute(
        text("""
            WITH valid_challenges AS (
                SELECT dc.challenge_id, dc.name
                FROM dojo_challenges dc
                INNER JOIN challenges c ON c.id = dc.challenge_id
                WHERE dc.dojo_id = :dojo_id
                    AND c.state = 'visible'
            )
            SELECT s.date, vc.name
            FROM submissions s
            INNER JOIN valid_challenges vc ON vc.challenge_id = s.challenge_id
            WHERE s.type = 'correct'
                AND s.user_id IN (
                    SELECT id FROM users 
                    WHERE type != 'admin' AND hidden = false
                )
                AND s.date >= NOW() - INTERVAL '10 days'
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
        'active': 0
    }
