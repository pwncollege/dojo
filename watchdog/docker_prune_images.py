#!/usr/local/bin/python3

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import docker

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{os.path.basename(__file__)}] [%(levelname)s] %(message)s")

logging.info("Starting")

workspace_nodes = json.load(open("/var/workspace_nodes.json"))
workspace_node_ips = [f"192.168.42.{int(node_id) + 1}" for node_id in workspace_nodes]

def prune_images(docker_client_ip):
    docker_client = docker.DockerClient(base_url=f"tcp://{docker_client_ip}:2375", timeout=3600)
    logging.info(f"Pruning docker images on {docker_client.api.base_url}")
    docker_client.images.prune()
    logging.info(f"Prune docker images complete on {docker_client.api.base_url}")

with ThreadPoolExecutor() as executor:
    logging.info("Pruning images")
    list(executor.map(prune_images, workspace_node_ips))
    logging.info("Pruned images")

logging.info("Finished")
