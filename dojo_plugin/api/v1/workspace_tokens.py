from flask import request
from flask_restx import Namespace, Resource
from CTFd.models import ma
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

from ...models import WorkspaceTokens
from ...utils import generate_workspace_token

workspace_tokens_namespace = Namespace(
    "workspace_tokens", description="Endpoint to manage belts"
)


# https://github.com/CTFd/CTFd/blob/3.6.0/CTFd/schemas/tokens.py#L5
class WorkspaceTokenSchema(ma.ModelSchema):
    class Meta:
        model = WorkspaceTokens
        include_fk = True


# https://github.com/CTFd/CTFd/blob/3.6.0/CTFd/api/v1/tokens.py#L47
# CTFd implements other
@workspace_tokens_namespace.route("")
class TokenList(Resource):
    @authed_only
    @workspace_tokens_namespace.doc(description="Endpoint to list workspace tokens")
    def get(self):
        user = get_current_user()
        tokens = WorkspaceTokens.query.filter_by(user_id=user.id)
        schema = WorkspaceTokenSchema(only=["id", "expiration"], many=True)
        response = schema.dump(tokens)
        if response.errors:
            return {"success": False, "errors": response.errors}, 400
        return {"success": True, "data": response.data}

    @authed_only
    @workspace_tokens_namespace.doc(description="Endpoint to create a token object")
    def post(self):
        req = request.get_json()
        expiration = req.get("expiration")
        if expiration:
            expiration = datetime.datetime.strptime(expiration, "%Y-%m-%d")
        else:
            expiration = None

        user = get_current_user()
        token = generate_workspace_token(user, expiration=expiration)
        schema = WorkspaceTokenSchema(only=["id", "expiration", "value"])
        response = schema.dump(token)

        if response.errors:
            return {"success": False, "errors": response.errors}, 400
        return {"success": True, "data": response.data}
