import json
import time
import datetime
import subprocess
from typing import Any

from utils import dojo_run, get_outer_container_for, get_user_id, workspace_run, start_challenge

CLI_INCORRECT_USAGE = 1
CLI_TOKEN_NOT_FOUND = 2
CLI_API_ERROR = 3
CLI_INCORRECT = 4

def inspect_container(username) -> dict[str, Any]:
    container_name = f"user_{get_user_id(username)}"
    args = [ "docker", "inspect", container_name ]
    try:
        outer_container = get_outer_container_for(container_name)
        result = dojo_run(*args, stdin=subprocess.DEVNULL, check=True, container=outer_container).stdout
        return json.loads(result)[0]
    except:
        return {}

def validate_current_container(username, dojo, module, challenge, attempts=5, mode:str=None, before:datetime.datetime=None, after:datetime.datetime=None) -> bool:
    for _ in range(attempts):
        container = inspect_container(username)
        try:
            labels = container["Config"]["Labels"]
            assert labels["dojo.dojo_id"] == dojo
            assert labels["dojo.module_id"] == module
            assert labels["dojo.challenge_id"] == challenge
            if mode is not None:
                assert labels["dojo.mode"] == mode
            if before is not None:
                assert before > datetime.datetime.fromisoformat(container["Created"])
            if after is not None:
                assert after < datetime.datetime.fromisoformat(container["Created"])
            return True
        except:
            time.sleep(1)
    return False

def validate_restart(username, mode):
    # Get info about current container.
    container = inspect_container(username)
    labels = container["Config"]["Labels"]

    # Restart
    command = {
        "privileged": "dojo restart -P",
        "standard": "dojo restart -N",
        "current": "dojo restart"
    }[mode]
    try:
        result = workspace_run(command, user=username)
        assert False, f"\"dojo restart\" should not have result: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        pass

    # Validate that the container is the same, and it is not the same container.
    assert validate_current_container(
        username,
        labels["dojo.dojo_id"],
        labels["dojo.module_id"],
        labels["dojo.challenge_id"],
        mode = labels["dojo.mode"] if mode == "current" else mode,
        after = datetime.datetime.fromisoformat(container["Created"]) # Should be created after the old container.
    ), f"Failed to restart:\nOriginal Container:\n{container}\nNewest Container:\n{inspect_container(username)}"

def test_whoami(random_user, welcome_dojo):
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "challenge", session=session)
    result = workspace_run("dojo whoami", user=name)
    assert name in result.stdout, f"Expected hacker to be {name}, got: {(result.stdout, result.stderr)}"

def test_solve_correct(random_user, welcome_dojo):
    # Start challenge.
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)

    # Submit.
    result = workspace_run("/challenge/solve; dojo submit $(< /flag)", user=name)
    assert "Successfully solved" in result.stdout, f"Expected to solve challenge, got: {(result.stdout, result.stderr)}"

    # Submit again.
    result = workspace_run("dojo submit $(< /flag)", user=name)
    assert "already been solved" in result.stdout, f"Expected to solve challenge, got: {(result.stdout, result.stderr)}"

def test_solve_incorrect(random_user, welcome_dojo):
    # Start challenge.
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)

    # Submit.
    try:
        result = workspace_run("dojo submit pwn.college{veryrealflag}", user=name)
        assert False, f"Expected submission of incorrect flag to fail, got: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert "Incorrect" in error.stderr, f"Expected flag to be incorrect, got: {(error.stdout, error.stderr)}"

def test_solve_practice(random_user, welcome_dojo):
    # Start challenge.
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)

    # Submit.
    try:
        result = workspace_run("dojo submit pwn.college{practice}", user=name)
        assert False, f"Expected submission of practice flag to fail, got: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert "This is the practice flag" in error.stderr, f"Expected flag to be the practice flag, got: {(error.stdout, error.stderr)}"

def test_restart(random_user, welcome_dojo):
    """
    Tests the dojo application with the "restart" command.

    This test case starts a challenge, then restarts in
    both privileged and normal modes.
    """
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "practice", session=session)
    validate_restart(name, "current")
    validate_restart(name, "privileged")
    validate_restart(name, "current")
    validate_restart(name, "standard")

def test_restart_no_practice(random_user, welcome_dojo):
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)
    try:
        result = workspace_run("dojo restart -P", user=name)
        assert False, f"\"dojo restart\" should not have succeeded: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert "does not support practice mode" in error.stderr, f"Should not be able to restart in privileged mode, got: {(error.stdout, error.stderr)}"

def format_path(name):
    container = inspect_container(name)
    labels = container.get("Config", {}).get("Labels", {})
    assert labels != {}, f"Failed to find a container for {name}."
    return f"/{labels["dojo.dojo_id"]}/{labels["dojo.module_id"]}/{labels["dojo.challenge_id"]} [{labels["dojo.mode"]}]"

def test_start_relative(random_user, welcome_dojo):
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)
    try:
        result = workspace_run("dojo start practice", user=name)
        assert False, f"\"dojo start\" should not have succeeded: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert validate_current_container(name, "welcome", "welcome", "practice"), f"Expected /welcome/welcome/practice, got {format_path(name)}."

def test_start_absolute(random_user, welcome_dojo, example_dojo):
    name, session = random_user
    start_challenge(example_dojo, "hello", "apple", session=session)
    try:
        result = workspace_run(f"dojo start /{welcome_dojo}/welcome/flag", user=name)
        assert False, f"\"dojo start\" should not have succeeded: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert validate_current_container(name, "welcome", "welcome", "flag"), f"Expected /welcome/welcome/flag, got {format_path(name)}."

def test_start_privileged(random_user, welcome_dojo):
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)
    try:
        result = workspace_run("dojo start practice -P", user=name)
        assert False, f"\"dojo start\" should not have succeeded: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert validate_current_container(name, "welcome", "welcome", "practice", mode="privileged"), f"Expected /welcome/welcome/practice [privileged], got {format_path(name)}."

def test_start_no_privileged(random_user, welcome_dojo):
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)
    try:
        result = workspace_run("dojo start challenge -P", user=name)
        assert False, f"\"dojo start\" should not have succeeded: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert "does not support practice mode" in error.stderr, f"Should not be able to start in privileged mode, got: {(error.stdout, error.stderr)}"

def test_list_dojos(random_user, welcome_dojo):
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)
    command = "dojo list /"
    try:
        slim = workspace_run(command, user=name)
        assert welcome_dojo in slim.stdout
        command = "dojo list -l /"
        wide = workspace_run(command, user=name)
        assert welcome_dojo in wide.stdout
        assert len(slim.stdout) < len(wide.stdout), f"-l should result in longer output, got: {(slim.stdout, wide.stdout)}"
    except subprocess.CalledProcessError as error:
        assert False, f"Failed to list dojos using {command}, got: {(error.stdout, error.stderr)}"

def test_list_modules(random_user, welcome_dojo):
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)
    command = f"dojo list /{welcome_dojo}"
    try:
        slim = workspace_run(command, user=name)
        assert "welcome" in slim.stdout
        command = f"dojo list -l /{welcome_dojo}"
        wide = workspace_run(command, user=name)
        assert "welcome" in wide.stdout
        assert len(slim.stdout) < len(wide.stdout), f"-l should result in longer output, got: {(slim.stdout, wide.stdout)}"
    except subprocess.CalledProcessError as error:
        assert False, f"Failed to list dojos using {command}, got: {(error.stdout, error.stderr)}"

def test_list_challenges(random_user, welcome_dojo):
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)
    command = f"dojo list /{welcome_dojo}/welcome"
    challenges = ["terminal", "vscode", "desktop", "desktop-paste", "ssh", "restart", "sensai", "challenge", "flag", "practice", "persist-1", "persist-2"]
    try:
        slim = workspace_run(command, user=name)
        for challenge in challenges:
            assert challenge in slim.stdout
        command = f"dojo list -l /{welcome_dojo}/welcome"
        wide = workspace_run(command, user=name)
        for challenge in challenges:
            assert challenge in wide.stdout
        assert len(slim.stdout) < len(wide.stdout), f"-l should result in longer output, got: {(slim.stdout, wide.stdout)}"
    except subprocess.CalledProcessError as error:
        assert False, f"Failed to list dojos using {command}, got: {(error.stdout, error.stderr)}"
