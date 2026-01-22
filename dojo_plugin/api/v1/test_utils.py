from flask import abort, current_app, request
from flask_restx import Namespace, Resource
from CTFd.models import db, Users, Submissions
from CTFd.plugins import bypass_csrf_protection

from ...utils import get_current_container, all_docker_clients
from ...utils.background_stats import get_redis_client
from ...models import Dojos, DojoChallenges


test_utils_namespace = Namespace(
    "test_utils", description="Debug-only helpers for tests"
)


@test_utils_namespace.route("/user_id")
class UserId(Resource):
    def get(self):
        username = request.args.get("username")
        if not username:
            abort(400)
        user = Users.query.filter_by(name=username).first_or_404()
        return {"id": user.id}


@test_utils_namespace.route("/delete_last_submission")
class DeleteLastSubmission(Resource):
    @bypass_csrf_protection
    def post(self):
        data = request.get_json() or {}
        username = data.get("username")
        dojo_reference_id = data.get("dojo")
        if not username:
            abort(400)
        user = Users.query.filter_by(name=username).first_or_404()
        submission_query = Submissions.query.filter_by(user_id=user.id)
        if dojo_reference_id:
            dojo = Dojos.from_id(dojo_reference_id).first_or_404()
            submission_query = submission_query.join(
                DojoChallenges, DojoChallenges.challenge_id == Submissions.challenge_id
            ).filter(DojoChallenges.dojo_id == dojo.dojo_id)
        submission = submission_query.order_by(Submissions.id.desc()).first()
        if submission:
            db.session.delete(submission)
            db.session.commit()
        return {"deleted": submission is not None}


@test_utils_namespace.route("/clear_dojo_award")
class ClearDojoAward(Resource):
    @bypass_csrf_protection
    def post(self):
        data = request.get_json() or {}
        dojo_reference_id = data.get("dojo")
        if not dojo_reference_id:
            abort(400)
        dojo = Dojos.from_id(dojo_reference_id).first_or_404()
        dojo.award = None
        db.session.commit()
        return {"success": True}


@test_utils_namespace.route("/workspace_exec")
class WorkspaceExec(Resource):
    @bypass_csrf_protection
    def post(self):
        data = request.get_json() or {}
        username = data.get("user")
        command = data.get("command")
        root = bool(data.get("root", False))
        if not username or not command:
            abort(400, description="Missing 'user' or 'command' in JSON body")
        user = Users.query.filter_by(name=username).first_or_404()
        container = get_current_container(user)
        if not container:
            abort(409, description=f"No running container for user '{username}'")
        exec_result = container.exec_run(
            cmd=["bash", "-c", command],
            user="0" if root else "1000",
            demux=True,
        )
        stdout, stderr = exec_result.output or ("", "")
        return {
            "returncode": exec_result.exit_code,
            "stdout": stdout.decode() if isinstance(stdout, (bytes, bytearray)) else stdout,
            "stderr": stderr.decode() if isinstance(stderr, (bytes, bytearray)) else stderr,
        }


@test_utils_namespace.route("/docker_images")
class DockerImages(Resource):
    @bypass_csrf_protection
    def post(self):
        data = request.get_json() or {}
        pulls = data.get("pulls")
        tags = data.get("tags")
        if pulls is None or tags is None:
            abort(400)
        errors = []
        for docker_client in all_docker_clients():
            for image in pulls:
                try:
                    docker_client.images.pull(image)
                except Exception as exc:
                    errors.append({"action": "pull", "image": image, "error": str(exc)})
            for tag in tags:
                try:
                    docker_client.images.get(tag["source"]).tag(tag["target"])
                except Exception as exc:
                    errors.append({"action": "tag", "source": tag["source"], "target": tag["target"], "error": str(exc)})
        if errors:
            return {"success": False, "errors": errors}, 500
        return {"success": True}


@test_utils_namespace.route("/redis")
class RedisCommand(Resource):
    @bypass_csrf_protection
    def post(self):
        data = request.get_json() or {}
        command = (data.get("command") or "").strip().lower()
        args = data.get("args") or []
        if not command:
            abort(400, description="Missing redis command")

        r = get_redis_client()
        if command == "get":
            if len(args) != 1:
                abort(400, description="GET requires 1 argument")
            result = r.get(args[0])
        elif command == "exists":
            if len(args) != 1:
                abort(400, description="EXISTS requires 1 argument")
            result = r.exists(args[0])
        elif command == "del":
            if not args:
                abort(400, description="DEL requires at least 1 argument")
            result = r.delete(*args)
        elif command == "keys":
            if len(args) != 1:
                abort(400, description="KEYS requires 1 argument")
            result = r.keys(args[0])
        elif command == "xadd":
            if len(args) < 3:
                abort(400, description="XADD requires stream, id, and field/value pairs")
            stream = args[0]
            message_id = args[1]
            field_args = args[2:]
            if len(field_args) % 2 != 0:
                abort(400, description="XADD field/value pairs are incomplete")
            fields = dict(zip(field_args[0::2], field_args[1::2]))
            result = r.xadd(stream, fields, id=message_id)
        elif command == "xlen":
            if len(args) != 1:
                abort(400, description="XLEN requires 1 argument")
            result = r.xlen(args[0])
        else:
            abort(400, description=f"Unsupported redis command '{command}'")

        return {"result": result}
