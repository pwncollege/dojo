import datetime

from flask import request
from flask_restx import Namespace, Resource
from CTFd.models import db, Solves
from CTFd.cache import cache
from CTFd.plugins.challenges import get_chal_class
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.utils.user import get_current_user, is_admin, get_ip

from ...models import Dojos, DojoModules, DojoChallenges, DojoUsers, Emojis
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
    @authed_only
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
    @authed_only
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
class DojoModulesResource(Resource):
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
                after_date = datetime.datetime.fromisoformat(after)
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


@dojos_namespace.route("/<dojo>/challenges/solve")
class DojoChallengeSolve(Resource):
    @authed_only
    @dojo_route
    def post(self, dojo):
        user = get_current_user()
        data = request.get_json()
        dojo_challenge = (DojoChallenges.from_id(dojo.reference_id, data.get("module_id"), data.get("challenge_id"))
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

@dojos_namespace.route("/<dojo>/surveys/<module>/<challenge>")
class DojoSurvey(Resource):
    @dojo_route
    def get(self, dojo, module, challenge):
        dojo_challenge = (DojoChallenges.from_id(dojo.reference_id, module.id, challenge)
                          .filter(DojoChallenges.visible()).first())
        if not dojo_challenge:
            return {"success": False, "error": "Challenge not found"}, 404
        survey = dojo_challenge.survey
        if not survey:
            return {"success": True, "type": "none"}
        response = {"success": True, "type": survey.type, "probability": survey.probability, "prompt": survey.prompt}
        if not survey.probability:
            response["probability"] = 1.0
        if survey.options:
            response["options"] = survey.options.split(",")
        return response
    
    @authed_only
    @dojo_route
    def post(self, dojo, module, challenge):
        return {} # TODO
