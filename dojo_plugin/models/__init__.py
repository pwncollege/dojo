import datetime
import pytz
import re

import yaml
from sqlalchemy import String, DateTime
from sqlalchemy.orm import synonym
from sqlalchemy.sql import or_, and_
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from CTFd.models import db, Challenges, Solves


class DojoChallenges(db.Model):
    __tablename__ = "dojo_challenges"
    id = db.Column(db.String(128), primary_key=True)
    dojo_challenge_id = synonym("id")

    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id"))
    description_override = db.Column(db.Text, nullable=True)
    docker_image_name = db.Column(db.String(256))

    dojo_id = db.Column(db.String(16), db.ForeignKey("dojos.id", ondelete="CASCADE"))
    module = db.Column(db.String(256))
    module_idx = db.Column(db.Integer)
    level_idx = db.Column(db.Integer)

    provider_dojo_id = db.Column(db.String(16), db.ForeignKey("dojos.id"), nullable=True)
    provider_module = db.Column(db.String(256), nullable=True)

    assigned_date = db.Column(db.DateTime(), nullable=True)
    due_date = db.Column(db.DateTime(), nullable=True)

    challenge = db.relationship("Challenges", foreign_keys="DojoChallenges.challenge_id", lazy="select")
    dojo = db.relationship("Dojos", foreign_keys="DojoChallenges.dojo_id", lazy="select")
    provider_dojo = db.relationship("Dojos", foreign_keys="DojoChallenges.provider_dojo_id", lazy="select")

    @property
    def description(self):
        return str(self.description_override) or str(self.challenge.description)

    @property
    def name(self):
        return self.challenge.name

    @property
    def category(self):
        return self.challenge.category

class Dojos(db.Model):
    __tablename__ = "dojos"
    id = db.Column(db.String(16), primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    join_code = db.Column(db.Text, unique=True)
    _data = db.Column("data", MEDIUMTEXT)

    owner = db.relationship("Users", foreign_keys="Dojos.owner_id", lazy="select")

    @hybrid_property
    def public(self):
        return self.join_code == None

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
    def description(self):
        return self.config.get("description", "")

    @property
    def modules(self):
        return self.config.get("modules", [])

    @property
    def grades(self):
        return self.config.get("grades", [])

    @property
    def extra_credit(self):
        return self.config.get("extra_credit", [])

    def module_by_id(self, module_id):
        for module in self.modules:
            if module.get("id") == module_id:
                return module
        return None

    def challenges_query(self, module_id=None, include_unassigned=False):
        if self.config.get("dojo_spec", None) == "v2":
            filters = [
                DojoChallenges.dojo_id == self.id,
                DojoChallenges.challenge_id == Challenges.id,
                Challenges.state == "visible"
            ]
            if module_id is not None:
                filters.append(DojoChallenges.module == module_id)
            if not include_unassigned:
                filters.append(or_(
                    DojoChallenges.assigned_date == None,
                    DojoChallenges.assigned_date < datetime.datetime.now(pytz.utc)
                ))
            return and_(*filters)
        else:
            return or_(*(
                and_(
                    Challenges.category == module_challenge["category"],
                    Challenges.name.in_(module_challenge["names"])
                ) if module_challenge.get("names") else (
                    Challenges.category == module_challenge["category"]
                ) for module in self.modules if (
                    (module_id is None or module["id"] == module_id) and
                    (include_unassigned or "time_assigned" not in module or module["time_assigned"] < datetime.datetime.now(pytz.utc))
                ) for module_challenge in module.get("challenges", [])
            ), False)


    def challenges(self, module=None, user=None, admin_view=False, solves_before=None):
        """
        Get all active challenges of a dojo, adding a '.solved' and 'solve_date' with data about
        challenges solved by the provided user.

        @param admin_view: whether to show not-yet-assigned challenges
        @param solves_before: only show solves up to this date
        @param user: show solves by this user if solves are before module assignment date
        """
        columns = [
            DojoChallenges.dojo_challenge_id,
            DojoChallenges.challenge_id, DojoChallenges.description_override, DojoChallenges.level_idx,
            DojoChallenges.provider_dojo_id, DojoChallenges.provider_module,
            DojoChallenges.module, DojoChallenges.module_idx,
            Challenges.name, Challenges.category, Challenges.description,
            db.func.count(Solves.id).label("solves") # number of solves
        ]
        if user is not None:
            columns.append(db.func.max(Solves.user_id == user.id).label("solved")) # did the user solve the chal?
            columns.append(db.func.substr(
                db.func.max((Solves.user_id == user.id).cast(String)+Solves.date.cast(String)),
                2, 1000
            ).cast(DateTime).label("solve_date")) # _when_ did the user solve the chal?
        else:
            columns.append(db.literal(False).label("solved"))
            columns.append(db.literal(None).label("solve_date"))

        solve_filters = [
            or_(
                DojoChallenges.assigned_date == None,
                False if user is None else Solves.user_id == user.id,
                Solves.date >= DojoChallenges.assigned_date
            )
        ]
        if solves_before:
            solve_filters.append(Solves.date < solves_before)

        # fuck sqlalchemy for making me write this insanity
        challenges = (
            Challenges.query
            .join(DojoChallenges, Challenges.id == DojoChallenges.challenge_id)
            .outerjoin(Solves, and_(Challenges.id == Solves.challenge_id, *solve_filters))
            .filter(self.challenges_query(module_id=module["id"] if module else None, include_unassigned=admin_view))
            .add_columns(*columns)
            .group_by(Challenges.id)
            .order_by(DojoChallenges.module_idx, DojoChallenges.level_idx)
        ).all()

        return challenges


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
            type_check("id", "[\w-]{1,50}", required=True)

            type_check("challenges", list, required=False)
            for challenge in module.get("challenges", []):
                container = challenge
                type_assert(challenge, dict, "challenge")
                #type_check("category", "\w+", required=True)

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
