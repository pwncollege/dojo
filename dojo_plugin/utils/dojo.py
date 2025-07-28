import subprocess
import tempfile
import functools
import inspect
import pathlib

from flask import abort, g
from CTFd.utils.user import get_current_user, is_admin

from ..models import Dojos, DojoModules, DojoChallenges
from ..utils import get_current_container


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


def dojo_git_command(dojo, *args, repo_path=None):
    key_file = tempfile.NamedTemporaryFile("w")
    key_file.write(dojo.private_key)
    key_file.flush()

    if repo_path is None:
        repo_path = str(dojo.path)

    return subprocess.run(["git", "-C", repo_path, *args],
                          env={
                              "GIT_SSH_COMMAND": f"ssh -i {key_file.name}",
                              "GIT_TERMINAL_PROMPT": "0",
                          },
                          check=True,
                          capture_output=True)



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


def dojo_accessible(id: int) -> Dojos:
    if is_admin():
        return Dojos.from_id(id).first()
    return Dojos.viewable(id=id, user=get_current_user()).first()


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
