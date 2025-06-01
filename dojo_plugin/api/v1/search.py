from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import or_
from CTFd.utils.user import get_current_user
import re

from ...models import Dojos, DojoModules, DojoChallenges

search_namespace = Namespace("search", description="Search across dojos, modules, and challenges")

def highlight_snippet(text, query, context=40):
    if not text:
        return None

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None

    start = max(match.start() - context, 0)
    end = min(match.end() + context, len(text))
    snippet = text[start:end]
    highlighted = pattern.sub(lambda m: f"<b style='font-weight:600; color:#f1c40f'>{m.group(0)}</b>", snippet)

    if start > 0:
        highlighted = "…" + highlighted
    if end < len(text):
        highlighted += "…"

    return highlighted

@search_namespace.route("")
class Search(Resource):
    def get(self):
        query = request.args.get("q", "").strip()

        user = get_current_user()

        if not query or len(query) < 2:
            return {"success": False, "error": "Query too short."}, 400

        like_query = f"%{query}%"

        dojos = Dojos.viewable(user=user).filter(
            or_(Dojos.name.ilike(like_query), Dojos.description.ilike(like_query))
        )
        modules = DojoModules.query.join(Dojos.viewable(user=user)).filter(
            or_(DojoModules.name.ilike(like_query), DojoModules.description.ilike(like_query))
        )
        challenges = DojoChallenges.query.join(Dojos.viewable(user=user)).filter(
            or_(DojoChallenges.name.ilike(like_query), DojoChallenges.description.ilike(like_query))
        )

        return {
            "success": True,
            "results": {
                "dojos": [
                    {
                        "id": dojo.reference_id,
                        "name": dojo.name,
                        "link": f"/{dojo.reference_id}",
                        "match": highlight_snippet(dojo.description, query)
                            if query.lower() in (dojo.description or "").lower()
                            and query.lower() not in dojo.name.lower()
                            else None
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
                        "match": highlight_snippet(module.description, query)
                            if query.lower() in (module.description or "").lower()
                            and query.lower() not in module.name.lower()
                            else None
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
                        "match": highlight_snippet(challenge.description, query)
                            if query.lower() in (challenge.description or "").lower()
                            and query.lower() not in challenge.name.lower()
                            else None
                    }
                    for challenge in challenges
                ]
            }
        }
