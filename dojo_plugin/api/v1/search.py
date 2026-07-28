from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.sql import and_, or_
from CTFd.models import db
from CTFd.utils.user import get_current_user, is_admin

from ...models import Dojos, DojoAdmins, DojoModules, DojoChallenges

search_namespace = Namespace("search", description="Search across dojos, modules, and challenges")

@search_namespace.route("")
class Search(Resource):
    def get(self):
        query = request.args.get("q", "").strip()

        user = get_current_user()

        if not query or len(query) < 2:
            return {"success": False, "error": "Query too short."}, 400

        # The query is a literal, so its LIKE metacharacters must not act as wildcards.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_query = f"%{escaped}%"

        def ilike(*columns):
            return or_(*(column.ilike(like_query, escape="\\") for column in columns))

        dojos = Dojos.viewable(user=user).filter(ilike(Dojos.name, Dojos.description))
        modules = (DojoModules.query
                   .join(Dojos.viewable(user=user))
                   .filter(ilike(DojoModules.name, DojoModules.description)))
        challenges = (DojoChallenges.query
                      .join(Dojos.viewable(user=user))
                      .join(DojoModules, and_(DojoModules.dojo_id == DojoChallenges.dojo_id,
                                              DojoModules.module_index == DojoChallenges.module_index))
                      .filter(ilike(DojoChallenges.name, DojoChallenges.description)))

        if not is_admin():
            admin_dojo_ids = (db.session.query(DojoAdmins.dojo_id)
                              .filter(DojoAdmins.user_id == user.id)
                              .subquery()) if user else db.session.query(DojoAdmins.dojo_id).filter(db.false()).subquery()
            module_access = DojoModules.dojo_id.in_(admin_dojo_ids)
            modules = modules.filter(or_(module_access, DojoModules.visible()))
            challenges = challenges.filter(or_(
                module_access,
                and_(
                    DojoChallenges.visible(),
                    DojoModules.visible(),
                    or_(DojoModules.data["show_challenges"].astext == None,
                        DojoModules.data["show_challenges"].astext != "false"),
                ),
            ))

        return {
            "success": True,
            "results": {
                "dojos": [
                    {
                        "id": dojo.reference_id,
                        "name": dojo.name,
                        "link": f"/{dojo.reference_id}",
                        "description": dojo.description,
                    }
                    for dojo in dojos
                ],
                "modules": [
                    {
                        "id": module.id,
                        "name": module.name,
                        "dojo": {
                            "id": module.dojo.reference_id,
                            "name": module.dojo.name,
                            "link": f"/{module.dojo.reference_id}"
                        },
                        "link": f"/{module.dojo.reference_id}/{module.id}",
                        "description": module.description,
                    }
                    for module in modules
                ],
                "challenges": [
                    {
                        "id": challenge.id,
                        "name": challenge.name,
                        "module": {
                            "id": challenge.module.id,
                            "name": challenge.module.name,
                            "link": f"/{challenge.module.dojo.reference_id}/{challenge.module.id}"
                        },
                        "dojo": {
                            "id": challenge.module.dojo.reference_id,
                            "name": challenge.module.dojo.name,
                            "link": f"/{challenge.module.dojo.reference_id}"
                        },
                        "link": f"/{challenge.module.dojo.reference_id}/{challenge.module.id}/{challenge.id}",
                        "description": challenge.description,
                    }
                    for challenge in challenges
                ]
            }
        }
