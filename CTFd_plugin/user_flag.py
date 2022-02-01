import sys
import datetime

from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from itsdangerous.exc import BadSignature
from CTFd.models import db, Challenges
from CTFd.plugins.flags import BaseFlag, FlagException
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from .utils import unserialize_user_flag


class Cheaters(db.Model):
    __tablename__ = "cheaters"
    id = db.Column(db.Integer, primary_key=True)
    cheater_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    cheatee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    cheater_challenge_id = db.Column(
        db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE")
    )
    cheatee_challenge_id = db.Column(
        db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE")
    )
    challenge_data = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    cheater = db.relationship(
        "Users", foreign_keys="Cheaters.cheater_id", lazy="select"
    )
    cheatee = db.relationship(
        "Users", foreign_keys="Cheaters.cheatee_id", lazy="select"
    )
    cheater_challenge = db.relationship(
        "Challenges", foreign_keys="Cheaters.cheater_challenge_id", lazy="select"
    )
    cheatee_challenge = db.relationship(
        "Challenges", foreign_keys="Cheaters.cheatee_challenge_id", lazy="select"
    )


class MultiSolves(db.Model):
    __tablename__ = "multi_solves"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    challenge_category = db.Column(db.String(80), primary_key=True)
    challenge_data = db.Column(db.String(80), primary_key=True)


class UserFlag(BaseFlag):
    name = "user"
    templates = {  # Nunjucks templates used for key editing & viewing
        "create": "/plugins/pwncollege_plugin/assets/user_flag/create.html",
        "update": "/plugins/pwncollege_plugin/assets/user_flag/edit.html",
    }

    @staticmethod
    def compare(chal_key_obj, provided):
        options = chal_key_obj.data.split(",")
        option_cheater = "cheater" in options
        option_multi = "multi" in options

        current_challenge_id = chal_key_obj.challenge_id
        current_account_id = get_current_user().account_id

        try:
            account_id, challenge_id, challenge_data = unserialize_user_flag(provided)
        except BadSignature:
            return False

        if account_id == 0 and challenge_id == 0 and challenge_data == 0:
            # Practice flag
            raise FlagException("This is a practice flag!")

        if account_id != current_account_id:
            print(
                f"Cheater: User ({current_account_id}, {current_challenge_id}) took flag from ({account_id}, {challenge_id}, {challenge_data})",
                file=sys.stderr,
            )

            cheater = Cheaters(
                cheater_id=current_account_id,
                cheatee_id=account_id,
                cheater_challenge_id=current_challenge_id,
                cheatee_challenge_id=challenge_id,
                challenge_data=challenge_data,
            )
            db.session.add(cheater)
            db.session.commit()

            if option_cheater and challenge_id == current_challenge_id:
                return True
            elif not option_cheater:
                raise FlagException("This flag does not belong to you!")

        if challenge_id != current_challenge_id:
            raise FlagException("This flag is not for this challenge!")

        if option_multi != bool(challenge_data):
            print(
                f"Challenge Configuration Error: Received challenge data ({challenge_data}) with multi ({option_multi})",
                file=sys.stderr,
            )
            raise FlagException("Error: this challenge is not correctly configured")

        if option_multi:
            challenge = Challenges.query.filter_by(id=current_challenge_id).first()

            multi_solve = MultiSolves(
                user_id=account_id,
                challenge_category=challenge.category,
                challenge_data=challenge_data,
            )
            try:
                db.session.add(multi_solve)
                db.session.commit()
                return True
            except IntegrityError:
                db.session.rollback()
                raise FlagException("You have already submitted this flag!")

        return True


user_flag_namespace = Namespace(
    "user_flag", description="Endpoint to manage user flags"
)


@user_flag_namespace.route("/multi_solved/<category>")
class MultiSolved(Resource):
    @authed_only
    def get(self, category):
        user = get_current_user()

        solves = MultiSolves.query.filter_by(
            user_id=user.account_id, challenge_category=category
        )
        solved = [solve.challenge_data for solve in solves]

        return {"success": True, "solved": solved}
