import logging
from datetime import datetime

import requests
from flask import request, Blueprint, abort, url_for
from CTFd.models import Users
from CTFd.utils.decorators import authed_only

from .course import grade
from ..models import DojoChallenges, DojoStudents, DojoStudents
from ..utils.dojo import dojo_route


canvas = Blueprint("canvas", __name__)

logger = logging.getLogger(__name__)


def canvas_request(endpoint, method="GET", *, dojo, **kwargs):
    missing = [attr for attr in ["canvas_token", "canvas_api_host", "canvas_course_id"] if not (dojo.course or {}).get(attr)]
    if missing:
        raise RuntimeError(f"Canvas not configured: missing {', '.join(missing)}")

    canvas_token = dojo.course["canvas_token"]
    canvas_api_host = dojo.course["canvas_api_host"]
    headers = {"Authorization": f"Bearer {canvas_token}"}
    url = f"https://{canvas_api_host}/api/v1{endpoint}"

    response = requests.request(method, url, headers=headers, **kwargs)
    response.raise_for_status()

    if "application/json" in response.headers.get("Content-Type", ""):
        return response.json()
    else:
        return response.content


def canvas_course_request(endpoint, method="GET", *, dojo, **kwargs):
    canvas_course_id = (dojo.course or {}).get("canvas_course_id")
    return canvas_request(f"/courses/{canvas_course_id}{endpoint}", method=method, dojo=dojo, **kwargs)


@canvas.route("/dojo/<dojo>/admin/canvas/sync")
@dojo_route
@authed_only
def canvas_sync(dojo):
    if not dojo.is_admin():
        abort(403)

    if not (dojo.course and dojo.course.get("canvas_token")):
        abort(404)

    ignore_pending = request.args.get("ignore_pending") is not None
    return sync_canvas(dojo, ignore_pending=ignore_pending)


@canvas.route("/dojo/<dojo>/admin/canvas/progress/<int:progress_id>")
@dojo_route
@authed_only
def canvas_progress(dojo, progress_id):
    if not dojo.is_admin():
        abort(403)

    if not (dojo.course and dojo.course.get("canvas_token")):
        abort(404)

    return canvas_request(f"/progress/{progress_id}", dojo=dojo)


def sync_canvas_user(user_id, challenge_id):
    for dojo_challenge in DojoChallenges.query.filter(DojoChallenges.challenge_id == challenge_id):
        dojo = dojo_challenge.dojo
        if not (dojo.course and dojo.course.get("canvas_token")):
            continue
        sync_canvas(dojo, module=dojo_challenge.module, user_id=user_id)


def sync_canvas(dojo, module=None, user_id=None, ignore_pending=False):
    course_students = dojo.course.get("students", [])
    users = (
        Users.query
        .join(DojoStudents, DojoStudents.user_id == Users.id)
        .filter(DojoStudents.dojo == dojo, DojoStudents.token.in_(course_students))
    )
    if user_id is not None:
        users = users.filter(DojoStudents.user_id == user_id)

    canvas_assignments = {}
    page = 1
    while True:
        response = canvas_course_request("/assignments", params=dict(per_page=100, page=page), dojo=dojo)
        if not response:
            break
        for assignment in response:
            canvas_assignments[assignment["id"]] = dict(
                id=assignment["id"],
                name=assignment["name"],
                due_date=datetime.strptime(assignment["due_at"], "%Y-%m-%dT%H:%M:%SZ") if assignment["due_at"] else None,
            )
        page += 1

    student_ids = {student.user_id: student.token for student in dojo.students}
    assessments = dojo.course.get("assessments", [])
    grades = grade(dojo, users, ignore_pending=ignore_pending)

    assignment_submissions = {}

    for user_grades in grades:
        for assessment, assessment_grade in zip(assessments, user_grades["assessment_grades"]):
            canvas_assignment = canvas_assignments.get(assessment.get("canvas_assignment_id"))

            if not canvas_assignment:
                continue
            if module and assessment["id"] != module.id:
                continue
            if not assessment_grade["credit"] and canvas_assignment["due_date"] and canvas_assignment["due_date"] > datetime.now():
                continue

            student_submissions = assignment_submissions.setdefault(canvas_assignment["id"], {})
            grade_data = student_submissions.setdefault("grade_data", {})
            student_id = student_ids[user_grades["user_id"]]
            grade_credit = f"{assessment_grade['credit'] * 100:.2f}%"
            grade_data[f"sis_user_id:{student_id}"] = {"posted_grade": grade_credit}

    progress_info = {}

    for assignment_id, grade_data in assignment_submissions.items():
        response = canvas_course_request(f"/assignments/{assignment_id}/submissions/update_grades", method="POST", dojo=dojo, json=grade_data)
        progress_url = url_for("canvas.canvas_progress", dojo=dojo.reference_id, progress_id=response["id"], _external=True)
        progress_info[assignment_id] = progress_url
        logger.info(f"Posted {len(grade_data)} grade(s) to Canvas assignment {assignment_id}: {progress_url}")

    return progress_info
