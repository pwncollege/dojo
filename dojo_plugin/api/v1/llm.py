import logging

import redis
from flask import current_app, request
from flask_restx import Namespace, Resource
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

from .user import authed_only_cli
from ...config import (
    DOJO_HOST,
    LITELLM_MASTER_KEY,
    LITELLM_URL,
    LITELLM_USER_BUDGET_LIMITS,
    LITELLM_USER_KEY_SECRET,
)
from ...utils.dojo import get_current_dojo_challenge
from ...utils.llm import LiteLLMKeyManager


logger = logging.getLogger(__name__)
llm_namespace = Namespace("llm", description="Managed LLM credentials")


def key_manager():
    return LiteLLMKeyManager(
        base_url=LITELLM_URL,
        master_key=LITELLM_MASTER_KEY,
        user_key_secret=LITELLM_USER_KEY_SECRET,
        budget_limits=LITELLM_USER_BUDGET_LIMITS,
    )


@llm_namespace.route("/credentials")
class LLMCredentials(Resource):
    @authed_only_cli
    @authed_only
    def post(self):
        if not LITELLM_MASTER_KEY or not LITELLM_USER_KEY_SECRET:
            return {"success": False, "error": "Managed LLM access is disabled."}, 503

        user = get_current_user()
        challenge = get_current_dojo_challenge(user)
        if challenge is None:
            return {"success": False, "error": "No active challenge."}, 403
        if "llm" not in challenge.dojo.permissions:
            return {"success": False, "error": "The active dojo does not allow managed LLM access."}, 403

        redis_client = redis.from_url(current_app.config["REDIS_URL"])
        try:
            with redis_client.lock(
                f"llm-key.user_{user.id}.lock",
                blocking_timeout=10,
                timeout=30,
                raise_on_release_error=False,
            ):
                credentials = key_manager().credentials(user.id)
        except Exception:
            logger.exception("failed to provision managed LLM credentials for user %s", user.id)
            return {"success": False, "error": "Managed LLM credentials are temporarily unavailable."}, 503

        return {
            "success": True,
            "base_url": f"{request.scheme}://{DOJO_HOST}/llm",
            **credentials,
        }


@llm_namespace.route("/usage")
class LLMUsage(Resource):
    @authed_only_cli
    @authed_only
    def get(self):
        if not LITELLM_MASTER_KEY or not LITELLM_USER_KEY_SECRET:
            return {"success": False, "error": "Managed LLM access is disabled."}, 503

        user = get_current_user()
        try:
            usage = key_manager().usage(user.id)
        except Exception:
            logger.exception("failed to read managed LLM usage for user %s", user.id)
            return {"success": False, "error": "Managed LLM usage is temporarily unavailable."}, 503

        return {"success": True, **usage}
