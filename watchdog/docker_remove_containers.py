#!/usr/local/bin/python3

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import docker

OLD_CONTAINER_AGE = timedelta(hours=6)

GiB = 1024 ** 3
LARGE_CONTAINER_SIZE = 16 * GiB

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{os.path.basename(__file__)}] [%(levelname)s] %(message)s")

logging.info("Starting")

workspace_nodes = json.load(open("/data/workspace_nodes.json"))
# Single-node deployments run every user container on the local daemon, which has no
# entry in workspace_nodes.json; sweeping only that file would sweep nothing at all.
docker_client_urls = ([f"tcp://192.168.42.{int(node_id) + 1}:2375" for node_id in workspace_nodes]
                      or ["unix:///var/run/docker.sock"])

now = datetime.now(timezone.utc)

def human_size(n):
    for unit in ['B','KiB','MiB','GiB','TiB']:
        if abs(n) < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PiB"

def remove_old_containers(docker_client_url):
    docker_client = docker.DockerClient(base_url=docker_client_url)

    logging.info(f"Removing docker containers on {docker_client.api.base_url}")

    containers = docker_client.containers.list(filters={"label": "dojo.user_id"}, ignore_removed=True)

    container_age = lambda container: now - datetime.fromisoformat(re.sub(r"(\.\d{0,6})\d*Z$", r"\1+00:00", container.attrs["Created"]))
    old_containers = [container for container in containers if container_age(container) > OLD_CONTAINER_AGE]
    for container in reversed(sorted(old_containers, key=container_age)):
        user_id = container.labels["dojo.user_id"]
        logging.info(f"Removing old docker container {container.id} (user {user_id}) on {docker_client.api.base_url}: {container_age(container).total_seconds() // 3600:.0f} hours")
        container.remove(force=True)

    container_sizes = {
        container["Id"]: container.get("SizeRw", 0)
        for container in docker_client.df()["Containers"]
    }
    container_size = lambda container: container_sizes.get(container.id, 0)
    large_containers = [container for container in containers if container_size(container) > LARGE_CONTAINER_SIZE]
    for container in reversed(sorted(large_containers, key=container_size)):
        user_id = container.labels["dojo.user_id"]
        logging.info(f"Removing large docker container {container.id} (user {user_id}) on {docker_client.api.base_url}: {human_size(container_size(container))}")
        container.remove(force=True)

    logging.info(f"Removed docker containers on {docker_client.api.base_url}")

with ThreadPoolExecutor() as executor:
    logging.info("Removing docker containers")
    list(executor.map(remove_old_containers, docker_client_urls))
    logging.info("Removed docker containers")

logging.info("Finished")
