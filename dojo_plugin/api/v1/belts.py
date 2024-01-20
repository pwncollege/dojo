from flask_restx import Namespace, Resource

from ...utils.awards import get_belts

belts_namespace = Namespace("belts", description="Endpoint to manage belts")


@belts_namespace.route("")
class Belts(Resource):
    def get(self):
        return get_belts()
