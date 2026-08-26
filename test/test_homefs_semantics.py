import json
import random
import re
import string
import time

import pytest

from utils import (
    DOJO_CONTAINER,
    DOJO_URL,
    dojo_run,
    get_outer_container_for,
    get_user_id,
    login,
    remove_workspace_container,
    start_challenge,
    workspace_run,
)


DOCKER_API = f"{DOJO_URL}/pwncollege_api/v1/docker"
TOKENS_API = f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens"


def _workspace_nodes():
    result = dojo_run("cat", "/data/workspace_nodes.json", check=False)
    try:
        return [int(node_id) for node_id in json.loads(result.stdout)]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


WORKSPACE_NODES = _workspace_nodes()
pytestmark = pytest.mark.skipif(len(WORKSPACE_NODES) < 2, reason="requires at least two workspace nodes")


def _random_name(prefix):
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def _worker_container(node_id):
    return f"{DOJO_CONTAINER}-node{node_id}"


def _cluster_containers():
    return [DOJO_CONTAINER, *[_worker_container(node_id) for node_id in WORKSPACE_NODES]]


def _expected_node(user_id):
    return WORKSPACE_NODES[user_id % len(WORKSPACE_NODES)]


def _driver(container, endpoint, payload):
    result = dojo_run(
        "curl", "-s", "-o", "/dev/stdout", "-w", "\n%{http_code}",
        "-XPOST", "-d", json.dumps(payload),
        f"http://localhost:4201/VolumeDriver.{endpoint}",
        container=container,
    )
    body, _, status = result.stdout.rpartition("\n")
    return int(status), body


def _homefs_rows(container, volume):
    script = (
        "import json, sqlite3, sys; "
        "connection = sqlite3.connect('/run/homefs/homefs.db'); "
        "print(json.dumps({table: connection.execute("
        "f'select * from {table} where name = ?', (sys.argv[1],)).fetchall() "
        "for table in ('active_volumes', 'docker_volumes')}))"
    )
    result = dojo_run(
        "python3", "-c", script, volume,
        container=container,
    )
    return json.loads(result.stdout)


def _delete_homefs_rows(container, volume):
    script = (
        "import sqlite3, sys; "
        "connection = sqlite3.connect('/run/homefs/homefs.db'); "
        "connection.execute('delete from active_volumes where name = ?', (sys.argv[1],)); "
        "connection.execute('delete from docker_volumes where name = ?', (sys.argv[1],)); "
        "connection.commit()"
    )
    dojo_run(
        "python3", "-c", script, volume,
        container=container, check=False,
    )


def _set_active_host(volume, host):
    script = (
        "import sqlite3, sys; "
        "connection = sqlite3.connect('/run/homefs/homefs.db'); "
        "connection.execute('insert into active_volumes (name, host) values (?, ?) "
        "on conflict(name) do update set host = excluded.host', (sys.argv[1], sys.argv[2])); "
        "connection.commit()"
    )
    dojo_run("python3", "-c", script, volume, host)


def _claim_volume(container, volume):
    result = dojo_run(
        "curl", "-s", "-o", "/dev/stdout", "-w", "\n%{http_code}",
        "-XPOST", f"http://192.168.42.1:4201/volume/{volume}/activate",
        container=container,
    )
    body, _, status = result.stdout.rpartition("\n")
    return int(status), body


def _subvolume_uuid(container, path):
    output = dojo_run("btrfs", "subvolume", "show", path, container=container).stdout
    match = re.search(r"^\s*UUID:\s+(\S+)", output, re.M)
    assert match, output
    return match.group(1)


def _numeric_volume_for(node_id):
    volume_id = random.randrange(10 ** 11, 10 ** 12)
    while _expected_node(volume_id) != node_id:
        volume_id += 1
    return str(volume_id)


def _delete_volume_tree(container, volume):
    dojo_run(
        "sh", "-c",
        f"for subvolume in /data/homes/{volume}/snapshots/* /data/homes/{volume}/overlays/* "
        f"/data/homes/{volume}/snapshots /data/homes/{volume}/overlays /data/homes/{volume}/active "
        f"/data/homes/{volume}; do btrfs subvolume delete \"$subvolume\" 2>/dev/null; done; true",
        container=container, check=False,
    )


def _remove_volume_everywhere(volume):
    for container in _cluster_containers():
        dojo_run("docker", "volume", "rm", "-f", volume, container=container, check=False)
        _driver(container, "Remove", {"Name": volume})
        _delete_homefs_rows(container, volume)
        _delete_volume_tree(container, volume)


def _container_id(user):
    outer = get_outer_container_for(f"user_{user['id']}")
    return dojo_run(
        "docker", "inspect", "--format", "{{.Id}}", f"user_{user['id']}",
        container=outer,
    ).stdout.strip()


@pytest.fixture(scope="module")
def multinode_home_users(example_dojo):
    users_by_node = {}
    registered_users = []
    required_nodes = set(WORKSPACE_NODES[:2])

    for _ in range(len(WORKSPACE_NODES) * 3):
        name = _random_name("homefsnode")
        session = login(name, name, register=True)
        user_id = get_user_id(name)
        node_id = _expected_node(user_id)
        registered_users.append(dict(name=name, session=session, id=user_id, node=node_id))
        if node_id in required_nodes and node_id not in users_by_node:
            users_by_node[node_id] = registered_users[-1]
        if required_nodes <= users_by_node.keys():
            break

    assert required_nodes <= users_by_node.keys(), users_by_node

    dormant_name = _random_name("homefsdormant")
    login(dormant_name, dormant_name, register=True)
    dormant_id = get_user_id(dormant_name)
    users = [users_by_node[node_id] for node_id in WORKSPACE_NODES[:2]]

    for user in users:
        start_challenge(example_dojo, "hello", "apple", session=user["session"])

    yield dict(users=users, dormant_id=dormant_id)

    for user in users:
        remove_workspace_container(user["name"])
    for user in users:
        _remove_volume_everywhere(f"{user['id']}-overlay")
        _remove_volume_everywhere(str(user["id"]))


def test_multinode_homes_are_lazy_worker_local_btrfs_volumes(multinode_home_users):
    users = multinode_home_users["users"]
    dormant_id = multinode_home_users["dormant_id"]

    for container in _cluster_containers():
        assert dojo_run(
            "test", "-e", f"/data/homes/{dormant_id}", container=container, check=False,
        ).returncode != 0, f"unused home {dormant_id} was provisioned on {container}"

    for index, user in enumerate(users):
        owner = _worker_container(user["node"])
        other_worker = _worker_container(users[1 - index]["node"])
        assert get_outer_container_for(f"user_{user['id']}") == owner

        subvolumes = dojo_run("btrfs", "subvolume", "list", "/data/homes", container=owner).stdout
        for path in (
            f"{user['id']}",
            f"{user['id']}/snapshots",
            f"{user['id']}/overlays",
            f"{user['id']}/active",
        ):
            assert re.search(rf"path {re.escape(path)}$", subvolumes, re.M), (
                f"missing {path} on owning worker {owner}"
            )

        for container in (DOJO_CONTAINER, other_worker):
            assert dojo_run(
                "test", "-e", f"/data/homes/{user['id']}/active",
                container=container, check=False,
            ).returncode != 0, f"home {user['id']} was active on non-owning node {container}"

        mountinfo = workspace_run("cat /proc/self/mountinfo", user=user["name"]).stdout
        home_mounts = [line for line in mountinfo.splitlines() if " /home/hacker " in line]
        assert len(home_mounts) == 1 and f"/{user['id']}/active" in home_mounts[0], home_mounts
        assert workspace_run("stat -c %i /home/hacker", user=user["name"]).stdout.strip() == "256"

        rows = _homefs_rows(DOJO_CONTAINER, str(user["id"]))
        assert rows["active_volumes"][0][1] == f"192.168.42.{user['node'] + 1}", rows

    for user in users:
        workspace_run(f"printf node-{user['node']} > /home/hacker/shared-name", user=user["name"])

    for index, user in enumerate(users):
        assert workspace_run("cat /home/hacker/shared-name", user=user["name"]).stdout == f"node-{user['node']}"
        assert workspace_run("cat /home/hacker/shared-name", user=users[1 - index]["name"]).stdout != f"node-{user['node']}"


def test_multinode_home_quota_is_enforced_on_owning_worker(multinode_home_users):
    user = multinode_home_users["users"][0]
    owner = _worker_container(user["node"])

    qgroups = dojo_run("btrfs", "qgroup", "show", "-re", "/data/homes", container=owner).stdout
    assert re.search(
        rf"^\S+\s+\S+\s+\S+\s+1\.00GiB\s+\S+\s+{user['id']}/active$",
        qgroups,
        re.M,
    ), f"no 1GiB qgroup limit for {user['id']} on {owner}"

    try:
        overflow = workspace_run(
            "dd if=/dev/zero of=/home/hacker/multinode-quota bs=1M count=1200 2>&1; true",
            user=user["name"],
        )
        assert "Disk quota exceeded" in overflow.stdout, overflow.stdout[-500:]
        size = int(workspace_run("stat -c %s /home/hacker/multinode-quota", user=user["name"]).stdout)
        assert size <= 1024 ** 3 + 8 * 1024 ** 2, size
    finally:
        workspace_run("rm -f /home/hacker/multinode-quota", user=user["name"])

    assert workspace_run("echo healthy", user=user["name"]).stdout.strip() == "healthy"
    assert workspace_run(
        "echo outside-home > /tmp/multinode-quota && cat /tmp/multinode-quota", user=user["name"],
    ).stdout.strip() == "outside-home"


def test_multinode_home_persists_and_snapshots_through_coordinator(multinode_home_users, example_dojo):
    user = multinode_home_users["users"][0]
    owner = _worker_container(user["node"])
    marker = _random_name("persist")
    before_container = _container_id(user)

    workspace_run(f"printf {marker} > /home/hacker/multinode-persistent", user=user["name"])
    headers = dojo_run(
        "curl", "-s", "-D-", "-o", "/dev/null",
        f"http://localhost:4201/volume/{user['id']}",
    ).stdout
    etag_match = re.search(r"(?i)^ETag: (\S+)", headers, re.M)
    assert etag_match, headers
    etag = etag_match.group(1)

    snapshots = sorted(dojo_run("ls", f"/data/homes/{user['id']}/snapshots").stdout.split())
    assert snapshots[-1] == etag, (snapshots, etag)
    assert dojo_run(
        "cat", f"/data/homes/{user['id']}/snapshots/{etag}/multinode-persistent",
    ).stdout == marker

    cached = dojo_run(
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "-H", f"If-None-Match: {etag}",
        f"http://localhost:4201/volume/{user['id']}",
    ).stdout.strip()
    assert cached == "304", cached

    start_challenge(example_dojo, "hello", "banana", session=user["session"])

    assert _container_id(user) != before_container
    assert get_outer_container_for(f"user_{user['id']}") == owner
    assert workspace_run(
        "cat /home/hacker/multinode-persistent", user=user["name"],
    ).stdout == marker
    assert dojo_run(
        "cat", f"/data/homes/{user['id']}/active/multinode-persistent", container=owner,
    ).stdout == marker


def test_multinode_cross_node_overlay_is_current_isolated_and_ephemeral(multinode_home_users, example_dojo):
    target, helper = multinode_home_users["users"]
    assert target["node"] != helper["node"]
    target_owner = _worker_container(target["node"])
    helper_owner = _worker_container(helper["node"])
    overlay_name = f"{helper['id']}-overlay"
    overlay_path = f"/data/homes/{target['id']}/overlays/{overlay_name}"
    target_marker = _random_name("target")
    helper_marker = _random_name("helper")

    workspace_run(f"printf {target_marker} > /home/hacker/cross-node-current", user=target["name"])
    token_response = target["session"].post(TOKENS_API, json={})
    assert token_response.status_code == 200, token_response.text
    token = token_response.json()["data"]["value"]
    response = helper["session"].post(
        DOCKER_API,
        json=dict(dojo=example_dojo, module="hello", challenge="apple", practice=False),
        headers={"X-Workspace-Token": token},
    )
    assert response.status_code == 200 and response.json().get("success"), response.text
    assert get_outer_container_for(f"user_{helper['id']}") == helper_owner

    mountinfo = workspace_run("cat /proc/self/mountinfo", user=helper["name"]).stdout.splitlines()
    target_mounts = [line for line in mountinfo if " /home/hacker " in line]
    own_mounts = [line for line in mountinfo if " /home/me " in line]
    assert len(target_mounts) == 1 and f"/{target['id']}/overlays/{overlay_name}" in target_mounts[0]
    assert len(own_mounts) == 1 and f"/{helper['id']}/active" in own_mounts[0]
    assert workspace_run("cat /home/hacker/cross-node-current", user=helper["name"]).stdout == target_marker

    workspace_run("printf overlay-only > /home/hacker/cross-node-overlay", user=helper["name"])
    workspace_run(f"printf {helper_marker} > /home/me/helper-own-home", user=helper["name"])
    assert dojo_run("cat", f"{overlay_path}/cross-node-overlay", container=helper_owner).stdout == "overlay-only"
    assert dojo_run("test", "-e", overlay_path, container=target_owner, check=False).returncode != 0
    assert workspace_run(
        "test ! -e /home/hacker/cross-node-overlay", user=target["name"],
    ).returncode == 0

    start_challenge(example_dojo, "world", "earth", session=helper["session"])

    assert dojo_run("test", "-e", overlay_path, container=helper_owner, check=False).returncode != 0
    assert workspace_run("cat /home/hacker/helper-own-home", user=helper["name"]).stdout == helper_marker
    assert workspace_run("cat /home/hacker/cross-node-current", user=target["name"]).stdout == target_marker
    assert workspace_run(
        "test ! -e /home/hacker/cross-node-overlay", user=target["name"],
    ).returncode == 0


def test_multinode_coordinator_rejects_competing_active_host():
    first_node, second_node = WORKSPACE_NODES[:2]
    first_worker = _worker_container(first_node)
    second_worker = _worker_container(second_node)
    volume = _random_name("homefs-conflict-")
    marker = _random_name("owner")

    try:
        for worker in (first_worker, second_worker):
            status, body = _driver(worker, "Create", {"Name": volume})
            assert status == 200, (worker, status, body)

        status, body = _driver(first_worker, "Mount", {"Name": volume, "ID": "first"})
        assert status == 200, (status, body)
        dojo_run(
            "sh", "-c", f"printf {marker} > /data/homes/{volume}/active/owner-marker",
            container=first_worker,
        )

        headers = dojo_run(
            "curl", "-s", "-D-", "-o", "/dev/null", f"http://localhost:4201/volume/{volume}",
        ).stdout
        etag_match = re.search(r"(?i)^ETag: (\S+)", headers, re.M)
        assert etag_match, headers
        assert dojo_run(
            "cat", f"/data/homes/{volume}/snapshots/{etag_match.group(1)}/owner-marker",
        ).stdout == marker

        status, body = _driver(second_worker, "Mount", {"Name": volume, "ID": "second"})
        assert status >= 400, (status, body)
        assert dojo_run(
            "test", "-e", f"/data/homes/{volume}/active",
            container=second_worker, check=False,
        ).returncode != 0

        rows = _homefs_rows(DOJO_CONTAINER, volume)
        assert rows["active_volumes"][0][1] == f"192.168.42.{first_node + 1}", rows
        status, body = _driver(first_worker, "Mount", {"Name": volume, "ID": "again"})
        assert status == 200, (status, body)
    finally:
        _remove_volume_everywhere(volume)


def test_multinode_legacy_active_owner_reconciles_without_replacing_subvolume():
    expected_node, wrong_node = WORKSPACE_NODES[:2]
    expected_worker = _worker_container(expected_node)
    wrong_worker = _worker_container(wrong_node)
    volume = _numeric_volume_for(expected_node)
    unresolved_volume = _random_name("homefs-legacy-unresolved-")
    legacy_host = "172.18.0.1"
    nonlegacy_private_host = "10.64.0.7"
    malformed_legacy_host = "legacy.invalid"
    expected_host = f"192.168.42.{expected_node + 1}"
    competing_host = f"192.168.42.{wrong_node + 1}"
    unregistered_node = next(
        (node_id for node_id in range(1, 16) if node_id not in WORKSPACE_NODES),
        16,
    )
    unregistered_wireguard_host = f"192.168.42.{unregistered_node + 1}"
    marker = _random_name("legacy-owner-")

    try:
        status, body = _driver(expected_worker, "Create", {"Name": volume})
        assert status == 200, (status, body)
        status, body = _driver(expected_worker, "Mount", {"Name": volume, "ID": "legacy"})
        assert status == 200, (status, body)
        active_path = f"/data/homes/{volume}/active"
        dojo_run(
            "sh", "-c", f"printf {marker} > {active_path}/legacy-owner-marker",
            container=expected_worker,
        )
        active_uuid = _subvolume_uuid(expected_worker, active_path)

        _delete_homefs_rows(DOJO_CONTAINER, volume)
        status, body = _claim_volume(wrong_worker, volume)
        assert status == 409, (status, body)
        assert _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"] == []
        status, body = _claim_volume(expected_worker, volume)
        assert status == 201, (status, body)
        assert _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"][0][1] == expected_host

        _set_active_host(volume, legacy_host)
        status, body = _claim_volume(wrong_worker, volume)
        assert status == 409, (status, body)
        assert _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"][0][1] == legacy_host

        _set_active_host(volume, competing_host)
        status, body = _claim_volume(wrong_worker, volume)
        assert status == 409, (status, body)
        status, body = _claim_volume(expected_worker, volume)
        assert status == 409, (status, body)
        assert _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"][0][1] == competing_host

        _set_active_host(volume, unregistered_wireguard_host)
        status, body = _claim_volume(expected_worker, volume)
        assert status == 409, (status, body)
        assert (
            _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"][0][1]
            == unregistered_wireguard_host
        )

        _set_active_host(volume, "127.0.0.1")
        status, body = _claim_volume(expected_worker, volume)
        assert status == 409, (status, body)
        assert _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"][0][1] == "127.0.0.1"

        _set_active_host(volume, malformed_legacy_host)
        status, body = _claim_volume(expected_worker, volume)
        assert status == 409, (status, body)
        assert (
            _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"][0][1]
            == malformed_legacy_host
        )

        _set_active_host(volume, nonlegacy_private_host)
        status, body = _claim_volume(expected_worker, volume)
        assert status == 409, (status, body)
        assert (
            _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"][0][1]
            == nonlegacy_private_host
        )

        _set_active_host(volume, legacy_host)
        status, body = _claim_volume(expected_worker, volume)
        assert status == 201, (status, body)
        assert _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"][0][1] == expected_host

        _set_active_host(unresolved_volume, legacy_host)
        status, body = _claim_volume(expected_worker, unresolved_volume)
        assert status == 409, (status, body)
        assert _homefs_rows(DOJO_CONTAINER, unresolved_volume)["active_volumes"][0][1] == legacy_host

        _set_active_host(volume, legacy_host)
        dojo_run("systemctl", "restart", "dojo-homefs.service", container=expected_worker)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            rows = _homefs_rows(DOJO_CONTAINER, volume)["active_volumes"]
            if rows and rows[0][1] == expected_host:
                break
            time.sleep(0.25)
        else:
            pytest.fail(f"legacy owner remained unreconciled: {rows}")

        assert _subvolume_uuid(expected_worker, active_path) == active_uuid
        assert dojo_run(
            "cat", f"{active_path}/legacy-owner-marker", container=expected_worker,
        ).stdout == marker
        assert _homefs_rows(DOJO_CONTAINER, unresolved_volume)["active_volumes"][0][1] == legacy_host
    finally:
        _remove_volume_everywhere(unresolved_volume)
        _remove_volume_everywhere(volume)
