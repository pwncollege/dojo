import datetime

from flask import request
from flask_restx import Namespace, Resource

from ...utils.decorators import authed_only
from ...utils.user import get_current_user
from ...models import WorkspaceTokens
from ...utils import generate_workspace_token, iso_utc

workspace_tokens_namespace = Namespace(
    "workspace_tokens", description="Endpoint to manage belts"
)


# https://github.com/CTFd/CTFd/blob/3.6.0/CTFd/api/v1/tokens.py#L47
# CTFd implements other
@workspace_tokens_namespace.route("")
class TokenList(Resource):
    @authed_only
    @workspace_tokens_namespace.doc(description="Endpoint to list workspace tokens")
    def get(self):
        user = get_current_user()
        tokens = WorkspaceTokens.query.filter_by(user_id=user.id)
        return {"success": True,
                "data": [{"id": token.id, "expiration": iso_utc(token.expiration)} for token in tokens]}

    @authed_only
    @workspace_tokens_namespace.doc(description="Endpoint to create a token object")
    def post(self):
        req = request.get_json(silent=True)
        if not isinstance(req, dict):
            return {"success": False, "error": "JSON body must be an object"}, 400
        expiration = req.get("expiration")
        if expiration is not None:
            try:
                expiration = datetime.datetime.strptime(expiration, "%Y-%m-%d")
            except (TypeError, ValueError):
                return {"success": False, "error": "expiration must be a YYYY-MM-DD date"}, 400
        else:
            expiration = None

        user = get_current_user()
        token = generate_workspace_token(user, expiration=expiration)
        return {"success": True,
                "data": {"id": token.id, "expiration": iso_utc(token.expiration), "value": token.value}}
