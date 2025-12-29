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
    """
    Validates that the current container for the given user
    matches the given challenge. Can also check that the
    container was started before or after a given point in
    time, and that it is in a certain mode.
    """
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
    """
    Tests the dojo application with the "whoami" command.

    Likely reasons for failure are:
    - Issue with the dojo application.
    - Issue with the integrations api.
    - Issue with container (challenge -> nginx) networking.
    """
    # Make sure we have a running challenge container.
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "challenge", session=session)

    try:
        result = workspace_run("dojo whoami", user=name)
        assert name in result.stdout, f"Expected hacker to be {name}, got: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert False, f"Exception in when running command \"dojo whoami\": {(error.stdout, error.stderr)}"

def test_solve_correct(random_user, welcome_dojo):
    """
    Tests the dojo application with the "solve" command.
    
    This test case covers submitting a correct flag,
    and submitting a flag for a challenge that has already
    been solved.
    """
    # Start challenge.
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)

    # Submit.
    try:
        result = workspace_run("/challenge/solve; dojo submit $(< /flag)", user=name)
        assert "Successfully solved" in result.stdout, f"Expected to solve challenge, got: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert False, f"Exception when running command \"dojo submit\": {(error.stdout, error.stderr)}"

    # Submit again.
    try:
        result = workspace_run("dojo submit $(< /flag)", user=name)
        assert "already been solved" in result.stdout, f"Expected to solve challenge, got: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert False, f"Exception when running command \"dojo submit\": {(error.stdout, error.stderr)}"

def test_solve_incorrect(random_user, welcome_dojo):
    """
    Tests the dojo application with the "solve" command.
    
    This test case covers submitting an incorrect flag.
    """
    # Start challenge.
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)

    # Submit.
    try:
        result = workspace_run("dojo submit pwn.college{veryrealflag}", user=name)
        assert False, f"Expected submission of incorrect flag to fail, got: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert error.returncode == CLI_INCORRECT, f"Exception when running command \"dojo submit\": {(error.stdout, error.stderr)}"
        assert "incorrect" in error.stdout, f"Expected flag to be incorrect, got: {(error.stdout, error.stderr)}"

def test_solve_practice(random_user, welcome_dojo):
    """
    Tests the dojo application with the "solve" command.
    
    This test case covers submitting the practice flag.
    """
    # Start challenge.
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)

    # Submit.
    try:
        result = workspace_run("dojo submit pwn.college{practice}", user=name)
        assert False, f"Expected submission of practice flag to fail, got: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert error.returncode == CLI_INCORRECT, f"Exception when running command \"dojo submit\": {(error.stdout, error.stderr)}"
        assert "This is the practice flag" in error.stdout, f"Expected flag to be the practice flag, got: {(error.stdout, error.stderr)}"

def test_restart(random_user, welcome_dojo):
    """
    Tests the dojo application with the "restart" command.

    This test case starts a challenge, then restarts in
    both privileged and normal modes.
    """
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "flag", session=session)
    validate_restart(name, "current")
    validate_restart(name, "privileged")
    validate_restart(name, "current")
    validate_restart(name, "standard")

