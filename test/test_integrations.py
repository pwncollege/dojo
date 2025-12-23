import subprocess

from utils import workspace_run, start_challenge

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
        assert False, f"Exxception when running command \"dojo submit\": {(error.stdout, error.stderr)}"

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
        assert "solve" not in result.stdout, f"Expected flag to be incorrect, got: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert False, f"Exception when running command \"dojo submit\": {(error.stdout, error.stderr)}"

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
        assert "This is the practice flag" in result.stdout, f"Expected flag to be the practice flag, got: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as error:
        assert False, f"Exception when running command \"dojo submit\": {(error.stdout, error.stderr)}"
