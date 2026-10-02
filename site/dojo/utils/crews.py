import re
import unicodedata

CREW_TAG_RE = re.compile(r"^(.*?)\s*\[([^\[\]]{1,24})\]\s*$", re.DOTALL)
CREW_STRIP_RE = re.compile(
    "[\u0000-\u001f\u007f-\u009f\u00ad\u034f\u17b4\u17b5\u180b-\u180e"
    "\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)
CREW_KEY_STRIP_RE = re.compile("[\ufe00-\ufe0f]")


def parse_crew_tag(name):
    match = CREW_TAG_RE.match(name or "")
    if not match:
        return None
    tag = CREW_STRIP_RE.sub("", match.group(2))
    tag = re.sub(r"\s+", " ", tag).strip()
    if not 1 <= len(tag) <= 20:
        return None
    key = unicodedata.normalize("NFKC", CREW_KEY_STRIP_RE.sub("", tag)).casefold()
    return {"tag": tag, "key": key, "base_name": match.group(1).strip()}


def aggregate_crews(standings, member_challenges=None):
    crews = {}
    for entry in standings or []:
        parsed = parse_crew_tag(entry.get("name"))
        if not parsed:
            continue
        crew = crews.get(parsed["key"])
        if crew is None:
            crew = crews[parsed["key"]] = {
                "key": parsed["key"],
                "tag": parsed["tag"],
                "score": 0,
                "best_rank": entry["rank"],
                "members": [],
            }
        crew["score"] += entry["solves"]
        member = dict(entry)
        if member_challenges is not None:
            member["challenges"] = sorted(member_challenges.get(entry["user_id"], []))
        crew["members"].append(member)

    ranked = sorted(
        crews.values(),
        key=lambda crew: (-crew["score"], len(crew["members"]), crew["best_rank"], crew["key"]),
    )
    for i, crew in enumerate(ranked):
        crew["rank"] = i + 1
        if member_challenges is not None:
            challenge_sets = [set(member["challenges"]) for member in crew["members"]]
            crew["unique"] = len(set().union(*challenge_sets)) if challenge_sets else 0
            crew["mastery"] = len(set.intersection(*challenge_sets)) if challenge_sets else 0
        else:
            crew["unique"] = None
            crew["mastery"] = None

    if member_challenges is not None:
        by_unique = sorted(
            ranked,
            key=lambda crew: (-crew["unique"], len(crew["members"]), crew["best_rank"], crew["key"]),
        )
        for i, crew in enumerate(by_unique):
            crew["unique_rank"] = i + 1
        # Bigger crews rank higher on mastery ties: a full-crew solve is harder with more members.
        by_mastery = sorted(
            ranked,
            key=lambda crew: (-crew["mastery"], -len(crew["members"]), crew["best_rank"], crew["key"]),
        )
        for i, crew in enumerate(by_mastery):
            crew["mastery_rank"] = i + 1
    else:
        for crew in ranked:
            crew["unique_rank"] = None
            crew["mastery_rank"] = None

    return ranked


def member_challenges_from_crews(crews):
    return {
        member["user_id"]: set(member.get("challenges", []))
        for crew in (crews or [])
        for member in crew.get("members", [])
    }
