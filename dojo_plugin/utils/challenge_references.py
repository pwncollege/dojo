from sqlalchemy import event, inspect, select, text
from sqlalchemy.orm.session import Session
from CTFd.models import Challenges, db

from ..models import SurveyResponses


CHALLENGE_REFERENCE_LOCK_ID = 7067756703636089967


def lock_challenge_references(session=None):
    session = session if session is not None else db.session()
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": CHALLENGE_REFERENCE_LOCK_ID},
    )


def missing_challenge_ids(challenge_ids, session=None):
    session = session if session is not None else db.session()
    challenge_ids = list(challenge_ids)
    integer_ids = {
        challenge_id
        for challenge_id in challenge_ids
        if type(challenge_id) is int
    }
    existing_ids = set(
        session.execute(
            select(Challenges.id).where(Challenges.id.in_(integer_ids))
        ).scalars()
    ) if integer_ids else set()
    existing_ids.update(
        challenge.id
        for challenge in session.new
        if isinstance(challenge, Challenges) and challenge.id is not None
    )
    existing_ids.difference_update(
        challenge.id
        for challenge in session.deleted
        if isinstance(challenge, Challenges) and challenge.id is not None
    )
    malformed_ids = [
        challenge_id
        for challenge_id in challenge_ids
        if type(challenge_id) is not int
    ]
    return malformed_ids + sorted(integer_ids - existing_ids)


@event.listens_for(Session, "before_flush")
def serialize_challenge_reference_writes(session, flush_context, instances):
    survey_responses = [
        response
        for response in list(session.new) + list(session.dirty)
        if (
            isinstance(response, SurveyResponses) and
            inspect(response).attrs.challenge_id.history.has_changes()
        )
    ]
    requirements_challenges = [
        challenge
        for challenge in list(session.new) + list(session.dirty)
        if (
            isinstance(challenge, Challenges) and
            inspect(challenge).attrs.requirements.history.has_changes()
        )
    ]
    if not survey_responses and not requirements_challenges:
        return

    lock_challenge_references(session)
    missing_survey_challenge_ids = missing_challenge_ids(
        [response.challenge_id for response in survey_responses],
        session,
    )
    if missing_survey_challenge_ids:
        raise ValueError(
            "Survey responses reference missing challenges: "
            f"{sorted(missing_survey_challenge_ids, key=str)}"
        )

    prerequisite_ids = []
    for challenge in requirements_challenges:
        requirements = challenge.requirements
        if not isinstance(requirements, dict):
            continue
        prerequisites = requirements.get("prerequisites")
        if not isinstance(prerequisites, list):
            continue
        prerequisite_ids.extend(
            prerequisite
            for prerequisite in prerequisites
            if type(prerequisite) is int
        )
    missing_prerequisite_ids = missing_challenge_ids(
        prerequisite_ids,
        session,
    )
    if missing_prerequisite_ids:
        raise ValueError(
            "Challenge requirements reference missing challenges: "
            f"{sorted(missing_prerequisite_ids, key=str)}"
        )
