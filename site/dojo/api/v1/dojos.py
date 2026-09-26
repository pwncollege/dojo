
import datetime
import logging
import sys
import traceback

import emoji as emojilib
from flask import g, request
from flask_restx import Namespace, Resource
from itsdangerous.exc import BadSignature
from sqlalchemy.sql import and_

from .user import authed_only_cli, authed_only_ssh
from ...models import (DojoChallenges, DojoModules, Dojos, DojoStudents,
                       DojoUsers, Emojis, SurveyResponses, Fails, Solves, Users, cache, db, get_config)
from ...utils import is_challenge_locked, parse_positive_int, render_markdown, unserialize_user_flag
from ...utils.decorators import admins_only, authed_only, ratelimit, require_verified_emails
from ...utils.user import audit_log, get_current_user, get_ip, is_admin
from ...utils.dojo import dojo_admins_only, dojo_create, dojo_route, dojo_from_spec
from ...utils.image_pulls import enqueue_dojo_image_pulls
from ...utils.stats import get_dojo_stats
from ...utils.events import publish_dojo_stats_event, publish_scoreboard_event
from ...utils.awards import dojo_gives_awards, grant_award, update_awards
from ...utils.feed import publish_challenge_solve

logger = logging.getLogger(__name__)

dojos_namespace = Namespace(
    "dojos", description="Endpoint to retrieve Dojos"
)


@dojos_namespace.route("")
class DojoList(Resource):
    @authed_only_ssh
    @authed_only_cli
    def get(self):
        # Query dojos with deferred fields for counts
        dojo_query = (
            Dojos.viewable(user=get_current_user())
            .options(db.undefer(Dojos.modules_count),
                     db.undefer(Dojos.challenges_count),
                     db.undefer(Dojos.required_challenges_count))
        )

        dojos = [
            dict(id=dojo.reference_id,
                 hex_id=dojo.hex_dojo_id,
                 name=dojo.name,
                 description=dojo.description,
                 type=dojo.type,
                 official=dojo.official,
                 award=dojo.award,
                 modules_count=dojo.modules_count,
                 challenges_count=dojo.required_challenges_count)
            for dojo in dojo_query
        ]
        return {"success": True, "dojos": dojos}


@dojos_namespace.route("/<dojo>/awards/prune")
class PruneAwards(Resource):
    @dojo_route
    @dojo_admins_only
    def post(self, dojo):
        all_completions = set(user for user,_ in dojo.completions())
        num_pruned = 0
        for award in Emojis.query.where(Emojis.category==dojo.hex_dojo_id, Emojis.name=="CURRENT"):
            if award.user not in all_completions:
                num_pruned += 1
                award.name = "STALE"
        db.session.commit()

        publish_dojo_stats_event(dojo.dojo_id)
        publish_scoreboard_event("dojo", dojo.dojo_id)

        return {"success": True, "pruned_awards": num_pruned}

@dojos_namespace.route("/<dojo>/promote")
class PromoteDojo(Resource):
    @admins_only
    @dojo_route
    def post(self, dojo):
        dojo.official = True
        db.session.commit()
        return {"success": True}

@dojos_namespace.route("/<dojo>/admins/promote")
class PromoteAdmin(Resource):
    @dojo_route
    @dojo_admins_only
    def post(self, dojo):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return {"success": False, "error": "JSON body must be an object"}, 400
        if 'user_id' not in data:
            return {"success": False, "error": "User not specified."}, 400
        new_admin_id = parse_positive_int(data['user_id'])
        if new_admin_id is None:
            return {"success": False, "error": "Invalid user id."}, 400
        u = DojoUsers.query.filter_by(dojo=dojo, user_id=new_admin_id).first()
        if u:
            u.type = 'admin'
        else:
            return {"success": False, "error": "User is not currently a dojo member."}, 400
        db.session.commit()
        return {"success": True}

@dojos_namespace.route("/create")
class CreateDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return {"success": False, "error": "JSON body must be an object"}, 400
        user = get_current_user()

        repository = data.get("repository", "")
        spec = data.get("spec", "")
        public_key = data.get("public_key", "")
        private_key = data.get("private_key", "")
        if not all(isinstance(value, str) for value in (repository, spec, public_key, private_key)):
            return {"success": False, "error": "Dojo fields must be strings"}, 400
        private_key = private_key.replace("\r\n", "\n")

        key = f"rl:{get_ip()}:{request.endpoint}"
        timeout = int(datetime.timedelta(days=1).total_seconds())

        if not is_admin() and cache.get(key) is not None:
            return {"success": False, "error": "You can only create 1 dojo per day."}, 429

        try:
            dojo = dojo_create(user, repository, public_key, private_key, spec)
        except RuntimeError as e:
            return {"success": False, "error": str(e)}, 400

        try:
            enqueue_dojo_image_pulls(dojo)
        except Exception as e:
            logger.error(f"Failed to enqueue image pulls for {dojo.reference_id}: {e}", exc_info=True)

        cache.set(key, 1, timeout=timeout)
        return {"success": True, "dojo": dojo.reference_id}


@dojos_namespace.route("/<dojo>/update")
class UpdateDojo(Resource):
    @dojo_route
    @dojo_admins_only
    def post(self, dojo):
        data = request.get_json()
        if not data:
            return {"success": False, "error": "Missing dojo spec."}, 400

        try:
            dojo_from_spec(data, dojo=dojo, platform_admin=is_admin())
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"ERROR: Dojo update failed for {dojo}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            return {"success": False, "error": str(e)}, 400

        try:
            enqueue_dojo_image_pulls(dojo)
        except Exception as e:
            logger.error(f"Failed to enqueue image pulls for {dojo.reference_id}: {e}", exc_info=True)

        return {"success": True}


@dojos_namespace.route("/<dojo>/modules")
class DojoModuleList(Resource):
    @authed_only_ssh
    @authed_only_cli
    @dojo_route
    def get(self, dojo):
        is_dojo_admin = dojo.is_admin()
        modules = [
            dict(id=module.id,
                 name=module.name,
                 description=module.description,
                 resources=[
                    dict(id=f"resource-{resource.resource_index}",
                         name=resource.name,
                         type=resource.type,
                         content=getattr(resource, 'content', None) if resource.type == "markdown" else None,
                         video=getattr(resource, 'video', None) if resource.type == "lecture" else None,
                         playlist=getattr(resource, 'playlist', None) if resource.type == "lecture" else None,
                         slides=getattr(resource, 'slides', None) if resource.type == "lecture" else None,
                         expandable=getattr(resource, 'expandable', True))
                    for resource in module.resources
                    if resource.visible or is_dojo_admin
                 ],
                 challenges=[
                    dict(id=challenge.id,
                         name=challenge.name,
                         required=challenge.required,
                         description=challenge.description)
                    for challenge in (module.visible_challenges() if not is_dojo_admin
                                      else module.challenges)
                 ],
                 unified_items=[
                     dict(
                         item_type=item.item_type,
                         id=f"resource-{item.resource_index}" if item.item_type == 'resource' else getattr(item, 'id', None),
                         name=item.name,
                         type=getattr(item, 'type', None),
                         content=getattr(item, 'content', None) if hasattr(item, 'type') and item.type in ["markdown", "header"] else None,
                         video=getattr(item, 'video', None) if hasattr(item, 'type') and item.type == "lecture" else None,
                         playlist=getattr(item, 'playlist', None) if hasattr(item, 'type') and item.type == "lecture" else None,
                         slides=getattr(item, 'slides', None) if hasattr(item, 'type') and item.type == "lecture" else None,
                         expandable=getattr(item, 'expandable', True) if hasattr(item, 'type') else None,
                         description=getattr(item, 'description', None),
                         required=getattr(item, 'required', None) if item.item_type == 'challenge' else None
                     ) for item in (module.unified_items if is_dojo_admin else module.visible_items)
                 ])

            for module in dojo.modules
            if module.visible() or is_dojo_admin
        ]

        return {
            "success": True,
            "modules": modules
        }

@dojos_namespace.route("/<dojo>/solves")
class DojoSolveList(Resource):
    @dojo_route
    def get(self, dojo):
        username = request.args.get("username")
        user = Users.query.filter_by(name=username, hidden=False).first() if username else get_current_user()
        if not user:
            return {"error": "User not found"}, 400

        solves_query = dojo.solves(
            user=user,
            include_visibility_exempt=True,
            include_hidden_users=True,
            include_admin_users=True,
        )

        if after := request.args.get("after"):
            try:
                after_date = datetime.datetime.fromisoformat(after).astimezone(datetime.timezone.utc)
            except ValueError:
                return {"success": False, "error": "Invalid after date format"}, 400
            solves_query = solves_query.filter(Solves.date > after_date)

        solves_query = solves_query.order_by(Solves.date.asc()).with_entities(Solves.date, DojoModules.id, DojoChallenges.id)
        solves = [
            dict(timestamp=timestamp.astimezone(datetime.timezone.utc).isoformat(),
                 module_id=module_id,
                 challenge_id=challenge_id)
            for timestamp, module_id, challenge_id in solves_query.all()
        ]
        return {"success": True, "solves": solves}


@dojos_namespace.route("/<dojo>/course")
class DojoCourse(Resource):
    @dojo_route
    def get(self, dojo):
        if not dojo.course:
            return {"success": False, "error": "This dojo is not a course"}, 404
        result = dict(syllabus=dojo.course.get("syllabus"), scripts=dojo.course.get("scripts"))
        student = DojoStudents.query.filter_by(dojo=dojo, user=get_current_user()).first()
        if student:
            result["student"] = dojo.course.get("students", {}).get(student.token, {}) | dict(token=student.token, user_id=student.user_id)
        return {"success": True, "course": result}


@dojos_namespace.route("/<dojo>/course/students")
class DojoCourseStudentList(Resource):
    @dojo_route
    @dojo_admins_only
    def get(self, dojo):
        if not dojo.course:
            return {"success": False, "error": "This dojo is not a course"}, 404
        dojo_students = {student.token: student.user_id for student in DojoStudents.query.filter_by(dojo=dojo).order_by(DojoStudents.user_id)}
        course_students = dojo.course.get("students", {})
        students = {
            token: course_data | dict(token=(token if token in dojo_students else None), user_id=dojo_students.get(token))
            for token, course_data in course_students.items()
        }
        return {"success": True, "students": students}


@dojos_namespace.route("/<dojo>/course/solves")
class DojoCourseSolveList(Resource):
    @dojo_route
    @dojo_admins_only
    def get(self, dojo):
        if not dojo.course:
            return {"success": False, "error": "This dojo is not a course"}, 404
        students = dojo.course.get("students", {})

        solves_query = dojo.solves(
            include_visibility_exempt=True,
            include_hidden_users=True,
            include_admin_users=True,
        )

        if after := request.args.get("after"):
            try:
                after_date = datetime.datetime.fromisoformat(after).astimezone(datetime.timezone.utc)
            except ValueError:
                return {"success": False, "error": "Invalid after date format"}, 400
            solves_query = solves_query.filter(Solves.date > after_date)

        student_token = request.args.get("student_token")
        if student_token is not None:
            solves_query = solves_query.filter(DojoStudents.token == student_token)

        if students:
            solves_query = solves_query.filter(DojoStudents.token.in_(students))

        # Selecting DojoStudents columns would restrict the query to student rows;
        # look the token up separately so solvers who never linked one still appear.
        student_tokens = {
            student.user_id: student.token
            for student in DojoStudents.query.filter_by(dojo=dojo)
        }
        solves_query = solves_query.order_by(Solves.date.asc()).with_entities(
            Solves.date, Solves.user_id, DojoModules.id, DojoChallenges.id)
        solves = [
            dict(timestamp=timestamp.astimezone(datetime.timezone.utc).isoformat(),
                 student_token=student_tokens.get(user_id),
                 user_id=user_id,
                 module_id=module_id,
                 challenge_id=challenge_id)
            for timestamp, user_id, module_id, challenge_id in solves_query.all()
        ]

        return {"success": True, "solves": solves}


def submitted_flag(request):
    return (request.form or request.get_json())["submission"].strip()


def attempt(challenge, request):
    if not any(flag.type == "dojo" for flag in challenge.flags):
        return False, "Incorrect"
    try:
        user_id, challenge_id = unserialize_user_flag(submitted_flag(request))
    except BadSignature:
        return False, "Incorrect"
    if user_id != get_current_user().id:
        return False, "This flag is not yours!"
    if challenge_id != challenge.id:
        return False, "This flag is not for this challenge!"
    return True, "Correct"


def record(model, user, challenge, request):
    db.session.add(model(user_id=user.id, challenge_id=challenge.id, ip=get_ip(request), provided=submitted_flag(request)))
    db.session.commit()


def fail(user, challenge, request):
    record(Fails, user, challenge, request)


def solve(user, challenge, request):
    record(Solves, user, challenge, request)
    update_awards(user)

    # A challenge row can be shared by several dojos through imports; credit the
    # dojo the solve was actually submitted against when the request names one.
    solved_dojo = getattr(g, "dojo", None)
    dojo_challenge = (
        DojoChallenges.query.filter_by(challenge_id=challenge.id, dojo_id=solved_dojo.dojo_id).first()
        if solved_dojo else None
    ) or DojoChallenges.query.filter_by(challenge_id=challenge.id).first()
    if dojo_challenge:
        dojo = dojo_challenge.module.dojo
        if dojo.official or dojo.data.get("type") == "public":
            module = dojo_challenge.module
            points = challenge.value
            first_blood = Solves.query.filter_by(challenge_id=challenge.id).count() == 1
            publish_challenge_solve(user, dojo_challenge, dojo, module, points, first_blood)


@dojos_namespace.route("/<dojo>/<module>/<challenge_id>/solve")
class DojoChallengeSolve(Resource):
    @authed_only_cli
    @authed_only
    @require_verified_emails
    @dojo_route
    def post(self, dojo, module, challenge_id):
        user = get_current_user()
        data = request.form or request.get_json(silent=True)
        if not isinstance(data, dict) and not hasattr(data, "get"):
            return {"success": False, "error": "Request body must be an object"}, 400
        submission = data.get("submission")
        if not isinstance(submission, str):
            return {"success": False, "error": "Must supply a submission."}, 400

        dojo_challenge = (DojoChallenges.from_id(dojo.reference_id, module.id, challenge_id)
                          .filter(DojoChallenges.visible()).first())
        if not dojo_challenge:
            return {"success": False, "error": "Challenge not found"}, 404
        challenge = dojo_challenge.challenge

        one_minute_ago = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
        kpm = Fails.query.filter(Fails.user_id == user.id, Fails.date >= one_minute_ago).count()

        def log(verdict):
            audit_log("submissions", f"{user.name} submitted {submission!r} on {challenge.id} with kpm {kpm} [{verdict}]")

        if kpm > int(get_config("incorrect_submissions_per_min", default=10)):
            fail(user, challenge, request)
            log("TOO FAST")
            return {"success": False, "status": "ratelimited"}, 429
        if Solves.query.filter_by(user=user, challenge=challenge).first():
            log("ALREADY SOLVED")
            return {"success": True, "status": "already_solved"}
        status, message = attempt(challenge, request)
        (solve if status else fail)(user, challenge, request)
        log("CORRECT" if status else "WRONG")
        if status:
            return {"success": True, "status": "solved"}
        return {"success": False, "status": "incorrect", "message": message}, 400


@dojos_namespace.route("/<dojo>/<module>/<challenge_id>/surveys")
class DojoSurvey(Resource):
    @dojo_route
    def get(self, dojo, module, challenge_id):
        dojo_challenge = (DojoChallenges.from_id(dojo.reference_id, module.id, challenge_id)
                          .filter(DojoChallenges.visible()).first())
        if not dojo_challenge:
            return {"success": False, "error": "Challenge not found"}, 404
        survey = dojo_challenge.survey
        if not survey:
            return {"success": True, "type": "none"}
        response = {
            "success": True,
            "prompt": survey["prompt"],
            "data": survey["data"],
            "probability": survey.get("probability", 1.0),
            "type": "user-specified"
        }
        return response

    @authed_only
    @dojo_route
    @ratelimit(method="POST", limit=10, interval=60)
    def post(self, dojo, module, challenge_id):
        user = get_current_user()
        data = request.get_json(silent=True) if request.is_json else request.form
        if not isinstance(data, dict) and not hasattr(data, "get"):
            return {"success": False, "error": "Request body must be an object"}, 400
        dojo_challenge = (DojoChallenges.from_id(dojo.reference_id, module.id, challenge_id)
                          .filter(DojoChallenges.visible()).first())
        if not dojo_challenge:
            return {"success": False, "error": "Challenge not found"}, 404
        survey = dojo_challenge.survey
        if not survey:
            return {"success": False, "error": "Survey not found"}, 404
        if "response" not in data:
            return {"success": False, "error": "Missing response"}, 400
        survey_response = data["response"]
        if not isinstance(survey_response, (str, int, float, bool)):
            return {"success": False, "error": "Invalid response"}, 400

        response = SurveyResponses(
            user_id=user.id,
            dojo_id=dojo_challenge.dojo_id,
            challenge_id=dojo_challenge.challenge_id,
            prompt=survey["prompt"],
            response=survey_response,
        )
        db.session.add(response)
        db.session.commit()
        return {"success": True}


@dojos_namespace.route("/<dojo>/<module>/<challenge_id>/description")
class DojoChallengeDescription(Resource):
    @authed_only
    @dojo_route
    def get(self, dojo, module, challenge_id):
        user = get_current_user()

        dojo_challenge = DojoChallenges.from_id(dojo.reference_id, module.id, challenge_id).first()

        if dojo_challenge is None or not (dojo_challenge.visible() or dojo.is_admin()):
            return {"success": False, "error": "Invalid challenge id"}, 404

        if is_challenge_locked(dojo_challenge, user):
            return {
                "success": False,
                "error": "This challenge is locked"
            }, 403

        return {
            "success": True,
            "description": render_markdown(dojo_challenge.description)
        }


@dojos_namespace.route("/<dojo>/award/grant")
class GrantAward(Resource):
    @dojo_route
    @dojo_gives_awards
    @dojo_admins_only
    def post(self, dojo):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return {"success": False, "error": "JSON body must be an object"}, 400
        user_id = data.get("user_id")
        emoji = data.get("emoji")
        description = data.get("description")
        if None in [user_id, emoji, description]:
            return {"success": False, "error": "Must supply user_id, emoji, and description."}, 400
        if not isinstance(emoji, str) or not isinstance(description, str):
            return {"success": False, "error": "emoji and description must be strings."}, 400
        if not emojilib.is_emoji(emoji):
            return {"success": False, "error": "emoji must be emoji."}, 400
        user_id = parse_positive_int(user_id)
        if user_id is None:
            return {"success": False, "error": "Invalid user id."}, 400
        user = Users.query.filter_by(id=user_id).first()
        if not user:
            return {"success": False, "error": "User not found."}, 404
        grant_award(user, emoji, description, dojo.hex_dojo_id)
        return {"success": True}
