from flask import request
from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import Users

from ...models import Dojos

score_namespace = Namespace("score")

def get_user_score(username):
    # Alternative: hardcode max count and challenge id's for speed
    # POSSIBLE BUG HERE - topics and courses dojos might result in doubling
    # but since solves carry over, it should not be an issue
    # Maybe have a proper scoring system where babyarch has more weight than babysuid
    official_dojos = Dojos.query.filter_by(official=1).all()
    official_challenge_ids = []
    user_score = 0
    max_score = 0

    for dojo in official_dojos:
        for challenge in dojo.challenges:
            official_challenge_ids.append(challenge.challenge_id)

        max_score += len(dojo.challenges)

    user = Users.query.filter_by(name=username).first()
    for solve in user.solves:
        if solve.challenge_id in official_challenge_ids:
            user_score += 1

    return f"{user_score}:{max_score}"

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

        return get_user_score(username=username)
