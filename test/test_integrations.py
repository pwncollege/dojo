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
