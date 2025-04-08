#!/usr/bin/env python3

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import docker

OLD_CONTAINER_AGE = timedelta(hours=6)

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{os.path.basename(__file__)}] [%(levelname)s] %(message)s")

logging.info("Starting")

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

logging.info("Finished")
