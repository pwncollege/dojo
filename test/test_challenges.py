import subprocess
import pytest
import json
import re

from utils import DOJO_HOST, workspace_run, start_challenge, solve_challenge, get_user_id

def check_mount(path, *, user, fstype=None, check_nosuid=True):
    try:
        result = workspace_run(f"findmnt -J {path}", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"'{path}' not mounted: {(e.stdout, e.stderr)}"
    assert result, f"'{path}' not mounted: {(e.stdout, e.stderr)}"

    mount_info = json.loads(result.stdout)
    assert len(mount_info.get("filesystems", [])) == 1, f"Expected exactly one filesystem, but got: {mount_info}"

    filesystem = mount_info["filesystems"][0]
    assert filesystem["target"] == path, f"Expected '{path}' to be mounted at '{path}', but got: {filesystem}"
    if fstype:
        assert filesystem["fstype"] == fstype, f"Expected '{path}' to be mounted as '{fstype}', but got: {filesystem}"
    if check_nosuid:
        assert "nosuid" in filesystem["options"], f"Expected '{path}' to be mounted nosuid, but got: {filesystem}"



def test_start_challenge(admin_session, example_dojo):
    start_challenge(example_dojo, "hello", "apple", session=admin_session)


def test_active_module_endpoint(random_user_session, example_dojo):
    start_challenge(example_dojo, "hello", "banana", session=random_user_session)
    response = random_user_session.get(f"http://{DOJO_HOST}/active-module")
    challenges = {
        "apple": {
            "challenge_id": 1,
            "challenge_name": "Apple",
            "challenge_reference_id": "apple",
            "dojo_name": "Example Dojo",
            "dojo_reference_id": "example",
            "module_id": "hello",
            "module_name": "Hello",
            "description": "<p>This is apple.</p>",
        },
        "banana": {
            "challenge_id": 2,
            "challenge_name": "Banana",
            "challenge_reference_id": "banana",
            "dojo_name": "Example Dojo",
            "dojo_reference_id": "example",
            "module_id": "hello",
            "module_name": "Hello",
            "description": "<p>This is banana.</p>",
        },
        "empty": {}
    }
    apple_description = challenges["apple"].pop("description")
    challenges["apple"]["description"] = None
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["c_current"] == challenges["banana"], f"Expected challenge 'Banana'\n{challenges['banana']}\n, but got {response.json()['c_current']}"
    assert response.json()["c_next"] == challenges["empty"], f"Expected empty {challenges['empty']} challenge, but got {response.json()['c_next']}"
    assert response.json()["c_previous"] == challenges["apple"], f"Expected challenge 'Apple'\n{challenges['apple']}\n, but got {response.json()['c_previous']}"
    challenges["apple"]["description"] = apple_description

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    response = random_user_session.get(f"http://{DOJO_HOST}/active-module")
    banana_description = challenges["banana"].pop("description")
    challenges["banana"]["description"] = None
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["c_current"] == challenges["apple"], f"Expected challenge 'Apple'\n{challenges['apple']}\n, but got {response.json()['c_current']}"
    assert response.json()["c_next"] == challenges["banana"], f"Expected challenge 'Banana'\n{challenges['banana']}\n, but got {response.json()['c_next']}"
    assert response.json()["c_previous"] == challenges["empty"], f"Expected empty {challenges['empty']} challenge, but got {response.json()['c_previous']}"
    challenges["banana"]["description"] = banana_description


def test_progression_locked(progression_locked_dojo, random_user_name, random_user_session):
    assert random_user_session.get(f"http://{DOJO_HOST}/dojo/{progression_locked_dojo}/join/").status_code == 200
    start_challenge(progression_locked_dojo, "progression-locked-module", "unlocked-challenge", session=random_user_session)

    with pytest.raises(AssertionError, match="Failed to start challenge: This challenge is locked"):
        start_challenge(progression_locked_dojo, "progression-locked-module", "locked-challenge", session=random_user_session)

    solve_challenge(progression_locked_dojo, "progression-locked-module", "unlocked-challenge", session=random_user_session, user=random_user_name)
    start_challenge(progression_locked_dojo, "progression-locked-module", "locked-challenge", session=random_user_session)


@pytest.mark.parametrize("path", ["/flag", "/challenge/apple"])
def test_workspace_path_exists(path):
    try:
        workspace_run(f"[ -f '{path}' ]", user="admin")
    except subprocess.CalledProcessError:
        assert False, f"Path does not exist: {path}"


def test_workspace_flag_permission():
    try:
        workspace_run("cat /flag", user="admin")
    except subprocess.CalledProcessError as e:
        assert "Permission denied" in e.stderr, f"Expected permission denied, but got: {(e.stdout, e.stderr)}"
    else:
        assert False, f"Expected permission denied, but got no error: {(e.stdout, e.stderr)}"


def test_workspace_challenge():
    result = workspace_run("/challenge/apple", user="admin")
    match = re.search("pwn.college{(\\S+)}", result.stdout)
    assert match, f"Expected flag, but got: {result.stdout}"


def test_workspace_home_mount():
    check_mount("/home/hacker", user="admin")


def test_workspace_no_sudo():
    try:
        s = workspace_run("sudo whoami", user="admin")
    except subprocess.CalledProcessError:
        pass
    else:
        assert False, f"Expected sudo to fail, but got no error: {(s.stdout, s.stderr)}"


def test_workspace_practice_challenge(random_user_name, random_user_session, example_dojo):
    start_challenge(example_dojo, "hello", "apple", practice=True, session=random_user_session)
    try:
        result = workspace_run("sudo whoami", user=random_user_name)
        assert result.stdout.strip() == "root", f"Expected 'root', but got: ({result.stdout}, {result.stderr})"
    except subprocess.CalledProcessError as e:
        assert False, f"Expected sudo to succeed, but got: {(e.stdout, e.stderr)}"


def test_workspace_home_persistent(random_user_name, random_user_session, example_dojo):
    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    workspace_run("touch /home/hacker/test", user=random_user_name)
    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    try:
        workspace_run("[ -f '/home/hacker/test' ]", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected file to exist, but got: {(e.stdout, e.stderr)}"


@pytest.mark.skip(reason="Disabling test temporarily until overlay issue is resolved")
def test_workspace_as_user(admin_user, random_user_name, random_user_session, example_dojo):
    admin_user, admin_session = admin_user
    random_user_id = get_user_id(random_user_name)

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    workspace_run("touch /home/hacker/test", user=random_user_name)

    start_challenge(example_dojo, "hello", "apple", session=admin_session, as_user=random_user_id)
    check_mount("/home/hacker", user=admin_user)
    check_mount("/home/me", user=admin_user)

    try:
        workspace_run("[ -f '/home/hacker/test' ]", user=admin_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected existing file to exist, but got: {(e.stdout, e.stderr)}"

    workspace_run("touch /home/hacker/test2", user=random_user_name)
    try:
        workspace_run("[ -f '/home/hacker/test2' ]", user=admin_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected new file to exist, but got: {(e.stdout, e.stderr)}"

    workspace_run("touch /home/hacker/test3", user=admin_user)
    try:
        workspace_run("[ ! -e '/home/hacker/test3' ]", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected overlay file to not exist, but got: {(e.stdout, e.stderr)}"


def test_reset_home_directory(random_user_name, random_user_session, example_dojo):
    # Create a file in the home directory
    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    workspace_run("touch /home/hacker/testfile", user=random_user_name)

    # Reset the home directory
    response = random_user_session.post(f"http://{DOJO_HOST}/pwncollege_api/v1/workspace/reset_home", json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to reset home directory: {response.json()['error']}"

    try:
        workspace_run("[ -f '/home/hacker/home-backup.tar.gz' ]", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected zip file to exist, but got: {(e.stdout, e.stderr)}"

    try:
        workspace_run("[ ! -f '/home/hacker/testfile' ]", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected test file to be wiped, but got: {(e.stdout, e.stderr)}"


def test_unprivileged_challenge(random_user_name, random_user_session, example_dojo):
    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    try:
        result = workspace_run("unshare true", user=random_user_name)
        assert False, f"Expected unshare to fail, but it succeeded: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as e:
        assert "unshare: unshare failed: Operation not permitted" in e.stderr, f"Expected unshare to fail, but got: {(e.stdout, e.stderr)}"


def test_privileged_challenge(random_user_name, random_user_session, privileged_dojo):
    start_challenge(privileged_dojo, "test", "test", session=random_user_session)
    try:
        workspace_run("unshare true", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected unshare to succeed, but got: {(e.stdout, e.stderr)}"
