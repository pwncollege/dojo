import logging

import docker


from ..utils import all_docker_clients
from ..config import DOCKER_USERNAME, DOCKER_TOKEN


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


for image, in DojoChallenges.query.with_entities(db.distinct(DojoChallenges.data["image"])).all():
    if not image or image.startswith("mac:") or image.startswith("pwncollege-"):
        continue

    for client in all_docker_clients():
        image_name = f"registry.localhost.pwn.college/{image}"

        if DOCKER_USERNAME and DOCKER_TOKEN:
            client.login(DOCKER_USERNAME, DOCKER_TOKEN, registry="registry.localhost.pwn.college")

        logger.info(f"Pulling image {image_name} on {client.api.base_url}...")
        try:
            client.images.pull(image_name)
        except docker.errors.ImageNotFound:
            logger.error(f"... image not found: {imange_name} on {client.api.base_url}...")
        except Exception as e:
            logger.error(f"... error: {image_name} on {client.api.base_url}...", exc_info=e)
