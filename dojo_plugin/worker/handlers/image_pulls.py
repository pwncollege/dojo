import logging

import docker

from ...config import DOCKER_USERNAME, DOCKER_TOKEN, REGISTRY_USERNAME, REGISTRY_PASSWORD, REGISTRY_HOST
from ...utils import all_docker_clients

logger = logging.getLogger(__name__)


def handle_image_pull_event(event):
    image = event.get("image")
    dojo_reference_id = event.get("dojo_reference_id")

    if not image:
        return True, False
    if image.startswith("mac:") or image.startswith("pwncollege-"):
        return True, False

    if REGISTRY_HOST and image.startswith(f"{REGISTRY_HOST}/"):
        for client in all_docker_clients():
            if REGISTRY_USERNAME and REGISTRY_PASSWORD:
                try:
                    client.login(REGISTRY_USERNAME, REGISTRY_PASSWORD, registry=REGISTRY_HOST)
                except Exception as e:
                    logger.error(f"Login failed for {client.api.base_url}: {e}", exc_info=e)
                    return False, True

            logger.info(f"Pulling image {image} on {client.api.base_url}...")
            try:
                client.images.pull(image)
            except docker.errors.ImageNotFound:
                logger.error(f"... image not found: {image} on {client.api.base_url}...")
                return False, False
            except Exception as e:
                logger.error(f"... error: {image} on {client.api.base_url}...", exc_info=e)
                return False, True
    else:
        for client in all_docker_clients():
            if DOCKER_USERNAME and DOCKER_TOKEN:
                try:
                    client.login(DOCKER_USERNAME, DOCKER_TOKEN)
                except Exception as e:
                    logger.error(f"Login failed for {client.api.base_url}: {e}", exc_info=e)
                    return False, True

            logger.info(f"Pulling image {image} for {dojo_reference_id or 'unknown dojo'} on {client.api.base_url}...")

            try:
                client.images.pull(image)
            except docker.errors.ImageNotFound:
                logger.error(f"... image not found: {image} on {client.api.base_url}...")
                return False, False
            except Exception as e:
                logger.error(f"... error: {image} on {client.api.base_url}...", exc_info=e)
                return False, True

    return True, False
