from flask_restx import Namespace, Resource
from CTFd.utils.decorators import admins_only

from ...config import bootstrap


bootstrap_namespace = Namespace(
    "bootstrap", description="Endpoint to manage bootstrapping"
)


@bootstrap_namespace.route("")
class Bootstrap(Resource):
    @admins_only
    def get(self):
        bootstrap()
        return {"success": True}
