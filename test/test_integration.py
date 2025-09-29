import requests
import shutil
import json
import subprocess

from .utils import DOJO_API, workspace_run, get_user_id, start_challenge, get_outer_container_for

def container_info(user):
    container_name = f"user_{get_user_id(user)}"
    outer_container = get_outer_container_for(container_name)
    result = subprocess.run(
        [shutil.which("docker"), "exec", "-i", outer_container, "docker", "inspect", container_name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if result.returncode != 0:
        assert False, f"failed to find container for {user} ({get_user_id(user)})"
    data = json.loads(result.stdout)
    return [0]

def container_token(user):
    return workspace_run("cat /run/dojo/var/auth_token", user=user).stdout.strip()

def test_int_auth(random_user_name):
    name = random_user_name
    token = container_token(name)
    id = get_user_id(name)

    result = requests.post(f"{DOJO_API}/integration/check_auth", json={"type": "container", "token": token})
    assert result.status_code == 200, f"Container authentication request failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["success"], f"Container authentication request failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["user_id"] == id, f"User ID mismatch, expected {id}, got {result.json()["user_id"]}"

def test_int_submit_current(random_user):
    name, session = random_user
    token = container_token(name)
    dojo = "welcome"
    module = "welcome"
    challenge = "challenge"

    start_challenge(dojo, module, challenge, practice=False, session=session)
    workspace_run("/challenge/solve > /tmp/out")
    flag = workspace_run("tail /tmp/out -n1").stdout.strip()

    # First submission (incorrect)
    result = requests.post(f"{DOJO_API}/integration/submit", json={"type": "container", "token": token, "flag": "pwn.college{not_a_real_flag}"})
    assert result.status_code == 200, f"Flag submission failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["success"], f"Flag submission failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["status"] == "incorrect", f"Expected flag to be incorrect: ({result.status_code}) {str(result.json())}"

    # Second submission (correct)
    result = requests.post(f"{DOJO_API}/integration/submit", json={"type": "container", "token": token, "flag": flag})
    assert result.status_code == 200, f"Flag submission failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["success"], f"Flag submission failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["status"] == "correct", f"Expected flag to be correct: ({result.status_code}) {str(result.json())}"

    # Third submission (already_solved)
    result = requests.post(f"{DOJO_API}/integration/submit", json={"type": "container", "token": token, "flag": flag})
    assert result.status_code == 200, f"Flag submission failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["success"], f"Flag submission failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["status"] == "already_solved", f"Expected challenge to already be solved: ({result.status_code}) {str(result.json())}"

def test_int_submit_other(random_user):
    name, session = random_user
    token = container_token(name)
    dojo = "welcome"
    module = "welcome"
    challenge = "challenge"

    start_challenge(dojo, module, challenge, practice=False, session=session)
    workspace_run("/challenge/solve > /tmp/out")
    flag = workspace_run("tail /tmp/out -n1").stdout.strip()
    start_challenge(dojo, module, "flag", practice=False, session=session)

    # Submit to a challenge which is not active
    data = {"type": "container", "token": token, "dojo": dojo, "module": module, "challenge": challenge, "flag": flag}
    result = requests.post(f"{DOJO_API}/integration/submit", json=data)
    assert result.status_code == 200, f"Flag submission failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["success"], f"Flag submission failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["status"] == "correct", f"Expected flag to be correct: ({result.status_code}) {str(result.json())}"

def starting_test(random_user, privileged):
    name = random_user
    token = container_token(name)
    dojo = "welcome"
    module = "welcome"
    challenge = "challenge"

    data = {"type": "container", "token": token, "dojo": dojo, "module": module, "challenge": challenge, "practice": privileged}
    result = requests.post(f"{DOJO_API}/integration/start", json=data)
    assert result.status_code == 200, f"Starting challenge failed: ({result.status_code}) {str(result.json())}"
    assert result.json()["succes"], f"Starting challenge failed: ({result.status_code}) {str(result.json())}"

    # Check the docker container has the correct info.
    info = container_info(name)
    labels = info["Config"]["Labels"]
    assert labels["dojo.dojo_id"] == dojo, f"Dojo id mismatch, expected {dojo} but got {labels["dojo.dojo_id"]}"
    assert labels["dojo.module_id"] == module, f"Module id mismatch, expected {module} but got {labels["dojo.module_id"]}"
    assert labels["dojo.challenge_id"] == challenge, f"Challenge id mismatch, expected {challenge} but got {labels["dojo.challenge_id"]}"
    assert labels["dojo.mode"] == "privileged" if privileged else "standard", f"Privilege mismatch, expected {"privileged" if privileged else "standard"} but got {labels["dojo.mode"]}"


def test_start(random_user):
    starting_test(random_user, False)

def test_privileged(random_user):
    starting_test(random_user, True)

def test_int_restart():
    pass

def test_int_list():
    pass

def test_int_list_priv():
    pass

def test_int_info():
    pass
