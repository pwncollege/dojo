from flask import request
from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import Users

validate_namespace = Namespace(
    "validate", description="Endpoint to validate if user exists"
)

def get_validate_user(username, email):
    user = Users.query.filter_by(name=username, email=email).first()

    if user:
        return 1
    else:
        return 0

@validate_namespace.route("")
class ValidateUser(Resource):
    """
    /validate?username=user&email=user@test.com
    This endpoint is publicly available, no auth needed.
    Returns 1 or 0 depending on if username/email exists or not.
    """
    def get(self):
        username = request.args.get("username")
        email = request.args.get("email")
        if not username or not email:
            return {"error": "`username` and `email` parameters are required"}, 400

        return get_validate_user(username=username, email=email)
