from flask import request
from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import Users
from CTFd.utils.decorators import ratelimit

from ...models import Dojos

score_namespace = Namespace("score")

@score_namespace.route("/validate")
class ValidateUser(Resource):
    """
    /validate?username=user&email=user@test.com
    This endpoint is publicly available, no auth needed.
    Returns 1 or 0 depending on if username/email exists or not.
    """
    @ratelimit(method="GET", limit=10, interval=60)
    def get(self):
        username = request.args.get("username")
        email = request.args.get("email")
        if not username or not email:
            return {"error": "`username` and `email` parameters are required"}, 400

        return int(bool(Users.query.filter_by(name=username, email=email).first()))

@score_namespace.route("")
class ScoreUser(Resource):
    """
    /score?username=user
    This endpoint is publicly available with no auth needed.
    Returns formatted data regarding a user's score.
    """
    def get(self):
        username = request.args.get("username")
        if not username:
            return {"error": "`username` parameter is required"}, 400

        user = Users.query.filter_by(name=username).first()
        if not user:
            return {"error": "user does not exist"}, 400

        official_challenge_ids = {challenge.challenge_id for dojo in Dojos.query.filter_by(official=1).all() for challenge in dojo.challenges}
        user_score = sum(1 for solve in user.solves if solve.challenge_id in official_challenge_ids)
        max_score = len(official_challenge_ids)

        return f"{user_score}:{max_score}"
