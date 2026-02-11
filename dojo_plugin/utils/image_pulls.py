import json
import logging
import os
import random
import time
from typing import Any, Callable, Dict, Iterable, Optional, Tuple, Union

import redis

from .background_stats import get_redis_client

logger = logging.getLogger(__name__)

IMAGE_PULL_STREAM_NAME = "image:pull:events"
CONSUMER_GROUP = "image-pull-workers"
CONSUMER_NAME = f"image-pull-worker-{os.getpid()}"
MAX_PULL_ATTEMPTS = 5
PENDING_IDLE_MS = 60_000


def publish_image_pull(image: str, dojo_reference_id: Optional[str] = None, attempt: int = 0, max_attempts: int = MAX_PULL_ATTEMPTS) -> Optional[str]:
    try:
        r = get_redis_client()
        event = {
            "image": image,
            "dojo_reference_id": dojo_reference_id,
            "attempt": attempt,
            "max_attempts": max_attempts,
        }
        message_id = r.xadd(IMAGE_PULL_STREAM_NAME, {"data": json.dumps(event)})
        logger.info(f"Published image pull for {image}: {message_id}")
        return message_id
    except (redis.RedisError, redis.ConnectionError) as e:
        logger.error(f"Failed to publish image pull for {image}: {e}")
        return None


def enqueue_dojo_image_pulls(dojo) -> None:
    images = set()
    for module in dojo.modules or []:
        for challenge in module.challenges or []:
            image = (challenge.data or {}).get("image")
            if image:
                images.add(image)

    for image in images:
        if image.startswith("mac:") or image.startswith("pwncollege-"):
            continue
        publish_image_pull(image, dojo_reference_id=dojo.reference_id)


HandlerResult = Union[bool, Tuple[bool, bool]]

def _parse_handler_result(result: HandlerResult) -> Tuple[bool, bool]:
    if isinstance(result, tuple) and len(result) == 2:
        return result[0], result[1]
    if isinstance(result, bool):
        return result, False
    return True, False

def consume_image_pull_events(handler: Callable[[Dict[str, Any]], HandlerResult], batch_size: int = 10, block_ms: int = 5000) -> None:
    r = get_redis_client()

    def ensure_consumer_group():
        try:
            r.xgroup_create(IMAGE_PULL_STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
            logger.info(f"Created consumer group {CONSUMER_GROUP} for stream {IMAGE_PULL_STREAM_NAME}")
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            logger.info(f"Consumer group {CONSUMER_GROUP} already exists")

    ensure_consumer_group()
    logger.info(f"Image pull worker {CONSUMER_NAME} waiting for events...")

    def process_message(message_id, message_data):
        try:
            raw = message_data.get("data")
            if not raw:
                raise ValueError("missing data field")
            event_data = json.loads(raw)
        except Exception as e:
            logger.error(f"Invalid image pull event {message_id}: {e}", exc_info=True)
            try:
                r.xackdel(IMAGE_PULL_STREAM_NAME, CONSUMER_GROUP, message_id)
            except Exception:
                pass
            return

        attempt = int(event_data.get("attempt", 0))
        max_attempts = int(event_data.get("max_attempts", MAX_PULL_ATTEMPTS))

        try:
            success, retry = _parse_handler_result(handler(event_data))
        except Exception as e:
            logger.error(f"Error handling image pull event {message_id}: {e}", exc_info=True)
            success, retry = False, True

        if success:
            r.xackdel(IMAGE_PULL_STREAM_NAME, CONSUMER_GROUP, message_id)
            logger.info(f"Processed image pull event {message_id}")
            return

        image = event_data.get("image")
        if retry and attempt + 1 < max_attempts:
            delay = min(60.0, (2 ** attempt) + random.random())
            logger.warning(f"Retrying image pull for {image} in {delay:.1f}s (next attempt {attempt + 2}/{max_attempts})")
            time.sleep(delay)
            republished = publish_image_pull(
                image,
                dojo_reference_id=event_data.get("dojo_reference_id"),
                attempt=attempt + 1,
                max_attempts=max_attempts,
            )
            if republished:
                r.xackdel(IMAGE_PULL_STREAM_NAME, CONSUMER_GROUP, message_id)
            else:
                logger.error(f"Failed to re-enqueue image pull for {image}; leaving message pending")
            return

        logger.error(f"Dropping image pull for {image} after {attempt + 1}/{max_attempts} attempts")
        r.xackdel(IMAGE_PULL_STREAM_NAME, CONSUMER_GROUP, message_id)

    while True:
        try:
            try:
                autoclaim = getattr(r, "xautoclaim", None)
                if autoclaim:
                    result = autoclaim(
                        IMAGE_PULL_STREAM_NAME,
                        CONSUMER_GROUP,
                        CONSUMER_NAME,
                        min_idle_time=PENDING_IDLE_MS,
                        start_id="0-0",
                        count=batch_size,
                    )
                    claimed = result[1] if isinstance(result, tuple) and len(result) >= 2 else []
                    for message_id, message_data in claimed:
                        process_message(message_id, message_data)
            except Exception as e:
                logger.error(f"Error autoclaiming image pull events: {e}", exc_info=True)
                time.sleep(1)

            messages = r.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {IMAGE_PULL_STREAM_NAME: ">"},
                count=batch_size,
                block=block_ms
            )

            if not messages:
                continue

            for _, stream_messages in messages:
                for message_id, message_data in stream_messages:
                    process_message(message_id, message_data)
        except redis.ResponseError as e:
            if "NOGROUP" in str(e):
                logger.warning("Image pull consumer group missing, recreating...")
                ensure_consumer_group()
            else:
                logger.error(f"Redis error in image pull worker: {e}")
                time.sleep(1)
        except redis.ConnectionError as e:
            logger.error(f"Redis connection error in image pull worker: {e}")
            time.sleep(1)
