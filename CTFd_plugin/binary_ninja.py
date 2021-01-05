import requests
from flask import request
from flask_restx import Namespace, Resource
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.utils.security.signing import serialize

from .settings import INSTANCE, BINARY_NINJA_API_KEY
from .docker_challenge import DockerChallenges


binary_ninja_namespace = Namespace(
    "binary_ninja", description="Endpoint to manage binary ninja"
)


@binary_ninja_namespace.route("/generate")
class GenerateSession(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        challenge_id = data.get("challenge_id")

        try:
            challenge_id = int(challenge_id)
        except (ValueError, TypeError):
            return {"success": False, "error": "Invalid challenge id"}

        challenge = DockerChallenges.query.filter_by(id=challenge_id).first()
        if not challenge:
            return {"success": False, "error": "Invalid challenge"}

        user = get_current_user()
        account_id = user.account_id

        token = serialize({"account_id": account_id, "challenge_id": challenge_id})

        download_url = f"https://{INSTANCE}.pwn.college/download/{token}"

        category = challenge.category
        challenge = challenge.name

        if not BINARY_NINJA_API_KEY:
            return {"success": False, "error": "Missing API key"}

        binary_ninja_url = "https://cloud.binary.ninja/api/generate_session_link/"
        binary_ninja_json = {
            "api_key": BINARY_NINJA_API_KEY,
            "file_url": download_url,
            "session_name": f"{category}_{challenge}",
        }
        try:
            response = requests.post(binary_ninja_url, json=binary_ninja_json).json()
        except:
            return {"success": False, "error": "Failed to generate session"}

        session_url = response.get("url")
        if not session_url:
            return {
                "success": False,
                "error": response.get("msg", "Failed to generate session"),
            }

        return {"success": True, "url": session_url}
