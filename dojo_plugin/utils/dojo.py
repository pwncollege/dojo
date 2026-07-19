import contextlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import datetime
import functools
import inspect
import pathlib
import urllib.request
import uuid
import base64
import logging
import json
import emoji

import yaml
import requests
from schema import Schema, Optional, Regex, Or, Use, SchemaError, And
from flask import abort, g, has_request_context
from sqlalchemy import MetaData, Table, inspect as inspect_database, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound
from CTFd.models import db, Challenges, Flags
from CTFd.utils.user import get_current_user, is_admin

from ..models import (
    TRANSFER_PROVENANCE_VERSION,
    DojoAdmins,
    Dojos,
    DojoModules,
    DojoChallenges,
    DojoChallengeTransferProvenances,
    DojoUpdateRecalculations,
    DojoResources,
    DojoChallengeVisibilities,
    DojoResourceVisibilities,
    DojoModuleVisibilities,
)
from ..config import DOJOS_DIR
from ..utils import get_current_container, sanitize_survey
from .events import (
    publish_activity_event,
    publish_belts_event,
    publish_dojo_stats_event,
    publish_emojis_event,
    publish_scoreboard_event,
    publish_scores_event,
    queue_stat_event,
    queued_stat_events_checkpoint,
    restore_queued_stat_events,
)
from .challenge_references import lock_challenge_references
from .checkout import (
    DurableCheckoutSwap,
    bounded_run,
    checkout_barrier,
    checkout_lock,
)


DOJOS_TMP_DIR = DOJOS_DIR/"tmp"
DOJOS_TMP_DIR.mkdir(exist_ok=True)
(DOJOS_TMP_DIR / "locks").mkdir(exist_ok=True)
MAX_TRANSFER_DOJOS = 128
MAX_TRANSFER_REFERENCES = MAX_TRANSFER_DOJOS
MAX_TRANSFER_REQUESTS = 4096
MAX_DOJO_UPDATE_ATTEMPTS = 3
DOJO_UPDATE_HEAD_TIMEOUT = 15
DOJO_CLONE_TIMEOUT = 300
DOJO_NETWORK_TIMEOUT = 30
DOJO_REFERENCE_ID_LOCK_NAMESPACE = 1146047055
DOJO_UPDATE_CHECKOUT_TOKEN = "_dojo_update_checkout_token"
MAX_PENDING_DOJO_UPDATE_RECALCULATIONS = 128


class DojoUpdateAuthorizationError(RuntimeError):
    pass


class DojoUpdateStaleCheckout(RuntimeError):
    pass


class DojoCacheRecalculationPlan:
    def __init__(self):
        self.dojo_ids = set()
        self.module_ids = set()
        self.activity_user_ids = set()
        self.awards = False

    def add_dojo(self, dojo_id):
        if dojo_id is not None:
            self.dojo_ids.add(dojo_id)

    def add_module(self, dojo_id, module_index):
        self.add_dojo(dojo_id)
        if dojo_id is not None and module_index is not None:
            self.module_ids.add((dojo_id, module_index))

    def add_challenges(self, challenge_ids):
        challenge_ids = set(challenge_ids)
        if not challenge_ids:
            return
        with db.session.no_autoflush:
            associations = (
                db.session.query(
                    DojoChallenges.dojo_id,
                    DojoChallenges.module_index,
                )
                .filter(DojoChallenges.challenge_id.in_(challenge_ids))
                .all()
            )
        for dojo_id, module_index in associations:
            self.add_module(dojo_id, module_index)

    def add_activity_users(self, user_ids):
        self.activity_user_ids.update(
            user_id for user_id in user_ids if user_id is not None
        )

    def queue(self):
        for dojo_id in sorted(self.dojo_ids):
            queue_stat_event(functools.partial(publish_dojo_stats_event, dojo_id))
            queue_stat_event(
                functools.partial(publish_scoreboard_event, "dojo", dojo_id)
            )
            queue_stat_event(functools.partial(publish_scores_event, dojo_id))
        for dojo_id, module_index in sorted(self.module_ids):
            model_id = {
                "dojo_id": dojo_id,
                "module_index": module_index,
            }
            queue_stat_event(
                functools.partial(publish_scoreboard_event, "module", model_id)
            )
        for user_id in sorted(self.activity_user_ids):
            queue_stat_event(functools.partial(publish_activity_event, user_id))
        if self.awards:
            queue_stat_event(publish_belts_event)
            queue_stat_event(publish_emojis_event)

    def serialize(self):
        return {
            "dojo_ids": sorted(self.dojo_ids),
            "module_ids": [
                list(module_id) for module_id in sorted(self.module_ids)
            ],
            "activity_user_ids": sorted(self.activity_user_ids),
            "awards": self.awards,
        }

    @classmethod
    def deserialize(cls, data):
        if not isinstance(data, dict) or set(data) != {
            "dojo_ids",
            "module_ids",
            "activity_user_ids",
            "awards",
        }:
            raise RuntimeError("Invalid durable cache recalculation plan")
        plan = cls()
        dojo_ids = data["dojo_ids"]
        module_ids = data["module_ids"]
        activity_user_ids = data["activity_user_ids"]
        if not all((
            isinstance(dojo_ids, list),
            all(type(dojo_id) is int for dojo_id in dojo_ids),
            dojo_ids == sorted(set(dojo_ids)),
            isinstance(module_ids, list),
            all(
                isinstance(module_id, list) and
                len(module_id) == 2 and
                all(type(component) is int for component in module_id)
                for module_id in module_ids
            ),
            module_ids == [
                list(module_id)
                for module_id in sorted(
                    {tuple(module_id) for module_id in module_ids}
                )
            ],
            isinstance(activity_user_ids, list),
            all(type(user_id) is int for user_id in activity_user_ids),
            activity_user_ids == sorted(set(activity_user_ids)),
            type(data["awards"]) is bool,
        )):
            raise RuntimeError("Invalid durable cache recalculation plan")
        plan.dojo_ids.update(dojo_ids)
        plan.module_ids.update(
            tuple(module_id) for module_id in module_ids
        )
        plan.activity_user_ids.update(activity_user_ids)
        plan.awards = data["awards"]
        return plan

    def publish(self):
        results = []
        for dojo_id in sorted(self.dojo_ids):
            results.extend((
                publish_dojo_stats_event(dojo_id),
                publish_scoreboard_event("dojo", dojo_id),
                publish_scores_event(dojo_id),
            ))
        for dojo_id, module_index in sorted(self.module_ids):
            results.append(publish_scoreboard_event(
                "module",
                {
                    "dojo_id": dojo_id,
                    "module_index": module_index,
                },
            ))
        for user_id in sorted(self.activity_user_ids):
            results.append(publish_activity_event(user_id))
        if self.awards:
            results.extend((publish_belts_event(), publish_emojis_event()))
        if any(result is None for result in results):
            raise RuntimeError("Failed to publish dojo cache recalculation")


def create_dojo_update_recalculation(plan, token=None):
    token = token or uuid.uuid4().hex
    recalculation = DojoUpdateRecalculations(
        token=token,
        data=plan.serialize(),
        published=False,
    )
    db.session.add(recalculation)
    db.session.flush()
    return recalculation


def publish_dojo_update_recalculation(token):
    recalculation = (
        DojoUpdateRecalculations.query
        .filter_by(token=token)
        .with_for_update()
        .one_or_none()
    )
    if recalculation is None:
        return False
    if not recalculation.published:
        DojoCacheRecalculationPlan.deserialize(
            recalculation.data
        ).publish()
        recalculation.published = True
        db.session.commit()
    return True


def delete_dojo_update_recalculation(token):
    DojoUpdateRecalculations.query.filter_by(token=token).delete()
    db.session.commit()


def drain_dojo_update_recalculation(token, *, delete=False):
    if not publish_dojo_update_recalculation(token):
        return False
    if delete:
        delete_dojo_update_recalculation(token)
    return True


def drain_pending_dojo_update_recalculations(*, barrier_held=False):
    barrier_context = (
        contextlib.nullcontext()
        if barrier_held else
        checkout_barrier(DOJOS_TMP_DIR, exclusive=False)
    )
    with barrier_context:
        tokens = [
            token
            for token, in (
                db.session.query(DojoUpdateRecalculations.token)
                .filter(DojoUpdateRecalculations.published.is_(False))
                .order_by(DojoUpdateRecalculations.token)
                .limit(MAX_PENDING_DOJO_UPDATE_RECALCULATIONS + 1)
                .all()
            )
        ]
        db.session.rollback()
        if len(tokens) > MAX_PENDING_DOJO_UPDATE_RECALCULATIONS:
            raise RuntimeError("Too many pending dojo update recalculations")
        for token in tokens:
            drain_dojo_update_recalculation(token)
        (
            DojoUpdateRecalculations.query
            .filter(
                DojoUpdateRecalculations.published.is_(True),
                DojoUpdateRecalculations.created < (
                    datetime.datetime.utcnow() - datetime.timedelta(days=1)
                ),
            )
            .delete(synchronize_session=False)
        )
        db.session.commit()


def commit_dojo_update(plan, *, drain=True):
    recalculation = create_dojo_update_recalculation(plan)
    token = recalculation.token
    recalculation_id = recalculation.id
    try:
        db.session.commit()
    except BaseException:
        db.session.rollback()
        if DojoUpdateRecalculations.query.filter_by(
            id=recalculation_id,
            token=token,
        ).first() is None:
            db.session.rollback()
            raise
    if drain:
        try:
            drain_dojo_update_recalculation(token, delete=True)
        except Exception:
            db.session.rollback()
            logging.getLogger(__name__).exception(
                "Failed to publish committed dojo update recalculation"
            )
    return token


def lock_dojo_reference_ids_for_update(reference_ids):
    locked_reference_ids = frozenset(
        reference_id
        for reference_id in reference_ids
        if reference_id is not None
    )
    for reference_id in sorted(locked_reference_ids):
        db.session.execute(
            select([
                db.func.pg_advisory_xact_lock(
                    DOJO_REFERENCE_ID_LOCK_NAMESPACE,
                    db.func.hashtext(reference_id),
                )
            ])
        ).scalar()
    return locked_reference_ids


def lock_dojo_for_official_promotion(dojo, *, authorize_before_lock=None):
    dojo_database_id = dojo.dojo_id
    expected_dojo_id = dojo.id
    for _ in range(MAX_DOJO_UPDATE_ATTEMPTS):
        if (
            authorize_before_lock is not None and
            not authorize_before_lock()
        ):
            raise DojoUpdateAuthorizationError(
                "Dojo promotion authorization changed"
            )
        lock_challenge_references()
        lock_dojo_reference_ids_for_update({expected_dojo_id})
        locked_dojo = Dojos.lock_ids_for_update({dojo_database_id}).get(
            dojo_database_id
        )
        if locked_dojo is None:
            return None
        if locked_dojo.id == expected_dojo_id:
            official_owner = (
                Dojos.query
                .filter(
                    Dojos.id == expected_dojo_id,
                    Dojos.official.is_(True),
                    Dojos.dojo_id != dojo_database_id,
                )
                .first()
            )
            if official_owner is not None:
                raise RuntimeError(
                    "Another official dojo already uses this id"
                )
            return locked_dojo
        expected_dojo_id = locked_dojo.id
        db.session.rollback()
    raise RuntimeError("Dojo identity changed too frequently")

ID_REGEX = Regex(r"^[a-z0-9-]{1,32}$")
UNIQUE_ID_REGEX = Regex(r"^[a-z0-9-~]{1,128}$")
NAME_REGEX = Regex(r"^[\S ]{1,128}$")
IMAGE_REGEX = Regex(r"^[\S]{1,256}$")
FILE_PATH_REGEX = Regex(r"^[A-Za-z0-9_][A-Za-z0-9-_./]*$")
FILE_URL_REGEX = Regex(r"^https://www.dropbox.com/[a-zA-Z0-9]*/[a-zA-Z0-9]*/[a-zA-Z0-9]*/[a-zA-Z0-9.-_]*?rlkey=[a-zA-Z0-9]*&dl=1")
INTERFACES_LIST = [Or({"name": Regex(r"^[a-zA-Z][a-zA-Z0-9 _-]{0,31}$"),"port": int},{"name": "SSH"})]
DATE = Use(datetime.datetime.fromisoformat)

ID_NAME_DESCRIPTION = {
    Optional("id"): ID_REGEX,
    Optional("name"): NAME_REGEX,
    Optional("description"): str,
}

VISIBILITY = {
    Optional("visibility", default={}): {
        Optional("start"): DATE,
        Optional("stop"): DATE,
    }
}

DOJO_SPEC = Schema({
    **ID_NAME_DESCRIPTION,
    **VISIBILITY,

    Optional("password"): Regex(r"^[\S ]{8,128}$"),

    Optional("type"): ID_REGEX,
    Optional("award"): {
        Optional("emoji"): And(str, emoji.is_emoji),
        Optional("belt"): IMAGE_REGEX
    },

    Optional("image"): IMAGE_REGEX,
    Optional("privileged"): bool,
    Optional("allow_privileged"): bool,
    Optional("show_scoreboard"): bool,
    Optional("importable"): bool,
    Optional("interfaces"): INTERFACES_LIST,

    Optional("import"): {
        "dojo": UNIQUE_ID_REGEX,
    },

    Optional("auxiliary", default={}, ignore_extra_keys=True): dict,

    Optional("survey"): {
        Optional("probability"): float,
        "prompt": str,
        "data": str
    },

    Optional("survey-sources", default={}): str,

    Optional("modules", default=[]): [{
        **ID_NAME_DESCRIPTION,
        **VISIBILITY,

        Optional("image"): IMAGE_REGEX,
        Optional("privileged"): bool,
        Optional("allow_privileged"): bool,
        Optional("show_challenges"): bool,
        Optional("show_scoreboard"): bool,
        Optional("importable"): bool,
        Optional("interfaces"): INTERFACES_LIST,

        Optional("import"): {
            Optional("dojo"): UNIQUE_ID_REGEX,
            "module": ID_REGEX,
        },

        Optional("survey"): {
            Optional("probability"): float,
            "prompt": str,
            "data": str
        },

        Optional("challenges", default=[]): [dict],

        Optional("resources", default=[]): [Or(
            {
                "type": "markdown",
                "name": NAME_REGEX,
                Optional("content"): str,
                Optional("file"): FILE_PATH_REGEX,
                Optional("expandable", default=True): bool,
                **VISIBILITY,
            },
            {
                "type": "lecture",
                "name": NAME_REGEX,
                Optional("video"): str,
                Optional("playlist"): str,
                Optional("slides"): str,
                **VISIBILITY,
            },
            {
                "type": "header",
                "content": str,
                **VISIBILITY,
            },
            {
                "type": "challenge",
                "id": ID_REGEX,
                "name": NAME_REGEX,
                Optional("description"): str,
                **VISIBILITY,
                Optional("image"): IMAGE_REGEX,
                Optional("privileged"): bool,
                Optional("allow_privileged"): bool,
                Optional("importable"): bool,
                Optional("progression_locked"): bool,
                Optional("auxiliary"): dict,
                Optional("required", default=True): bool,
                Optional("import"): {
                    Optional("dojo"): UNIQUE_ID_REGEX,
                    Optional("module"): ID_REGEX,
                    "challenge": ID_REGEX,
                },
                Optional("transfer"): {
                    Optional("dojo"): UNIQUE_ID_REGEX,
                    Optional("module"): ID_REGEX,
                    "challenge": ID_REGEX,
                },
                Optional("survey"): {
                    Optional("probability"): float,
                    "prompt": str,
                    "data": str
                },
                Optional("interfaces"): INTERFACES_LIST,
            },
        )],

        Optional("auxiliary", default={}, ignore_extra_keys=True): dict,
    }],
    Optional("pages", default=[]): [str],
    Optional("files", default=[]): [Or(
        {
            "type": "download",
            "path": FILE_PATH_REGEX,
            "url": FILE_URL_REGEX,
        },
        {
            "type": "text",
            "path": FILE_PATH_REGEX,
            "content": str,
        }
    )],
})


def setdefault_name(entry):
    if "import" in entry:
        return
    if "name" in entry:
        return
    if "id" not in entry:
        return
    entry["name"] = entry["id"].replace("-", " ").title()


def setdefault_file(data, key, file_path):
    if file_path.exists():
        data.setdefault(key, file_path.read_text())


def setdefault_subyaml(data, subyaml_path):
    if not subyaml_path.exists():
        return data

    topyaml_data = dict(data)
    subyaml_data = yaml.safe_load(subyaml_path.read_text())
    data.clear()
    data.update(subyaml_data)
    data.update(topyaml_data)


def load_dojo_subyamls(data, dojo_dir):
    """
    The dojo yaml gets augmented with additional yamls and markdown files found in the dojo repo structure.

    The meta-structure is:

    repo-root/dojo.yml
    repo-root/DESCRIPTION.md <- if dojo description is missing
    repo-root/module-id/module.yml <- fills in missing fields for module in dojo.yml (only module id *needs* to be in dojo.yml)
    repo-root/module-id/DESCRIPTION.md <- if module description is missing
    repo-root/module-id/challenge-id/challenge.yml <- fills in missing fields for challenge in higher-level ymls (only challenge id *needs* to be in dojo.yml/module.yml)
    repo-root/module-id/challenge-id/DESCRIPTION.md <- if challenge description is missing

    The higher-level details override the lower-level details.
    """

    setdefault_file(data, "description", dojo_dir / "DESCRIPTION.md")

    for module_data in data.get("modules", []):
        if "id" not in module_data:
            continue

        module_dir = dojo_dir / module_data["id"]
        setdefault_subyaml(module_data, module_dir / "module.yml")
        setdefault_file(module_data, "description", module_dir / "DESCRIPTION.md")
        setdefault_name(module_data)

        if "resources" not in module_data:
            module_data["resources"] = []

        challenges = module_data.pop("challenges", [])
        if challenges:
            module_data["resources"].append({
                "type": "header",
                "content": "Challenges"
            })

            for challenge_data in challenges:
                challenge_data["type"] = "challenge"
                module_data["resources"].append(challenge_data)

        for resource_data in module_data["resources"]:
            if resource_data.get("type") == "challenge":
                if "import" in resource_data and "id" not in resource_data:
                    resource_data["id"] = resource_data["import"]["challenge"]

                if "id" not in resource_data:
                    continue

                challenge_dir = module_dir / resource_data["id"]
                setdefault_subyaml(resource_data, challenge_dir / "challenge.yml")
                setdefault_file(resource_data, "description", challenge_dir / "DESCRIPTION.md")
                setdefault_name(resource_data)

                if "import" in resource_data and "name" not in resource_data:
                    resource_data["name"] = resource_data.get("id", "Imported Challenge").replace("-", " ").title()

    return data

def load_surveys(data, dojo_dir):
    """
    Optional survey data can be stored in an arbitrary directory under dojo_dir

    This directory is specified by 'survey-sources' under the base yml file

    This function copies the html survey data into the survey.data attribute
    """

    survey_data = data.get("survey-sources", None)
    if survey_data and isinstance(survey_data, str):
        survey_dir = dojo_dir / survey_data
        if data.get("survey", {}).get("src"):
            survey_path = survey_dir / data["survey"]["src"]
            assert dojo_dir in survey_path.resolve().parents, f"Error: `{survey_path}` references path outside of the dojo"
            setdefault_file(data["survey"], "data", survey_path)
            del data["survey"]["src"]

        for module_data in data.get("modules", []):
            if module_data.get("survey", {}).get("src"):
                survey_path = survey_dir / module_data["survey"]["src"]
                assert dojo_dir in survey_path.resolve().parents, f"Error: `{survey_path}` references path outside of the dojo"
                setdefault_file(module_data["survey"], "data", survey_path)
                del module_data["survey"]["src"]

            for challenge_data in module_data.get("resources", []):
                if challenge_data["type"] != "challenge":
                    continue
                if challenge_data.get("survey", {}).get("src"):
                    survey_path = survey_dir / challenge_data["survey"]["src"]
                    assert dojo_dir in survey_path.resolve().parents, f"Error: `{survey_path}` references path outside of the dojo"
                    setdefault_file(challenge_data["survey"], "data", survey_path)
                    del challenge_data["survey"]["src"]

    return data

def dojo_initialize_files(data, dojo_dir):
    for dojo_file in data.get("files", []):
        assert is_admin(), "yml-specified files support requires admin privileges"
        rel_path = dojo_dir / dojo_file["path"]

        abs_path = dojo_dir / rel_path
        assert not abs_path.is_symlink(), f"{rel_path} is a symbolic link!"
        if abs_path.exists():
            continue
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        if dojo_file["type"] == "download":
            with (
                urllib.request.urlopen(
                    dojo_file["url"],
                    timeout=DOJO_NETWORK_TIMEOUT,
                ) as source,
                open(abs_path, "wb") as destination,
            ):
                shutil.copyfileobj(source, destination)
            assert abs_path.stat().st_size >= 50*1024*1024, f"{rel_path} is small enough to fit into git ({abs_path.stat().st_size} bytes) --- put it in the repository!"
        if dojo_file["type"] == "text":
            with open(abs_path, "w") as o:
                o.write(dojo_file["content"])


def dojo_from_dir(
    dojo_dir,
    *,
    dojo=None,
    authorize=None,
    authorize_before_lock=None,
    cache_recalculation_plan=None,
    prepare=None,
):
    dojo_yml_path = dojo_dir / "dojo.yml"
    assert dojo_yml_path.exists(), "Missing file: `dojo.yml`"

    for path in dojo_dir.rglob("**"):
        assert dojo_dir == path or dojo_dir in path.resolve().parents, f"Error: symlink `{path}` references path outside of the dojo"

    data_raw = yaml.safe_load(dojo_yml_path.read_text())
    data = load_dojo_subyamls(data_raw, dojo_dir)
    data = load_surveys(data, dojo_dir)
    dojo_initialize_files(data, dojo_dir)
    if prepare is not None:
        prepare(dojo_dir)
    return dojo_from_spec(
        data,
        dojo_dir=dojo_dir,
        dojo=dojo,
        authorize=authorize,
        authorize_before_lock=authorize_before_lock,
        cache_recalculation_plan=cache_recalculation_plan,
    )


def immutable_reference_dojo_id(reference_id):
    old_id, separator, hex_dojo_id = (reference_id or "").rpartition("~")
    if not (
        separator and
        re.fullmatch(r"[a-z0-9-]{1,32}", old_id) and
        re.fullmatch(r"[0-9a-f]{1,8}", hex_dojo_id)
    ):
        return None
    return Dojos.hex_to_int(hex_dojo_id)


def challenge_transfer_requests(dojo_data):
    requests = []
    for module_data in dojo_data.get("modules", []):
        for challenge_data in module_data.get("resources", []):
            transfer = challenge_data.get("transfer")
            if (
                challenge_data.get("type") != "challenge" or
                not transfer or
                "import" in challenge_data
            ):
                continue
            requests.append({
                "destination": (module_data["id"], challenge_data["id"]),
                "reference": transfer.get("dojo"),
                "source": (
                    transfer.get("module", module_data["id"]),
                    transfer["challenge"],
                ),
            })
    return requests


def transfer_reference_dojo_ids(reference_ids):
    dojo_ids = set()
    official_reference_ids = set()
    for reference_id in reference_ids:
        immutable_dojo_id = immutable_reference_dojo_id(reference_id)
        if immutable_dojo_id is not None:
            dojo_ids.add(immutable_dojo_id)
        else:
            official_reference_ids.add(reference_id)

    if official_reference_ids:
        with db.session.no_autoflush:
            dojo_ids.update(
                dojo_id
                for dojo_id, in Dojos.query
                .with_entities(Dojos.dojo_id)
                .filter(
                    Dojos.official.is_(True),
                    Dojos.id.in_(official_reference_ids),
                )
                .all()
            )
    return dojo_ids


def transfer_lock_dojo_ids(
    dojo_data,
    destination_dojo_id,
    *,
    lock_external_sources=True,
):
    transfer_requests = challenge_transfer_requests(dojo_data)
    if len(transfer_requests) > MAX_TRANSFER_REQUESTS:
        raise RuntimeError("Too many challenge transfers in one update")

    reference_ids = {
        request["reference"]
        for request in transfer_requests
        if request["reference"] is not None
    }
    if len(reference_ids) > MAX_TRANSFER_REFERENCES:
        raise RuntimeError("Too many dojo references participate in one update")

    dojo_ids = {destination_dojo_id} if destination_dojo_id is not None else set()
    if lock_external_sources:
        dojo_ids.update(transfer_reference_dojo_ids(reference_ids))
    dojo_ids.discard(None)
    if len(dojo_ids) > MAX_TRANSFER_DOJOS:
        raise RuntimeError("Too many dojos participate in one update")
    return dojo_ids


def lock_transfer_dojos_for_update(
    dojo_data,
    dojo,
    *,
    lock_external_sources,
):
    destination_dojo_id = dojo.dojo_id if dojo is not None else None
    requested_dojo_ids = transfer_lock_dojo_ids(
        dojo_data,
        destination_dojo_id,
        lock_external_sources=lock_external_sources,
    )
    locked_dojos = Dojos.lock_ids_for_update(requested_dojo_ids)
    if destination_dojo_id is not None and destination_dojo_id not in locked_dojos:
        raise RuntimeError("Dojo no longer exists")

    revalidated_dojo_ids = transfer_lock_dojo_ids(
        dojo_data,
        destination_dojo_id,
        lock_external_sources=lock_external_sources,
    )
    with db.session.no_autoflush:
        unlocked_existing_dojo_ids = {
            dojo_id
            for dojo_id in revalidated_dojo_ids - set(locked_dojos)
            if Dojos.query.filter_by(dojo_id=dojo_id).first() is not None
        }
    if unlocked_existing_dojo_ids:
        raise RuntimeError("Challenge transfer sources changed while acquiring update locks")
    return locked_dojos.get(destination_dojo_id, dojo), locked_dojos


def dojo_from_spec(
    data,
    *,
    dojo_dir=None,
    dojo=None,
    authorize=None,
    authorize_before_lock=None,
    authorize_legacy_replay=None,
    cache_recalculation_plan=None,
):
    try:
        dojo_data = DOJO_SPEC.validate(data)
    except SchemaError as e:
        raise AssertionError(e)  # TODO: this probably shouldn't be re-raised as an AssertionError

    existing_dojo = dojo is not None
    transfer_lock_dojo_ids(
        dojo_data,
        dojo.dojo_id if existing_dojo else None,
        lock_external_sources=False,
    )
    if authorize_before_lock is not None and not authorize_before_lock(dojo):
        raise DojoUpdateAuthorizationError("Dojo update authorization changed")
    proposed_dojo_id = dojo_data.get("id")
    if proposed_dojo_id is None and "import" in dojo_data:
        proposed_dojo_id = dojo_data["import"]["dojo"].split("~", 1)[0]
    assert proposed_dojo_id is not None, "Dojo id must be defined"
    global_admin_authorized = bool(
        authorize_legacy_replay and authorize_legacy_replay()
    ) if authorize_legacy_replay is not None else bool(
        has_request_context() and is_admin()
    )
    lock_challenge_references()
    locked_reference_ids = lock_dojo_reference_ids_for_update({
        proposed_dojo_id,
        dojo.id if existing_dojo else None,
    })
    if existing_dojo:
        with db.session.no_autoflush:
            db.session.refresh(dojo, attribute_names=["id", "official"])
        if dojo.id not in locked_reference_ids:
            raise RuntimeError(
                "Dojo identity changed while acquiring update locks"
            )
    def other_official_dojo():
        query = Dojos.query.filter(
            Dojos.id == proposed_dojo_id,
            Dojos.official.is_(True),
        )
        if existing_dojo:
            query = query.filter(Dojos.dojo_id != dojo.dojo_id)
        return query.first()

    with db.session.no_autoflush:
        official_twin_absent = other_official_dojo() is None
    if existing_dojo and dojo.official and not official_twin_absent:
        raise RuntimeError("Another official dojo already uses this id")
    global_admin_destination_allowed = bool(
        global_admin_authorized and official_twin_absent
    )
    lock_external_sources = bool(
        (existing_dojo and dojo.official) or
        global_admin_destination_allowed
    )
    dojo, locked_transfer_dojos = lock_transfer_dojos_for_update(
        dojo_data,
        dojo,
        lock_external_sources=lock_external_sources,
    )
    if existing_dojo:
        if dojo.id not in locked_reference_ids:
            raise RuntimeError(
                "Dojo identity changed while acquiring update locks"
            )
        with db.session.no_autoflush:
            revalidated_official_twin_absent = (
                other_official_dojo() is None
            )
            revalidated_external_authority = bool(
                dojo.official or
                (
                    global_admin_authorized and
                    revalidated_official_twin_absent
                )
            )
        if revalidated_external_authority != lock_external_sources:
            raise RuntimeError(
                "Dojo transfer authority changed while acquiring update locks"
            )
        if dojo.official and not revalidated_official_twin_absent:
            raise RuntimeError("Another official dojo already uses this id")
        official_twin_absent = revalidated_official_twin_absent
    if authorize is not None and not authorize(dojo):
        raise DojoUpdateAuthorizationError("Dojo update authorization changed")
    self_transfer_reference_ids = (
        {dojo.id, dojo.reference_id}
        if existing_dojo else set()
    )
    if existing_dojo and cache_recalculation_plan is not None:
        cache_recalculation_plan.add_dojo(dojo.dojo_id)
        for module in dojo.modules:
            cache_recalculation_plan.add_module(
                dojo.dojo_id,
                module.module_index,
            )

    def assert_dojo_challenge_type(dojo_challenge):
        if (
            dojo_challenge.challenge is None or
            dojo_challenge.challenge.type != "dojo"
        ):
            raise AssertionError(
                "Dojo challenge association must reference a challenge of type `dojo`"
            )

    def assert_importable(o):
        assert o.importable, f"Import disallowed for {o}."
        if isinstance(o, Dojos):
            for m in o.modules:
                assert_importable(m)
        elif isinstance(o, DojoModules):
            for c in o.challenges:
                assert_importable(c)
        elif isinstance(o, DojoChallenges):
            assert_dojo_challenge_type(o)

    def assert_import_one(query, error_message):
        try:
            o = query.one()
            assert_importable(o)
            return o
        except NoResultFound:
            raise AssertionError(error_message)

    # TODO: we probably don't need to restrict imports to official dojos
    import_dojo = (
        assert_import_one(Dojos.from_id(dojo_data["import"]["dojo"]).filter_by(official=True),
                   "Import dojo `{dojo_data['import']['dojo']}` does not exist")
        if "import" in dojo_data else None
    )

    dojo_kwargs = {
        field: dojo_data.get(field, getattr(import_dojo, field, None))
        for field in ["id", "name", "description", "password", "type", "award"]
    }

    assert dojo_kwargs.get("id") is not None, "Dojo id must be defined"
    if dojo_kwargs["id"] != proposed_dojo_id:
        raise RuntimeError("Proposed dojo identity changed during update")

    if not existing_dojo:
        dojo = Dojos(**dojo_kwargs)
    else:
        for name, value in dojo_kwargs.items():
            setattr(dojo, name, value)

    existing_dojo_challenges = {
        (challenge.module.id, challenge.id): challenge
        for challenge in dojo.challenges
    }
    existing_challenges = {
        destination: dojo_challenge.challenge
        for destination, dojo_challenge in existing_dojo_challenges.items()
    }
    if any(
        challenge is None or challenge.type != "dojo"
        for challenge in existing_challenges.values()
    ):
        raise RuntimeError("Dojo challenge association references a non-dojo challenge")
    ordinary_destinations = {
        (module_data["id"], challenge_data["id"])
        for module_data in dojo_data.get("modules", [])
        for challenge_data in module_data.get("resources", [])
        if (
            challenge_data.get("type") == "challenge" and
            (not challenge_data.get("transfer") or "import" in challenge_data)
        )
    }
    provenance_records = {}

    def normalize_provenance(value):
        if not isinstance(value, dict):
            return None
        reference = value.get("dojo")
        dojo_id = value.get("dojo_id")
        module_id = value.get("module")
        challenge_id = value.get("challenge")
        if reference is not None and not isinstance(reference, str):
            return None
        if (
            dojo_id is not None and
            (not isinstance(dojo_id, int) or isinstance(dojo_id, bool))
        ):
            return None
        if not isinstance(module_id, str) or not isinstance(challenge_id, str):
            return None
        return {
            "dojo": reference,
            "dojo_id": dojo_id,
            "module": module_id,
            "challenge": challenge_id,
        }

    def provenance_record(challenge):
        if challenge is not None and challenge.type != "dojo":
            raise RuntimeError(
                "Challenge transfer provenance cannot reference a non-dojo challenge"
            )
        if challenge is None or challenge.id is None:
            return None
        if challenge.id not in provenance_records:
            provenance_records[challenge.id] = (
                DojoChallengeTransferProvenances.query
                .filter_by(challenge_id=challenge.id)
                .one_or_none()
            )
        return provenance_records[challenge.id]

    def challenge_owned_by(challenge, owner, coordinate):
        return bool(
            owner and
            challenge and
            challenge.type == "dojo" and
            challenge.category == owner.hex_dojo_id and
            challenge.name == f"{coordinate[0]}:{coordinate[1]}"
        )

    def consolidate_challenges(authoritative, duplicates, owner, coordinate):
        duplicate_ids = {challenge.id for challenge in duplicates}
        challenge_ids = duplicate_ids | {authoritative.id}
        if cache_recalculation_plan is not None:
            cache_recalculation_plan.add_challenges(challenge_ids)
            if owner.dojo_id == dojo.dojo_id:
                module_index = next(
                    (
                        module_index
                        for module_index, module_data in enumerate(
                            dojo_data["modules"]
                        )
                        if module_data["id"] == coordinate[0]
                    ),
                    None,
                )
                if module_index is None:
                    with db.session.no_autoflush:
                        module_index = (
                            db.session.query(DojoModules.module_index)
                            .filter_by(
                                dojo_id=owner.dojo_id,
                                id=coordinate[0],
                            )
                            .scalar()
                        )
            else:
                with db.session.no_autoflush:
                    module_index = (
                        db.session.query(DojoModules.module_index)
                        .filter_by(dojo_id=owner.dojo_id, id=coordinate[0])
                        .scalar()
                    )
            cache_recalculation_plan.add_module(owner.dojo_id, module_index)
            cache_recalculation_plan.awards = True
        database_inspector = inspect_database(db.engine)
        legacy_solves = db.metadata.tables.get("solves")
        if legacy_solves is None and database_inspector.has_table("solves"):
            legacy_solves = Table(
                "solves",
                MetaData(),
                autoload_with=db.engine,
            )
        submissions = db.metadata.tables.get("submissions")
        if submissions is not None:
            solve_rows = db.session.execute(
                select(
                    submissions.c.id,
                    submissions.c.user_id,
                    submissions.c.team_id,
                    submissions.c.date,
                )
                .where(
                    submissions.c.challenge_id.in_(challenge_ids),
                    submissions.c.type == "correct",
                )
                .order_by(
                    submissions.c.date.asc().nullslast(),
                    submissions.c.id,
                )
            ).all()
            seen_user_ids = set()
            seen_team_ids = set()
            duplicate_solve_ids = set()
            for solve_id, user_id, team_id, solve_date in solve_rows:
                duplicate_solve = bool(
                    (user_id is not None and user_id in seen_user_ids) or
                    (team_id is not None and team_id in seen_team_ids)
                )
                if duplicate_solve:
                    duplicate_solve_ids.add(solve_id)
                    continue
                if user_id is not None:
                    seen_user_ids.add(user_id)
                if team_id is not None:
                    seen_team_ids.add(team_id)
            if duplicate_solve_ids:
                if cache_recalculation_plan is not None:
                    cache_recalculation_plan.add_activity_users(
                        user_id
                        for solve_id, user_id, team_id, solve_date in solve_rows
                        if solve_id in duplicate_solve_ids
                    )
                if legacy_solves is not None:
                    db.session.execute(
                        legacy_solves.delete().where(
                            legacy_solves.c.id.in_(duplicate_solve_ids)
                        ),
                        execution_options={"synchronize_session": False},
                    )
                db.session.execute(
                    submissions.update().where(
                        submissions.c.id.in_(duplicate_solve_ids)
                    ).values(type="discard"),
                    execution_options={"synchronize_session": False},
                )

        provenance_rows = (
            DojoChallengeTransferProvenances.query
            .filter(
                DojoChallengeTransferProvenances.challenge_id.in_(challenge_ids)
            )
            .order_by(DojoChallengeTransferProvenances.challenge_id)
            .with_for_update()
            .all()
        )
        if len(provenance_rows) > 1:
            provenance_values = {
                (
                    record.dojo_id,
                    record.module_id,
                    record.dojo_challenge_id,
                    json.dumps(record.data, sort_keys=True),
                )
                for record in provenance_rows
            }
            if len(provenance_values) != 1:
                raise RuntimeError(
                    "Duplicate challenges have conflicting transfer provenance"
                )
        if provenance_rows:
            authoritative_record = next(
                (
                    record
                    for record in provenance_rows
                    if record.challenge_id == authoritative.id
                ),
                provenance_rows[0],
            )
            for record in provenance_rows:
                if record is not authoritative_record:
                    db.session.delete(record)
            db.session.flush()
            authoritative_record.challenge_id = authoritative.id
            db.session.flush()

        duplicate_associations = (
            DojoChallenges.query
            .filter(DojoChallenges.challenge_id.in_(duplicate_ids))
            .with_for_update()
            .all()
        )
        for association in duplicate_associations:
            association.challenge = authoritative
        db.session.flush()

        next_ids = {
            challenge.id: challenge.next_id
            for challenge in [authoritative, *duplicates]
        }
        for challenge_id in challenge_ids:
            path = set()
            current_id = challenge_id
            while current_id in challenge_ids:
                if current_id in path:
                    raise RuntimeError(
                        "Duplicate challenges contain a next-challenge cycle"
                    )
                path.add(current_id)
                current_id = next_ids[current_id]
        external_next_ids = {
            next_id
            for next_id in next_ids.values()
            if next_id is not None and next_id not in challenge_ids
        }
        if len(external_next_ids) > 1:
            raise RuntimeError(
                "Duplicate challenges have conflicting next challenges"
            )
        authoritative_next_id = next(iter(external_next_ids), None)
        current_id = authoritative_next_id
        visited_external_ids = set()
        while current_id is not None and current_id not in visited_external_ids:
            if current_id in challenge_ids:
                raise RuntimeError(
                    "Duplicate consolidation would create a next-challenge cycle"
                )
            visited_external_ids.add(current_id)
            current_id = (
                db.session.query(Challenges.next_id)
                .filter_by(id=current_id)
                .with_for_update()
                .scalar()
            )
        authoritative.next_id = authoritative_next_id
        db.session.flush()
        db.session.execute(
            Challenges.__table__.update()
            .where(
                ~Challenges.__table__.c.id.in_(challenge_ids),
                Challenges.__table__.c.next_id.in_(duplicate_ids),
            )
            .values(next_id=authoritative.id),
            execution_options={"synchronize_session": False},
        )

        handled_tables = {
            DojoChallenges.__table__.name,
            DojoChallengeTransferProvenances.__table__.name,
        }
        challenge_reference_columns = {}
        for table in db.metadata.tables.values():
            if table.name in handled_tables:
                continue
            for column in table.columns:
                if (
                    table.name == Challenges.__table__.name and
                    column.name == Challenges.next_id.name
                ):
                    continue
                if not any(
                    foreign_key.column.table.name == Challenges.__table__.name and
                    foreign_key.column.name == Challenges.id.name
                    for foreign_key in column.foreign_keys
                ):
                    continue
                challenge_reference_columns[(table.name, column.name)] = (
                    table,
                    column,
                )
        for table_name in database_inspector.get_table_names():
            if table_name in handled_tables:
                continue
            for foreign_key in database_inspector.get_foreign_keys(table_name):
                if (
                    foreign_key["referred_table"] != Challenges.__table__.name or
                    foreign_key["referred_columns"] != [Challenges.id.name] or
                    len(foreign_key["constrained_columns"]) != 1
                ):
                    continue
                column_name = foreign_key["constrained_columns"][0]
                key = (table_name, column_name)
                if key == (
                    Challenges.__table__.name,
                    Challenges.next_id.name,
                ):
                    continue
                if key in challenge_reference_columns:
                    continue
                table = Table(
                    table_name,
                    MetaData(),
                    autoload_with=db.engine,
                )
                challenge_reference_columns[key] = (table, table.c[column_name])
        for key in sorted(challenge_reference_columns):
            table, column = challenge_reference_columns[key]
            db.session.execute(
                table.update()
                .where(column.in_(duplicate_ids))
                .values({column.name: authoritative.id}),
                execution_options={"synchronize_session": False},
            )

        survey_responses = db.metadata.tables.get("survey_responses")
        if (
            survey_responses is None and
            database_inspector.has_table("survey_responses")
        ):
            survey_responses = Table(
                "survey_responses",
                MetaData(),
                autoload_with=db.engine,
            )
        if survey_responses is not None:
            db.session.execute(
                survey_responses.update()
                .where(survey_responses.c.challenge_id.in_(duplicate_ids))
                .values(challenge_id=authoritative.id),
                execution_options={"synchronize_session": False},
            )

        requirements_challenges = (
            Challenges.query
            .filter(
                Challenges.requirements.isnot(None),
                ~Challenges.id.in_(duplicate_ids),
            )
            .order_by(Challenges.id)
            .populate_existing()
            .with_for_update()
            .all()
        )
        for requirements_challenge in requirements_challenges:
            requirements = requirements_challenge.requirements
            if not isinstance(requirements, dict):
                continue
            prerequisites = requirements.get("prerequisites")
            if not isinstance(prerequisites, list):
                continue
            rewritten_prerequisites = []
            canonical_added = False
            for prerequisite in prerequisites:
                canonical_reference = (
                    type(prerequisite) is int and
                    prerequisite in challenge_ids
                )
                if not canonical_reference:
                    rewritten_prerequisites.append(prerequisite)
                elif not canonical_added:
                    rewritten_prerequisites.append(authoritative.id)
                    canonical_added = True
            if rewritten_prerequisites != prerequisites:
                requirements_challenge.requirements = {
                    **requirements,
                    "prerequisites": rewritten_prerequisites,
                }
        db.session.flush()
        db.session.execute(
            Challenges.__table__.delete().where(
                Challenges.__table__.c.id.in_(duplicate_ids)
            ),
            execution_options={"synchronize_session": False},
        )
        for duplicate in duplicates:
            if duplicate in db.session:
                db.session.expunge(duplicate)
        provenance_records.pop(authoritative.id, None)
        for duplicate_id in duplicate_ids:
            provenance_records.pop(duplicate_id, None)

    def canonical_challenge(owner, coordinate, authoritative=None):
        if owner is None:
            return None
        challenges = (
            Challenges.query
            .filter_by(
                type="dojo",
                category=owner.hex_dojo_id,
                name=f"{coordinate[0]}:{coordinate[1]}",
            )
            .order_by(Challenges.id)
            .with_for_update()
            .all()
        )
        if not challenges:
            return None
        challenge_ids = {challenge.id for challenge in challenges}
        if authoritative is None and owner.dojo_id in locked_transfer_dojos:
            with db.session.no_autoflush:
                live_challenge_ids = (
                    db.session.query(DojoChallenges.challenge_id)
                    .join(DojoChallenges.module)
                    .filter(
                        DojoChallenges.dojo_id == owner.dojo_id,
                        DojoModules.id == coordinate[0],
                        DojoChallenges.id == coordinate[1],
                        DojoChallenges.challenge_id.in_(challenge_ids),
                    )
                    .all()
                )
            if len(live_challenge_ids) > 1:
                raise RuntimeError(
                    "Dojo coordinate has multiple live challenge associations"
                )
            if live_challenge_ids:
                live_challenge_id = live_challenge_ids[0][0]
                authoritative = next(
                    challenge
                    for challenge in challenges
                    if challenge.id == live_challenge_id
                )
        if authoritative is None or authoritative.id not in challenge_ids:
            authoritative = challenges[0]
        duplicates = [
            challenge
            for challenge in challenges
            if challenge.id != authoritative.id
        ]
        if duplicates:
            consolidate_challenges(
                authoritative,
                duplicates,
                owner,
                coordinate,
            )
        return authoritative

    def challenge_at(challenge, destination):
        return challenge_owned_by(challenge, dojo, destination)

    def durable_provenance(challenge, destination):
        record = provenance_record(challenge)
        if record is None or (
            record.dojo_id != dojo.dojo_id or
            record.module_id != destination[0] or
            record.dojo_challenge_id != destination[1]
        ):
            return None
        if not challenge_at(challenge, destination):
            raise RuntimeError("Stored challenge transfer provenance conflicts with its destination")
        data = record.data or {}
        provenance = normalize_provenance(data.get("transfer"))
        if data.get("version") != TRANSFER_PROVENANCE_VERSION or provenance is None:
            raise RuntimeError("Stored challenge transfer provenance is invalid")
        return provenance

    def save_provenance(challenge, destination, provenance):
        record = provenance_record(challenge)
        if record is None:
            record = DojoChallengeTransferProvenances(challenge_id=challenge.id)
            db.session.add(record)
            provenance_records[challenge.id] = record
        record.dojo = dojo
        record.dojo_id = dojo.dojo_id
        record.module_id = destination[0]
        record.dojo_challenge_id = destination[1]
        record.data = {
            "version": TRANSFER_PROVENANCE_VERSION,
            "transfer": provenance,
        }

    def clear_provenance(challenge, destination):
        record = provenance_record(challenge)
        if record is None or (
            record.dojo_id != dojo.dojo_id or
            record.module_id != destination[0] or
            record.dojo_challenge_id != destination[1]
        ):
            return
        if record in db.session.new:
            db.session.expunge(record)
        else:
            db.session.delete(record)
        provenance_records[challenge.id] = None

    locked_official_transfer_dojos = {
        locked_dojo.id: locked_dojo
        for locked_dojo in locked_transfer_dojos.values()
        if locked_dojo.official
    }

    def source_dojo_for(request, stored):
        reference = request["reference"]
        if reference is None:
            return dojo, dojo.dojo_id
        if existing_dojo and (
            reference == dojo.id or
            reference in self_transfer_reference_ids
        ):
            return dojo, dojo.dojo_id
        immutable_dojo_id = immutable_reference_dojo_id(reference)
        if immutable_dojo_id is not None:
            return locked_transfer_dojos.get(immutable_dojo_id), immutable_dojo_id
        source_dojo = locked_official_transfer_dojos.get(reference)
        if source_dojo is not None:
            if source_dojo.dojo_id not in locked_transfer_dojos:
                raise RuntimeError("Challenge transfer source was not locked for update")
            return source_dojo, source_dojo.dojo_id
        if stored and stored["dojo"] == reference:
            return locked_transfer_dojos.get(stored["dojo_id"]), stored["dojo_id"]
        return None, None

    global_admin_transfer_allowed = bool(
        global_admin_authorized and official_twin_absent
    )
    legacy_transfer_allowed = dojo.official or global_admin_transfer_allowed
    transfer_plans = {}
    for request in challenge_transfer_requests(dojo_data):
        destination = request["destination"]
        if destination in transfer_plans:
            raise RuntimeError("Cannot transfer more than one challenge to the same destination")
        destination_association = existing_dojo_challenges.get(destination)
        destination_challenge = (
            destination_association.challenge
            if destination_association else None
        )
        if destination_challenge is None or challenge_owned_by(
            destination_challenge,
            dojo,
            destination,
        ):
            destination_challenge = canonical_challenge(
                dojo,
                destination,
                authoritative=destination_challenge,
            )
        persisted_provenance = durable_provenance(destination_challenge, destination)
        stored_provenance = persisted_provenance
        source_dojo, source_dojo_id = source_dojo_for(request, stored_provenance)
        source_module_id, source_challenge_id = request["source"]
        internal_transfer = existing_dojo and source_dojo_id == dojo.dojo_id
        provenance_replay = bool(
            stored_provenance and
            stored_provenance["dojo_id"] == source_dojo_id and
            (
                source_dojo_id is not None or
                stored_provenance["dojo"] == request["reference"]
            ) and
            stored_provenance["module"] == source_module_id and
            stored_provenance["challenge"] == source_challenge_id
        )
        if persisted_provenance and not provenance_replay:
            raise RuntimeError("Requested challenge transfer conflicts with durable transfer provenance")
        provenance = stored_provenance if provenance_replay else {
            "dojo": request["reference"],
            "dojo_id": source_dojo_id,
            "module": source_module_id,
            "challenge": source_challenge_id,
        }
        source_association = (
            existing_dojo_challenges.get(request["source"])
            if source_dojo_id == dojo.dojo_id else None
        )
        source_is_alias = bool(
            source_association and
            (
                source_association.path_override or
                not challenge_owned_by(
                    source_association.challenge,
                    source_dojo,
                    request["source"],
                )
            )
        )
        if source_association:
            source_challenge = (
                None if source_is_alias else source_association.challenge
            )
            if source_challenge is not None:
                source_challenge = canonical_challenge(
                    source_dojo,
                    request["source"],
                    authoritative=source_challenge,
                )
        else:
            source_challenge = canonical_challenge(
                source_dojo,
                request["source"],
            )
        legacy_replay = bool(
            destination_association and
            not destination_association.path_override and
            challenge_at(destination_challenge, destination) and
            stored_provenance is None and
            (
                legacy_transfer_allowed or
                (
                    source_challenge is None and
                    request["reference"] is not None
                ) or
                (
                    source_challenge is not None and
                    source_challenge.id == destination_challenge.id
                )
            )
        )
        if not (
            legacy_transfer_allowed or
            internal_transfer or
            provenance_replay or
            legacy_replay
        ):
            raise RuntimeError("Permission denied: community dojos can only transfer challenges within the same dojo")
        if provenance_replay or legacy_replay:
            transfer_plans[destination] = {
                "challenge": destination_challenge,
                "destination_challenge": destination_challenge,
                "moving": False,
                "provenance": provenance,
                "source": request["source"],
                "source_dojo_id": source_dojo_id,
            }
            continue
        if source_is_alias:
            raise RuntimeError("Cannot transfer a challenge alias that is not canonically owned by its dojo")
        if source_challenge is None:
            source_label = request["reference"] or dojo.reference_id
            raise RuntimeError(
                f"Unable to find source dojo/module/challenge in database for "
                f"{source_label}:{source_module_id}:{source_challenge_id}"
            )
        transfer_plans[destination] = {
            "challenge": source_challenge,
            "destination_challenge": destination_challenge,
            "moving": True,
            "provenance": provenance,
            "source": request["source"],
            "source_dojo_id": source_dojo_id,
        }

    moving_plans = [plan for plan in transfer_plans.values() if plan["moving"]]
    moving_challenge_ids = [plan["challenge"].id for plan in moving_plans]
    if len(moving_challenge_ids) != len(set(moving_challenge_ids)):
        raise RuntimeError("Cannot transfer the same source challenge more than once")
    moving_challenge_ids = set(moving_challenge_ids)
    if moving_challenge_ids and cache_recalculation_plan is not None:
        cache_recalculation_plan.add_challenges(moving_challenge_ids)
        destination_module_indices = {
            module_data["id"]: module_index
            for module_index, module_data in enumerate(dojo_data["modules"])
        }
        for destination, plan in transfer_plans.items():
            if plan["moving"]:
                cache_recalculation_plan.add_module(
                    dojo.dojo_id,
                    destination_module_indices[destination[0]],
                )
        cache_recalculation_plan.awards = True
    replay_challenge_ids = {
        plan["challenge"].id
        for plan in transfer_plans.values()
        if not plan["moving"]
    }
    if replay_challenge_ids & moving_challenge_ids:
        raise RuntimeError("Cannot transfer a challenge that is also used by a replayed destination")
    if len(replay_challenge_ids) != len(transfer_plans) - len(moving_plans):
        raise RuntimeError("Cannot replay the same challenge at more than one destination")
    for plan in moving_plans:
        destination_challenge = plan["destination_challenge"]
        if (
            destination_challenge and
            destination_challenge.id != plan["challenge"].id and
            destination_challenge.id not in moving_challenge_ids
        ):
            raise RuntimeError("Cannot transfer when the destination challenge already exists")

    consumed_local_sources = {
        plan["source"]
        for destination, plan in transfer_plans.items()
        if (
            plan["moving"] and
            plan["source_dojo_id"] == dojo.dojo_id and
            plan["source"] != destination
        )
    }
    if moving_plans:
        transfer_namespace = os.urandom(8).hex()
        for plan in moving_plans:
            plan["challenge"].name = f"__move__{transfer_namespace}:{plan['challenge'].id}"
        db.session.flush()
        for destination, plan in transfer_plans.items():
            if plan["moving"]:
                plan["challenge"].category = dojo.hex_dojo_id
                plan["challenge"].name = f"{destination[0]}:{destination[1]}"
        db.session.flush()

    for destination, plan in transfer_plans.items():
        if not challenge_at(plan["challenge"], destination):
            raise RuntimeError("Challenge transfer did not reach its destination")
        save_provenance(plan["challenge"], destination, plan["provenance"])
    for destination in ordinary_destinations:
        destination_challenge = existing_challenges.get(destination)
        if destination_challenge is None or challenge_at(
            destination_challenge,
            destination,
        ):
            destination_challenge = canonical_challenge(
                dojo,
                destination,
                authoritative=destination_challenge,
            )
        if destination_challenge:
            clear_provenance(destination_challenge, destination)

    def challenge(module_id, challenge_id, transfer=None):
        destination = (module_id, challenge_id)
        if transfer:
            return transfer_plans[destination]["challenge"]
        if destination in consumed_local_sources:
            return Challenges(
                type="dojo",
                category=dojo.hex_dojo_id,
                name=f"{module_id}:{challenge_id}",
                flags=[Flags(type="dojo")],
            )
        destination_challenge = existing_challenges.get(destination)
        if not challenge_at(destination_challenge, destination):
            destination_challenge = canonical_challenge(dojo, destination)
        else:
            destination_challenge = canonical_challenge(
                dojo,
                destination,
                authoritative=destination_challenge,
            )
        if destination_challenge:
            return destination_challenge
        return Challenges(type="dojo", category=dojo.hex_dojo_id, name=f"{module_id}:{challenge_id}", flags=[Flags(type="dojo")])

    def visibility(cls, *args):
        start = None
        stop = None
        for arg in args:
            start = arg.get("visibility", {}).get("start") or start
            stop = arg.get("visibility", {}).get("stop") or stop
        if start or stop:
            start = start.astimezone(datetime.timezone.utc) if start else None
            stop = stop.astimezone(datetime.timezone.utc) if stop else None
            return cls(start=start, stop=stop)

    _missing = object()
    def shadow(attr, *datas, default=_missing, default_dict=None):
        for data in reversed(datas):
            if attr in data:
                return data[attr]
        if default is not _missing:
            return default
        elif default_dict and attr in default_dict:
            return default_dict[attr]
        raise KeyError(f"Missing `{attr}` in `{datas}`")

    def survey(*datas):
        for data in reversed(datas):
            if "survey" in data:
                survey = dict(data["survey"])
                if not "data" in survey:
                    raise KeyError(f"Survey data not specified")
                survey["data"] = sanitize_survey(survey["data"])
                return survey
        return None

    def import_ids(attrs, *datas):
        datas_import = [data.get("import", {}) for data in datas]
        return tuple(shadow(id, *datas_import) for id in attrs)

    challenge_resources = []
    regular_resources = []
    for module_data in dojo_data.get("modules", []):
        for resource_index, resource_data in enumerate(module_data.get("resources", [])):
            if resource_data.get("type") == "challenge":
                resource_data["unified_index"] = resource_index
                challenge_resources.append((module_data, resource_data))
            else:
                # Handle markdown file loading
                if resource_data.get("type") == "markdown" and resource_data.get("file") and dojo_dir:
                    module_dir = dojo_dir / module_data["id"]
                    file_path = module_dir / resource_data["file"]
                    # Validate file is within dojo directory
                    try:
                        file_path = file_path.resolve()
                        dojo_dir_resolved = dojo_dir.resolve()
                        if dojo_dir_resolved not in file_path.parents and file_path != dojo_dir_resolved:
                            raise AssertionError(f"Markdown file {resource_data['file']} is outside dojo directory")
                        if file_path.exists():
                            resource_data["content"] = file_path.read_text()
                        else:
                            raise AssertionError(f"Markdown file {resource_data['file']} not found")
                    except (OSError, ValueError) as e:
                        raise AssertionError(f"Invalid markdown file path: {resource_data['file']}")
                regular_resources.append((module_data, resource_data))

    dojo.modules = [
        DojoModules(
            **{kwarg: module_data.get(kwarg) for kwarg in ["id", "name", "description"]},
            challenges=[
                DojoChallenges(
                    **{kwarg: challenge_data.get(kwarg) for kwarg in ["id", "name", "description"]},
                    image=shadow("image", dojo_data, module_data, challenge_data, default=None),
                    privileged=shadow("privileged", dojo_data, module_data, challenge_data, default_dict=DojoChallenges.data_defaults),
                    allow_privileged=shadow("allow_privileged", dojo_data, module_data, challenge_data, default_dict=DojoChallenges.data_defaults),
                    importable=shadow("importable", dojo_data, module_data, challenge_data, default_dict=DojoChallenges.data_defaults),
                    interfaces=shadow("interfaces", dojo_data, module_data, challenge_data, default_dict=DojoChallenges.data_defaults),
                    challenge=challenge(
                        module_data.get("id"), challenge_data.get("id"), transfer=challenge_data.get("transfer", None)
                    ) if "import" not in challenge_data else None,
                    progression_locked=challenge_data.get("progression_locked"),
                    required=challenge_data.get("required"),
                    visibility=visibility(DojoChallengeVisibilities, dojo_data, module_data, challenge_data),
                    survey=survey(dojo_data, module_data, challenge_data),
                    default=(assert_import_one(DojoChallenges.from_id(*import_ids(["dojo", "module", "challenge"], dojo_data, module_data, challenge_data)),
                                        f"Import challenge `{'/'.join(import_ids(['dojo', 'module', 'challenge'], dojo_data, module_data, challenge_data))}` does not exist")
                             if "import" in challenge_data else None),
                    unified_index=challenge_data.get("unified_index"),
                )
                for challenge_data in [r for m, r in challenge_resources if m == module_data]
            ],
            resources = [
                DojoResources(
                    **{kwarg: resource_data.get(kwarg) for kwarg in ["name", "type", "content", "video", "playlist", "slides", "expandable"]},
                    visibility=visibility(DojoResourceVisibilities, dojo_data, module_data, resource_data),
                    resource_index=resource_index,
                )
                for resource_index, resource_data in enumerate(module_data.get("resources", []))
                if resource_data.get("type") != "challenge"
            ],
            default=(assert_import_one(DojoModules.from_id(*import_ids(["dojo", "module"], dojo_data, module_data)),
                                f"Import module `{'/'.join(import_ids(['dojo', 'module'], dojo_data, module_data))}` does not exist")
                     if "import" in module_data else None),
            visibility=visibility(DojoModuleVisibilities, dojo_data, module_data),
            show_challenges=shadow("show_challenges", dojo_data, module_data, default_dict=DojoModules.data_defaults),
            show_scoreboard=shadow("show_scoreboard", dojo_data, module_data, default_dict=DojoModules.data_defaults),
        )
        for module_data in dojo_data["modules"]
    ] if dojo_data["modules"] or import_dojo is None else [
        DojoModules(
            default=module,
            visibility=visibility(DojoModuleVisibilities, dojo_data),
        )
        for module in (import_dojo.modules if import_dojo else [])
    ]

    for module in dojo.modules:
        for dojo_challenge in module.challenges:
            assert_dojo_challenge_type(dojo_challenge)
    if cache_recalculation_plan is not None:
        cache_recalculation_plan.add_dojo(dojo.dojo_id)
        if existing_dojo:
            for module in dojo.modules:
                cache_recalculation_plan.add_module(
                    dojo.dojo_id,
                    module.module_index,
                )

    if dojo_dir:
        with dojo.located_at(dojo_dir):
            missing_challenge_paths = [
                challenge
                for module in dojo.modules
                for challenge in module.challenges
                if not (challenge.data.get("image") or challenge.path.exists())
            ]
            assert not missing_challenge_paths, "".join(
                f"Missing challenge path: {challenge.module.id}/{challenge.id}\n"
                for challenge in missing_challenge_paths)

        course_yml_path = dojo_dir / "course.yml"
        if course_yml_path.exists():
            course = yaml.safe_load(course_yml_path.read_text())

            if "discord_role" in course and not dojo.official:
                raise AssertionError("Unofficial dojos cannot have a discord role")

            students_yml_path = dojo_dir / "students.yml"
            if "students" not in course and students_yml_path.exists():
                students = yaml.safe_load(students_yml_path.read_text())
                if isinstance(students, list):
                    students = {student_token: {} for student_token in students}
                course["students"] = students

            syllabus_path = dojo_dir / "SYLLABUS.md"
            if "syllabus" not in course and syllabus_path.exists():
                course["syllabus"] = syllabus_path.read_text()

            course_scripts = course.setdefault("scripts", {})

            grade_path = dojo_dir / "grade.py"
            if "grade" not in course and grade_path.exists():
                course_scripts["grade"] = grade_path.read_text()

            dojo.course = course

        custom_js_path = dojo_dir / "custom.js"
        if "custom_js" in dojo.permissions and custom_js_path.exists():
            dojo.custom_js = custom_js_path.read_text()

        if dojo_data.get("pages"):
            dojo.pages = dojo_data["pages"]

    return dojo


def generate_ssh_keypair():
    temp_dir = tempfile.TemporaryDirectory()
    key_dir = pathlib.Path(temp_dir.name)

    public_key = key_dir / "key.pub"
    private_key = key_dir / "key"

    subprocess.run(["ssh-keygen",
                    "-t", "ed25519",
                    "-P", "",
                    "-C", "",
                    "-f", str(private_key)],
                    check=True,
                    capture_output=True)

    return (public_key.read_text().strip(), private_key.read_text())


def dojo_yml_dir(spec):
    yml_dir = tempfile.TemporaryDirectory(dir=DOJOS_TMP_DIR)    # TODO: ignore_cleanup_errors=True
    yml_dir_path = pathlib.Path(yml_dir.name)
    with open(yml_dir_path / "dojo.yml", "w") as do:
        do.write(spec)
    return yml_dir


def _assert_no_symlinks(dojo_dir):
    if not isinstance(dojo_dir, pathlib.Path):
        dojo_dir = pathlib.Path(dojo_dir)
    for path in dojo_dir.rglob("*"):
        assert dojo_dir == path or dojo_dir in path.resolve().parents, f"Error: symlink `{path}` references path outside of the dojo"


def dojo_clone(repository, private_key):
    url = f"https://github.com/{repository}"
    if requests.head(url, timeout=DOJO_NETWORK_TIMEOUT).status_code != 200:
        url = f"git@github.com:{repository}"
    return dojo_clone_url(url, private_key)


def dojo_clone_url(url, private_key):
    DOJOS_TMP_DIR.mkdir(exist_ok=True)
    clone_dir = tempfile.TemporaryDirectory(dir=DOJOS_TMP_DIR)  # TODO: ignore_cleanup_errors=True
    key_file = tempfile.NamedTemporaryFile("w")
    key_file.write(private_key)
    key_file.flush()
    bounded_run(
        [
            "git",
            "clone",
            "--depth=1",
            "--recurse-submodules",
            url,
            clone_dir.name,
        ],
        env={
            "GIT_SSH_COMMAND": f"ssh -i {key_file.name}",
            "GIT_TERMINAL_PROMPT": "0",
        },
        timeout=DOJO_CLONE_TIMEOUT,
    )

    _assert_no_symlinks(clone_dir.name)

    return clone_dir


def dojo_git_command(dojo, *args, repo_path=None, timeout=None):
    key_file = tempfile.NamedTemporaryFile("w")
    key_file.write(dojo.private_key)
    key_file.flush()

    if repo_path is None:
        repo_path = str(dojo.path)

    return bounded_run(
        ["git", "-C", repo_path, *args],
        env={
            "GIT_SSH_COMMAND": f"ssh -i {key_file.name}",
            "GIT_TERMINAL_PROMPT": "0",
        },
        timeout=timeout,
    )


def dojo_checkout_version(dojo, repo_path):
    return dojo_git_command(
        dojo,
        "rev-parse",
        "HEAD",
        repo_path=repo_path,
        timeout=DOJO_UPDATE_HEAD_TIMEOUT,
    ).stdout.decode().strip()


def dojo_create(user, repository, public_key, private_key, spec):
    stat_events_checkpoint = queued_stat_events_checkpoint()
    cache_recalculation_plan = DojoCacheRecalculationPlan()
    committed = False
    try:
        if repository:
            repository_re = r"[\w\-]+/[\w\-]+"
            repository = repository.replace("https://github.com/", "")
            assert re.match(repository_re, repository), f"Invalid repository, expected format: <code>{repository_re}</code>"

            if Dojos.query.filter_by(repository=repository).first():
                raise AssertionError("This repository already exists as a dojo")

            dojo_dir = dojo_clone(repository, private_key)

        elif spec:
            assert is_admin(), "Must be an admin user to create dojos from spec rather than repositories"
            dojo_dir = dojo_yml_dir(spec)
            repository, public_key, private_key = None, None, None

        else:
            raise AssertionError("Repository is required")

        dojo_path = pathlib.Path(dojo_dir.name)

        dojo = dojo_from_dir(
            dojo_path,
            cache_recalculation_plan=cache_recalculation_plan,
        )
        dojo.repository = repository
        dojo.public_key = public_key
        dojo.private_key = private_key
        dojo.admins = [DojoAdmins(user=user)]

        db.session.add(dojo)
        recalculation_token = commit_dojo_update(
            cache_recalculation_plan,
            drain=False,
        )
        committed = True
        restore_queued_stat_events(stat_events_checkpoint)

        dojo.path.parent.mkdir(exist_ok=True)
        dojo_path.rename(dojo.path)
        dojo_path.mkdir()  # TODO: ignore_cleanup_errors=True

        try:
            drain_dojo_update_recalculation(
                recalculation_token,
                delete=True,
            )
        except Exception:
            db.session.rollback()
            logging.getLogger(__name__).exception(
                "Failed to publish committed dojo creation recalculation"
            )

    except subprocess.CalledProcessError as e:
        if not committed:
            db.session.rollback()
            restore_queued_stat_events(stat_events_checkpoint)
        deploy_url = f"https://github.com/{repository}/settings/keys"
        raise RuntimeError(f"Failed to clone: <a href='{deploy_url}' target='_blank'>add deploy key</a>")

    except IntegrityError:
        if not committed:
            db.session.rollback()
            restore_queued_stat_events(stat_events_checkpoint)
        raise RuntimeError("This repository already exists as a dojo")

    except AssertionError as e:
        if not committed:
            db.session.rollback()
            restore_queued_stat_events(stat_events_checkpoint)
        raise RuntimeError(str(e))

    except Exception as e:
        if not committed:
            db.session.rollback()
            restore_queued_stat_events(stat_events_checkpoint)
        traceback.print_exc(file=sys.stderr)
        raise RuntimeError("An error occurred while creating the dojo")

    return dojo


def complete_committed_dojo_update(swap):
    swap.prove_finalize()
    if swap.data["phase"] != "events_published":
        if not publish_dojo_update_recalculation(swap.token):
            raise RuntimeError("Committed dojo update has no recalculation outbox")
        swap.mark_events_published()
    else:
        recalculation = DojoUpdateRecalculations.query.filter_by(
            token=swap.token
        ).one_or_none()
        if recalculation is not None and not recalculation.published:
            raise RuntimeError(
                "Checkout journal conflicts with recalculation outbox"
            )
    delete_dojo_update_recalculation(swap.token)
    swap.finalize()


def recover_dojo_update_locked(dojo, live_path, *, include_outcome=False):
    swap = DurableCheckoutSwap.load(live_path, DOJOS_TMP_DIR)
    if swap is None:
        return (dojo, None) if include_outcome else dojo

    lock_challenge_references()
    lock_dojo_reference_ids_for_update({dojo.id})
    locked_dojo = Dojos.lock_ids_for_update({dojo.dojo_id}).get(dojo.dojo_id)
    if locked_dojo is None:
        db.session.rollback()
        raise RuntimeError("Dojo no longer exists")
    swap = DurableCheckoutSwap.load(locked_dojo.path, DOJOS_TMP_DIR)
    if swap is None:
        db.session.commit()
        return (locked_dojo, None) if include_outcome else locked_dojo

    committed_token = (locked_dojo.data or {}).get(
        DOJO_UPDATE_CHECKOUT_TOKEN
    )
    try:
        if committed_token == swap.token:
            if swap.data["phase"] not in {
                "committed",
                "finalize_proven",
                "events_published",
            }:
                swap.mark_committed()
            complete_committed_dojo_update(swap)
            outcome = "committed"
        elif committed_token == swap.data["previous_token"]:
            if DojoUpdateRecalculations.query.filter_by(
                token=swap.token
            ).first() is not None:
                raise RuntimeError(
                    "Rolled-back dojo update has a recalculation outbox"
                )
            swap.rollback()
            outcome = "rolled_back"
        else:
            raise RuntimeError(
                "Dojo database state does not match checkout swap journal"
            )
        db.session.commit()
    except BaseException:
        db.session.rollback()
        raise
    return (locked_dojo, outcome) if include_outcome else locked_dojo


def recover_dojo_update(dojo, *, barrier_held=False):
    barrier_context = (
        contextlib.nullcontext()
        if barrier_held else
        checkout_barrier(DOJOS_TMP_DIR, exclusive=False)
    )
    with barrier_context:
        live_path = dojo.path
        with checkout_lock(live_path, DOJOS_TMP_DIR):
            return recover_dojo_update_locked(dojo, live_path)


def recover_pending_dojo_updates(*, barrier_held=False):
    barrier_context = (
        contextlib.nullcontext()
        if barrier_held else
        checkout_barrier(DOJOS_TMP_DIR, exclusive=False)
    )
    with barrier_context:
        for live_name in DurableCheckoutSwap.pending_live_names(DOJOS_TMP_DIR):
            dojo_id = Dojos.hex_to_int(live_name)
            live_path = DOJOS_DIR / live_name
            with checkout_lock(live_path, DOJOS_TMP_DIR):
                with db.session.no_autoflush:
                    dojo = Dojos.query.filter_by(dojo_id=dojo_id).one_or_none()
                if dojo is None:
                    db.session.rollback()
                    raise RuntimeError(
                        "Checkout swap journal references a missing dojo"
                    )
                recover_dojo_update_locked(dojo, live_path)


def dojo_update(dojo, *, authorize=None):
    stat_events_checkpoint = queued_stat_events_checkpoint()
    dojo = recover_dojo_update(dojo)
    dojo_id = dojo.dojo_id
    with checkout_barrier(DOJOS_TMP_DIR, exclusive=False):
        with checkout_lock(dojo.path, DOJOS_TMP_DIR):
            if dojo.path.exists():
                remote_url = dojo_git_command(
                    dojo,
                    "remote",
                    "get-url",
                    "origin",
                    timeout=DOJO_UPDATE_HEAD_TIMEOUT,
                ).stdout.decode().strip()
            else:
                remote_url = None

    repository = dojo.repository
    private_key = dojo.private_key

    for attempt in range(MAX_DOJO_UPDATE_ATTEMPTS):
        if dojo is None:
            dojo = Dojos.query.filter_by(dojo_id=dojo_id).one_or_none()
            if dojo is None:
                raise RuntimeError("Dojo no longer exists")
        expected_live_path = dojo.path
        cache_recalculation_plan = DojoCacheRecalculationPlan()
        with checkout_barrier(DOJOS_TMP_DIR, exclusive=False):
            with checkout_lock(expected_live_path, DOJOS_TMP_DIR):
                expected_live_version = (
                    dojo_checkout_version(dojo, expected_live_path)
                    if expected_live_path.exists() else
                    None
                )
        staged_checkout = (
            dojo_clone_url(remote_url, private_key)
            if remote_url is not None else
            dojo_clone(repository, private_key)
        )
        staged_path = pathlib.Path(staged_checkout.name)

        def authorize_update(locked_dojo):
            if (
                locked_dojo.repository != repository or
                locked_dojo.private_key != private_key
            ):
                raise RuntimeError("Dojo repository changed during update")
            if authorize is not None and not authorize(locked_dojo):
                return False
            return True

        def authorize_staged_update(locked_dojo):
            if not authorize_update(locked_dojo):
                return False
            current_live_version = (
                dojo_checkout_version(locked_dojo, locked_dojo.path)
                if locked_dojo.path.exists() else
                None
            )
            if current_live_version != expected_live_version:
                raise DojoUpdateStaleCheckout("Dojo repository changed while waiting for update lock")
            return True

        checkout_swap = None
        prepared_checkout = None
        prepared_live_checkout = None
        commit_started = False
        swap_resolved = False
        with contextlib.ExitStack() as checkout_context:
            try:
                def prepare_checkout(path):
                    nonlocal prepared_checkout, prepared_live_checkout
                    db.session.rollback()
                    prepared_checkout = DurableCheckoutSwap.prepare(path)
                    checkout_context.enter_context(
                        checkout_barrier(DOJOS_TMP_DIR, exclusive=True)
                    )
                    checkout_context.enter_context(
                        checkout_lock(expected_live_path, DOJOS_TMP_DIR)
                    )
                    prepared_live_checkout = (
                        DurableCheckoutSwap.prepare_existing(expected_live_path)
                    )

                dojo = dojo_from_dir(
                    staged_path,
                    dojo=dojo,
                    authorize=authorize_staged_update,
                    authorize_before_lock=authorize_update,
                    cache_recalculation_plan=cache_recalculation_plan,
                    prepare=prepare_checkout,
                )
                live_path = dojo.path
                checkout_swap = DurableCheckoutSwap.begin(
                    live_path,
                    staged_path,
                    DOJOS_TMP_DIR,
                    (dojo.data or {}).get(DOJO_UPDATE_CHECKOUT_TOKEN),
                    prepared_checkout,
                    prepared_live_checkout,
                    {"transactional_outbox": True},
                )
                create_dojo_update_recalculation(
                    cache_recalculation_plan,
                    checkout_swap.token,
                )
                dojo.data = {
                    **(dojo.data or {}),
                    DOJO_UPDATE_CHECKOUT_TOKEN: checkout_swap.token,
                }
                db.session.flush()
                checkout_swap.install()
                checkout_swap.mark_commit_started()
                commit_started = True
                db.session.commit()
                restore_queued_stat_events(stat_events_checkpoint)
                checkout_swap.mark_committed()
                complete_committed_dojo_update(checkout_swap)
                swap_resolved = True
            except DojoUpdateStaleCheckout as error:
                db.session.rollback()
                restore_queued_stat_events(stat_events_checkpoint)
                staged_checkout.cleanup()
                if attempt + 1 == MAX_DOJO_UPDATE_ATTEMPTS:
                    raise RuntimeError("Dojo repository changed too frequently during update") from error
                dojo = None
                continue
            except BaseException:
                if not commit_started:
                    restore_queued_stat_events(stat_events_checkpoint)
                    db.session.rollback()
                    if checkout_swap is not None:
                        checkout_swap.rollback()
                        swap_resolved = True
                else:
                    restore_queued_stat_events(stat_events_checkpoint)
                    db.session.rollback()
                    dojo, outcome = recover_dojo_update_locked(
                        dojo,
                        dojo.path,
                        include_outcome=True,
                    )
                    if outcome is None:
                        raise RuntimeError(
                            "Checkout journal disappeared before outcome reconciliation"
                        )
                    swap_resolved = True
                    if outcome == "committed":
                        staged_checkout.cleanup()
                        return dojo
                if checkout_swap is None or swap_resolved:
                    staged_checkout.cleanup()
                raise
        staged_checkout.cleanup()
        return dojo


def dojo_accessible(id):
    if is_admin():
        return Dojos.from_id(id).first()
    return Dojos.viewable(id=id, user=get_current_user()).first()


def dojo_admins_only(func):
    signature = inspect.signature(func)
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bound_args = signature.bind(*args, **kwargs)
        bound_args.apply_defaults()

        dojo = bound_args.arguments["dojo"]
        if not (dojo.is_admin(get_current_user()) or is_admin()):
            abort(403)
        return func(*bound_args.args, **bound_args.kwargs)
    return wrapper


def dojo_route(func):
    signature = inspect.signature(func)
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bound_args = signature.bind(*args, **kwargs)
        bound_args.apply_defaults()

        dojo = dojo_accessible(bound_args.arguments["dojo"])
        if not dojo:
            abort(404)
        bound_args.arguments["dojo"] = dojo
        g.dojo = dojo

        if "module" in bound_args.arguments:
            module = DojoModules.query.filter_by(dojo=dojo, id=bound_args.arguments["module"]).first()
            if module is None:
                abort(404)
            bound_args.arguments["module"] = module

        return func(*bound_args.args, **bound_args.kwargs)
    return wrapper


def get_current_dojo_challenge(user=None):
    container = get_current_container(user)
    if not container:
        return None

    return (
        DojoChallenges.query
        .filter(DojoChallenges.id == container.labels.get("dojo.challenge_id"),
                DojoChallenges.module == DojoModules.from_id(container.labels.get("dojo.dojo_id"), container.labels.get("dojo.module_id")).first(),
                DojoChallenges.dojo == Dojos.from_id(container.labels.get("dojo.dojo_id")).first())
        .first()
    )
