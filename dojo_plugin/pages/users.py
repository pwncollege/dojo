import datetime
import hashlib
import itertools
import re

from flask import Blueprint, Response, render_template, abort, url_for
from sqlalchemy.sql import and_
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.models import db, Users, Challenges, Solves
from CTFd.cache import cache

from ..models import Dojos, DojoModules, DojoChallenges
from ..utils import DATA_DIR
from ..utils.dojo import dojo_scoreboard_data


users = Blueprint("pwncollege_users", __name__)


def hacker_rank(user, dojo, module=None):
    return (
        dojo_scoreboard_data(dojo, module, fields=[])
        .filter(Users.id == user.id)
        .first()
    )


def view_hacker(user):
    current_user_dojos = set(Dojos.viewable(user=get_current_user()))
    dojos = [dojo for dojo in Dojos.viewable(user=user) if dojo in current_user_dojos]

    def competitors(dojo, module=None, user=None):
        query = dojo_scoreboard_data(dojo, module)
        if user:
            return db.session.query(query.subquery()).filter_by(user_id=user.id).first()
        return query

    return render_template("hacker.html", dojos=dojos, user=user, competitors=competitors)

@users.route("/hacker/<int:user_id>")
def view_other(user_id):
    user = Users.query.filter_by(id=user_id).first()
    if user is None:
        abort(404)
    return view_hacker(user)

@users.route("/hacker/")
@authed_only
def view_self():
    return view_hacker(get_current_user())

@users.route("/hacker/completion-report/")
@authed_only
def create_completion_report():
    user = get_current_user()
    solves = (
        dojo
        .solves(user=user, ignore_visibility=True)
        .join(DojoModules, and_(
            DojoModules.dojo_id == DojoChallenges.dojo_id,
            DojoModules.module_index == DojoChallenges.module_index))
        .order_by(Solves.id)
        .with_entities(Dojos.id, DojoModules.id, DojoChallenges.id, Solves.date)
        for dojo in Dojos.viewable(user=user)
    )
    result = []
    for dojo_id, module_id, challenge_id, date in itertools.chain.from_iterable(solves):
        date = date.replace(tzinfo=datetime.timezone.utc)
        result.append((dojo_id, module_id, challenge_id, date))
    result.sort(key=lambda row: row[-1])

    result = "".join(f"{dojo_id}/{module_id}/{challenge_id} @ {date}\n"
                     for dojo_id, module_id, challenge_id, date in result)
    result_hash = hashlib.sha256(result.encode()).hexdigest()

    completion_reports_dir = DATA_DIR / "completion-reports"
    completion_reports_dir.mkdir(exist_ok=True)
    completion_report_path = completion_reports_dir / f"{result_hash}.txt"
    completion_report_path.write_text(result)

    url = url_for("pwncollege_users.view_completion_report", hash=result_hash, _external=True)
    return Response(url, mimetype="text")


@users.route("/hacker/completion-report/<hash>.txt")
def view_completion_report(hash):
    if not re.match(r"^[0-9a-f]{64}$", hash):
        abort(404)

    completion_reports_dir = DATA_DIR / "completion-reports"
    completion_report_path = completion_reports_dir / f"{hash}.txt"
    if not completion_report_path.exists():
        abort(404)

    return Response(completion_report_path.read_text(), mimetype="text")