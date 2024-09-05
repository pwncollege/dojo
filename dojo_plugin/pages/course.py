import collections
import datetime
import re

from flask import Blueprint, Response, render_template, request, abort, stream_with_context
from sqlalchemy import and_, cast
from CTFd.models import db, Challenges, Solves, Users
from CTFd.utils import get_config
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only, ratelimit

from ..models import DiscordUsers, DojoChallenges, DojoUsers, DojoStudents, DojoModules, DojoStudents
from ..utils import is_dojo_admin
from ..utils.dojo import dojo_route
from ..utils.discord import add_role, get_discord_member
from .writeups import WriteupComments, writeup_weeks, all_writeups

course = Blueprint("course", __name__)


def get_letter_grade(dojo, grade):
    for letter_grade, min_score in dojo.course.get("letter_grades", {}).items():
        if grade >= min_score:
            return letter_grade
    return "?"


def assessment_name(dojo, assessment):
    module_names = {module.id: module.name for module in dojo.modules}
    if assessment["type"] == "checkpoint":
        return f"{module_names[assessment['id']]} Checkpoint"
    if assessment["type"] == "due":
        return module_names[assessment["id"]]
    return assessment["name"]


def grade(dojo, users_query, *, ignore_pending=False):
    if isinstance(users_query, Users):
        users_query = Users.query.filter_by(id=users_query.id)

    now = datetime.datetime.now(datetime.timezone.utc)
    assessments = dojo.course.get("assessments", [])

    assessment_dates = collections.defaultdict(lambda: collections.defaultdict(dict))
    for assessment in assessments:
        if assessment["type"] not in ["checkpoint", "due"]:
            continue
        assessment_dates[assessment["id"]][assessment["type"]] = (
            datetime.datetime.fromisoformat(assessment["date"]).astimezone(datetime.timezone.utc),
            datetime.datetime.fromisoformat(assessment.get("extra_late_date","3000-01-01T16:59:59-07:00")).astimezone(datetime.timezone.utc),
            assessment.get("extensions", {}),
        )

    def dated_count(label, date_type):
        if date_type is None:
            query = lambda module_id: True
        else:
            def query(module_id):
                if date_type not in assessment_dates[module_id]:
                    return None
                date, extra_late_date, extensions = assessment_dates[module_id][date_type]
                if label == "extra_late_solves":
                    if extra_late_date is None:
                        return False 
                    date = extra_late_date
                user_date = db.case(
                    [(Solves.user_id == int(user_id), date + datetime.timedelta(days=days))
                     for user_id, days in extensions.items()],
                    else_=date
                ) if extensions else date
                if label == "late_solves":
                    
                    return and_(Solves.date >= user_date, Solves.date < extra_late_date)  
                elif label == "extra_late_solves":
                    return Solves.date >= user_date                
                return Solves.date < user_date
        return db.func.sum(
            db.case([(DojoModules.id == module_id, cast(query(module_id), db.Integer))
                     for module_id in assessment_dates] +
                    [(False, None)])
        ).label(label)

    solves = (
        dojo
        .solves(ignore_visibility=True)
        .join(DojoModules, and_(
            DojoModules.dojo_id == DojoChallenges.dojo_id,
            DojoModules.module_index == DojoChallenges.module_index,
        ))
        .group_by(Solves.user_id, DojoModules.id)
        .order_by(Solves.user_id, DojoModules.module_index)
        .with_entities(
            Solves.user_id,
            DojoModules.id.label("module_id"),
            dated_count("checkpoint_solves", "checkpoint"),
            dated_count("due_solves", "due"),
            dated_count("late_solves", "due"),
            dated_count("extra_late_solves", "due"),            
            dated_count("all_solves", None)
        )
    ).subquery()
    user_solves = (
        users_query
        .join(solves, Users.id == solves.c.user_id, isouter=True)
        .with_entities(Users.id, *(column for column in solves.c if column.name != "user_id"))
    )

    challenge_counts = {module.id: len(module.challenges) for module in dojo.modules}

    module_solves = {}

    def result(user_id):
        assessment_grades = []

        for assessment in assessments:
            type = assessment.get("type")

            date = datetime.datetime.fromisoformat(assessment["date"]) if type in ["checkpoint", "due"] else None
            if ignore_pending and date and date > now:
                continue
            
            extra_late_date = datetime.datetime.fromisoformat(assessment.get("extra_late_date",None)) if type in ["checkpoint", "due"] and "extra_late_date" in assessment else None

            if type == "checkpoint":
                module_id = assessment["id"]
                weight = assessment["weight"]
                percent_required = assessment.get("percent_required", 0.334)
                extension = assessment.get("extensions", {}).get(str(user_id), 0)

                challenge_count = challenge_counts[module_id]
                checkpoint_solves, due_solves, late_solves, extra_late_solves, all_solves = module_solves.get(module_id, (0, 0, 0, 0, 0))
                challenge_count_required = int(challenge_count * percent_required)
                user_date = date + datetime.timedelta(days=extension)

                assessment_grades.append(dict(
                    name=assessment_name(dojo, assessment),
                    date=str(user_date) + (" *" if extension else ""),
                    weight=weight,
                    progress=f"{checkpoint_solves} / {challenge_count_required}",
                    credit=bool(checkpoint_solves // (challenge_count_required)) if challenge_count_required > 0 else False,
                ))

            if type == "due":
                module_id = assessment["id"]
                weight = assessment["weight"]
                percent_required = assessment.get("percent_required", 1.0)
                late_penalty = assessment.get("late_penalty", 0.0)

                extra_late_penalty = assessment.get("extra_late_penalty", 0.0)

                extension = assessment.get("extensions", {}).get(str(user_id), 0)
                override = assessment.get("overrides", {}).get(str(user_id), None)

                challenge_count = challenge_counts[module_id]
                checkpoint_solves, due_solves, late_solves, extra_late_solves, all_solves = module_solves.get(module_id, (0, 0, 0, 0, 0))
                
                challenge_count_required = int(challenge_count * percent_required)
                user_date = date + datetime.timedelta(days=extension)
                extra_late_user_date = None 
                if extra_late_date is not None:
                    extra_late_user_date = extra_late_date + datetime.timedelta(days=extension)
                late_value = 1 - late_penalty
                extra_late_value = 1 - extra_late_penalty

                max_late_solves = challenge_count_required - min(due_solves, challenge_count_required)
                capped_late_solves =  min(max_late_solves, late_solves)
                capped_extra_late_solves = min(max_late_solves-capped_late_solves, extra_late_solves)
                
                if not late_solves and not extra_late_solves:
                    progress = f"{due_solves} / {challenge_count_required}"
                elif late_solves and not extra_late_solves:
                    progress = f"{due_solves} (+{late_solves}) / {challenge_count_required}"
                elif not late_solves and extra_late_solves:
                    progress = f"{due_solves} (+{extra_late_solves}) / {challenge_count_required}"
                else: 
                    progress = f"{due_solves} (+{late_solves}) (+{extra_late_solves}) / {challenge_count_required}"
                if override is None:
                    late_points = late_value * capped_late_solves
                    extra_late_points = extra_late_value * capped_extra_late_solves
                    credit = min((due_solves +  late_points + extra_late_points ) / challenge_count_required, 1.0) if challenge_count_required > 0 else 0
                else:
                    credit = override
                    progress = f"{progress} *"

                assessment_grades.append(dict(
                    name=assessment_name(dojo, assessment),
                    date=str(user_date) + (" *" if extension else ""),
                    extra_late_date=str(extra_late_user_date)  + (" *" if extension else ""),                    
                    weight=weight,
                    progress=progress,
                    credit=credit,
                    module_id=module_id
                ))

            if type == "manual":
                assessment_grades.append(dict(
                    name=assessment_name(dojo, assessment),
                    weight=assessment["weight"],
                    progress=assessment.get("progress", {}).get(str(user_id), ""),
                    credit=assessment.get("credit", {}).get(str(user_id), 0.0),
                ))

            if type == "extra":
                assessment_grades.append(dict(
                    name=assessment_name(dojo, assessment),
                    progress=assessment.get("progress", {}).get(str(user_id), ""),
                    credit=assessment.get("credit", {}).get(str(user_id), 0.0),
                ))

        overall_grade = (
            sum(grade["credit"] * grade["weight"] for grade in assessment_grades if "weight" in grade) /
            sum(grade["weight"] for grade in assessment_grades if "weight" in grade)
        ) if assessment_grades else 1.0
        extra_credit = (
            sum(grade["credit"] for grade in assessment_grades if "weight" not in grade)
        )
        overall_grade += extra_credit
        overall_grade = round(overall_grade, 4)
        letter_grade = get_letter_grade(dojo, overall_grade)

        return dict(user_id=user_id,
                    assessment_grades=assessment_grades,
                    overall_grade=overall_grade,
                    letter_grade=letter_grade,
                    show_extra_late_date= any(row.get('extra_late_date',None) is not None for row in assessments))

    user_id = None
    previous_user_id = None
    for user_id, module_id, checkpoint_solves, due_solves, late_solves, extra_late_solves, all_solves in user_solves:
        if user_id != previous_user_id:
            if previous_user_id is not None:
                yield result(previous_user_id)
                module_solves = {}
            previous_user_id = user_id
        if module_id is not None:
            module_solves[module_id] = (
                int(checkpoint_solves) if checkpoint_solves is not None else 0,
                int(due_solves) if due_solves is not None else 0,
                int(late_solves) if late_solves is not None else 0,
                int(extra_late_solves) if extra_late_solves is not None else 0,
                int(all_solves) if all_solves is not None else 0,
            )
    if user_id:
        yield result(user_id)


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

    ignore_pending = request.args.get("ignore_pending") is not None

    student = DojoStudents.query.filter_by(dojo=dojo, user=user).first()

    grades = next(grade(dojo, user, ignore_pending=ignore_pending)) if user else {}

    identity = dict(identity_name=dojo.course.get("student_id", "Identity"),
                    identity_value=student.token if student else None)

    setup = {}
    setup["create_account"] = "complete" if user else "incomplete"
    setup["link_student"] = (
        "incomplete" if not student else
        "unknown" if not student.official else
        "complete"
    )

    discord_role = dojo.course.get("discord_role")
    if discord_role:
        if DiscordUsers.query.filter_by(user=user).first():
            setup["create_discord"] = "complete"
            setup["link_discord"] = "complete"
        else:
            setup["create_discord"] = "incomplete"
            setup["link_discord"] = "incomplete"

        if user and get_discord_member(user.id):
            setup["join_discord"] = "complete"
        else:
            setup["join_discord"] = "incomplete"

    setup_complete = all(status == "complete" for status in setup.values())

    return render_template("course.html",
                           name=name,
                           **grades,
                           **identity,
                           **setup,
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
        discord_member = get_discord_member(user.id)
        if discord_member is None:
            return {"success": True, "warning": "Your Discord account is not linked"}
        if discord_member is False:
            return {"success": True, "warning": "Your Discord account has not joined the official Discord server"}
        add_role(discord_member["user"]["id"], discord_role)

    return {"success": True}


@course.route("/dojo/<dojo>/admin/grades")
@dojo_route
@authed_only
def view_all_grades(dojo):
    if not dojo.course:
        abort(404)

    if not dojo.is_admin():
        abort(403)

    ignore_pending = request.args.get("ignore_pending") is not None

    students = {student.user_id: student.token for student in dojo.students}
    course_students = dojo.course.get("students", [])
    missing_students = list(set(course_students) - set(students.values()))

    users = (
        Users
        .query
        .join(DojoStudents, DojoStudents.user_id == Users.id)
        .filter(DojoStudents.dojo == dojo,
                DojoStudents.token.in_(course_students))
    )
    grades = sorted(grade(dojo, users, ignore_pending=ignore_pending),
                    key=lambda grade: grade["overall_grade"],
                    reverse=True)

    average_grade = sum(grade["overall_grade"] for grade in grades) / len(grades) if grades else 0.0
    average_letter_grade = get_letter_grade(dojo, average_grade)
    average_grade_summary = f"{average_letter_grade} ({average_grade * 100:.2f}%)"
    average_grade_details = []
    cumulative_count = 0
    for letter_grade in dojo.course.get("letter_grades", {}):
        count = sum(1 for grade in grades if grade["letter_grade"] == letter_grade)
        cumulative_count += count
        percent = f"{count / len(grades) * 100:.2f}%" if grades else "0.00%"
        cumulative_percent = f"{cumulative_count / len(grades) * 100:.2f}%" if grades else "0.00%"
        average_grade_details.append({
            "Grade": letter_grade,
            "Count": count,
            "Percent": percent,
            "Cumulative Percent": cumulative_percent,
        })
    grade_statistics = {
        "Average": (average_grade_summary, average_grade_details),
    }

    return render_template("grades_admin.html",
                           grades=grades,
                           grade_statistics=grade_statistics,
                           students=students,
                           missing_students=missing_students,
                           dojo=dojo)


@course.route("/dojo/<dojo>/admin/grades.csv")
@dojo_route
@authed_only
def download_all_grades(dojo):
    if not dojo.course:
        abort(404)

    if not dojo.is_admin():
        abort(403)

    ignore_pending = request.args.get("ignore_pending") is not None

    def stream():
        assessments = dojo.course.get("assessments", [])

        fields = ["student", "user", "letter", "overall"]
        fields.extend([re.sub("[^a-z0-9\-]", "", re.sub("\s+", "-", assessment_name(dojo, assessment).lower()))
                       for assessment in assessments])
        yield ",".join(fields) + "\n"

        students = {student.user_id: student.token for student in dojo.students}
        course_students = dojo.course.get("students", [])
        missing_students = list(set(course_students) - set(students.values()))

        users = (
            Users
            .query
            .join(DojoStudents, DojoStudents.user_id == Users.id)
            .filter(DojoStudents.dojo == dojo,
                    DojoStudents.token.in_(dojo.course.get("students", [])))
        )
        grades = sorted(grade(dojo, users, ignore_pending=ignore_pending),
                        key=lambda grade: grade["overall_grade"],
                        reverse=True)
        yield from (
            ",".join(str(value) if not isinstance(value, float) else f"{value:.2f}" for value in [
                students[grade["user_id"]], grade["user_id"], grade["letter_grade"], grade["overall_grade"],
                *[float(assessment_grade["credit"]) for assessment_grade in grade["assessment_grades"]],
            ]) + "\n"
            for grade in grades
        )

        yield from (
            ",".join([student, "", "", ""] + [""] * len(dojo.course.get("assessments", []))) + "\n"
            for student in missing_students
        )

    headers = {"Content-Disposition": "attachment; filename=data.csv"}
    return Response(stream_with_context(stream()), headers=headers, mimetype="text/csv")


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
    discord_member = get_discord_member(user.id) if dojo.course.get("discord_role") else None

    return render_template("dojo_admin_user.html",
                           dojo=dojo,
                           user=user,
                           discord_member=discord_member,
                           **identity)
