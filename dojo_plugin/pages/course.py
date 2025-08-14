import collections
import datetime
import math
import re

from flask import Blueprint, Response, render_template, request, abort, stream_with_context
from sqlalchemy import and_, cast
from CTFd.models import db, Challenges, Solves, Users
from CTFd.utils import get_config
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only, ratelimit

from ..models import DiscordUsers, DojoChallenges, DojoUsers, DojoStudents, DojoModules, DojoStudents, DiscordUserActivity
from ..utils.dojo import dojo_route
from ..utils.discord import add_role, get_discord_member

course = Blueprint("course", __name__)


@course.route("/dojo/<dojo>/course")
@course.route("/dojo/<dojo>/course/<resource>")
@dojo_route
def view_course(dojo, resource=None):
    if not dojo.course:
        abort(404)

    if request.args.get("user"):
        if not dojo.is_admin():
            abort(403)
        user = Users.query.filter_by(id=request.args.get("user")).first_or_404()
        name = f"{user.name}'s"
    else:
        user = get_current_user()
        name = "Your"

    student = DojoStudents.query.filter_by(dojo=dojo, user=user).first()

    identity = dict(name=dojo.course.get("student_id", "Identity"),
                    value=student.token if student else None)

    setup = {}
    setup["create_account"] = "complete" if user else "incomplete"
    setup["link_student"] = (
        "incomplete" if not student else
        "unknown" if not student.official else
        "complete"
    )

    discord_role = dojo.course.get("discord_role")
    if discord_role:
        discord_user = DiscordUsers.query.filter_by(user=user).first()
        setup["create_discord"] = "complete" if discord_user else "incomplete"
        setup["link_discord"] = "complete" if discord_user else "incomplete"
        setup["join_discord"] = "complete" if discord_user and get_discord_member(discord_user.discord_id) else "incomplete"

    setup_complete = all(status == "complete" for status in setup.values())

    return render_template("course.html",
                           name=name,
                           identity=identity,
                           setup=setup,
                           discord_role=discord_role,
                           setup_complete=setup_complete,
                           user=user,
                           dojo=dojo)


@course.route("/dojo/<dojo>/course/identity", methods=["PATCH"])
@dojo_route
@authed_only
@ratelimit(method="PATCH", limit=10, interval=60)
def update_identity(dojo):
    if not dojo.course:
        abort(404)

    user = get_current_user()
    dojo_user = DojoUsers.query.filter_by(dojo=dojo, user=user).first()

    if dojo_user and dojo_user.type == "admin":
        return {"success": False, "error": "Cannot identify admin"}

    if dojo_user:
        db.session.delete(dojo_user)

    identity = request.json.get("identity", "").strip()
    student = DojoStudents(dojo=dojo, user=user, token=identity)
    db.session.add(student)
    db.session.commit()

    if not student.official:
        identity_name = dojo.course.get("student_id", "Identity")
        return {"success": True, "warning": f"Your {identity_name} is not on the official student roster"}

    discord_role = dojo.course.get("discord_role")
    if discord_role:
        discord_user = DiscordUsers.query.filter_by(user=user).first()
        if not discord_user:
            return {"success": True, "warning": "Your Discord account is not linked"}
        discord_member = get_discord_member(discord_user.discord_id)
        if not discord_member:
            return {"success": True, "warning": "Your Discord account has not joined the official Discord server"}
        add_role(discord_user.discord_id, discord_role)

    return {"success": True}


@course.route("/dojo/<dojo>/admin/grades")
@dojo_route
@authed_only
def view_all_grades(dojo):
    if not dojo.is_admin():
        abort(403)

    if not (dojo.course and dojo.course["scripts"].get("grade")):
        abort(404)

    return render_template("grades_admin.html", dojo=dojo)


@course.route("/dojo/<dojo>/admin/users/<user_id>")
@dojo_route
@authed_only
def view_user_info(dojo, user_id):
    if not dojo.course:
        abort(404)

    if not dojo.is_admin():
        abort(403)

    user = Users.query.filter_by(id=user_id).first_or_404()
    student = DojoStudents.query.filter_by(dojo=dojo, user=user).first()
    identity = dict(identity_name=dojo.course.get("student_id", "Identity"),
                    identity_value=student.token if student else None)
    discord_member = (get_discord_member(DiscordUsers.query.filter_by(user=user)
                                         .with_entities(DiscordUsers.discord_id).scalar())
                      if dojo.course.get("discord_role") else None)

    return render_template("dojo_admin_user.html",
                           dojo=dojo,
                           user=user,
                           discord_member=discord_member,
                           **identity)
