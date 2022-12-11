import sqlalchemy
import datetime
import hashlib
import pathlib
import logging
import pytz
import yaml
import re

from sqlalchemy import String, DateTime
from sqlalchemy.orm import synonym
from sqlalchemy.sql import or_, and_
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from CTFd.models import db, Challenges, Solves, Flags, Users
from CTFd.utils.user import get_current_user
from ..utils import current_app, CHALLENGES_DIR, DOJOS_DIR, id_regex


class DojoChallenges(db.Model):
    __tablename__ = "dojo_challenges"
    id = db.Column(db.Integer, primary_key=True)
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

    @property
    def short_category(self):
        return self.challenge.category.split(":")[-1]

    @property
    def root_dir(self):
        # don't allow file overrides for imported challenges. Since solves
        # are tracked per challenge, not per dojo_challenge, this can lead
        # to cheesing
        dojo = self.provider_dojo or self.dojo

        chaldir = CHALLENGES_DIR
        if dojo.owner_id:
            dojo_chal_dir = (DOJOS_DIR/str(dojo.owner_id)/dojo.id/self.short_category/self.name)
            global_chal_dir = (chaldir/self.short_category/self.name)
            if not global_chal_dir.exists():
                chaldir = dojo_chal_dir.parent.parent

        return chaldir.resolve()

    @property
    def category_dir(self):
        if (self.root_dir/self.short_category).resolve() != (self.root_dir/self.short_category):
            raise ValueError("path injection? %s %s" %(self.root_dir, self.category))
        return self.root_dir/self.short_category

    @property
    def challenge_dir(self):
        if (self.category_dir/self.name).resolve() != (self.category_dir/self.name):
            raise ValueError("path injection? %s %s %s" %(self.root_dir, self.category, self.name))
        return self.category_dir/self.name

    def challenge_paths(self, *, secret=None, user=None):
        if secret is None:
            secret = current_app.config["SECRET_KEY"]

        category_global = self.category_dir / "_global"
        challenge_global = self.challenge_dir / "_global"

        if category_global.exists():
            yield from category_global.iterdir()

        if challenge_global.exists():
            yield from challenge_global.iterdir()

        options = sorted(
            option
            for option in (self.challenge_dir).iterdir()
            if not (option.name.startswith(".") or option.name.startswith("_"))
        )

        if options:
            user = get_current_user()
            option_hash = hashlib.sha256(f"{secret}_{user.id}_{self.challenge.id}".encode()).digest()
            option = options[int.from_bytes(option_hash[:8], "little") % len(options)]
            yield from option.iterdir()


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

    @property
    def emoji(self):
        return self.config.get("completion_emoji", None)

    @property
    def belt(self):
        return self.config.get("completion_belt", None)

    def module_by_id(self, module_id):
        for module in self.modules:
            if module.get("id") == module_id:
                return module
        return None

    def apply_spec(self, dojo_log=logging.getLogger(__name__), dojo_dir=None):
        # delete all challenge mappings owned by this dojo
        dojo_log.info("Deleting existing challenge mappings (if committing).")
        deleter = sqlalchemy.delete(DojoChallenges).where(DojoChallenges.dojo == self).execution_options(synchronize_session="fetch")
        db.session.execute(deleter)

        # make sure the owner is an admin or has a "GRANT_BELT" award
        if self.belt and self.owner_id:
            owner = Users.query.filter_by(id=self.owner_id).first() # somehow, self.owner is not always set properly??
            if owner.type != "admin" and not any(award.name == "GRANT_BELT" for award in owner.awards):
                dojo_log.error("You are not authorized to award belts for dojo completion. Remove completion_belt or contact the admins.")
                return

        # make sure our emoji is valid
        if self.emoji:
            if len(self.emoji) != 1:
                dojo_log.error("Your completion emoji must be a single unicode character (e.g., '\U0001F408' for a cat emoji).")
                return
            if self.emoji in [ d.emoji for d in Dojos.query.all() if d != self ]:
                dojo_log.error("Your completion emoji (%s) is already reserved by another dojo.", self.emoji)
                return
            if self.emoji in [
                b"\x00\x01\xF6\x80".decode("utf-32-be"), # rocket, for first blood
                b"\x00\x01\xF4\x1B".decode("utf-32-be"), # bug, for bug reports
                b"\x00\x01\xf5\x77".decode("utf-32-be"), # spider, for serious bug reports?
                b"\x00\x01\xf3\x46".decode("utf-32-be"), # eggplant...
                b"\x00\x01\xf3\x51".decode("utf-32-be"), # peach...
                b"\x00\x01\xf9\x24".decode("utf-32-be"), # drool...
            ]:
                dojo_log.error("Please choose another completion emoji.")
                return

        if not self.modules:
            dojo_log.warning("No modules defined in dojo spec!")

        # re-load the dojo challenges
        seen_modules = set()
        for module_idx,module in enumerate(self.modules):
            if "id" not in module:
                dojo_log.warning("Module %d is missing 'id' field; skipping.", module_idx)
                continue

            if not id_regex(module["id"]):
                dojo_log.warning("Module ID (%s) is not a valid URL component. Skipping.", module["id"])
                continue

            if module["id"] in seen_modules:
                dojo_log.warning("Duplicate module with ID %s; skipping.", module["id"])
                continue
            seen_modules.add(module["id"])

            if "name" not in module:
                dojo_log.warning("Module with ID %s is missing 'name' field; skipping.", module["id"])
                continue

            if "challenges" not in module:
                dojo_log.info("Module %s has no challenges defined. Skipping challenge load.", module["id"])
                continue

            self._load_module_challenges(module_idx, module, dojo_dir=dojo_dir, dojo_log=dojo_log)

        dojo_log.info("Done with dojo %s", self.id)

    def _load_module_challenges(self, module_idx, module, dojo_dir=None, dojo_log=logging.getLogger(__name__)):
        dojo_log.info("Loading challenges for module %s.", module["id"])

        for level_idx,challenge_spec in enumerate(module["challenges"], start=1):
            dojo_log.info("Loading module %s challenge %d", module["id"], level_idx)
            description = challenge_spec.get("description", None)

            # spec dependent
            provider_dojo_id = None
            provider_module = None

            if "import" not in challenge_spec:
                if "name" not in challenge_spec:
                    dojo_log.warning("... challenge is missing a name. Skipping.")
                    continue

                # if this is our dojo's challenge, make sure it's in the DB
                name = challenge_spec["name"]
                category = challenge_spec.get("category", f"{self.id}")

                if not id_regex(name):
                    dojo_log.warning("... challenge name (%s) is not a valid URL component. Skipping.", name)
                    continue
                if not id_regex(category):
                    dojo_log.warning("... challenge category (%s) is not a valid URL component. Skipping.", category)
                    continue

                if self.owner_id:
                    dojo_log.info("... checking challenge directory")
                    expected_dir = (dojo_dir or DOJOS_DIR/str(self.owner_id)/self.id)/category/name
                    if not expected_dir.exists():
                        dojo_log.warning("... expected challenge directory %s does not exist; skipping!", expected_dir)
                        continue
                    dojo_log.info("... challenge directory exists. Checking for variants.")
                    variants = [ ed for ed in expected_dir.iterdir() if ed.is_dir() ]
                    if not variants:
                        dojo_log.warning("... the challenge needs at least one variant subdirectory. Skipping!")
                        continue
                    else:
                        dojo_log.info("... %d variants found.", len(variants))

                    category = f"{str(self.owner_id)}:{str(self.id)}:{str(category)}"

                dojo_log.info("... challenge name: %s", name)
                dojo_log.info("... challenge category: %s", category)

                challenge = Challenges.query.filter_by(
                    name=name, category=category
                ).first()
                if not challenge:
                    dojo_log.info("... challenge is new; creating")
                    challenge = Challenges(
                        name=name,
                        category=category,
                        value=1,
                        state="visible",
                    )
                    db.session.add(challenge)

                    flag = Flags(challenge_id=challenge.id, type="dojo")
                    db.session.add(flag)
                elif description is not None and challenge.description != description:
                    dojo_log.info("... challenge already exists; updating description")
                    challenge.description = description
            else:
                if challenge_spec["import"].count("/") != 2:
                    dojo_log.warning("... malformed import statement, should be dojo_id/module_name/challenge_name. Skipping.")
                    continue

                # if we're importing this from another dojo, do that
                provider_dojo_id, provider_module, provider_challenge = challenge_spec["import"].split("/")
                dojo_log.info("... importing from dojo %s, module %s, challenge %s", provider_dojo_id, provider_module, provider_challenge)

                provider_dojo_challenge = (
                    DojoChallenges.query
                    .join(Challenges, Challenges.id == DojoChallenges.challenge_id)
                    .filter(
                        DojoChallenges.dojo_id==provider_dojo_id, DojoChallenges.module==provider_module,
                        Challenges.name==provider_challenge
                    )
                ).first()
                if not provider_dojo_challenge:
                    dojo_log.warning("... can't find provider challenge; skipping")
                    continue

                challenge = provider_dojo_challenge.challenge

            dojo_log.info("... creating dojo-challenge for challenge #%d", level_idx)
            # then create the DojoChallenge link
            dojo_challenge = DojoChallenges(
                challenge_id=challenge.id,
                dojo_id=self.id,
                provider_dojo_id=provider_dojo_id,
                provider_module=provider_module,
                level_idx=level_idx,
                module_idx=module_idx,
                description_override=description,
                assigned_date=module.get("time_assigned", None),
                module=module["id"],
                docker_image_name="pwncollege-challenge",
            )
            db.session.add(dojo_challenge)

        dojo_log.info("Done with module %s", module["id"])

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
        type_check("name", r"[\S ]{1,50}", required=True)

        type_check("modules", list, required=True)
        for module in data.get("modules"):
            container = module
            type_assert(module, dict, "module")
            type_check("name", r"[\S ]{1,50}", required=True)
            type_check("id", r"[\w-]{1,50}", required=True)

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
                type_check("name", r"[\S ]{1,100}", required=True)
                type_check("video", r"[\w-]+", required=True)
                type_check("playlist", r"[\w-]+", required=True)
                type_check("slides", r"[\w-]+", required=True)



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
