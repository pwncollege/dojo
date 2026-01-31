import json
import logging
import os
import time

import redis
from flask import current_app

from ..api.v1.docker import (
    CONTAINER_STARTS_STREAM,
    start_challenge,
    set_start_status,
    get_start_status,
)
from ..utils.feed import publish_container_start
from ..utils.background_stats import publish_stat_event
from ..models import DojoChallenges
from CTFd.models import Users

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "container-workers"
AUTOCLAIM_MIN_IDLE_MS = 60_000
MAX_ATTEMPTS = 3
RETRY_DELAY = 2


def get_redis_client():
    redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
    return redis.from_url(redis_url)


def ensure_consumer_group(r):
    try:
        r.xgroup_create(CONTAINER_STARTS_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info(f"Created consumer group {CONSUMER_GROUP}")
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def release_user_lock(r, user_id, lock_token):
    lock_key = f"user.{user_id}.docker.lock"
    try:
        current_token = r.get(lock_key)
        if current_token is not None:
            token_to_compare = lock_token.encode() if isinstance(lock_token, str) else lock_token
            if current_token == token_to_compare:
                r.delete(lock_key)
    except redis.RedisError:
        logger.warning(f"Failed to release lock for user {user_id}")


def process_start(r, consumer_name, message_id, message_data):
    start_id = message_data[b"start_id"].decode()
    user_id = int(message_data[b"user_id"])
    dojo_id = int(message_data[b"dojo_id"])
    module_index = int(message_data[b"module_index"])
    challenge_index = int(message_data[b"challenge_index"])
    practice = bool(int(message_data[b"practice"]))
    as_user_id_raw = message_data[b"as_user_id"].decode()
    as_user_id = int(as_user_id_raw) if as_user_id_raw else None
    dojo_ref_id = message_data[b"dojo_ref_id"].decode()
    dojo_official = bool(int(message_data[b"dojo_official"]))
    lock_token = message_data[b"lock_token"].decode()

    logger.info(f"Processing start {start_id} for user {user_id}")

    try:
        user = Users.query.get(user_id)
        if user is None:
            set_start_status(r, start_id, {
                "status": "failed", "attempt": 0, "max_attempts": MAX_ATTEMPTS,
                "error": "User not found", "user_id": user_id,
            })
            return

        dojo_challenge = DojoChallenges.query.filter_by(
            dojo_id=dojo_id, module_index=module_index, challenge_index=challenge_index
        ).first()
        if dojo_challenge is None:
            set_start_status(r, start_id, {
                "status": "failed", "attempt": 0, "max_attempts": MAX_ATTEMPTS,
                "error": "Challenge not found", "user_id": user_id,
            })
            return

        as_user = None
        if as_user_id is not None:
            as_user = Users.query.get(as_user_id)

        last_error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                set_start_status(r, start_id, {
                    "status": "starting", "attempt": attempt, "max_attempts": MAX_ATTEMPTS,
                    "error": None, "user_id": user_id,
                })

                logger.info(f"Starting challenge for user {user_id} start={start_id} (attempt {attempt}/{MAX_ATTEMPTS})")
                start_challenge(user, dojo_challenge, practice, as_user=as_user)

                if dojo_official:
                    challenge_data = {
                        "challenge_id": dojo_challenge.challenge_id,
                        "challenge_name": dojo_challenge.name,
                        "module_id": dojo_challenge.module.id if dojo_challenge.module else None,
                        "module_name": dojo_challenge.module.name if dojo_challenge.module else None,
                        "dojo_id": dojo_ref_id,
                        "dojo_name": dojo_challenge.dojo.name,
                    }
                    mode = "practice" if practice else "assessment"
                    actual_user = as_user or user
                    publish_container_start(actual_user, mode, challenge_data)

                publish_stat_event("container_stats_update", {})

                set_start_status(r, start_id, {
                    "status": "ready", "attempt": attempt, "max_attempts": MAX_ATTEMPTS,
                    "error": None, "user_id": user_id,
                })
                logger.info(f"Container start {start_id} succeeded for user {user_id} on attempt {attempt}")
                return
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Attempt {attempt} failed for start {start_id} user {user_id}: {e}")
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_DELAY)

        set_start_status(r, start_id, {
            "status": "failed", "attempt": MAX_ATTEMPTS, "max_attempts": MAX_ATTEMPTS,
            "error": last_error or "Docker failed", "user_id": user_id,
        })
        logger.error(f"Container start {start_id} failed for user {user_id} after {MAX_ATTEMPTS} attempts")
    finally:
        release_user_lock(r, user_id, lock_token)


def consume_container_starts(shutdown_event=None):
    consumer_name = f"worker-{os.getpid()}"
    r = get_redis_client()
    ensure_consumer_group(r)
    logger.info(f"Consumer {consumer_name} waiting for container start jobs...")

    autoclaim_counter = 0

    while True:
        if shutdown_event is not None and shutdown_event.is_set():
            logger.info(f"Consumer {consumer_name} shutting down")
            break

        try:
            if autoclaim_counter >= 12:
                autoclaim_counter = 0
                try:
                    result = r.xautoclaim(
                        CONTAINER_STARTS_STREAM, CONSUMER_GROUP, consumer_name,
                        min_idle_time=AUTOCLAIM_MIN_IDLE_MS, start_id="0-0", count=1,
                    )
                    if result and len(result) >= 2:
                        claimed_messages = result[1]
                        for msg_id, msg_data in claimed_messages:
                            logger.info(f"Autoclaimed message {msg_id}")
                            process_start(r, consumer_name, msg_id, msg_data)
                            r.xack(CONTAINER_STARTS_STREAM, CONSUMER_GROUP, msg_id)
                except redis.ResponseError:
                    pass

            messages = r.xreadgroup(
                CONSUMER_GROUP, consumer_name,
                {CONTAINER_STARTS_STREAM: ">"},
                count=1, block=5000,
            )

            autoclaim_counter += 1

            if not messages:
                continue

            for stream_name, stream_messages in messages:
                for message_id, message_data in stream_messages:
                    try:
                        process_start(r, consumer_name, message_id, message_data)
                    except Exception as e:
                        logger.error(f"Unexpected error processing {message_id}: {e}", exc_info=True)
                    finally:
                        r.xack(CONTAINER_STARTS_STREAM, CONSUMER_GROUP, message_id)

        except redis.ResponseError as e:
            if "NOGROUP" in str(e):
                logger.warning("Consumer group was deleted, recreating...")
                ensure_consumer_group(r)
            else:
                logger.error(f"Redis error: {e}")
                time.sleep(1)
        except redis.ConnectionError as e:
            logger.error(f"Redis connection error: {e}")
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info(f"Consumer {consumer_name} interrupted")
            break
