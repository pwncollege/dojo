import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Set
from collections import defaultdict

from sqlalchemy import text
from CTFd.models import db

logger = logging.getLogger(__name__)


@dataclass
class SolveRecord:
    solve_id: int
    user_id: int
    challenge_id: int
    date: datetime
    dojo_id: int
    module_index: int
    challenge_index: int
    challenge_name: str
    required: bool
    dojo_official: bool
    dojo_type: Optional[str]
    dojo_ref_id: str
    user_name: str
    user_email: str
    user_hidden: bool
    membership_type: Optional[str]

    @property
    def is_public_or_official(self) -> bool:
        return self.dojo_official or self.dojo_type == "public"

    @property
    def is_admin(self) -> bool:
        return self.membership_type == "admin"

    @property
    def is_member(self) -> bool:
        return self.is_public_or_official or self.membership_type is not None


@dataclass
class DojoMeta:
    dojo_id: int
    ref_id: str
    name: str
    official: bool
    dojo_type: Optional[str]
    challenge_count: int = 0
    visible_challenge_count: int = 0
    module_indexes: Set[int] = field(default_factory=set)

    @property
    def is_public_or_official(self) -> bool:
        return self.official or self.dojo_type == "public"


@dataclass
class ModuleMeta:
    dojo_id: int
    module_index: int
    module_id: str
    name: str


@dataclass
class ChallengeMeta:
    dojo_id: int
    module_index: int
    challenge_index: int
    challenge_id: int
    name: str
    required: bool


@dataclass
class VisibilityRule:
    start: Optional[datetime]
    stop: Optional[datetime]


@dataclass
class StatsIndexes:
    all_solves: List[SolveRecord] = field(default_factory=list)
    by_dojo: Dict[int, List[SolveRecord]] = field(default_factory=lambda: defaultdict(list))
    by_module: Dict[Tuple[int, int], List[SolveRecord]] = field(default_factory=lambda: defaultdict(list))
    by_user: Dict[int, List[SolveRecord]] = field(default_factory=lambda: defaultdict(list))
    dojos: Dict[int, DojoMeta] = field(default_factory=dict)
    modules: Dict[Tuple[int, int], ModuleMeta] = field(default_factory=dict)
    challenges: Dict[Tuple[int, int, int], ChallengeMeta] = field(default_factory=dict)
    visibility: Dict[Tuple[int, int, int], VisibilityRule] = field(default_factory=dict)


def load_bulk_solves(
    filter_dojo_id: Optional[int] = None,
    filter_module_index: Optional[int] = None
) -> List[SolveRecord]:
    dojo_filter = ""
    params = {}

    if filter_dojo_id is not None:
        dojo_filter = "AND dc.dojo_id = :filter_dojo_id"
        params["filter_dojo_id"] = filter_dojo_id
        if filter_module_index is not None:
            dojo_filter += " AND dc.module_index = :filter_module_index"
            params["filter_module_index"] = filter_module_index

    query = text(f"""
        SELECT
            s.id as solve_id,
            s.user_id,
            s.challenge_id,
            s.date,
            dc.dojo_id,
            dc.module_index,
            dc.challenge_index,
            dc.name as challenge_name,
            dc.required,
            d.official as dojo_official,
            d.data->>'type' as dojo_type,
            CASE
                WHEN d.official THEN d.id
                ELSE d.id || '~' || to_hex(d.dojo_id & x'ffffffff'::int)
            END as dojo_ref_id,
            u.name as user_name,
            u.email as user_email,
            u.hidden as user_hidden,
            du.type as membership_type
        FROM submissions s
        JOIN dojo_challenges dc ON dc.challenge_id = s.challenge_id
        JOIN dojos d ON d.dojo_id = dc.dojo_id
        JOIN users u ON u.id = s.user_id
        LEFT JOIN dojo_users du ON du.user_id = s.user_id AND du.dojo_id = dc.dojo_id
        WHERE s.type = 'correct'
        {dojo_filter}
        ORDER BY s.date
    """)

    logger.info(f"Loading bulk solves (filter_dojo_id={filter_dojo_id}, filter_module_index={filter_module_index})...")
    start = datetime.now()

    result = db.session.execute(query, params)
    rows = result.fetchall()

    solves = []
    for row in rows:
        solves.append(SolveRecord(
            solve_id=row.solve_id,
            user_id=row.user_id,
            challenge_id=row.challenge_id,
            date=row.date,
            dojo_id=row.dojo_id,
            module_index=row.module_index,
            challenge_index=row.challenge_index,
            challenge_name=row.challenge_name or "",
            required=row.required,
            dojo_official=row.dojo_official,
            dojo_type=row.dojo_type,
            dojo_ref_id=row.dojo_ref_id,
            user_name=row.user_name or "",
            user_email=row.user_email or "",
            user_hidden=row.user_hidden or False,
            membership_type=row.membership_type,
        ))

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"Loaded {len(solves)} solves in {elapsed:.2f}s")

    return solves


def load_dojo_metadata(
    filter_dojo_id: Optional[int] = None
) -> Tuple[Dict[int, DojoMeta], Dict[Tuple[int, int], ModuleMeta]]:
    dojo_filter = ""
    params = {}

    if filter_dojo_id is not None:
        dojo_filter = "WHERE d.dojo_id = :filter_dojo_id"
        params["filter_dojo_id"] = filter_dojo_id

    query = text(f"""
        SELECT
            d.dojo_id,
            d.id,
            d.name,
            d.official,
            d.data->>'type' as dojo_type,
            dm.module_index,
            dm.id as module_id,
            dm.name as module_name
        FROM dojos d
        LEFT JOIN dojo_modules dm ON dm.dojo_id = d.dojo_id
        {dojo_filter}
        ORDER BY d.dojo_id, dm.module_index
    """)

    result = db.session.execute(query, params)
    rows = result.fetchall()

    dojos: Dict[int, DojoMeta] = {}
    modules: Dict[Tuple[int, int], ModuleMeta] = {}

    for row in rows:
        dojo_id = row.dojo_id
        if dojo_id not in dojos:
            ref_id = row.id if row.official else f"{row.id}~{dojo_id & 0xFFFFFFFF:08x}"
            dojos[dojo_id] = DojoMeta(
                dojo_id=dojo_id,
                ref_id=ref_id,
                name=row.name or "",
                official=row.official,
                dojo_type=row.dojo_type,
            )

        if row.module_index is not None:
            dojos[dojo_id].module_indexes.add(row.module_index)
            modules[(dojo_id, row.module_index)] = ModuleMeta(
                dojo_id=dojo_id,
                module_index=row.module_index,
                module_id=row.module_id or "",
                name=row.module_name or "",
            )

    return dojos, modules


def load_challenge_metadata(
    filter_dojo_id: Optional[int] = None
) -> Dict[Tuple[int, int, int], ChallengeMeta]:
    dojo_filter = ""
    params = {}

    if filter_dojo_id is not None:
        dojo_filter = "WHERE dc.dojo_id = :filter_dojo_id"
        params["filter_dojo_id"] = filter_dojo_id

    query = text(f"""
        SELECT
            dc.dojo_id,
            dc.module_index,
            dc.challenge_index,
            dc.challenge_id,
            dc.name,
            dc.required
        FROM dojo_challenges dc
        {dojo_filter}
        ORDER BY dc.dojo_id, dc.module_index, dc.challenge_index
    """)

    result = db.session.execute(query, params)
    rows = result.fetchall()

    challenges: Dict[Tuple[int, int, int], ChallengeMeta] = {}
    for row in rows:
        key = (row.dojo_id, row.module_index, row.challenge_index)
        challenges[key] = ChallengeMeta(
            dojo_id=row.dojo_id,
            module_index=row.module_index,
            challenge_index=row.challenge_index,
            challenge_id=row.challenge_id,
            name=row.name or "",
            required=row.required,
        )

    return challenges


def load_visibility_rules(
    filter_dojo_id: Optional[int] = None
) -> Dict[Tuple[int, int, int], VisibilityRule]:
    dojo_filter = ""
    params = {}

    if filter_dojo_id is not None:
        dojo_filter = "WHERE dojo_id = :filter_dojo_id"
        params["filter_dojo_id"] = filter_dojo_id

    query = text(f"""
        SELECT dojo_id, module_index, challenge_index, start, stop
        FROM dojo_challenge_visibilities
        {dojo_filter}
    """)

    result = db.session.execute(query, params)
    rows = result.fetchall()

    visibility: Dict[Tuple[int, int, int], VisibilityRule] = {}
    for row in rows:
        key = (row.dojo_id, row.module_index, row.challenge_index)
        visibility[key] = VisibilityRule(start=row.start, stop=row.stop)

    return visibility


def build_indexes(
    filter_dojo_id: Optional[int] = None,
    filter_module_index: Optional[int] = None
) -> StatsIndexes:
    logger.info(f"Building indexes (filter_dojo_id={filter_dojo_id}, filter_module_index={filter_module_index})...")
    start = datetime.now()

    indexes = StatsIndexes()

    indexes.dojos, indexes.modules = load_dojo_metadata(filter_dojo_id)
    indexes.challenges = load_challenge_metadata(filter_dojo_id)
    indexes.visibility = load_visibility_rules(filter_dojo_id)

    for dojo_id, dojo in indexes.dojos.items():
        dojo.challenge_count = sum(
            1 for key in indexes.challenges
            if key[0] == dojo_id
        )
        dojo.visible_challenge_count = dojo.challenge_count

    solves = load_bulk_solves(filter_dojo_id, filter_module_index)
    indexes.all_solves = solves

    for solve in solves:
        indexes.by_dojo[solve.dojo_id].append(solve)
        indexes.by_module[(solve.dojo_id, solve.module_index)].append(solve)
        indexes.by_user[solve.user_id].append(solve)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"Built indexes in {elapsed:.2f}s: {len(indexes.all_solves)} solves, {len(indexes.dojos)} dojos, {len(indexes.modules)} modules")

    return indexes


def is_solve_visible(solve: SolveRecord, visibility: Dict[Tuple[int, int, int], VisibilityRule]) -> bool:
    key = (solve.dojo_id, solve.module_index, solve.challenge_index)
    rule = visibility.get(key)
    if rule is None:
        return True
    if rule.start and solve.date < rule.start:
        return False
    if rule.stop and solve.date > rule.stop:
        return False
    return True


def filter_solves_for_stats(
    solves: List[SolveRecord],
    visibility: Dict[Tuple[int, int, int], VisibilityRule],
    required_only: bool = True,
    ignore_admins: bool = True,
    ignore_hidden: bool = True,
    members_only: bool = True,
) -> List[SolveRecord]:
    result = []
    for s in solves:
        if required_only and not s.required:
            continue
        if ignore_admins and s.is_admin:
            continue
        if ignore_hidden and s.user_hidden:
            continue
        if members_only and not s.is_member:
            continue
        if not is_solve_visible(s, visibility):
            continue
        result.append(s)
    return result
