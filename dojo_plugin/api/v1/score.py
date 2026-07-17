from flask import request
from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import Users, db, Solves, Challenges
from CTFd.utils.decorators import ratelimit

from ...models import Dojos, DojoChallenges, UserVisibilityUpdates
from ...utils.public_stats import lock_public_stats_visibility

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
        lock_public_stats_visibility()
        username = request.args.get("username")
        email = request.args.get("email")
        if not username or not email:
            return {"error": "`username` and `email` parameters are required"}, 400

        return int(bool(
            Users.query
            .outerjoin(
                UserVisibilityUpdates,
                UserVisibilityUpdates.user_id == Users.id,
            )
            .filter(
                Users.name == username,
                Users.email == email,
                ~Users.hidden,
                ~Users.banned,
            )
            .filter(UserVisibilityUpdates.user_id.is_(None))
            .first()
        ))

@score_namespace.route("")
class ScoreUser(Resource):
    """
    /score?username=user
    This endpoint is publicly available with no auth needed.
    Returns formatted data regarding a user's score.
    """
    def get(self):
        lock_public_stats_visibility()
        username = request.args.get("username")
        if not username:
            return {"error": "`username` parameter is required"}, 400

        user = (
            Users.query
            .outerjoin(
                UserVisibilityUpdates,
                UserVisibilityUpdates.user_id == Users.id,
            )
            .filter(
                Users.name == username,
                ~Users.hidden,
                ~Users.banned,
                UserVisibilityUpdates.user_id.is_(None),
            )
            .first()
        )
        if not user:
            return {"error": "user does not exist"}, 400

        official_challenges = (
            Challenges.query
            .join(DojoChallenges)
            .join(Dojos)
            .filter(Dojos.official, DojoChallenges.visible())
            .distinct()
            .with_entities(Challenges.id)
        )
        rank = db.func.row_number().over(
            order_by=(db.func.count(Solves.id).desc(), db.func.max(Solves.id))
        ).label("rank")
        scoreboard = (
            db.session.query(rank, Solves.user_id, db.func.count(Solves.id).label("solves"))
            .join(official_challenges.subquery())
            .join(Users, Users.id == Solves.user_id)
            .outerjoin(
                UserVisibilityUpdates,
                UserVisibilityUpdates.user_id == Users.id,
            )
            .filter(
                ~Users.hidden,
                ~Users.banned,
                UserVisibilityUpdates.user_id.is_(None),
            )
            .group_by(Solves.user_id)
            .order_by(rank)
            .all()
        )

        max_score = official_challenges.count()
        user_count = len(scoreboard)
        user_ranking = next((ranking for ranking in scoreboard if ranking.user_id == user.id), None)
        if not user_ranking:
            return {"error": "user is not ranked"}, 400

        # rank:score:max_score:challs_solved:chall_count:user_count
        return f"{user_ranking.rank}:{user_ranking.solves}:{max_score}:{user_ranking.solves}:{max_score}:{user_count}"
