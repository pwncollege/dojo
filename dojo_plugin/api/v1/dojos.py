
import datetime

from CTFd.cache import cache
from CTFd.models import Solves, Users, db
from CTFd.plugins.challenges import get_chal_class
from CTFd.utils.decorators import admins_only, authed_only, ratelimit
from CTFd.utils.user import get_current_user, get_ip, is_admin
from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.sql import and_

from ...models import (DojoChallenges, DojoModules, Dojos, DojoStudents,
                       DojoUsers, Emojis, SurveyResponses)
from ...utils import is_challenge_locked, render_markdown
from ...utils.dojo import dojo_admins_only, dojo_create, dojo_route, dojo_gives_awards
from ...utils.stats import get_dojo_stats
from ...utils.awards import grant_event_medal

dojos_namespace = Namespace(
    "dojos", description="Endpoint to retrieve Dojos"
)


@dojos_namespace.route("")
class DojoList(Resource):
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
                 name=dojo.name,
                 description=dojo.description,
                 official=dojo.official,
                 award=dojo.award,
                 modules_count=dojo.modules_count,
                 challenges_count=dojo.required_challenges_count)
            for dojo in dojo_query
        ]
        return {"success": True, "dojos": dojos}

@dojos_namespace.route("/<dojo>/event/grant")
class GrantEventAward(Resource):
    """
    Supported methods:

    ### `POST: [user_id, event_name, place, expiration]`

    Grants an award to the specified user.
    The award consists of the issuing event,
    and the place the user achieved in the event.

    Arguments should be passed in as part of the request's JSON data.

    Only some dojos support this operation,
    and the issuing user must be an administrator of the dojo.
    """
    @dojo_route
    @dojo_admins_only
    @dojo_gives_awards
    def post(self, dojo):
        data = request.get_json()
        user = data.get("user_id")
        event = data.get("event_name")
        place = data.get("place")
        expiration = data.get("expiration")

        # Validate input
        if None in [user, event, place, expiration]:
            return ({"success": False, "error": "failed to supply user_id, event_name, or place"}, 400)
        try:
            user = int(user)
            place = int(place)
        except:
            return ({"success": False, "error": "user_id and place must be integers"})
        try:
            expiration = datetime.datetime.fromisoformat(expiration)
        except:
            return ({"success": False, "error": "expiration must be a valid datetime"})
        if expiration < datetime.datetime.now():
            return ({"success": False, "error": "expiration must be sometime in the future"})
        
        user = Users.query.filter_by(id=user, hidden=False).first()
        if not user:
            return ({"success": False, "error": "user not found"}, 400)

        result = grant_event_medal(user, event, place, expiration)
        return ({"success": result}, 200)

@dojos_namespace.route("/<dojo>/awards/prune")
class PruneAwards(Resource):
    @dojo_route
    @dojo_admins_only
    def post(self, dojo):
        all_completions = set(user for user,_ in dojo.completions())
        num_pruned = 0
        for award in Emojis.query.where(Emojis.category==dojo.hex_dojo_id, Emojis.name != "STALE"):
            if award.user not in all_completions:
                num_pruned += 1
                award.name = "STALE"
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
                     ) for item in module.unified_items
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
        dojo_students = {student.token: student.user_id for student in DojoStudents.query.filter_by(dojo=dojo)}
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

        solves_query = solves_query.order_by(Solves.date.asc()).with_entities(Solves.date, DojoStudents.token, DojoStudents.user_id, DojoModules.id, DojoChallenges.id)
        solves = [
            dict(timestamp=timestamp.astimezone(datetime.timezone.utc).isoformat(),
                 student_token=student_token,
                 user_id=user_id,
                 module_id=module_id,
                 challenge_id=challenge_id)
            for timestamp, student_token, user_id, module_id, challenge_id in solves_query.all()
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

        response = SurveyResponses(
            user_id=user.id,
            dojo_id=dojo_challenge.dojo_id,
            challenge_id=dojo_challenge.challenge_id,
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
