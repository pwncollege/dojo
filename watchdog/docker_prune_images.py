#!/usr/local/bin/python3

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import docker

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{os.path.basename(__file__)}] [%(levelname)s] %(message)s")

logging.info("Starting")

workspace_nodes = json.load(open("/var/workspace_nodes.json"))
docker_client_urls = ([f"tcp://192.168.42.{int(node_id) + 1}:2375" for node_id in workspace_nodes]
                      or ["unix:///var/run/docker.sock"])

def prune_images(docker_client_url):
    docker_client = docker.DockerClient(base_url=docker_client_url, timeout=3600)
    logging.info(f"Pruning docker images on {docker_client.api.base_url}")
    docker_client.images.prune()
    logging.info(f"Prune docker images complete on {docker_client.api.base_url}")

with ThreadPoolExecutor() as executor:
    logging.info("Pruning images")
    list(executor.map(prune_images, docker_client_urls))
    logging.info("Pruned images")

logging.info("Finished")
