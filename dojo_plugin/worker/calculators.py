import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from collections import defaultdict

from .bulk_loader import (
    StatsIndexes, SolveRecord, DojoMeta,
    build_indexes, filter_solves_for_stats, is_solve_visible
)

logger = logging.getLogger(__name__)

COMMON_DURATIONS = [0, 7, 30]


def calculate_dojo_stats_from_indexes(
    indexes: StatsIndexes,
    filter_dojo_id: Optional[int] = None
) -> Dict[str, Dict[str, Any]]:
    now = datetime.now()
    results = {}

    dojo_ids = [filter_dojo_id] if filter_dojo_id else list(indexes.dojos.keys())

    for dojo_id in dojo_ids:
        dojo = indexes.dojos.get(dojo_id)
        if not dojo:
            continue

        solves = indexes.by_dojo.get(dojo_id, [])
        filtered_solves = filter_solves_for_stats(
            solves, indexes.visibility,
            required_only=True, ignore_admins=True, ignore_hidden=True, members_only=True
        )

        total_solves = len(filtered_solves)
        total_users = len(set(s.user_id for s in filtered_solves))

        snapshot_days = [1, 7, 30, 60]
        chart_labels = ['Today', '1w ago', '1mo ago', '2mo ago']
        chart_solves = []
        chart_users = []

        for days_ago in snapshot_days:
            snapshot_date = now - timedelta(days=days_ago)
            day_start = snapshot_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            day_solves = [s for s in filtered_solves if day_start <= s.date < day_end]
            chart_solves.append(len(day_solves))
            chart_users.append(len(set(s.user_id for s in day_solves)))

        week_ago = now - timedelta(days=7)
        recent = sorted(
            [s for s in filtered_solves if s.date >= week_ago],
            key=lambda s: s.date,
            reverse=True
        )[:5]

        recent_solves = [
            {
                'challenge_name': s.challenge_name,
                'date': s.date.isoformat() if s.date else None,
                'date_display': s.date.strftime('%m/%d/%y %I:%M %p') if s.date else 'Unknown time'
            }
            for s in recent
        ]

        def trend_calc(current, previous):
            if previous == 0:
                return 100 if current > 0 else 0
            change = ((current - previous) / previous) * 100
            return max(-99, min(999, round(change)))

        trends = {
            'solves': trend_calc(chart_solves[0], chart_solves[1]) if len(chart_solves) >= 2 else 0,
            'users': trend_calc(chart_users[0], chart_users[1]) if len(chart_users) >= 2 else 0,
            'active': 0,
            'challenges': 0,
        }

        cache_key = f"stats:dojo:{dojo.ref_id}"
        results[cache_key] = {
            'users': total_users,
            'challenges': dojo.challenge_count,
            'visible_challenges': dojo.visible_challenge_count,
            'solves': total_solves,
            'recent_solves': recent_solves,
            'trends': trends,
            'chart_data': {
                'labels': chart_labels,
                'solves': chart_solves,
                'users': chart_users
            }
        }

    return results


def calculate_scoreboards_from_indexes(
    indexes: StatsIndexes,
    filter_dojo_id: Optional[int] = None,
    filter_module_index: Optional[int] = None
) -> Dict[str, List[Dict[str, Any]]]:
    now = datetime.now()
    results = {}

    dojo_ids = [filter_dojo_id] if filter_dojo_id else list(indexes.dojos.keys())

    for dojo_id in dojo_ids:
        dojo = indexes.dojos.get(dojo_id)
        if not dojo:
            continue

        if filter_module_index is None:
            for duration in COMMON_DURATIONS:
                solves = indexes.by_dojo.get(dojo_id, [])
                scoreboard = _build_scoreboard(solves, indexes.visibility, duration, now)
                cache_key = f"stats:scoreboard:dojo:{dojo_id}:{duration}"
                results[cache_key] = scoreboard

        if filter_module_index is not None:
            module_indexes = [filter_module_index]
        else:
            module_indexes = list(dojo.module_indexes)

        for module_index in module_indexes:
            for duration in COMMON_DURATIONS:
                solves = indexes.by_module.get((dojo_id, module_index), [])
                scoreboard = _build_scoreboard(solves, indexes.visibility, duration, now)
                cache_key = f"stats:scoreboard:module:{dojo_id}:{module_index}:{duration}"
                results[cache_key] = scoreboard

    return results


def _build_scoreboard(
    solves: List[SolveRecord],
    visibility: Dict[Tuple[int, int, int], Any],
    duration: int,
    now: datetime
) -> List[Dict[str, Any]]:
    if duration > 0:
        cutoff = now - timedelta(days=duration)
        solves = [s for s in solves if s.date >= cutoff]

    filtered = filter_solves_for_stats(
        solves, visibility,
        required_only=True, ignore_admins=True, ignore_hidden=True, members_only=True
    )

    user_stats: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
        'solves': 0,
        'last_solve_id': 0,
        'name': '',
        'email': ''
    })

    for s in filtered:
        user_stats[s.user_id]['solves'] += 1
        user_stats[s.user_id]['last_solve_id'] = max(
            user_stats[s.user_id]['last_solve_id'],
            s.solve_id
        )
        user_stats[s.user_id]['name'] = s.user_name
        user_stats[s.user_id]['email'] = s.user_email

    sorted_users = sorted(
        user_stats.items(),
        key=lambda x: (-x[1]['solves'], x[1]['last_solve_id'])
    )

    return [
        {
            'rank': i + 1,
            'user_id': user_id,
            'name': data['name'],
            'email': data['email'],
            'solves': data['solves']
        }
        for i, (user_id, data) in enumerate(sorted_users)
    ]


def calculate_scores_from_indexes(
    indexes: StatsIndexes,
    filter_dojo_id: Optional[int] = None,
    filter_module_index: Optional[int] = None
) -> Dict[str, Dict[str, Any]]:
    results = {}

    dojo_ids = [filter_dojo_id] if filter_dojo_id else list(indexes.dojos.keys())

    for dojo_id in dojo_ids:
        dojo = indexes.dojos.get(dojo_id)
        if not dojo or not dojo.is_public_or_official:
            continue

        if filter_module_index is None:
            solves = indexes.by_dojo.get(dojo_id, [])
            scores = _build_scores(solves)
            cache_key = f"stats:scores:dojo:{dojo_id}"
            results[cache_key] = scores

        if filter_module_index is not None:
            module_indexes = [filter_module_index]
        else:
            module_indexes = list(dojo.module_indexes)

        for module_index in module_indexes:
            solves = indexes.by_module.get((dojo_id, module_index), [])
            scores = _build_scores(solves)
            cache_key = f"stats:scores:module:{dojo_id}:{module_index}"
            results[cache_key] = scores

    return results


def _build_scores(solves: List[SolveRecord]) -> Dict[str, Any]:
    user_solves: Dict[int, int] = defaultdict(int)
    user_last_solve: Dict[int, datetime] = {}

    for s in solves:
        user_solves[s.user_id] += 1
        if s.user_id not in user_last_solve or s.date > user_last_solve[s.user_id]:
            user_last_solve[s.user_id] = s.date

    sorted_users = sorted(
        user_solves.keys(),
        key=lambda uid: (-user_solves[uid], user_last_solve.get(uid, datetime.min))
    )

    return {
        "ranks": sorted_users,
        "solves": dict(user_solves)
    }


def calculate_activity_from_indexes(
    indexes: StatsIndexes,
    filter_user_ids: Optional[List[int]] = None
) -> Dict[str, Dict[str, Any]]:
    now = datetime.utcnow()
    one_year_ago = now - timedelta(days=365)
    results = {}

    user_timestamps: Dict[int, List[str]] = defaultdict(list)

    for solve in indexes.all_solves:
        if solve.date and solve.date >= one_year_ago:
            if filter_user_ids is None or solve.user_id in filter_user_ids:
                user_timestamps[solve.user_id].append(solve.date.isoformat() + 'Z')

    for user_id, timestamps in user_timestamps.items():
        cache_key = f"stats:activity:{user_id}"
        results[cache_key] = {
            'solve_timestamps': timestamps,
            'total_solves': len(timestamps),
        }

    return results


def calculate_all_stats(
    filter_dojo_id: Optional[int] = None,
    filter_module_index: Optional[int] = None
) -> Dict[str, Any]:
    logger.info(f"calculate_all_stats(filter_dojo_id={filter_dojo_id}, filter_module_index={filter_module_index})")
    start = datetime.now()

    indexes = build_indexes(filter_dojo_id, filter_module_index)

    results = {}

    if filter_module_index is None:
        logger.info("Calculating dojo stats...")
        dojo_stats = calculate_dojo_stats_from_indexes(indexes, filter_dojo_id)
        results.update(dojo_stats)
        logger.info(f"Calculated {len(dojo_stats)} dojo stats")

    logger.info("Calculating scoreboards...")
    scoreboards = calculate_scoreboards_from_indexes(indexes, filter_dojo_id, filter_module_index)
    results.update(scoreboards)
    logger.info(f"Calculated {len(scoreboards)} scoreboards")

    logger.info("Calculating scores...")
    scores = calculate_scores_from_indexes(indexes, filter_dojo_id, filter_module_index)
    results.update(scores)
    logger.info(f"Calculated {len(scores)} scores")

    if filter_dojo_id is None:
        logger.info("Calculating activity...")
        activity = calculate_activity_from_indexes(indexes)
        results.update(activity)
        logger.info(f"Calculated {len(activity)} user activities")

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"calculate_all_stats complete: {len(results)} cache entries in {elapsed:.2f}s")

    return results
