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

now = datetime.now(timezone.utc)

def remove_old_containers(docker_client_ip):
    docker_client = docker.DockerClient(base_url=f"tcp://{docker_client_ip}:2375")
    containers = docker_client.containers.list(filters={"label": "dojo.user_id"}, ignore_removed=True)
    container_is_old = lambda container: (now - datetime.fromisoformat(container.attrs["Created"].replace("Z", "+00:00"))) > OLD_CONTAINER_AGE
    old_containers = [container for container in containers if container_is_old(container)]

    for container in old_containers:
        user_id = container.labels["dojo.user_id"]
        logging.info(f"Removing old docker container {container.id} (user {user_id}) on {docker_client.api.base_url}")
        container.remove(force=True)

    logging.info(f"Removed old docker containers on {docker_client.api.base_url}")

with ThreadPoolExecutor() as executor:
    logging.info("Removing old containers")
    list(executor.map(remove_old_containers, workspace_node_ips))
    logging.info("Removed old containers")

def prune_images(docker_client_ip):
    docker_client = docker.DockerClient(base_url=f"tcp://{docker_client_ip}:2375", timeout=3600)
    logging.info(f"Pruning docker images on {docker_client.api.base_url}")
    docker_client.images.prune()
    logging.info(f"Prune docker images complete on {docker_client.api.base_url}")

with ThreadPoolExecutor() as executor:
    logging.info("Pruning images")
    list(executor.map(prune_images, workspace_node_ips))
    logging.info("Pruned images")

logging.info("Completed docker cleanup")
