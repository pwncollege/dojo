from flask import abort, current_app, request
from flask_restx import Namespace, Resource
from CTFd.models import db, Users, Submissions
from CTFd.plugins import bypass_csrf_protection

from ...utils import get_current_container, all_docker_clients
from ...models import Dojos


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
        if not username:
            abort(400)
        user = Users.query.filter_by(name=username).first_or_404()
        submission = (
            Submissions.query.filter_by(user_id=user.id)
            .order_by(Submissions.id.desc())
            .first()
        )
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
