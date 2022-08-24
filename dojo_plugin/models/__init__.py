import re
import datetime

import yaml
from sqlalchemy.sql import or_, and_
from sqlalchemy.ext.hybrid import hybrid_property
from CTFd.models import db, Challenges


class DojoChallenges(Challenges):
    __tablename__ = "dojo_challenges"
    __mapper_args__ = {"polymorphic_identity": "dojo"}
    id = db.Column(db.Integer, db.ForeignKey("challenges.id"), primary_key=True)
    docker_image_name = db.Column(db.String(256))


class Dojos(db.Model):
    __tablename__ = "dojos"
    id = db.Column(db.String(16), primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    join_code = db.Column(db.Text, unique=True)
    _data = db.Column("data", db.Text)

    @hybrid_property
    def public(self):
        return self.owner_id == None

    @property
    def archived(self):
        return self.name.lower().startswith("archive")

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self.validate_data(value)
        self._data = value
        if hasattr(self, "_config"):
            del self._config

    @property
    def config(self):
        if not hasattr(self, "_config"):
            self._config = yaml.safe_load(self.data) or {}
        return self._config

    @property
    def name(self):
        return self.config.get("name", "")

    @property
    def modules(self):
        return self.config.get("modules", [])

    def challenges_query(self, module_id=None):
        return or_(*(
            and_(Challenges.category == module_challenge["category"],
                 Challenges.name.in_(module_challenge["names"]))
            if module_challenge.get("names") else
            Challenges.category == module_challenge["category"]
            for module in self.modules
            if module_id is None or module["id"] == module_id
            for module_challenge in module.get("challenges", [])
        ), False)

    @staticmethod
    def validate_data(data):
        try:
            data = yaml.safe_load(data)
        except yaml.error.YAMLError as e:
            assert False, f"YAML Error:\n{e}"

        if data is None:
            return

        def type_assert(object_, type_, name):
            assert isinstance(object_, type_), f"YAML Type Error: {name} expected type `{type_.__name__}`, got `{type(object_).__name__}`"

        def type_check(name, type_, required=True):
            if required and name not in container:
                assert False, f"YAML Required Error: missing field `{name}`"
            if name not in container:
                return
            value = container.get(name)
            if isinstance(type_, str):
                match = isinstance(value, str) and re.fullmatch(type_, value)
                assert match, f"YAML Type Error: field `{name}` must be of type `{type_}`"
            else:
                type_assert(value, type_, f"field `{name}`")

        container = data
        type_assert(data, dict, "outer")
        type_check("name", "[\S ]{1,50}", required=True)

        type_check("modules", list, required=True)
        for module in data.get("modules"):
            container = module
            type_assert(module, dict, "module")
            type_check("name", "[\S ]{1,50}", required=True)
            type_check("id", "\w{1,50}", required=True)

            type_check("challenges", list, required=False)
            for challenge in module.get("challenges", []):
                container = challenge
                type_assert(challenge, dict, "challenge")
                type_check("category", "\w+", required=True)

                type_check("names", list, required=False)
                for name in challenge.get("names", []):
                    type_assert(name, str, "challenge name")

            container = module
            type_check("deadline", datetime.datetime, required=False)
            type_check("late", float, required=False)

            type_check("lectures", list, required=False)
            for lecture in module.get("lectures", []):
                container = lecture
                type_assert(lecture, dict, "lecture")
                type_check("name", "[\S ]{1,100}", required=True)
                type_check("video", "[\w-]+", required=True)
                type_check("playlist", "[\w-]+", required=True)
                type_check("slides", "[\w-]+", required=True)



class DojoMembers(db.Model):
    __tablename__ = "dojo_members"
    dojo_id = db.Column(
        db.String(16), db.ForeignKey("dojos.id", ondelete="CASCADE"), primary_key=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class SSHKeys(db.Model):
    __tablename__ = "ssh_keys"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    value = db.Column(db.Text, unique=True)


class DiscordUsers(db.Model):
    __tablename__ = "discord_users"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id = db.Column(db.Text, unique=True)


class BeltInfos(db.Model):
    __tablename__ = "belt_infos"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name = db.Column(db.Text)
    emoji = db.Column(db.Text)
    email = db.Column(db.Text)
    website = db.Column(db.Text)
