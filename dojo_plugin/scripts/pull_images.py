import logging

import docker


from ..utils import all_docker_clients
from ..config import REGISTRY_USERNAME, REGISTRY_PASSWORD, REGISTRY_HOST


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


for image, in DojoChallenges.query.with_entities(db.distinct(DojoChallenges.data["image"])).all():
    if not image or image.startswith("mac:") or image.startswith("pwncollege-"):
        continue

    for client in all_docker_clients():
        image_name = f"{REGISTRY_HOST}/{image}"

        if REGISTRY_USERNAME and REGISTRY_PASSWORD:
            client.login(REGISTRY_USERNAME, REGISTRY_PASSWORD, registry=REGISTRY_HOST)

        logger.info(f"Pulling image {image_name} on {client.api.base_url}...")
        try:
            client.images.pull(image_name)
        except docker.errors.ImageNotFound:
            logger.error(f"... image not found what are you doing: {image_name} on {client.api.base_url}...")
        except Exception as e:
            logger.error(f"... error: {image_name} on {client.api.base_url}...", exc_info=e)
