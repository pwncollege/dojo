import os
import re
import sys
import subprocess
import tempfile
import pathlib
import urllib.request

import yaml
import requests
import typing
from typing import Any
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from CTFd.models import db, Users
from CTFd.utils.user import is_admin

from ...models import DojoAdmins, Dojos
from ...config import DOJOS_DIR
from ..dojo import dojo_git_command
from .dojo_builder import dojo_from_spec


DOJOS_TMP_DIR = DOJOS_DIR/"tmp"
DOJOS_TMP_DIR.mkdir(exist_ok=True)



def setdefault_name(data):
    if "import" in data:
        return
    if "name" in data:
        return
    if "id" not in data:
        return
    data["name"] = data["id"].replace("-", " ").title()


def setdefault_description(data, file_path):
    if file_path.exists():
        data.setdefault("description", file_path.read_text())


def setdefault_subyaml(data: dict[str, Any], subyaml_path: Path):
    if not subyaml_path.exists():
        return data

    topyaml_data = dict(data)
    subyaml_data = yaml.safe_load(subyaml_path.read_text())
    data.clear()
    data.update(subyaml_data)
    data.update(topyaml_data) # This overwrites any subyaml data with the "topyaml" data


def load_dojo_subyamls(data: dict[str, Any], dojo_dir: Path) -> dict[str, Any]:
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

    setdefault_description(data, dojo_dir / "DESCRIPTION.md")

    for module_data in data.get("modules", []):
        if "id" not in module_data:
            continue

        module_dir = dojo_dir / module_data["id"]
        setdefault_subyaml(module_data, module_dir / "module.yml")
        setdefault_description(module_data, module_dir / "DESCRIPTION.md")
        setdefault_name(module_data)

        for challenge_data in module_data.get("challenges", []):
            if "id" not in challenge_data:
                continue

            challenge_dir = module_dir / challenge_data["id"]
            setdefault_subyaml(challenge_data, challenge_dir / "challenge.yml")
            setdefault_description(challenge_data, challenge_dir / "DESCRIPTION.md")
            setdefault_name(challenge_data)

    return data


def dojo_initialize_files(data: dict[str, Any], dojo_dir: Path):
    for dojo_file in data.get("files", []):
        assert is_admin(), "yml-specified files support requires admin privileges"
        rel_path = dojo_dir / dojo_file["path"]

        abs_path = dojo_dir / rel_path
        assert not abs_path.is_symlink(), f"{rel_path} is a symbolic link!"
        if abs_path.exists():
            continue
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        if dojo_file["type"] == "download":
            urllib.request.urlretrieve(dojo_file["url"], str(abs_path))
            assert abs_path.stat().st_size >= 50*1024*1024, f"{rel_path} is small enough to fit into git ({abs_path.stat().st_size} bytes) --- put it in the repository!"
        if dojo_file["type"] == "text":
            with open(abs_path, "w") as o:
                o.write(dojo_file["content"])


def dojo_from_dir(dojo_dir: Path, *, dojo: typing.Optional[Dojos]=None) -> Dojos:
    dojo_yml_path = dojo_dir / "dojo.yml"
    assert dojo_yml_path.exists(), "Missing file: `dojo.yml`"

    for path in dojo_dir.rglob("**"):
        assert dojo_dir == path or dojo_dir in path.resolve().parents, f"Error: symlink `{path}` references path outside of the dojo"

    data_raw = yaml.safe_load(dojo_yml_path.read_text())
    data = load_dojo_subyamls(data_raw, dojo_dir)
    dojo_initialize_files(data, dojo_dir)

    built_dojo = dojo_from_spec(data, dojo=dojo)

    validate_challenge_paths(built_dojo, dojo_dir)
    initialize_course(built_dojo, dojo_dir)

    return built_dojo


    
def validate_challenge_paths(dojo, dojo_dir):
    with dojo.located_at(dojo_dir):
        missing_challenge_paths = [
            challenge
            for module in dojo.modules
            for challenge in module.challenges
            if not challenge.path.exists()
        ]
        assert not missing_challenge_paths, "".join(
            f"Missing challenge path: {challenge.module.id}/{challenge.id}\n"
            for challenge in missing_challenge_paths)

def initialize_course(dojo, dojo_dir):
    course_yml_path = dojo_dir / "course.yml"
    if course_yml_path.exists():
        course = yaml.safe_load(course_yml_path.read_text())

        if "discord_role" in course and not dojo.official:
            raise AssertionError("Unofficial dojos cannot have a discord role")

        dojo.course = course

        students_yml_path = dojo_dir / "students.yml"
        if students_yml_path.exists():
            students = yaml.safe_load(students_yml_path.read_text())
            dojo.course["students"] = students

        syllabus_path = dojo_dir / "SYLLABUS.md"
        if "syllabus" not in dojo.course and syllabus_path.exists():
            dojo.course["syllabus"] = syllabus_path.read_text()

        grade_path = dojo_dir / "grade.py"
        if grade_path.exists():
            dojo.course["grade_code"] = grade_path.read_text()


def dojo_yml_dir(spec: str) -> tempfile.TemporaryDirectory:
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
    tmp_dojos_dir = DOJOS_TMP_DIR
    tmp_dojos_dir.mkdir(exist_ok=True) # Creates the DOJOS_TMP_DIR if it doesn't already exist
    clone_dir = tempfile.TemporaryDirectory(dir=tmp_dojos_dir)  # TODO: ignore_cleanup_errors=True

    key_file = tempfile.NamedTemporaryFile("w")
    key_file.write(private_key)
    key_file.flush()

    url = f"https://github.com/{repository}"

    # If the github repository isn't public, the url is set so that cloning can be done over ssh
    if requests.head(url).status_code != 200:
        url = f"git@github.com:{repository}"

    subprocess.run(["git", "clone", "--depth=1", "--recurse-submodules", url, clone_dir.name],
                   env={
                       "GIT_SSH_COMMAND": f"ssh -i {key_file.name}",
                       "GIT_TERMINAL_PROMPT": "0",
                   },
                   check=True,
                   capture_output=True)

    _assert_no_symlinks(clone_dir.name)

    return clone_dir


def dojo_create(user: Users, repository: str, public_key: str, private_key: str , spec: str):
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
            raise AssertionError("Repository or specification is required")

        dojo_path = pathlib.Path(dojo_dir.name)

        dojo = dojo_from_dir(dojo_path)
        dojo.repository = repository
        dojo.public_key = public_key
        dojo.private_key = private_key
        dojo.admins = [DojoAdmins(user=user)]

        db.session.add(dojo)
        db.session.commit()

        dojo.path.parent.mkdir(exist_ok=True)
        dojo_path.rename(dojo.path)
        dojo_path.mkdir()  # TODO: ignore_cleanup_errors=True

    except subprocess.CalledProcessError as e:
        deploy_url = f"https://github.com/{repository}/settings/keys"
        raise RuntimeError(f"Failed to clone: <a href='{deploy_url}' target='_blank'>add deploy key</a>")

    except IntegrityError:
        raise RuntimeError("This repository already exists as a dojo")

    except AssertionError as e:
        raise RuntimeError(str(e))

    except Exception as e:
        print(f"Encountered error: {e}", file=sys.stderr, flush=True)
        raise RuntimeError("An error occurred while creating the dojo")

    return dojo


def dojo_update(dojo):
    if dojo.path.exists():
        old_commit = dojo_git_command(dojo, "rev-parse", "HEAD").stdout.decode().strip()

        tmp_dir = tempfile.TemporaryDirectory(dir=DOJOS_TMP_DIR)

        os.rename(str(dojo.path), tmp_dir.name)

        dojo_git_command(dojo, "fetch", "--depth=1", "origin", repo_path=tmp_dir.name)
        dojo_git_command(dojo, "reset", "--hard", "origin", repo_path=tmp_dir.name)
        dojo_git_command(dojo, "submodule", "update", "--init", "--recursive", repo_path=tmp_dir.name)

        try:
            _assert_no_symlinks(tmp_dir.name)
        except AssertionError:
            dojo_git_command(dojo, "reset", "--hard", old_commit, repo_path=tmp_dir.name)
            dojo_git_command(dojo, "submodule", "update", "--init", "--recursive", repo_path=tmp_dir.name)
            raise
        finally:
            os.rename(tmp_dir.name, str(dojo.path))
    else:
        tmpdir = dojo_clone(dojo.repository, dojo.private_key)
        os.rename(tmpdir.name, str(dojo.path))
    return dojo_from_dir(dojo.path, dojo=dojo)

