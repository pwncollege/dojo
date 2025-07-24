import json
import re
import subprocess

import pytest

from utils import DOJO_URL, workspace_run, start_challenge, dojo_run


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


def db_sql(sql):
    db_result = dojo_run("db", "-qAt", input=sql)
    return db_result.stdout


def get_user_id(user_name):
    return int(db_sql(f"SELECT id FROM users WHERE name = '{user_name}'"))


@pytest.mark.dependency(depends=["test_start_challenge"])
@pytest.mark.parametrize("path", ["/flag", "/challenge/apple"])
def test_workspace_path_exists(path):
    try:
        workspace_run(f"[ -f '{path}' ]", user="admin")
    except subprocess.CalledProcessError:
        assert False, f"Path does not exist: {path}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_flag_permission():
    try:
        workspace_run("cat /flag", user="admin")
    except subprocess.CalledProcessError as e:
        assert "Permission denied" in e.stderr, f"Expected permission denied, but got: {(e.stdout, e.stderr)}"
    else:
        assert False, f"Expected permission denied, but got no error: {(e.stdout, e.stderr)}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_challenge():
    result = workspace_run("/challenge/apple", user="admin")
    match = re.search("pwn.college{(\\S+)}", result.stdout)
    assert match, f"Expected flag, but got: {result.stdout}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_home_mount():
    check_mount("/home/hacker", user="admin")


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_no_sudo():
    try:
        s = workspace_run("sudo whoami", user="admin")
    except subprocess.CalledProcessError:
        pass
    else:
        assert False, f"Expected sudo to fail, but got no error: {(s.stdout, s.stderr)}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_practice_challenge(random_user):
    user, session = random_user
    start_challenge("example", "hello", "apple", practice=True, session=session)
    try:
        result = workspace_run("sudo whoami", user=user)
        assert result.stdout.strip() == "root", f"Expected 'root', but got: ({result.stdout}, {result.stderr})"
    except subprocess.CalledProcessError as e:
        assert False, f"Expected sudo to succeed, but got: {(e.stdout, e.stderr)}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_home_persistent(random_user):
    user, session = random_user
    start_challenge("example", "hello", "apple", session=session)
    workspace_run("touch /home/hacker/test", user=user)
    start_challenge("example", "hello", "apple", session=session)
    try:
        workspace_run("[ -f '/home/hacker/test' ]", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected file to exist, but got: {(e.stdout, e.stderr)}"


@pytest.mark.skip(reason="Disabling test temporarily until overlay issue is resolved")
@pytest.mark.dependency(depends=["test_workspace_home_persistent"])
def test_workspace_as_user(admin_user, random_user):
    admin_user, admin_session = admin_user
    random_user, random_session = random_user
    random_user_id = get_user_id(random_user)

    start_challenge("example", "hello", "apple", session=random_session)
    workspace_run("touch /home/hacker/test", user=random_user)

    start_challenge("example", "hello", "apple", session=admin_session, as_user=random_user_id)
    check_mount("/home/hacker", user=admin_user)
    check_mount("/home/me", user=admin_user)

    try:
        workspace_run("[ -f '/home/hacker/test' ]", user=admin_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected existing file to exist, but got: {(e.stdout, e.stderr)}"

    workspace_run("touch /home/hacker/test2", user=random_user)
    try:
        workspace_run("[ -f '/home/hacker/test2' ]", user=admin_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected new file to exist, but got: {(e.stdout, e.stderr)}"

    workspace_run("touch /home/hacker/test3", user=admin_user)
    try:
        workspace_run("[ ! -e '/home/hacker/test3' ]", user=random_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected overlay file to not exist, but got: {(e.stdout, e.stderr)}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_reset_home_directory(random_user):
    user, session = random_user

    # Create a file in the home directory
    start_challenge("example", "hello", "apple", session=session)
    workspace_run("touch /home/hacker/testfile", user=user)

    # Reset the home directory
    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/workspace/reset_home", json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to reset home directory: {response.json()['error']}"

    try:
        workspace_run("[ -f '/home/hacker/home-backup.tar.gz' ]", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected zip file to exist, but got: {(e.stdout, e.stderr)}"

    try:
        workspace_run("[ ! -f '/home/hacker/testfile' ]", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected test file to be wiped, but got: {(e.stdout, e.stderr)}"