import datetime

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.sql import and_
from CTFd.models import db, Solves
from CTFd.cache import cache
from CTFd.plugins.challenges import get_chal_class
from CTFd.utils.decorators import authed_only, admins_only, ratelimit
from CTFd.utils.user import get_current_user, is_admin, get_ip

from ...models import DojoStudents, Dojos, DojoModules, DojoChallenges, DojoUsers, Emojis, SurveyResponses
from ...utils import render_markdown, is_challenge_locked
from ...utils.dojo import dojo_route, dojo_admins_only, dojo_create


dojos_namespace = Namespace(
    "dojos", description="Endpoint to retrieve Dojos"
)


@dojos_namespace.route("")
class DojoList(Resource):
    def get(self):
        dojos = [
            dict(id=dojo.reference_id,
                 name=dojo.name,
                 description=dojo.description,
                 official=dojo.official)
            for dojo in Dojos.viewable(user=get_current_user())
        ]
        return {"success": True, "dojos": dojos}


@dojos_namespace.route("/<dojo>/awards/prune")
class PruneAwards(Resource):
    @dojo_route
    @dojo_admins_only
    def post(self, dojo):
        all_completions = set(user for user,_ in dojo.completions())
        num_pruned = 0
        for award in Emojis.query.where(Emojis.category==dojo.hex_dojo_id):
            if award.user not in all_completions:
                num_pruned += 1
                db.session.delete(award)
        db.session.commit()
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
        data = request.get_json()
        if 'user_id' not in data:
            return {"success": False, "error": "User not specified."}, 400
        new_admin_id = data['user_id']
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
        data = request.get_json()
        user = get_current_user()

        repository = data.get("repository", "")
        spec = data.get("spec", "")
        public_key = data.get("public_key", "")
        private_key = data.get("private_key", "").replace("\r\n", "\n")

        key = f"rl:{get_ip()}:{request.endpoint}"
        timeout = int(datetime.timedelta(days=1).total_seconds())

        if not is_admin() and cache.get(key) is not None:
            return {"success": False, "error": "You can only create 1 dojo per day."}, 429

        try:
            dojo = dojo_create(user, repository, public_key, private_key, spec)
        except RuntimeError as e:
            return {"success": False, "error": str(e)}, 400

        cache.set(key, 1, timeout=timeout)
        return {"success": True, "dojo": dojo.reference_id}


@dojos_namespace.route("/<dojo>/modules")
class DojoModuleList(Resource):
    @dojo_route
    def get(self, dojo):
        modules = [
            dict(id=module.id,
                 name=module.name,
                 description=module.description,
                 challenges=[
                    dict(id=challenge.id,
                         name=challenge.name,
                         description=challenge.description)
                    for challenge in module.visible_challenges()
                 ])
            for module in dojo.modules
        ]
        return {"success": True, "modules": modules}

@dojos_namespace.route("/<dojo>/solves")
class DojoSolveList(Resource):
    @authed_only
    @dojo_route
    def get(self, dojo):
        user = get_current_user()
        solves_query = dojo.solves(user=user, ignore_visibility=True, ignore_admins=False)

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
        result = dict(syllabus=dojo.course.get("syllabus", ""), grade_code=dojo.course.get("grade_code", ""))
        student = DojoStudents.query.filter_by(dojo=dojo, user=get_current_user()).first()
        if student:
            result["student"] = dojo.course.get("students", {}).get(student.token, {}) | dict(token=student.token)
        return {"success": True, "course": result}


@dojos_namespace.route("/<dojo>/course/students")
class DojoCourseStudentList(Resource):
    @dojo_route
    @dojo_admins_only
    def get(self, dojo):
        students = dojo.course.get("students", {})
        return {"success": True, "students": students}


@dojos_namespace.route("/<dojo>/course/solves")
class DojoCourseSolveList(Resource):
    @dojo_route
    @dojo_admins_only
    def get(self, dojo):
        students = dojo.course.get("students", {})

        solves_query = dojo.solves(ignore_visibility=True, ignore_admins=False)

        if after := request.args.get("after"):
            try:
                after_date = datetime.datetime.fromisoformat(after).astimezone(datetime.timezone.utc)
            except ValueError:
                return {"success": False, "error": "Invalid after date format"}, 400
            solves_query = solves_query.filter(Solves.date > after_date)

        if students:
            solves_query = solves_query.filter(DojoStudents.token.in_(students))

        solves_query = solves_query.order_by(Solves.date.asc()).with_entities(Solves.date, DojoStudents.token, DojoModules.id, DojoChallenges.id)
        solves = [
            dict(timestamp=timestamp.astimezone(datetime.timezone.utc).isoformat(),
                 student_token=student_token,
                 module_id=module_id,
                 challenge_id=challenge_id)
            for timestamp, student_token, module_id, challenge_id in solves_query.all()
        ]

        return {"success": True, "solves": solves}


@dojos_namespace.route("/<dojo>/<module>/<challenge_id>/solve")
class DojoChallengeSolve(Resource):
    @authed_only
    @dojo_route
    def post(self, dojo, module, challenge_id):
        user = get_current_user()
        dojo_challenge = (DojoChallenges.from_id(dojo.reference_id, module.id, challenge_id)
                          .filter(DojoChallenges.visible()).first())
        if not dojo_challenge:
            return {"success": False, "error": "Challenge not found"}, 404

        solve = Solves.query.filter_by(user=user, challenge=dojo_challenge.challenge).first()
        if solve:
            return {"success": True, "status": "already_solved"}

        chal_class = get_chal_class(dojo_challenge.challenge.type)
        status, _ = chal_class.attempt(dojo_challenge.challenge, request)
        if status:
            chal_class.solve(user, None, dojo_challenge.challenge, request)
            return {"success": True, "status": "solved"}
        else:
            chal_class.fail(user, None, dojo_challenge.challenge, request)
            return {"success": False, "status": "incorrect"}, 400


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
            "type": survey["type"],
            "prompt": survey["prompt"],
            "probability": survey.get("probability", 1.0),
        }
        if "options" in survey:
            response["options"] = survey["options"]
        return response

    @authed_only
    @dojo_route
    @ratelimit(method="POST", limit=10, interval=60)
    def post(self, dojo, module, challenge_id):
        user = get_current_user()
        data = request.get_json()
        dojo_challenge = (DojoChallenges.from_id(dojo.reference_id, module.id, challenge_id)
                          .filter(DojoChallenges.visible()).first())
        if not dojo_challenge:
            return {"success": False, "error": "Challenge not found"}, 404
        survey = dojo_challenge.survey
        if not survey:
            return {"success": False, "error": "Survey not found"}, 404
        if "response" not in data:
            return {"success": False, "error": "Missing response"}, 400

        if survey["type"] == "thumb":
            if data["response"] not in ["up", "down"]:
                return {"success": False, "error": "Invalid response"}, 400
        elif survey["type"] == "multiplechoice":
            if not isinstance(data["response"], int) or not (0 <= int(data["response"]) < len(survey["options"])):
                return {"success": False, "error": "Invalid response"}, 400
        elif survey["type"] == "freeform":
            if not isinstance(data["response"], str):
                return {"success": False, "error": "Invalid response"}, 400
        else:
            return {"success": False, "error": "Bad survey type"}, 400

        response = SurveyResponses(
            user_id=user.id,
            dojo_id=dojo_challenge.dojo_id,
            challenge_id=dojo_challenge.challenge_id,
            type=survey["type"],
            prompt=survey["prompt"],
            response=data["response"],
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

        dojo_challenge = next((c for c in module.visible_challenges() if c.id == challenge_id), None)

        if dojo_challenge is None:
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