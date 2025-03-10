#!/usr/bin/env python3

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import docker

OLD_CONTAINER_AGE = timedelta(days=1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

logging.info("Starting docker cleanup")

workspace_nodes = json.load(open("/var/workspace_nodes.json"))
workspace_node_ips = [f"192.168.42.{int(node_id) + 1}" for node_id in workspace_nodes]
docker_clients = [docker.DockerClient(base_url=f"tcp://{node_ip}:2375") for node_ip in workspace_node_ips]

now = datetime.now(timezone.utc)

def cleanup(docker_client):
    containers = docker_client.containers.list(filters={"label": "dojo.user_id"}, ignore_removed=True)
    container_is_old = lambda container: (now - datetime.fromisoformat(container.attrs["Created"].replace("Z", "+00:00"))) > OLD_CONTAINER_AGE
    old_containers = [container for container in containers if container_is_old(container)]

    def remove_container(container):
        user_id = container.labels["dojo.user_id"]
        logging.info(f"Removing docker container {container.id} (user {user_id}) on {docker_client.api.base_url}")
        container.remove(force=True)
        container.wait(condition="removed")
        logging.info(f"Removed docker container {container.id} (user {user_id}) on {docker_client.api.base_url}")

    with ThreadPoolExecutor() as executor:
        list(executor.map(remove_container, old_containers))

    logging.info(f"Pruning docker images on {docker_client.api.base_url}")
    docker_client.images.prune()
    logging.info(f"Prune docker images complete on {docker_client.api.base_url}")

with ThreadPoolExecutor() as executor:
    list(executor.map(cleanup, docker_clients))

logging.info("Completed docker cleanup")
