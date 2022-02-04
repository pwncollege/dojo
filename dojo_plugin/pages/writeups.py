import datetime

from flask import request, Blueprint, render_template, abort, send_file
from flask.helpers import safe_join
from CTFd.models import db, Users, Files, Comments
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.utils.uploads import get_uploader


writeups = Blueprint("writeups", __name__)


class WriteupFiles(Files):
    __mapper_args__ = {"polymorphic_identity": "writeup"}
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    date = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class WriteupComments(Comments):
    __mapper_args__ = {"polymorphic_identity": "writeup"}
    writeup_id = db.Column(db.Integer, db.ForeignKey("files.id", ondelete="CASCADE"))
    accepted = db.Column(db.Boolean)


def writeup_weeks():
    first_deadline = datetime.datetime.fromisoformat("2021-08-24 06:59:00")
    return [
        (
            first_deadline + datetime.timedelta(weeks=i) - datetime.timedelta(days=4),
            first_deadline + datetime.timedelta(weeks=i),
        )
        for i in range(16)
    ]


def all_writeups(user_id=None):
    writeups = WriteupFiles.query
    if user_id:
        writeups = writeups.filter_by(user_id=user_id)
    writeups = writeups.order_by(WriteupFiles.date)

    weeks = writeup_weeks()

    for writeup in writeups:
        for start, end in weeks:
            if start < writeup.date < end:
                yield (start, end), writeup


@writeups.route("/writeups", methods=["GET", "POST"])
@authed_only
def view_writeups():
    user = get_current_user()

    weeks = {week: (None, None) for week in writeup_weeks()}

    if request.method == "POST":
        writeup_file = request.files.get("writeup")
        if writeup_file:
            uploader = get_uploader()
            location = uploader.upload(
                file_obj=writeup_file, filename=writeup_file.filename
            )
            writeup = WriteupFiles(type="writeup", location=location, user_id=user.id)
            db.session.add(writeup)
            db.session.commit()

    for week, writeup in all_writeups(user.id):
        comment = (
            WriteupComments.query.filter_by(writeup_id=writeup.id)
            .order_by(WriteupComments.date.desc())
            .first()
        )
        weeks[week] = (writeup, comment)

    countdown = None
    now = datetime.datetime.utcnow()
    for i, (start, end) in enumerate(weeks):
        if start < now < end:
            remainder = datetime.timedelta(seconds=int((end - now).total_seconds()))
            countdown = f"Week #{i + 1} due in {remainder}"
            break

    return render_template("writeups.html", weeks=weeks, countdown=countdown)


@writeups.route("/writeups/<int:writeup_id>")
@authed_only
def view_writeup(writeup_id):
    user = get_current_user()
    writeup = WriteupFiles.query.filter_by(id=writeup_id).first()
    if not writeup:
        abort(404)
    if user.id != writeup.user_id and not is_admin():
        abort(404)
    uploader = get_uploader()
    return send_file(safe_join(uploader.base_path, writeup.location))


@writeups.route("/admin/writeups", methods=["GET", "POST"])
@admins_only
def view_admin_writeups():
    weeks = {week: {} for week in writeup_weeks()}

    if request.method == "POST":
        user = get_current_user()

        writeup_id = int(request.form["writeup_id"])
        content = request.form["comment"]
        accepted = request.form["accepted"].lower() == "accept"

        comment = WriteupComments(
            type="writeup",
            content=content,
            author_id=user.id,
            writeup_id=writeup_id,
            accepted=accepted,
        )
        db.session.add(comment)
        db.session.commit()

    for week, writeup in all_writeups():
        user = Users.query.filter_by(id=writeup.user_id).first()
        comment = (
            WriteupComments.query.filter_by(writeup_id=writeup.id)
            .order_by(WriteupComments.date.desc())
            .first()
        )
        weeks[week][user] = (writeup, comment)

    return render_template("admin_writeups.html", weeks=weeks)
