from flask_restx import Namespace, Resource
from CTFd.utils.user import get_current_user

from ...models import Dojos


dojos_namespace = Namespace(
    "dojos", description="Endpoint to manage dojos in aggregate"
)

@dojos_namespace.route("")
class GetDojos(Resource):
    def get(self):
        dojos = [
            dict(id=dojo.id,
                 name=dojo.name,
                 description=dojo.description,
                 official=dojo.official)
            for dojo in Dojos.viewable(user=get_current_user())
        ]
        return {"success": True, "dojos": dojos}
