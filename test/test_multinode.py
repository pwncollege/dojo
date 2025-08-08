import subprocess
import pytest
import shutil
import time
import json
from utils import start_challenge, get_user_id, dojo_run, DOJO_CONTAINER

def test_multinode_container_placement(random_user_name, random_user_session, example_dojo):
    try:
        result = subprocess.run(
            [shutil.which("docker"), "exec", "-i", DOJO_CONTAINER, "cat", "/data/workspace_nodes.json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        workspace_nodes = json.loads(result.stdout)
    except subprocess.CalledProcessError:
        pytest.skip("Singlenode deployment - skipping multinode test")

    if not workspace_nodes or len(workspace_nodes) == 0:
        pytest.skip("No worker nodes configured - skipping multinode test")

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    time.sleep(5)
    user_id = get_user_id(random_user_name)
    expected_container_name = f"user_{user_id}"

    main_containers_result = dojo_run("docker", "ps", "--format", "{{.Names}}")
    main_containers = main_containers_result.stdout.strip().split('\n') if main_containers_result.stdout.strip() else []
    assert expected_container_name not in main_containers, "learner container launched on main node instead of worker nodes"

    for node_id in workspace_nodes.keys():
        node_container_name = f"{DOJO_CONTAINER}-node{node_id}"
        worker_result = subprocess.run(
            [shutil.which("docker"), "exec", "-i", node_container_name, "docker", "ps", "--format", "{{.Names}}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        worker_containers = worker_result.stdout.strip().split('\n') if worker_result.stdout.strip() else []

        if expected_container_name in worker_containers:
            # success!
            return

    assert False, "Could not find learner container on any node!"
