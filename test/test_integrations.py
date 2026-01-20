from utils import start_challenge, workspace_run


def test_whoami(random_user, welcome_dojo):
    name, session = random_user
    start_challenge(welcome_dojo, "welcome", "challenge", session=session)
    result = workspace_run("dojo whoami", user=name)
    assert name in result.stdout, f"Expected hacker to be {name}, got: {(result.stdout, result.stderr)}"
