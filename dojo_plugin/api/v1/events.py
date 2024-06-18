import datetime
import docker

from flask_restx import Namespace, Resource
from ...models import Dojos, Emojis, Belts, Solves, Challenges, DojoChallenges, Users

events_namespace = Namespace("events", description="Endpoint to view events")

@events_namespace.route("")
class Events(Resource):
    def get(self):
        hour_ago = (datetime.datetime.now() - datetime.timedelta(hours=1)).replace(minute=0, second=0)
        emojis = Emojis.query.where(Emojis.date > hour_ago, Emojis.user_id == Users.id, ~Users.hidden).all()
        belts = Belts.query.where(Belts.date > hour_ago, Belts.user_id == Users.id, ~Users.hidden).all()
        solves = Solves.query.where(
            Solves.date > hour_ago, Solves.user_id == Users.id, ~Users.hidden,
            Challenges.id == Solves.challenge_id, DojoChallenges.challenge_id == Challenges.id
        ).add_columns(
            Challenges.category, Challenges.name, DojoChallenges.name.label("longname"),
            Solves.user_id, Solves.date # what the fuck
        ).all()
        hidden_users = set(u.id for u in Users.query.where(Users.hidden).all())
        user_containers = [
            c for c in docker.from_env().containers.list(filters={"name": "user_"}, ignore_removed=True)
            if datetime.datetime.fromisoformat(c.attrs['Created'].split(".")[0]) > hour_ago and
            not int(c.labels["dojo.user_id"]) in hidden_users
        ]

        dojos_by_hex = { d.hex_dojo_id: d for d in Dojos.query.all() }

        return {
            "emojis": [ {
                "user_id": e.user_id,
                "date": e.date.isoformat(),
                "emoji": e.name,
                "description": e.description,
                "dojo_reference_id": None if not e.category else dojos_by_hex[e.category].reference_id,
            } for e in emojis ],
            "belts": [ {
                "user_id": b.user_id,
                "date": b.date.isoformat(),
                "belt": b.name,
            } for b in belts ],
            "solves": [ {
                "user_id": s.user_id,
                "date": s.date.isoformat(),
                "dojo_reference_id": dojos_by_hex[s.category].reference_id,
                "module": s.name.split(":")[0],
                "challenge_id": s.name.split(":")[1],
                "challenge_name": s.longname,
            } for s in solves ],
            "containers": [ {
                "user_id": int(c.labels["dojo.user_id"]),
                "date": datetime.datetime.fromisoformat(c.attrs['Created'].split(".")[0]).isoformat(), # re-converted consistency
                "dojo_reference_id": c.labels("dojo.dojo_id"),
                "module": c.labels("dojo.module_id"),
                "challenge_id": c.labels("dojo.challenge_id"),
                "mode": c.labels("dojo.mode"),
            } for c in user_containers ]
        }
