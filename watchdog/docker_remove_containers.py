#!/usr/local/bin/python3

import fcntl
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import docker
from requests.exceptions import RequestException

OLD_CONTAINER_AGE = timedelta(hours=6)

GiB = 1024 ** 3
LARGE_CONTAINER_SIZE = 16 * GiB
LOCK_PATH = "/run/docker-container-remove.lock"

def human_size(n):
    for unit in ['B','KiB','MiB','GiB','TiB']:
        if abs(n) < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PiB"

def collect_containers(client):
    node = client.api.base_url
    logging.info("Removing docker containers on %s", node)
    now = datetime.now(timezone.utc).timestamp()
    containers = client.api.containers(filters={"label": "dojo.user_id"}, size=True)
    removed = failed = 0
    for container in sorted(containers, key=lambda c: c.get("SizeRw", 0), reverse=True):
        age = now - container["Created"]
        size = container.get("SizeRw", 0)
        if age <= OLD_CONTAINER_AGE.total_seconds() and size <= LARGE_CONTAINER_SIZE:
            continue
        container_id = container["Id"]
        user_id = container["Labels"]["dojo.user_id"]
        logging.info("%s: removing %s (user %s): %.1f hours, %s writable",
                     node, container_id, user_id, age / 3600, human_size(size))
        try:
            client.api.remove_container(container_id, force=True, v=False)
        except docker.errors.NotFound:
            logging.info("%s: %s already removed", node, container_id)
        except RequestException as error:
            failed += 1
            logging.warning("%s: removal not confirmed for %s; Docker may still be processing it; continuing: %s",
                            node, container_id, error)
        else:
            removed += 1
    logging.info("%s: cleanup complete: %d removed, %d unconfirmed", node, removed, failed)
    return failed == 0


def remove_old_containers(url):
    try:
        with closing(docker.DockerClient(base_url=url, timeout=60)) as client:
            return collect_containers(client)
    except Exception:
        logging.exception("%s: node cleanup failed", url)
        return False


def main():
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{os.path.basename(__file__)}] [%(levelname)s] %(message)s")
    with open(LOCK_PATH, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("Another container cleanup is running; skipping")
            return 0
        logging.info("Starting")
        nodes = json.loads(Path("/var/workspace_nodes.json").read_text())
        urls = [f"tcp://192.168.42.{int(node) + 1}:2375" for node in nodes] or ["unix:///var/run/docker.sock"]
        with ThreadPoolExecutor() as executor:
            results = list(executor.map(remove_old_containers, urls))
        logging.info("Finished")
        return int(not all(results))


if __name__ == "__main__":
    raise SystemExit(main())
