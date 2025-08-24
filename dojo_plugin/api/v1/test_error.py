from flask_restx import Namespace, Resource
from CTFd.utils.decorators import authed_only
from CTFd.plugins import bypass_csrf_protection
from CTFd.models import db, Users
from sqlalchemy import text, select, literal, func
from ...utils.query_timer import query_timeout

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

@test_error_namespace.route("/capped_query")
class TestCappedQuery(Resource):
    @authed_only
    @bypass_csrf_protection
    def get(self):
        result = query_timeout(Users.query.with_entities(literal(1), func.pg_sleep(5).label("sleep")).all, 500, ["TIMEOUT"])
        return {"status": "ok", "result": result[0]}
