import logging
import os
import threading
import time

import redis
from flask import current_app

from ..api.v1.docker import (
    CONTAINER_STARTS_STREAM,
    DOCKER_START_LOCK_TIMEOUT,
    start_challenge,
    set_start_status,
)
from ..utils.feed import publish_container_start
from ..utils.background_stats import publish_stat_event, get_redis_client
from ..models import DojoChallenges
from CTFd.models import Users

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "container-workers"
AUTOCLAIM_MIN_IDLE_MS = 60_000
AUTOCLAIM_INTERVAL_TICKS = 12
MAX_ATTEMPTS = 3
RETRY_DELAY = 2
LOCK_REFRESH_INTERVAL = max(1, DOCKER_START_LOCK_TIMEOUT // 3)
RENEW_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
end
return 0
"""


def ensure_consumer_group(r):
    try:
        r.xgroup_create(CONTAINER_STARTS_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info(f"Created consumer group {CONSUMER_GROUP}")
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def release_user_lock(user_id, lock_token):
    redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
    raw_r = redis.from_url(redis_url)
    lock_key = f"user.{user_id}.docker.lock"
    try:
        current_token = raw_r.get(lock_key)
        if current_token is not None:
            token_to_compare = lock_token.encode() if isinstance(lock_token, str) else lock_token
            if current_token == token_to_compare:
                raw_r.delete(lock_key)
    except redis.RedisError:
        logger.warning(f"Failed to release lock for {user_id=}")


def renew_user_lock(r, user_id, lock_token, timeout_seconds):
    lock_key = f"user.{user_id}.docker.lock"
    try:
        result = r.eval(
            RENEW_LOCK_SCRIPT,
            1,
            lock_key,
            str(lock_token),
            int(timeout_seconds * 1000),
        )
        return bool(result)
    except redis.RedisError as e:
        logger.warning(f"Failed to renew lock for {user_id=}: {e}")
        return None


class UserLockHeartbeat:
    def __init__(self, r, user_id, lock_token, timeout_seconds):
        self.r = r
        self.user_id = user_id
        self.lock_token = lock_token
        self.timeout_seconds = timeout_seconds
        self.refresh_interval = LOCK_REFRESH_INTERVAL
        self.stop_event = threading.Event()
        self.thread = None
        self.lock_lost = False

    def _run(self):
        while not self.stop_event.wait(self.refresh_interval):
            renewed = renew_user_lock(self.r, self.user_id, self.lock_token, self.timeout_seconds)
            if renewed is True:
                continue
            if renewed is False:
                self.lock_lost = True
                logger.error(f"Lost docker lock for {self.user_id=}")
                break

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2)


def process_start(r, consumer_name, message_id, message_data):
    start_id = message_data["start_id"]
    user_id = int(message_data["user_id"])
    dojo_id = int(message_data["dojo_id"])
    module_index = int(message_data["module_index"])
    challenge_index = int(message_data["challenge_index"])
    practice = bool(int(message_data["practice"]))
    as_user_id_raw = message_data["as_user_id"]
    as_user_id = int(as_user_id_raw) if as_user_id_raw else None
    dojo_ref_id = message_data["dojo_ref_id"]
    dojo_official = bool(int(message_data["dojo_official"]))
    lock_token = message_data["lock_token"]

    logger.info(f"Processing {start_id=} {user_id=}")
    lock_heartbeat = UserLockHeartbeat(r, user_id, lock_token, DOCKER_START_LOCK_TIMEOUT)
    lock_heartbeat.start()

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
            if lock_heartbeat.lock_lost:
                last_error = "Lost start lock while starting challenge"
                break
            try:
                set_start_status(r, start_id, {
                    "status": "starting", "attempt": attempt, "max_attempts": MAX_ATTEMPTS,
                    "error": None, "user_id": user_id,
                })

                logger.info(f"Starting challenge {start_id=} {user_id=} {attempt=}/{MAX_ATTEMPTS}")
                start_challenge(user, dojo_challenge, practice, as_user=as_user)
                if lock_heartbeat.lock_lost:
                    raise RuntimeError("Lost start lock while starting challenge")

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
                logger.info(f"Container start succeeded {start_id=} {user_id=} {attempt=}")
                return
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Attempt failed {start_id=} {user_id=} {attempt=}: {e}")
                if attempt < MAX_ATTEMPTS and not lock_heartbeat.lock_lost:
                    time.sleep(RETRY_DELAY)

        set_start_status(r, start_id, {
            "status": "failed", "attempt": MAX_ATTEMPTS, "max_attempts": MAX_ATTEMPTS,
            "error": last_error or "Docker failed", "user_id": user_id,
        })
        logger.error(f"Container start failed {start_id=} {user_id=} attempts={MAX_ATTEMPTS}")
    finally:
        lock_heartbeat.stop()
        release_user_lock(user_id, lock_token)


def consume_container_starts(shutdown_event=None):
    consumer_name = f"worker-{os.getpid()}"
    r = get_redis_client()
    ensure_consumer_group(r)
    logger.info(f"Consumer {consumer_name=} waiting for container start jobs...")

    autoclaim_counter = 0

    while True:
        if shutdown_event is not None and shutdown_event.is_set():
            logger.info(f"Consumer {consumer_name=} shutting down")
            break

        try:
            if autoclaim_counter >= AUTOCLAIM_INTERVAL_TICKS:
                autoclaim_counter = 0
                try:
                    result = r.xautoclaim(
                        CONTAINER_STARTS_STREAM, CONSUMER_GROUP, consumer_name,
                        min_idle_time=AUTOCLAIM_MIN_IDLE_MS, start_id="0-0", count=1,
                    )
                    if result and len(result) >= 2:
                        claimed_messages = result[1]
                        for msg_id, msg_data in claimed_messages:
                            logger.info(f"Autoclaimed message {msg_id=}")
                            process_start(r, consumer_name, msg_id, msg_data)
                            r.xackdel(CONTAINER_STARTS_STREAM, CONSUMER_GROUP, msg_id)
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
                        r.xackdel(CONTAINER_STARTS_STREAM, CONSUMER_GROUP, message_id)
                    except Exception as e:
                        logger.error(f"Unexpected error processing {message_id=}: {e}", exc_info=True)

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
            logger.info(f"Consumer {consumer_name=} interrupted")
            break
