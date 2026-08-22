import concurrent.futures
import datetime
import json
import random
import string
import subprocess
import time
from urllib.parse import urlparse

import pytest
import requests

from utils import (
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    challenge_flag,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    get_outer_container_for,
    get_user_id,
    login,
    remove_workspace_container,
    start_challenge,
)

DOCKER_API = f"{DOJO_URL}/pwncollege_api/v1/docker"
NEXT_API = f"{DOJO_URL}/pwncollege_api/v1/docker/next"
WORKSPACE_API = f"{DOJO_URL}/pwncollege_api/v1/workspace"
RESET_HOME_API = f"{DOJO_URL}/pwncollege_api/v1/workspace/reset_home"
TOKENS_API = f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens"
USERS_ME_API = f"{DOJO_URL}/pwncollege_api/v1/users/me"

ROSTER_TOKEN = "wsapi-roster-token"
CAP_SYS_PTRACE = 1 << 19
CAP_NET_ADMIN = 1 << 12
NET_ADMIN_COMMAND = "ip addr add 10.99.99.99/32 dev lo"


def random_name(prefix):
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def new_user(prefix):
    name = random_name(prefix)
    return name, login(name, name, register=True)


def unique_dojo(spec_file, spec_id, *, session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = open(TEST_DOJOS_LOCATION / spec_file).read().replace(f"id: {spec_id}", f"id: {spec_id}-{suffix}", 1)
    return create_dojo_yml(spec, session=session)


def dojo_data(dojo_reference_id):
    return json.loads(db_sql(f"SELECT data FROM dojos WHERE dojo_id = {dojo_db_id(dojo_reference_id)};"))


def set_dojo_data(dojo_reference_id, data):
    db_sql(f"UPDATE dojos SET data = '{json.dumps(data)}' WHERE dojo_id = {dojo_db_id(dojo_reference_id)};")


def container_name(user_name):
    return f"user_{get_user_id(user_name)}"


def container_exists(user_name):
    try:
        get_outer_container_for(container_name(user_name))
    except RuntimeError:
        return False
    return True


def container_inspect(user_name):
    container = container_name(user_name)
    outer = get_outer_container_for(container)
    return json.loads(dojo_run("docker", "inspect", container, container=outer).stdout)[0]


def container_removed(user_name, container_id):
    outer = get_outer_container_for(container_name(user_name))
    listing = dojo_run(
        "docker", "ps", "-a", "--filter", f"id={container_id}", "--format", "{{.ID}}",
        container=outer, check=False,
    )
    return not listing.stdout.strip()


def workspace_exec(user_name, command, *, root=False):
    container = container_name(user_name)
    outer = get_outer_container_for(container)
    return dojo_run(
        "docker", "exec", f"--user={0 if root else 1000}", container, "bash", "-c", command,
        container=outer, check=False, stdin=subprocess.DEVNULL, timeout=30,
    )


def workspace_output(user_name, command, *, root=False):
    result = workspace_exec(user_name, command, root=root)
    assert result.returncode == 0, f"Expected `{command}` to succeed in the workspace, but got {result.stderr!r}"
    return result.stdout.strip()


def workspace_nodes():
    nodes = dojo_run("cat", "/data/workspace_nodes.json", check=False).stdout.strip()
    try:
        return [int(node) for node in json.loads(nodes)] if nodes else []
    except (json.JSONDecodeError, ValueError):
        return []


def workspace_capabilities(user_name):
    return int(workspace_output(user_name, "awk '/^CapEff:/ {print $2}' /proc/self/status", root=True), 16)


def expected_user_ipv4(user_id):
    nodes = workspace_nodes()
    node_id = nodes[user_id % len(nodes)] if nodes else 0
    service_id = user_id + 256
    return f"10.{(node_id << 4) | ((service_id >> 16) & 0xff)}.{(service_id >> 8) & 0xff}.{service_id & 0xff}"


def start_request(session, dojo, module, challenge, **extra):
    payload = dict(dojo=dojo, module=module, challenge=challenge, practice=False)
    payload.update(extra)
    return session.post(DOCKER_API, json=payload)


def proxy_get(iframe_src, *, timeout=15):
    """Fetch a signed workspace url, returning None if the proxy never answers."""
    parsed = urlparse(iframe_src)
    try:
        return requests.get(
            f"{DOJO_URL.rstrip('/')}{parsed.path}",
            headers={"Host": parsed.netloc},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException:
        return None


def solve_count(user_id):
    return int(db_sql(f"SELECT count(*) FROM solves WHERE user_id = {user_id}").strip())


def submit_flag(session, dojo, module, challenge, flag):
    return session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/solve", json={"submission": flag}
    )


@pytest.fixture(scope="module")
def standard_workspace(example_dojo):
    """A standard-mode workspace, started by racing two concurrent requests for the same user."""
    name, session = new_user("wsapistd")
    racing_session = login(name, name)
    payload = dict(dojo=example_dojo, module="hello", challenge="apple", practice=False)

    race_results = None
    for _ in range(3):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(s.post, DOCKER_API, json=payload) for s in (session, racing_session)]
            race_results = [future.result().json() for future in futures]
        if sum(1 for result in race_results if result.get("success")) == 1:
            break

    assert container_exists(name), f"The workspace never started: {race_results}"
    yield dict(name=name, session=session, user_id=get_user_id(name), race_results=race_results)
    remove_workspace_container(name)


@pytest.fixture(scope="module")
def practice_workspace(example_dojo):
    name, session = new_user("wsapiprac")
    start_challenge(example_dojo, "hello", "apple", practice=True, session=session)
    yield dict(name=name, session=session, user_id=get_user_id(name))
    remove_workspace_container(name)


@pytest.fixture(scope="module")
def restarted_workspace(example_dojo):
    """A practice-mode workspace that is then restarted, standard-mode, onto the next challenge."""
    name, session = new_user("wsapirestart")
    user_id = get_user_id(name)

    start_challenge(example_dojo, "hello", "apple", practice=True, session=session)
    before = container_inspect(name)
    state = dict(
        name=name,
        session=session,
        user_id=user_id,
        before=before,
        before_token=workspace_output(name, "cat /run/dojo/var/auth_token"),
        before_privileged=workspace_output(name, "cat /run/dojo/sys/workspace/privileged"),
        before_sudo=workspace_exec(name, "sudo whoami"),
        before_hostname=workspace_output(name, "hostname"),
    )
    workspace_exec(name, "touch /home/hacker/survives-restart")

    db_sql(
        "INSERT INTO awards (user_id, name, value, type, date) "
        f"VALUES ({user_id}, 'INTERNET', 0, 'standard', now())"
    )
    start_challenge(example_dojo, "hello", "banana", session=session)

    state.update(
        after=container_inspect(name),
        after_privileged=workspace_output(name, "cat /run/dojo/sys/workspace/privileged"),
        after_sudo=workspace_exec(name, "sudo whoami"),
        after_hostname=workspace_output(name, "hostname"),
        home_survived=workspace_exec(name, "[ -f /home/hacker/survives-restart ]").returncode == 0,
        old_container_removed=container_removed(name, before["Id"]),
        stale_token_response=requests.get(DOCKER_API, headers={"Authorization": f"Bearer {state['before_token']}"}),
        next_response=session.get(NEXT_API),
    )

    terminal = session.get(f"{WORKSPACE_API}?service=terminal").json()
    state["terminal_iframe"] = terminal.get("iframe_src")
    for _ in range(5):
        state["terminal_live"] = proxy_get(state["terminal_iframe"])
        if state["terminal_live"] is not None and state["terminal_live"].status_code == 200:
            break
        time.sleep(1)

    state.update(delete_response=session.delete(DOCKER_API, json={}))
    state.update(
        container_gone=not container_exists(name),
        get_after_delete=session.get(DOCKER_API),
        delete_after_delete=session.delete(DOCKER_API, json={}),
        token_after_delete=requests.get(DOCKER_API, headers={"Authorization": f"Bearer {state['before_token']}"}),
        terminal_dead=proxy_get(state["terminal_iframe"], timeout=8),
    )

    yield state
    remove_workspace_container(name)


@pytest.fixture(scope="module")
def support_workspaces(example_dojo, admin_session):
    """A workspace impersonated both through a workspace token and through site-admin as_user."""
    target, target_session = new_user("wsapitarget")
    target_id = get_user_id(target)
    start_challenge(example_dojo, "hello", "apple", session=target_session)
    workspace_exec(target, "touch /home/hacker/target-file")

    helper, helper_session = new_user("wsapihelper")
    token = target_session.post(TOKENS_API, json={}).json()["data"]["value"]
    token_response = helper_session.post(
        DOCKER_API,
        json=dict(dojo=example_dojo, module="hello", challenge="apple", practice=False),
        headers={"X-Workspace-Token": token},
    )
    helper_state = dict(response=token_response)
    if token_response.json().get("success"):
        helper_state.update(
            labels=container_inspect(helper)["Config"]["Labels"],
            flag=workspace_output(helper, "cat /flag", root=True),
            home_me=workspace_exec(helper, "findmnt -no TARGET /home/me").returncode,
            target_file_visible=workspace_exec(helper, "[ -f /home/hacker/target-file ]").returncode == 0,
        )
        workspace_exec(helper, "touch /home/hacker/helper-file")
        helper_state["leaked_into_target"] = workspace_exec(target, "[ -e /home/hacker/helper-file ]").returncode == 0

    rejected, rejected_session = new_user("wsapibadtoken")
    rejected_response = rejected_session.post(
        DOCKER_API,
        json=dict(dojo=example_dojo, module="hello", challenge="apple", practice=False),
        headers={"X-Workspace-Token": "workspace_" + "0" * 64},
    )

    admin_response = start_request(admin_session, example_dojo, "hello", "apple", as_user=target_id)
    admin_state = dict(response=admin_response)
    if admin_response.json().get("success"):
        admin_state.update(
            labels=container_inspect("admin")["Config"]["Labels"],
            flag=workspace_output("admin", "cat /flag", root=True),
            home_me=workspace_exec("admin", "findmnt -no TARGET /home/me").returncode,
            home_hacker=workspace_exec("admin", "findmnt -no TARGET /home/hacker").returncode,
            target_file_visible=workspace_exec("admin", "[ -f /home/hacker/target-file ]").returncode == 0,
        )
        workspace_exec("admin", "touch /home/hacker/admin-file")
        admin_state["leaked_into_target"] = workspace_exec(target, "[ -e /home/hacker/admin-file ]").returncode == 0
        admin_state["support_flag_submission"] = submit_flag(
            admin_session, example_dojo, "hello", "apple", "pwn.college{support_flag}"
        )
        admin_state["target_flag_submission"] = submit_flag(
            target_session, example_dojo, "hello", "apple", "pwn.college{support_flag}"
        )

    yield dict(
        target=target,
        target_id=target_id,
        helper=helper,
        helper_id=get_user_id(helper),
        helper_state=helper_state,
        admin_state=admin_state,
        rejected=rejected,
        rejected_response=rejected_response,
    )

    for user in [target, helper, "admin"]:
        remove_workspace_container(user)


@pytest.fixture(scope="module")
def private_dojo(admin_session):
    return unique_dojo("workspace_api_private.yml", "workspace-api-private", session=admin_session)


@pytest.fixture(scope="module")
def private_workspace(private_dojo):
    """A private dojo workspace, started only after joining, with an as_user the starter may not use."""
    name, session = new_user("wsapiprivate")
    impersonation_target = get_user_id("admin")

    denied = start_request(session, private_dojo, "solo", "only")
    join = session.get(f"{DOJO_URL}/dojo/{private_dojo}/join/")
    started = start_request(session, private_dojo, "solo", "only", as_user=impersonation_target)

    yield dict(
        name=name,
        session=session,
        user_id=get_user_id(name),
        dojo=private_dojo,
        impersonation_target=impersonation_target,
        denied=denied,
        join=join,
        started=started,
    )
    remove_workspace_container(name)


@pytest.fixture(scope="module")
def course_dojo(admin_session):
    dojo = unique_dojo("workspace_api_course.yml", "workspace-api-course", session=admin_session)
    data = dojo_data(dojo)
    data["course"] = {"students": [ROSTER_TOKEN]}
    set_dojo_data(dojo, data)
    return dojo


@pytest.fixture(scope="module")
def course_workspace(course_dojo, admin_session):
    """A dojo admin impersonating students of their course dojo, on a progression-locked challenge."""
    dojo_admin, dojo_admin_session = new_user("wsapidojoadmin")
    assert dojo_admin_session.get(f"{DOJO_URL}/dojo/{course_dojo}/join/").status_code == 200
    promotion = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{course_dojo}/admins/promote",
        json={"user_id": get_user_id(dojo_admin)},
    )
    assert promotion.status_code == 200, f"Failed to promote the dojo admin: {promotion.text}"

    member, member_session = new_user("wsapimember")
    assert member_session.get(f"{DOJO_URL}/dojo/{course_dojo}/join/").status_code == 200
    member_locked = start_request(member_session, course_dojo, "gate", "second")

    unofficial, unofficial_session = new_user("wsapiunofficial")
    unofficial_session.get(f"{DOJO_URL}/dojo/{course_dojo}/join/")
    unofficial_session.patch(
        f"{DOJO_URL}/dojo/{course_dojo}/course/identity", json={"identity": "not-on-the-roster"}
    )

    student, student_session = new_user("wsapistudent")
    student_session.get(f"{DOJO_URL}/dojo/{course_dojo}/join/")
    identity = student_session.patch(
        f"{DOJO_URL}/dojo/{course_dojo}/course/identity", json={"identity": ROSTER_TOKEN}
    )
    assert identity.status_code == 200 and "warning" not in identity.json(), (
        f"Expected the student to be on the official roster, but got {identity.text}"
    )

    not_a_student = start_request(dojo_admin_session, course_dojo, "gate", "second", as_user=get_user_id(member))
    not_official = start_request(dojo_admin_session, course_dojo, "gate", "second", as_user=get_user_id(unofficial))
    official = start_request(dojo_admin_session, course_dojo, "gate", "second", as_user=get_user_id(student))

    state = dict(
        dojo=course_dojo,
        dojo_admin=dojo_admin,
        member_id=get_user_id(member),
        unofficial_id=get_user_id(unofficial),
        student_id=get_user_id(student),
        member_locked=member_locked,
        not_a_student=not_a_student,
        not_official=not_official,
        official=official,
    )
    if official.json().get("success"):
        state["labels"] = container_inspect(dojo_admin)["Config"]["Labels"]

    yield state
    remove_workspace_container(dojo_admin)


@pytest.fixture(scope="module")
def net_admin_workspace(admin_session):
    """A privileged workspace, started before and after its dojo is granted workspace_net_admin."""
    dojo = unique_dojo("workspace_api_privileged.yml", "wsapi-privileged", session=admin_session)
    name, session = new_user("wsapinetadmin")
    session.get(f"{DOJO_URL}/dojo/{dojo}/join/")

    start_challenge(dojo, "net", "admin", session=session)
    without_permission = workspace_exec(name, NET_ADMIN_COMMAND, root=True)
    without_capability = workspace_capabilities(name)

    data = dojo_data(dojo)
    data["permissions"] = ["workspace_net_admin"]
    set_dojo_data(dojo, data)

    start_challenge(dojo, "net", "admin", session=session)
    with_permission = workspace_exec(name, NET_ADMIN_COMMAND, root=True)
    with_capability = workspace_capabilities(name)

    yield dict(
        without_permission=without_permission,
        without_capability=without_capability,
        with_permission=with_permission,
        with_capability=with_capability,
    )
    remove_workspace_container(name)


def test_docker_api_requires_a_session(example_dojo):
    anonymous = requests.Session()
    payload = dict(dojo=example_dojo, module="hello", challenge="apple", practice=False)

    for name, response in [
        ("POST /docker", anonymous.post(DOCKER_API, json=payload)),
        ("GET /docker", anonymous.get(DOCKER_API, headers={"Content-Type": "application/json"})),
        ("DELETE /docker", anonymous.delete(DOCKER_API, json={})),
        ("POST /workspace/reset_home", anonymous.post(RESET_HOME_API, json={})),
    ]:
        assert response.status_code == 403, f"Expected {name} to be rejected with 403, got {response.status_code}"
        try:
            body = response.json()
        except ValueError:
            body = {}
        assert body.get("success") is not True, f"Expected {name} to report no success, but got {body}"


def test_start_rejects_unknown_dojo_module_and_challenge(random_user_session, example_dojo):
    missing_fields = random_user_session.post(DOCKER_API, json={"dojo": example_dojo})
    assert missing_fields.status_code == 400, f"Expected status code 400, but got {missing_fields.status_code}"
    assert missing_fields.json() == {"success": False, "error": "Must supply dojo, module, and challenge."}, (
        f"Unexpected response to an incomplete start request: {missing_fields.json()}"
    )

    unknown_dojo = start_request(random_user_session, "no-such-dojo-xyz", "hello", "apple")
    assert unknown_dojo.status_code == 200, f"Expected status code 200, but got {unknown_dojo.status_code}"
    assert unknown_dojo.json() == {"success": False, "error": "Invalid dojo"}, (
        f"Unexpected response for an unknown dojo: {unknown_dojo.json()}"
    )

    for module, challenge in [("no-such-module", "apple"), ("hello", "no-such-challenge")]:
        response = start_request(random_user_session, example_dojo, module, challenge)
        assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
        assert response.json() == {"success": False, "error": "Invalid challenge"}, (
            f"Unexpected response for {module}/{challenge}: {response.json()}"
        )


def test_container_endpoints_report_no_active_challenge_without_a_container(random_user_session):
    current = random_user_session.get(DOCKER_API)
    assert current.status_code == 200, f"Expected status code 200, but got {current.status_code}"
    assert current.json() == {"success": False, "error": "No active challenge"}, (
        f"Expected no active challenge, but got {current.json()}"
    )

    next_challenge = random_user_session.get(NEXT_API)
    assert next_challenge.status_code == 200, f"Expected status code 200, but got {next_challenge.status_code}"
    assert next_challenge.json() == {"success": False, "error": "No active challenge"}, (
        f"Expected no next challenge, but got {next_challenge.json()}"
    )

    terminate = random_user_session.delete(DOCKER_API, json={})
    assert terminate.status_code == 200, f"Expected status code 200, but got {terminate.status_code}"
    assert terminate.json() == {"success": False, "error": "No active challenge container"}, (
        f"Expected nothing to terminate, but got {terminate.json()}"
    )

    reset = random_user_session.post(RESET_HOME_API, json={})
    assert reset.status_code == 200, f"Expected status code 200, but got {reset.status_code}"
    assert reset.json()["success"] is False, f"Expected the reset to fail, but got {reset.json()}"
    assert "No running container found" in reset.json()["error"], (
        f"Expected a no-container error, but got {reset.json()}"
    )

    workspace = random_user_session.get(WORKSPACE_API)
    assert workspace.status_code == 200, f"Expected status code 200, but got {workspace.status_code}"
    assert workspace.json() == {"success": False, "active": False}, (
        f"Expected an inactive workspace, but got {workspace.json()}"
    )


def test_concurrent_starts_are_serialized_by_the_per_user_lock(standard_workspace):
    results = standard_workspace["race_results"]
    successes = [result for result in results if result.get("success")]
    rejections = [result for result in results if not result.get("success")]

    assert len(successes) == 1, f"Expected exactly one of two concurrent starts to win, but got {results}"
    assert rejections[0].get("error") == "Already starting a challenge; try again in 20 seconds.", (
        f"Expected the losing start to be rejected by the per-user lock, but got {rejections[0]}"
    )


def test_started_container_is_labeled_with_the_running_challenge(standard_workspace, example_dojo):
    name, session, user_id = standard_workspace["name"], standard_workspace["session"], standard_workspace["user_id"]
    labels = container_inspect(name)["Config"]["Labels"]

    assert labels["dojo.dojo_id"] == example_dojo, f"Unexpected dojo label: {labels['dojo.dojo_id']}"
    assert labels["dojo.module_id"] == "hello", f"Unexpected module label: {labels['dojo.module_id']}"
    assert labels["dojo.challenge_id"] == "apple", f"Unexpected challenge label: {labels['dojo.challenge_id']}"
    assert labels["dojo.user_id"] == str(user_id), f"Unexpected user label: {labels['dojo.user_id']}"
    assert labels["dojo.as_user_id"] == str(user_id), (
        f"Expected a self-started container to run as its own user, but got {labels['dojo.as_user_id']}"
    )
    assert labels["dojo.mode"] == "standard", f"Expected standard mode, but got {labels['dojo.mode']}"

    current = session.get(DOCKER_API)
    assert current.json() == {
        "success": True, "dojo": example_dojo, "module": "hello", "challenge": "apple", "practice": False
    }, f"Unexpected active challenge: {current.json()}"

    workspace = session.get(WORKSPACE_API).json()
    assert workspace["success"] and workspace["active"], f"Expected an active workspace, but got {workspace}"
    assert workspace["iframe_src"] is None, (
        f"Expected no iframe without a service or port, but got {workspace['iframe_src']}"
    )
    assert workspace["current_challenge"] == {
        "dojo_id": example_dojo, "module_id": "hello", "challenge_id": "apple"
    }, f"Unexpected current challenge: {workspace['current_challenge']}"


def test_container_resource_limits_and_network_placement(standard_workspace):
    name, user_id = standard_workspace["name"], standard_workspace["user_id"]
    info = container_inspect(name)
    host_config = info["HostConfig"]

    assert host_config["Memory"] == 4 * 1024 ** 3, f"Expected a 4G memory limit, but got {host_config['Memory']}"
    assert host_config["PidsLimit"] == 1024, f"Expected a 1024 pid limit, but got {host_config['PidsLimit']}"
    assert host_config["CpuQuota"] == 400000, f"Expected a 4 cpu quota, but got {host_config['CpuQuota']}"
    assert host_config["CpuPeriod"] == 100000, f"Expected a 100ms cpu period, but got {host_config['CpuPeriod']}"

    networks = info["NetworkSettings"]["Networks"]
    assert "workspace_net" in networks, f"Expected the workspace to join workspace_net, but got {list(networks)}"
    assert networks["workspace_net"]["IPAddress"] == expected_user_ipv4(user_id), (
        f"Expected the deterministic per-user address {expected_user_ipv4(user_id)}, "
        f"but got {networks['workspace_net']['IPAddress']}"
    )
    assert f"user_{user_id}" in (networks["workspace_net"]["Aliases"] or []), (
        f"Expected the container to be reachable as user_{user_id}, but got {networks['workspace_net']['Aliases']}"
    )
    assert "bridge" not in networks, (
        f"Expected a user without an INTERNET award to be off the bridge network, but got {list(networks)}"
    )


def test_container_hostname_and_hosts_entries(standard_workspace):
    name, user_id = standard_workspace["name"], standard_workspace["user_id"]

    assert workspace_output(name, "hostname") == "hello~apple", "Expected the hostname to encode module~challenge"

    for host, address in [
        ("pwn.college", "192.168.42.1"),
        ("challenge.localhost", "127.0.0.1"),
        ("hacker.localhost", "127.0.0.1"),
        ("vm", "127.0.0.1"),
        ("hello~apple", "127.0.0.1"),
        ("dojo-user", expected_user_ipv4(user_id)),
    ]:
        resolved = workspace_output(name, f"getent ahostsv4 {host}").split()[0]
        assert resolved == address, f"Expected {host} to resolve to {address} in the workspace, but got {resolved}"

    assert workspace_exec(name, "getent ahostsv4 example.com").returncode == 0, (
        "Expected the firewall allowlist hosts to be resolvable in the workspace"
    )


def test_home_and_challenge_files_are_initialized(standard_workspace):
    name = standard_workspace["name"]

    ownership = workspace_output(name, "stat -c %U:%G:%a /home/hacker /home/hacker/.config").split()
    assert ownership == ["hacker:hacker:755", "hacker:hacker:755"], (
        f"Expected a hacker-owned mode 755 home, but got {ownership}"
    )
    assert workspace_exec(name, "touch /home/hacker/writable").returncode == 0, (
        "Expected the hacker user to be able to write to their fresh home directory"
    )

    assert workspace_output(name, "stat -c %a:%U:%G /challenge/apple") == "4755:root:root", (
        "Expected challenge files to be installed setuid root"
    )
    flag = workspace_output(name, "cat /flag", root=True)
    assert workspace_output(name, "/challenge/apple").strip().endswith(flag), (
        "Expected the setuid challenge to print the flag it cannot read as the hacker user"
    )


def test_standard_mode_workspace_is_unprivileged_but_ptrace_and_personality_capable(standard_workspace):
    name = standard_workspace["name"]

    assert workspace_output(name, "cat /run/dojo/sys/workspace/privileged") == "0", (
        "Expected a standard-mode workspace to be flagged unprivileged"
    )
    sudo = workspace_exec(name, "sudo whoami")
    assert sudo.returncode != 0, f"Expected sudo to be refused in standard mode, but it printed {sudo.stdout!r}"
    assert "not privileged" in sudo.stderr, f"Expected a not-privileged error, but got {sudo.stderr!r}"

    capabilities = int(workspace_output(name, "awk '/^CapEff:/ {print $2}' /proc/self/status", root=True), 16)
    assert capabilities & CAP_SYS_PTRACE, (
        f"Expected every workspace to carry CAP_SYS_PTRACE, but CapEff was {capabilities:#x}"
    )

    assert workspace_output(name, "setarch $(uname -m) -R /run/dojo/bin/true && echo OK").endswith("OK"), (
        "Expected the dojo seccomp profile to permit personality(ADDR_NO_RANDOMIZE)"
    )
    stacks = [
        workspace_output(name, "setarch $(uname -m) -R grep '\\[stack\\]' /proc/self/maps").split()[0]
        for _ in range(2)
    ]
    assert stacks[0] == stacks[1], f"Expected setarch -R to disable randomization, but got {stacks}"


def test_flag_is_specific_to_its_user(standard_workspace, example_dojo, random_user):
    name, session, user_id = standard_workspace["name"], standard_workspace["session"], standard_workspace["user_id"]
    other_name, _ = random_user

    flag = workspace_output(name, "cat /flag", root=True)
    assert flag == challenge_flag(example_dojo, "hello", "apple", user=name), (
        "Expected the workspace flag to be the per-user serialized flag"
    )
    other_flag = challenge_flag(example_dojo, "hello", "apple", user=other_name)
    assert flag != other_flag, "Expected two users of the same challenge to get different flags"

    response = submit_flag(session, example_dojo, "hello", "apple", other_flag)
    assert response.json()["success"] is False, f"Expected another user's flag to be rejected, but got {response.json()}"
    assert solve_count(user_id) == 0, "Expected another user's flag to register no solve"


def test_container_auth_token_authenticates_its_owner(standard_workspace):
    name = standard_workspace["name"]
    info = container_inspect(name)
    environment = dict(entry.split("=", 1) for entry in info["Config"]["Env"])

    assert environment["HOME"] == "/home/hacker", f"Unexpected HOME: {environment['HOME']}"
    assert environment["SHELL"] == "/run/dojo/bin/bash", f"Unexpected SHELL: {environment['SHELL']}"
    assert environment["PATH"].startswith("/run/challenge/bin:/run/dojo/bin:"), (
        f"Expected the challenge and dojo bin directories to lead PATH, but got {environment['PATH']}"
    )

    token = workspace_output(name, "cat /run/dojo/var/auth_token")
    assert token == info["Config"]["Labels"]["dojo.auth_token"] == environment["DOJO_AUTH_TOKEN"], (
        "Expected the container token to be recorded identically in the file, the label, and the environment"
    )
    assert token.startswith("sk-workspace-local-"), f"Unexpected token prefix: {token[:24]}"

    identity = requests.get(USERS_ME_API, headers={"Authorization": f"Bearer {token}"})
    assert identity.status_code == 200, f"Expected status code 200, but got {identity.status_code}"
    assert identity.json()["name"] == name, f"Expected the token to identify {name}, but got {identity.json()}"


def test_next_challenge_within_a_module(standard_workspace, example_dojo):
    response = standard_workspace["session"].get(NEXT_API)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    result = response.json()

    assert result["success"], f"Expected a next challenge, but got {result}"
    assert (result["dojo"], result["module"], result["challenge"]) == (example_dojo, "hello", "banana"), (
        f"Expected the next challenge in the same module, but got {result}"
    )
    assert result["challenge_index"] == 1, f"Expected challenge index 1, but got {result['challenge_index']}"
    assert "new_module" not in result, f"Expected no module transition, but got {result}"


def test_workspace_containers_are_isolated_from_each_other(standard_workspace, practice_workspace):
    name = standard_workspace["name"]
    peer_ip = container_inspect(practice_workspace["name"])["NetworkSettings"]["Networks"]["workspace_net"]["IPAddress"]

    reachable = workspace_exec(name, f"timeout 5 bash -c 'echo > /dev/tcp/{peer_ip}/22'")
    assert reachable.returncode != 0, f"Expected another user's workspace at {peer_ip} to be unreachable"

    status = workspace_output(name, "curl -s -o /dev/null --max-time 15 -w '%{http_code}' http://pwn.college/")
    assert status.startswith(("2", "3")), f"Expected the dojo web service to be reachable, but got status {status}"


def test_practice_mode_workspace_is_privileged_and_carries_the_practice_flag(practice_workspace, example_dojo):
    name, session = practice_workspace["name"], practice_workspace["session"]
    labels = container_inspect(name)["Config"]["Labels"]

    assert labels["dojo.mode"] == "privileged", f"Expected practice mode to be labeled privileged, got {labels['dojo.mode']}"
    assert workspace_output(name, "hostname") == "practice~hello~apple", (
        "Expected the practice hostname to be prefixed"
    )
    assert workspace_output(name, "cat /run/dojo/sys/workspace/privileged") == "1", (
        "Expected a practice workspace to be flagged privileged"
    )
    assert workspace_output(name, "sudo whoami") == "root", "Expected sudo to work in practice mode"
    assert workspace_output(name, "cat /flag", root=True) == "pwn.college{practice}", (
        "Expected the practice flag rather than the user's real flag"
    )

    current = session.get(DOCKER_API)
    assert current.json() == {
        "success": True, "dojo": example_dojo, "module": "hello", "challenge": "apple", "practice": True
    }, f"Expected the active challenge to be reported as practice, but got {current.json()}"


def test_practice_flag_does_not_solve_the_challenge(practice_workspace, example_dojo):
    session, user_id = practice_workspace["session"], practice_workspace["user_id"]

    response = submit_flag(session, example_dojo, "hello", "apple", "pwn.college{practice}")
    assert response.json()["success"] is False, f"Expected the practice flag to be rejected, but got {response.json()}"
    assert solve_count(user_id) == 0, "Expected the practice flag to register no solve"


def test_starting_a_challenge_replaces_the_previous_container(restarted_workspace, example_dojo):
    state = restarted_workspace

    assert state["after"]["Id"] != state["before"]["Id"], "Expected a restart to create a brand new container"
    assert state["old_container_removed"], (
        f"Expected the previous container {state['before']['Id'][:12]} to be removed by the new start"
    )
    assert state["after"]["Config"]["Labels"]["dojo.challenge_id"] == "banana", (
        f"Expected the new container to run banana, but got {state['after']['Config']['Labels']['dojo.challenge_id']}"
    )
    assert state["home_survived"], "Expected the home directory to persist across a container replacement"


def test_restarting_out_of_practice_mode_drops_privilege(restarted_workspace):
    state = restarted_workspace

    assert state["before_privileged"] == "1", "Expected the practice container to be flagged privileged"
    assert state["before_sudo"].returncode == 0 and state["before_sudo"].stdout.strip() == "root", (
        f"Expected sudo to work in practice mode, but got {state['before_sudo'].stdout!r}"
    )
    assert state["before_hostname"] == "practice~hello~apple", f"Unexpected practice hostname: {state['before_hostname']}"

    assert state["after"]["Config"]["Labels"]["dojo.mode"] == "standard", (
        "Expected the restarted container to be labeled standard"
    )
    assert state["after_privileged"] == "0", "Expected the restarted container to be flagged unprivileged"
    assert state["after_sudo"].returncode != 0, "Expected sudo to stop working after leaving practice mode"
    assert state["after_hostname"] == "hello~banana", f"Unexpected standard hostname: {state['after_hostname']}"


def test_internet_award_attaches_the_bridge_network(restarted_workspace):
    state = restarted_workspace

    assert "bridge" not in state["before"]["NetworkSettings"]["Networks"], (
        "Expected a user without an INTERNET award to be disconnected from the bridge network"
    )
    assert "bridge" in state["after"]["NetworkSettings"]["Networks"], (
        "Expected an INTERNET award to leave the bridge network attached"
    )


def test_next_challenge_crosses_the_module_boundary(restarted_workspace, example_dojo):
    result = restarted_workspace["next_response"].json()

    assert result["success"], f"Expected a next challenge past the end of the module, but got {result}"
    assert (result["dojo"], result["module"], result["challenge"]) == (example_dojo, "world", "earth"), (
        f"Expected the first challenge of the next module, but got {result}"
    )
    assert result["challenge_index"] == 0, f"Expected the first challenge index, but got {result['challenge_index']}"
    assert result["new_module"] is True, f"Expected the module transition to be announced, but got {result}"


def test_delete_terminates_the_container(restarted_workspace):
    state = restarted_workspace

    assert state["delete_response"].json() == {"success": True, "message": "Challenge container terminated"}, (
        f"Unexpected termination response: {state['delete_response'].json()}"
    )
    assert state["container_gone"], "Expected the workspace container to be gone after termination"
    assert state["get_after_delete"].json() == {"success": False, "error": "No active challenge"}, (
        f"Expected no active challenge after termination, but got {state['get_after_delete'].json()}"
    )
    assert state["delete_after_delete"].json() == {"success": False, "error": "No active challenge container"}, (
        f"Expected nothing left to terminate, but got {state['delete_after_delete'].json()}"
    )


@pytest.mark.xfail(
    reason="a workspace url that was used before the container was terminated hangs instead of 404ing",
    strict=False,
)
def test_workspace_urls_stop_serving_once_the_container_is_gone(restarted_workspace):
    live = restarted_workspace["terminal_live"]
    assert live is not None and live.status_code == 200, (
        f"Expected the signed workspace url to reach the running service, but got {live}"
    )

    dead = restarted_workspace["terminal_dead"]
    assert dead is not None, (
        "Expected the proxy to answer promptly for a terminated container, but the request hung"
    )
    assert dead.status_code == 404, (
        f"Expected the signed workspace url to stop serving once the container is gone, but got {dead.status_code}"
    )
    assert dead.text.strip() == "Workspace not found", f"Unexpected rejection body: {dead.text[:200]!r}"


def test_container_token_only_authenticates_its_own_challenge_container(restarted_workspace):
    state = restarted_workspace

    stale = state["stale_token_response"]
    assert stale.status_code == 403, f"Expected status code 403 for a stale token, but got {stale.status_code}"
    assert stale.json()["error"] == "Token failed to authenticate active challenge container.", (
        f"Unexpected stale token error: {stale.json()}"
    )

    orphaned = state["token_after_delete"]
    assert orphaned.status_code == 403, f"Expected status code 403 without a container, but got {orphaned.status_code}"
    assert orphaned.json()["error"] == "No active challenge container.", (
        f"Unexpected orphaned token error: {orphaned.json()}"
    )


def test_workspace_token_impersonates_its_owner(support_workspaces):
    state = support_workspaces["helper_state"]
    assert state["response"].json().get("success"), (
        f"Expected a workspace token to start an impersonating workspace, but got {state['response'].json()}"
    )

    assert state["labels"]["dojo.user_id"] == str(support_workspaces["helper_id"]), (
        "Expected the container to belong to the requesting user"
    )
    assert state["labels"]["dojo.as_user_id"] == str(support_workspaces["target_id"]), (
        f"Expected the container to run as the token owner, but got {state['labels']['dojo.as_user_id']}"
    )
    assert state["home_me"] == 0, "Expected the impersonator's own home to be mounted at /home/me"
    assert state["flag"] == "pwn.college{support_flag}", (
        f"Expected an impersonated workspace to get the support flag, but got {state['flag']}"
    )
    assert state["target_file_visible"], "Expected the target's existing home files to be visible in the overlay"
    assert not state["leaked_into_target"], "Expected overlay writes to stay out of the target's home"


def test_site_admin_impersonation_overlays_the_target_home(support_workspaces):
    state = support_workspaces["admin_state"]
    assert state["response"].json().get("success"), (
        f"Expected a site admin to start a workspace as another user, but got {state['response'].json()}"
    )

    assert state["labels"]["dojo.user_id"] == str(get_user_id("admin")), (
        "Expected the container to belong to the admin who started it"
    )
    assert state["labels"]["dojo.as_user_id"] == str(support_workspaces["target_id"]), (
        f"Expected the container to run as the target user, but got {state['labels']['dojo.as_user_id']}"
    )
    assert state["home_hacker"] == 0 and state["home_me"] == 0, (
        "Expected both the overlaid target home and the admin's own home to be mounted"
    )
    assert state["target_file_visible"], "Expected the target's existing home files to be visible in the overlay"
    assert not state["leaked_into_target"], "Expected the admin's overlay writes to stay out of the target's home"


def test_impersonated_flag_is_a_support_flag_that_cannot_solve(support_workspaces):
    state = support_workspaces["admin_state"]
    assert state["response"].json().get("success"), (
        f"Expected a site admin to start a workspace as another user, but got {state['response'].json()}"
    )

    assert state["flag"] == "pwn.college{support_flag}", (
        f"Expected an impersonating workspace to get the support flag, but got {state['flag']}"
    )
    for who, response in [("the admin", state["support_flag_submission"]), ("the target", state["target_flag_submission"])]:
        assert response.json()["success"] is False, (
            f"Expected the support flag submitted by {who} to be rejected, but got {response.json()}"
        )
    assert solve_count(support_workspaces["target_id"]) == 0, (
        "Expected the support flag to register no solve for the impersonated user"
    )


def test_invalid_workspace_token_is_rejected_without_starting_a_container(support_workspaces):
    response = support_workspaces["rejected_response"]

    assert response.status_code == 401, f"Expected status code 401, but got {response.status_code}"
    assert "Invalid workspace token" in response.text, f"Unexpected rejection body: {response.text[:200]}"
    assert not container_exists(support_workspaces["rejected"]), (
        "Expected a rejected workspace token to start no container"
    )


def test_private_dojo_membership_gates_challenge_start(private_workspace):
    assert private_workspace["denied"].json() == {"success": False, "error": "Invalid dojo"}, (
        f"Expected a non-member to be unable to see the private dojo, but got {private_workspace['denied'].json()}"
    )
    assert private_workspace["join"].status_code == 200, (
        f"Expected the join to succeed, but got {private_workspace['join'].status_code}"
    )
    assert private_workspace["started"].json() == {"success": True}, (
        f"Expected a member to be able to start the challenge, but got {private_workspace['started'].json()}"
    )


def test_as_user_is_ignored_for_non_dojo_admins(private_workspace):
    name, user_id = private_workspace["name"], private_workspace["user_id"]
    labels = container_inspect(name)["Config"]["Labels"]

    assert labels["dojo.user_id"] == str(user_id), "Expected the container to belong to its starter"
    assert labels["dojo.as_user_id"] == str(user_id), (
        f"Expected as_user={private_workspace['impersonation_target']} to be ignored for a non-admin, "
        f"but the container runs as {labels['dojo.as_user_id']}"
    )
    assert workspace_exec(name, "findmnt -no TARGET /home/me").returncode != 0, (
        "Expected no impersonation overlay home for a non-admin start"
    )
    assert workspace_output(name, "cat /flag", root=True) == challenge_flag(
        private_workspace["dojo"], "solo", "only", user=name
    ), "Expected the starter to get their own flag rather than a support or impersonated flag"


def test_next_challenge_at_the_end_of_a_dojo(private_workspace):
    response = private_workspace["session"].get(NEXT_API)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json() == {"success": False, "error": "No next challenge available"}, (
        f"Expected no next challenge at the end of the dojo, but got {response.json()}"
    )


def test_reset_home_restores_an_empty_writable_home(private_workspace):
    name, session = private_workspace["name"], private_workspace["session"]
    workspace_exec(name, "touch /home/hacker/doomed-file")

    response = session.post(RESET_HOME_API, json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json() == {"success": True, "message": "Home directory reset successfully"}, (
        f"Unexpected reset response: {response.json()}"
    )

    assert workspace_exec(name, "[ ! -e /home/hacker/doomed-file ]").returncode == 0, (
        "Expected the reset to wipe the home directory"
    )
    assert workspace_exec(name, "[ -f /home/hacker/home-backup.tar.gz ]").returncode == 0, (
        "Expected the reset to leave a backup of the old home directory"
    )
    assert workspace_output(name, "stat -c %U:%G /home/hacker") == "hacker:hacker", (
        "Expected the reset home directory to stay owned by the hacker user"
    )
    assert workspace_exec(name, "touch /home/hacker/after-reset").returncode == 0, (
        "Expected the hacker user to still be able to write to their home directory after a reset"
    )


def test_progression_lock_applies_to_members_but_not_dojo_admins(course_workspace):
    assert course_workspace["member_locked"].json() == {"success": False, "error": "This challenge is locked"}, (
        f"Expected an unsolved predecessor to lock the challenge, but got {course_workspace['member_locked'].json()}"
    )
    assert course_workspace["official"].json().get("success"), (
        f"Expected a dojo admin to bypass the progression lock, but got {course_workspace['official'].json()}"
    )
    assert course_workspace["labels"]["dojo.challenge_id"] == "second", (
        f"Expected the locked challenge to be running, but got {course_workspace['labels']['dojo.challenge_id']}"
    )


def test_dojo_admin_impersonation_requires_an_official_student(course_workspace):
    not_a_student = course_workspace["not_a_student"].json()
    assert not_a_student == {
        "success": False, "error": f"Not a student in this dojo ({course_workspace['member_id']})"
    }, f"Expected a plain member to be unusable as as_user, but got {not_a_student}"

    not_official = course_workspace["not_official"].json()
    assert not_official == {
        "success": False, "error": f"Not an official student in this dojo ({course_workspace['unofficial_id']})"
    }, f"Expected an off-roster student to be unusable as as_user, but got {not_official}"

    assert course_workspace["official"].json().get("success"), (
        f"Expected an official student to be usable as as_user, but got {course_workspace['official'].json()}"
    )
    assert course_workspace["labels"]["dojo.as_user_id"] == str(course_workspace["student_id"]), (
        f"Expected the container to run as the official student, but got {course_workspace['labels']['dojo.as_user_id']}"
    )
    assert course_workspace["labels"]["dojo.user_id"] == str(get_user_id(course_workspace["dojo_admin"])), (
        "Expected the container to belong to the dojo admin who started it"
    )


def test_net_admin_capability_requires_the_dojo_permission(net_admin_workspace):
    without_permission = net_admin_workspace["without_permission"]
    assert not net_admin_workspace["without_capability"] & CAP_NET_ADMIN, (
        "Expected a privileged workspace of a dojo without workspace_net_admin to lack CAP_NET_ADMIN"
    )
    assert without_permission.returncode != 0, (
        "Expected network administration to be denied to a privileged workspace without workspace_net_admin"
    )
    assert "not permitted" in without_permission.stderr, (
        f"Expected a permission error, but got {without_permission.stderr!r}"
    )

    with_permission = net_admin_workspace["with_permission"]
    assert net_admin_workspace["with_capability"] & CAP_NET_ADMIN, (
        "Expected workspace_net_admin to grant CAP_NET_ADMIN to a privileged workspace"
    )
    assert with_permission.returncode == 0, (
        f"Expected workspace_net_admin to allow network administration, but got {with_permission.stderr!r}"
    )


def test_workspace_token_creation_defaults_to_thirty_days(random_user):
    name, session = random_user
    response = session.post(TOKENS_API, json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"

    data = response.json()["data"]
    assert data["value"].startswith("workspace_") and len(data["value"]) == len("workspace_") + 64, (
        f"Unexpected token value: {data['value']}"
    )
    assert db_sql(f"SELECT user_id FROM workspace_tokens WHERE value = '{data['value']}'").strip() == str(
        get_user_id(name)
    ), "Expected the created token to belong to its creator"

    expiration = datetime.datetime.fromisoformat(data["expiration"].replace("Z", "+00:00")).replace(tzinfo=None)
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    remaining = (expiration - now).total_seconds()
    assert 29 * 86400 < remaining <= 30 * 86400 + 60, (
        f"Expected the default token expiration to be 30 days out, but it expires in {remaining / 86400:.2f} days"
    )
