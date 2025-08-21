from flask_restx import Namespace, Resource
from CTFd.utils.decorators import authed_only
from CTFd.plugins import bypass_csrf_protection
from CTFd.models import db
from sqlalchemy import text

test_error_namespace = Namespace(
    "test_error", description="Test endpoint for error handling"
)

@test_error_namespace.route("")
class TestError(Resource):
    @authed_only
    @bypass_csrf_protection
    def get(self):
        raise Exception("Test error: This is a deliberate test of the error handler!")
    
    @authed_only
    @bypass_csrf_protection
    def post(self):
        raise Exception("Test error: This is a deliberate test of the error handler!")


@test_error_namespace.route("/slow_query")
class TestSlowQuery(Resource):
    @authed_only
    @bypass_csrf_protection
    def get(self):
        result = db.session.execute(text("SELECT 1, pg_sleep(1)")).fetchone()
        return {"status": "ok", "result": result[0]}