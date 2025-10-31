import base64
import contextlib
import functools
import os
import string
import datetime
import hashlib
import pathlib
import logging
import re
import zlib

import pytz
import yaml
from flask import current_app
from sqlalchemy import String, DateTime, case, cast, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import synonym
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.session import object_session
from sqlalchemy.sql import or_, and_
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from sqlalchemy.ext.associationproxy import association_proxy
from CTFd.models import db, get_class_by_tablename, Challenges, Solves, Flags, Users, Admins, Awards
from CTFd.utils.user import get_current_user, is_admin

from ..config import DOJOS_DIR


def delete_before_insert(column, null=[]):
    # https://github.com/sqlalchemy/sqlalchemy/issues/2501
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, value):
            setattr(self, column, null)
            db.session.flush()
            return func(self, value)
        return wrapper
    return decorator


deferred_definitions = []
def deferred_definition(func):
    deferred_definitions.append(
        lambda: setattr(func.__globals__[func.__qualname__.split(".")[0]],
                        func.__name__,
                        func()))


def columns_repr(column_names):
    def __repr__(self):
        description = " ".join(f"{name}={getattr(self, name)!r}" for name in column_names)
        return f"<{self.__class__.__name__} {description}>"
    return __repr__


class Dojos(db.Model):
    __tablename__ = "dojos"

    dojo_id = db.Column(db.Integer, primary_key=True)

    repository = db.Column(db.String(256), unique=True, index=True)
    public_key = db.Column(db.String(128), unique=True)
    private_key = db.Column(db.String(512), unique=True)
    update_code = db.Column(db.String(32), unique=True, index=True)

    id = db.Column(db.String(32), index=True, nullable=False)
    name = db.Column(db.String(128))
    description = db.Column(db.Text)

    official = db.Column(db.Boolean, index=True)
    password = db.Column(db.String(128))

    data = db.Column(JSONB)
    data_fields = ["type", "award", "course", "permissions", "pages", "privileged", "importable", "comparator", "show_scoreboard", "custom_js"]
    data_defaults = {
        "permissions": [],
        "pages": [],
        "privileged": False,
        "importable": True,
        "show_scoreboard": True,
        "custom_js": None,
    }

    users = db.relationship("DojoUsers", back_populates="dojo")
    members = db.relationship("DojoMembers", back_populates="dojo", overlaps="users")
    admins = db.relationship("DojoAdmins", back_populates="dojo", overlaps="users")
    students = db.relationship("DojoStudents", back_populates="dojo", overlaps="users")
    _modules = db.relationship("DojoModules",
                               order_by=lambda: DojoModules.module_index,
                               cascade="all, delete-orphan",
                               back_populates="dojo")
    challenges = db.relationship("DojoChallenges",
                                 order_by=lambda: (DojoChallenges.module_index, DojoChallenges.challenge_index),
                                 back_populates="dojo",
                                 viewonly=True)
    resources = db.relationship("DojoResources",
                                 order_by=lambda: (DojoResources.module_index, DojoResources.resource_index),
                                 back_populates="dojo",
                                 viewonly=True)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("dojo_id", int.from_bytes(os.urandom(4), "little", signed=True))
        kwargs.setdefault("update_code", os.urandom(16).hex())
        kwargs.setdefault("official", False)

        data = kwargs.pop("data", {})
        for field in self.data_fields:
            if field in kwargs:
                data[field] = kwargs.pop(field)
        kwargs["data"] = data

        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name in self.data_fields:
            return (self.data or {}).get(name, self.data_defaults.get(name))
        raise AttributeError(f"No attribute '{name}'")

    def __setattr__(self, name, value):
        if name in self.data_fields:
            self.data[name] = value
            flag_modified(self, "data")
        super().__setattr__(name, value)

    @classmethod
    def from_id(cls, reference_id):
        constraints = []
        if "~" not in reference_id:
            id = reference_id
            constraints.append(cls.official)
        else:
            id, dojo_id = reference_id.split("~", 1)
            dojo_id = cls.hex_to_int(dojo_id)
            constraints.append(cls.dojo_id == dojo_id)
        constraints.append(cls.id == id)
        return cls.query.filter(*constraints)

    @staticmethod
    def int_to_hex(i):
        return f"{i & 0xFFFFFFFF:08x}"

    @staticmethod
    def hex_to_int(hex):
        return int.from_bytes(bytes.fromhex(hex.rjust(8, "0")), "big", signed=True)

    @property
    def hex_dojo_id(self):
        return self.int_to_hex(self.dojo_id)

    @property
    def unique_id(self):
        return self.id + "-" + self.hex_dojo_id

    @property
    def reference_id(self):
        return self.id if self.official else self.unique_id

    @hybrid_property
    def modules(self):
        return self._modules

    @modules.setter
    @delete_before_insert("_modules")
    def modules(self, value):
        for module_index, module in enumerate(value):
            module.module_index = module_index
            for challenge in module.challenges:
                challenge.module_index = module_index
        self._modules = value

    @deferred_definition
    def modules_count():
        return db.column_property(
            db.select([db.func.count()])
            .where(Dojos.dojo_id == DojoModules.dojo_id)
            .scalar_subquery(),
            deferred=True)

    @deferred_definition
    def challenges_count():
        return db.column_property(
            db.select([db.func.count()])
            .where(Dojos.dojo_id == DojoChallenges.dojo_id)
            .scalar_subquery(),
            deferred=True)

    @deferred_definition
    def required_challenges_count():
        return db.column_property(
            db.select([db.func.count()])
            .where(Dojos.dojo_id == DojoChallenges.dojo_id)
            .where(DojoChallenges.required)
            .scalar_subquery(),
            deferred=True)

    @property
    def solves_code(self):
        return hashlib.md5(self.private_key.encode() + b"SOLVES").hexdigest()

    @property
    def path(self):
        if hasattr(self, "_path"):
            return self._path
        return DOJOS_DIR / self.hex_dojo_id

    @contextlib.contextmanager
    def located_at(self, path):
        self._path = pathlib.Path(str(path))
        try:
            yield self
        finally:
            del self._path

    @property
    def hash(self):
        from ..utils.dojo import dojo_git_command
        if os.path.exists(self.path):
            return dojo_git_command(self, "rev-parse", "HEAD").stdout.decode().strip()
        else:
            return ""

    @property
    def last_commit_time(self):
        from ..utils.dojo import dojo_git_command
        return datetime.datetime.fromisoformat(dojo_git_command(self, "show", "--no-patch", "--format=%ci", "HEAD").stdout.decode().strip().replace(" -", "-")[:-2]+":00")

    @classmethod
    def ordering(cls):
        return (
            ~cls.official,
            cls.data["type"],
            db.func.coalesce(cast(cls.data["comparator"].astext, Numeric()), 1000),
            cls.name,
        )

    @classmethod
    def viewable(cls, id=None, user=None):
        return (
            (cls.from_id(id) if id is not None else cls.query)
            .filter(or_(cls.official,
                        and_(cls.data["type"].astext == "public", cls.password == None),
                        cls.dojo_id.in_(db.session.query(DojoUsers.dojo_id)
                                        .filter_by(user=user)
                                        .subquery())))
            .order_by(*cls.ordering())
        )

    def solves(self, **kwargs):
        return DojoChallenges.solves(dojo=self, **kwargs)

    def completions(self):
        solves_subquery = (
            self.solves(ignore_visibility=True, ignore_admins=False)
            .with_entities(Solves.user_id,
                           db.func.count().label("solve_count"),
                           db.func.max(Solves.date).label("last_solve"))
            .group_by(Solves.user_id)
            .having(db.func.count() == len([challenge for challenge in self.challenges if challenge.required]))
            .subquery()
        )
        return (
            Users.query
            .join(solves_subquery, Users.id == solves_subquery.c.user_id)
            .add_columns(solves_subquery.c.last_solve)
            .order_by(solves_subquery.c.last_solve)
            .all()
        )

    def awards(self):
        if not self.award:
            return None
        result = Awards.query.join(Users).filter(~Users.hidden)
        if "belt" in self.award:
            result = result.where(Awards.type == "belt", Awards.name == self.award["belt"])
        elif "emoji" in self.award:
            result = result.where(Awards.type == "emoji", Awards.name != "STALE", Awards.category == self.hex_dojo_id)

        awards = result.order_by(Awards.date.desc()).all()

        return awards

    def completed(self, user):
        return self.solves(user=user, ignore_visibility=True, ignore_admins=False).count() == len([challenge for challenge in self.challenges if challenge.required])

    def is_admin(self, user=None):
        if user is None:
            user = get_current_user()
        dojo_admin = DojoAdmins.query.filter_by(dojo=self, user=user).first()
        return dojo_admin is not None or is_admin()

    @property
    def is_public_or_official(self):
        return self.official or self.type == "public"

    def is_member(self, user_id):
        if self.is_public_or_official:
            return True
        return DojoUsers.query.filter_by(dojo_id=self.dojo_id, user_id=user_id).first() is not None

    __repr__ = columns_repr(["name", "reference_id"])


class DojoUsers(db.Model):
    __tablename__ = "dojo_users"
    __mapper_args__ = {"polymorphic_on": "type"}

    dojo_id = db.Column(db.Integer, db.ForeignKey("dojos.dojo_id", ondelete="CASCADE"), primary_key=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)

    type = db.Column(db.String(80), index=True)

    dojo = db.relationship("Dojos", back_populates="users", overlaps="admins,members,students")
    user = db.relationship("Users")

    def survey_responses(self):
        return DojoChallenges.survey_responses(user=self.user)

    def solves(self, **kwargs):
        return DojoChallenges.solves(user=self.user, dojo=self.dojo, **kwargs)

    __repr__ = columns_repr(["dojo", "user"])


class DojoMembers(DojoUsers):
    __mapper_args__ = {"polymorphic_identity": "member", "polymorphic_on": "type"}

    dojo = db.relationship("Dojos", back_populates="members", overlaps="users")


class DojoAdmins(DojoUsers):
    __mapper_args__ = {"polymorphic_identity": "admin"}

    dojo = db.relationship("Dojos", back_populates="admins", overlaps="users")


class DojoStudents(DojoUsers):
    __mapper_args__ = {"polymorphic_identity": "student"}

    token = db.Column(db.String(256))

    dojo = db.relationship("Dojos", back_populates="students", overlaps="users")

    @property
    def official(self):
        return self.token in (self.dojo.course or {}).get("students", [])


class DojoModules(db.Model):
    __tablename__ = "dojo_modules"
    __table_args__ = (
        db.UniqueConstraint("dojo_id", "id"),
    )

    dojo_id = db.Column(db.Integer, db.ForeignKey("dojos.dojo_id", ondelete="CASCADE"), primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)

    id = db.Column(db.String(32), index=True, nullable=False)
    name = db.Column(db.String(128))
    description = db.Column(db.Text)

    data = db.Column(JSONB)
    data_fields = ["importable", "show_scoreboard", "show_challenges"]
    data_defaults = {
        "importable": True,
        "show_scoreboard": True,
        "show_challenges": True,
    }

    dojo = db.relationship("Dojos", back_populates="_modules")
    _challenges = db.relationship("DojoChallenges",
                                  order_by=lambda: DojoChallenges.challenge_index,
                                  cascade="all, delete-orphan",
                                  back_populates="module")
    _resources = db.relationship("DojoResources",
                                 cascade="all, delete-orphan",
                                 back_populates="module")

    visibility = db.relationship("DojoModuleVisibilities",
                                 uselist=False,
                                 cascade="all, delete-orphan",
                                 back_populates="module")


    def __init__(self, *args, **kwargs):
        default = kwargs.pop("default", None)
        visibility = kwargs["visibility"] if "visibility" in kwargs else None

        data = kwargs.pop("data", {})
        for field in self.data_fields:
            if field in kwargs:
                data[field] = kwargs.pop(field)
        kwargs["data"] = data

        if default:
            for field in ["id", "name", "description"]:
                kwargs[field] = kwargs[field] if kwargs.get(field) is not None else getattr(default, field, None)

        def set_module_import(challenge):
            challenge.data["module_import"] = True
            return challenge

        kwargs["challenges"] = (
            kwargs.pop("challenges", None) or
            ([DojoChallenges(
                default=set_module_import(challenge),
                visibility=(DojoChallengeVisibilities(start=visibility.start) if visibility else None),
            ) for challenge in default.challenges] if default else [])
        )
        kwargs["resources"] = (
            kwargs.pop("resources", None) or
            ([DojoResources(
                default=resource,
                visibility=(DojoResourceVisibilities(start=visibility.start) if visibility else None),
            ) for resource in default.resources] if default else [])
        )

        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name in self.data_fields:
            return (self.data or {}).get(name, self.data_defaults.get(name))
        raise AttributeError(f"No attribute '{name}'")

    @classmethod
    def from_id(cls, dojo_reference_id, id):
        return cls.query.filter_by(id=id).join(Dojos.from_id(dojo_reference_id).subquery())

    @hybrid_property
    def challenges(self):
        return self._challenges

    @challenges.setter
    @delete_before_insert("_challenges")
    def challenges(self, value):
        for challenge_index, challenge in enumerate(value):
            challenge.challenge_index = challenge_index
        self._challenges = value

    @hybrid_property
    def resources(self):
        return self._resources

    @resources.setter
    @delete_before_insert("_resources")
    def resources(self, value):
        for resource_index, resource in enumerate(value):
            if not hasattr(resource, 'resource_index') or resource.resource_index is None:
                resource.resource_index = resource_index
        self._resources = value

    @property
    def path(self):
        return self.dojo.path / self.id

    @property
    def assessments(self):
        return [assessment for assessment in (self.dojo.course or {}).get("assessments", []) if assessment.get("id") == self.id]

    @property
    def unified_items(self):
        items = []

        for resource in self.resources:
            items.append((resource.resource_index, resource))

        for challenge in self.challenges:
            if challenge.unified_index is not None:
                index = challenge.unified_index
            else:
                index = 1000 + challenge.challenge_index
            items.append((index, challenge))

        items.sort(key=lambda x: x[0])
        return [item for _, item in items]

    def visible_challenges(self, when=None, required_only=False):
        when = when or datetime.datetime.utcnow()
        return list(
            DojoChallenges.query
            .filter(DojoChallenges.dojo_id == self.dojo_id,
                    DojoChallenges.module_index == self.module_index)
            .outerjoin(DojoChallengeVisibilities, and_(
                DojoChallengeVisibilities.dojo_id == DojoChallenges.dojo_id,
                DojoChallengeVisibilities.module_index == DojoChallenges.module_index,
                DojoChallengeVisibilities.challenge_index == DojoChallenges.challenge_index
                ))
            .filter(
                or_(DojoChallengeVisibilities.start == None, when >= DojoChallengeVisibilities.start),
                or_(DojoChallengeVisibilities.stop == None, when <= DojoChallengeVisibilities.stop),
            )
            .filter(
                not required_only or DojoChallenges.required
            )
            .order_by(DojoChallenges.challenge_index)
        )

    def solves(self, **kwargs):
        return DojoChallenges.solves(module=self, **kwargs)

    @hybrid_method
    def visible(self, when=None):
        when = when or datetime.datetime.utcnow()
        return not self.visibility or all((
            not self.visibility.start or when >= self.visibility.start,
            not self.visibility.stop or when <= self.visibility.stop,
        ))

    @visible.expression
    def visible(cls, when=None):
        when = when or datetime.datetime.utcnow()
        return or_(cls.visibility == None, and_(
            cls.visibility.has(or_(DojoChallengeVisibilities.start == None, when >= DojoChallengeVisibilities.start)),
            cls.visibility.has(or_(DojoChallengeVisibilities.stop == None, when <= DojoChallengeVisibilities.stop)),
        ))

    __repr__ = columns_repr(["dojo", "id"])


class DojoChallenges(db.Model):
    __tablename__ = "dojo_challenges"
    item_type = "challenge"
    __table_args__ = (
        db.ForeignKeyConstraint(["dojo_id"], ["dojos.dojo_id"], ondelete="CASCADE"),
        db.ForeignKeyConstraint(["dojo_id", "module_index"],
                                ["dojo_modules.dojo_id", "dojo_modules.module_index"],
                                ondelete="CASCADE"),
        db.UniqueConstraint("dojo_id", "module_index", "id"),
    )

    dojo_id = db.Column(db.Integer, db.ForeignKey("dojos.dojo_id", ondelete="CASCADE"), primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)
    challenge_index = db.Column(db.Integer, primary_key=True)

    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), index=True)
    id = db.Column(db.String(32), index=True, nullable=False)
    name = db.Column(db.String(128))
    description = db.Column(db.Text)
    required = db.Column(db.Boolean, default=True, nullable=False)

    data = db.Column(JSONB)
    data_fields = ["image", "privileged", "path_override", "importable", "allow_privileged", "progression_locked", "survey", "unified_index", "interfaces"]
    data_defaults = {
        "privileged": False,
        "importable": True,
        "allow_privileged": True,
        "progression_locked": False,
        "interfaces": [
            dict(name="Terminal", port=7681),
            dict(name="Code",     port=8080),
            dict(name="Desktop",  port=6080),
            dict(name="SSH"),
        ],
    }

    dojo = db.relationship("Dojos",
                           foreign_keys=[dojo_id],
                           back_populates="challenges",
                           viewonly=True)
    module = db.relationship("DojoModules", back_populates="_challenges")
    challenge = db.relationship("Challenges")
    visibility = db.relationship("DojoChallengeVisibilities",
                                 uselist=False,
                                 cascade="all, delete-orphan",
                                 back_populates="challenge")

    def __init__(self, *args, **kwargs):
        default = kwargs.pop("default", None)

        data = kwargs.pop("data", {})
        for field in self.data_fields:
            if field in kwargs:
                data[field] = kwargs.pop(field)
        kwargs["data"] = data

        if default:
            if kwargs.get("challenge") is not None:
                raise AttributeError("Import requires challenge to be None")

            for field in ["id", "name", "description", "challenge"]:
                kwargs[field] = kwargs[field] if kwargs.get(field) is not None else getattr(default, field, None)

            # TODO: maybe we should track the entire import
            kwargs["data"]["image"] = default.data.get("image")
            kwargs["data"]["path_override"] = str(default.path)
            # only update the unified_index for module and dojo imports, not challenge specific ones
            if default.data.get("module_import", False):
                kwargs["data"]["unified_index"] = default.data.get("unified_index")

        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name in self.data_fields:
            return (self.data or {}).get(name, self.data_defaults.get(name))
        raise AttributeError(f"No attribute '{name}'")

    @classmethod
    def from_id(cls, dojo_reference_id, module_id, id):
        return cls.query.filter_by(id=id).join(DojoModules.from_id(dojo_reference_id, module_id).subquery())

    @hybrid_method
    def visible(self, when=None):
        when = when or datetime.datetime.utcnow()
        return not self.visibility or all((
            not self.visibility.start or when >= self.visibility.start,
            not self.visibility.stop or when <= self.visibility.stop,
        ))

    @visible.expression
    def visible(cls, when=None):
        when = when or datetime.datetime.utcnow()
        return or_(cls.visibility == None, and_(
            cls.visibility.has(or_(DojoChallengeVisibilities.start == None, when >= DojoChallengeVisibilities.start)),
            cls.visibility.has(or_(DojoChallengeVisibilities.stop == None, when <= DojoChallengeVisibilities.stop)),
        ))

    # note: currently unused, may need future testing
    @hybrid_method
    def survey_responses(self, user=None):
        result = SurveyResponses.query.filter(
            SurveyResponses.dojo_id == self.dojo_id,
            SurveyResponses.challenge_id == self.challenge_id
            )

        if user is not None:
            result = result.filter(SurveyResponses.user_id == user.id)

        return result

    @hybrid_method
    def solves(self, *, user=None, dojo=None, module=None, ignore_visibility=False, ignore_admins=True, required_only=True):
        result = (
            Solves.query
            .filter_by(type=Solves.__mapper__.polymorphic_identity)
            .join(DojoChallenges, and_(
                DojoChallenges.challenge_id==Solves.challenge_id,
                ))
            .join(DojoModules, and_(
                DojoModules.dojo_id == DojoChallenges.dojo_id,
                DojoModules.module_index == DojoChallenges.module_index))
            .outerjoin(DojoUsers, and_(
                DojoUsers.user_id == Solves.user_id,
                DojoUsers.dojo_id == DojoChallenges.dojo_id,
                ))
            .join(Dojos, and_(
                Dojos.dojo_id == DojoChallenges.dojo_id,
                or_(Dojos.official, Dojos.data["type"].astext == "public", DojoUsers.user_id != None),
                ))
            .join(Users, Users.id == Solves.user_id)
        )

        if not ignore_visibility:
            result = (
                result.outerjoin(DojoChallengeVisibilities, and_(
                    DojoChallengeVisibilities.dojo_id == DojoChallenges.dojo_id,
                    DojoChallengeVisibilities.module_index == DojoChallenges.module_index,
                    DojoChallengeVisibilities.challenge_index == DojoChallenges.challenge_index
                    ))
                .filter(
                    or_(DojoChallengeVisibilities.start == None, Solves.date >= DojoChallengeVisibilities.start),
                    or_(DojoChallengeVisibilities.stop == None, Solves.date <= DojoChallengeVisibilities.stop),
                )
                .filter(~Users.hidden)
            )

        if ignore_admins:
            result = result.filter(or_(DojoUsers.type == None, DojoUsers.type != "admin"))

        if user:
            result = result.filter(Solves.user == user)
        if dojo:
            result = result.filter(DojoChallenges.dojo == dojo)
        if module:
            result = result.filter(DojoChallenges.module == module)

        if required_only:
            result = result.filter(DojoChallenges.required)

        return result

    @property
    def path(self):
        return (self.module.path / self.id
                if not self.path_override or (self.module.dojo.official and os.path.exists(self.module.path / self.id)) else
                pathlib.Path(self.path_override))

    @property
    def image(self):
        return self.data.get("image") or "pwncollege/challenge-legacy"

    @property
    def reference_id(self):
        return f"{self.dojo.reference_id}/{self.module.id}/{self.id}"

    def resolve(self):
        # TODO: We should probably refactor to correctly store a reference to the DojoChallenge
        if not self.path_override:
            return self
        return (DojoChallenges.query
                .filter(DojoChallenges.challenge_id == self.challenge_id,
                        DojoChallenges.data["path_override"] == None)
                .first())

    __repr__ = columns_repr(["module", "id", "challenge_id"])


class SurveyResponses(db.Model):
    __tablename__ = "survey_responses"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dojo_id = db.Column(db.Integer, nullable=False)
    challenge_id = db.Column(db.Integer, index=True, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)

    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)



class DojoResources(db.Model):
    __tablename__ = "dojo_resources"
    item_type = "resource"

    __table_args__ = (
        db.ForeignKeyConstraint(["dojo_id", "module_index"],
                                ["dojo_modules.dojo_id", "dojo_modules.module_index"],
                                ondelete="CASCADE"),
    )

    dojo_id = db.Column(db.Integer, db.ForeignKey("dojos.dojo_id", ondelete="CASCADE"), primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)
    resource_index = db.Column(db.Integer, primary_key=True)

    type = db.Column(db.String(80), index=True)
    name = db.Column(db.String(128))

    data = db.Column(JSONB)
    data_fields = ["content", "video", "playlist", "slides", "expandable"]
    data_defaults = {"expandable": True}

    dojo = db.relationship("Dojos", back_populates="resources", viewonly=True)
    module = db.relationship("DojoModules", back_populates="_resources")
    visibility = db.relationship("DojoResourceVisibilities",
                                 uselist=False,
                                 cascade="all, delete-orphan",
                                 back_populates="resource")


    def __init__(self, *args, **kwargs):
        default = kwargs.pop("default", None)

        data = kwargs.pop("data", {})
        for field in self.data_fields:
            if field in kwargs:
                data[field] = kwargs.pop(field)
        kwargs["data"] = data

        if default:
            if kwargs.get("data"):
                raise AttributeError("Import requires data to be empty")

            for field in ["type", "name", "resource_index"]:
                kwargs[field] = kwargs[field] if kwargs.get(field) is not None else getattr(default, field, None)

            for field in self.data_fields:
                kwargs["data"][field] = (
                    kwargs["data"][field]
                    if kwargs["data"].get(field) is not None
                    else getattr(default, field, None)
                )

        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name in self.data_fields:
            return (self.data or {}).get(name, self.data_defaults.get(name))
        raise AttributeError(f"No attribute '{name}'")

    @hybrid_property
    def visible(self):
        now = datetime.datetime.utcnow()
        return not self.visibility or all((
            not self.visibility.start or now >= self.visibility.start,
            not self.visibility.stop or now <= self.visibility.stop,
        ))

    @visible.expression
    def visible(cls):
        now = datetime.datetime.utcnow()
        return or_(cls.visibility == None, and_(
            cls.visibility.has(or_(DojoResourceVisibilities.start == None, now >= DojoResourceVisibilities.start)),
            cls.visibility.has(or_(DojoResourceVisibilities.stop == None, now <= DojoResourceVisibilities.stop)),
        ))

    __repr__ = columns_repr(["module", "name"])


class DojoChallengeVisibilities(db.Model):
    __tablename__ = "dojo_challenge_visibilities"
    __table_args__ = (
        db.ForeignKeyConstraint(["dojo_id", "module_index", "challenge_index"],
                                ["dojo_challenges.dojo_id", "dojo_challenges.module_index", "dojo_challenges.challenge_index"],
                                ondelete="CASCADE"),
    )

    dojo_id = db.Column(db.Integer, primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)
    challenge_index = db.Column(db.Integer, primary_key=True)

    start = db.Column(db.DateTime, index=True)
    stop = db.Column(db.DateTime, index=True)

    challenge = db.relationship("DojoChallenges", back_populates="visibility")

    __repr__ = columns_repr(["challenge", "start", "stop"])


class DojoResourceVisibilities(db.Model):
    __tablename__ = "dojo_resource_visibilities"
    __table_args__ = (
        db.ForeignKeyConstraint(["dojo_id", "module_index", "resource_index"],
                                ["dojo_resources.dojo_id", "dojo_resources.module_index", "dojo_resources.resource_index"],
                                ondelete="CASCADE"),
    )

    dojo_id = db.Column(db.Integer, primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)
    resource_index = db.Column(db.Integer, primary_key=True)

    start = db.Column(db.DateTime, index=True)
    stop = db.Column(db.DateTime, index=True)

    resource = db.relationship("DojoResources", back_populates="visibility")

    __repr__ = columns_repr(["resource", "start", "stop"])

class DojoModuleVisibilities(db.Model):
    __tablename__ = "dojo_module_visibilities"
    __table_args__ = (
        db.ForeignKeyConstraint(["dojo_id", "module_index"],
                                ["dojo_modules.dojo_id", "dojo_modules.module_index"],
                                ondelete="CASCADE"),
    )

    dojo_id = db.Column(db.Integer, primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)

    start = db.Column(db.DateTime, index=True)
    stop = db.Column(db.DateTime, index=True)

    module = db.relationship("DojoModules", back_populates="visibility")

    __repr__ = columns_repr(["module", "start", "stop"])


class SSHKeys(db.Model):
    __tablename__ = "ssh_keys"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    value = db.Column(db.Text)

    __table_args__ = (
        db.Index("uq_ssh_keys_digest",
                 db.func.digest(value, "sha256"),
                 unique=True),
    )

    user = db.relationship("Users")

    __repr__ = columns_repr(["user", "value"])


class DiscordUserActivity(db.Model):
    __tablename__ = "discord_user_activity"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, index=True)
    source_user_id = db.Column(db.BigInteger)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    type = db.Column(db.String(80), index=True)
    guild_id = db.Column(db.BigInteger)
    channel_id = db.Column(db.BigInteger)
    message_id = db.Column(db.BigInteger)
    message_timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class DiscordUsers(db.Model):
    __tablename__ = "discord_users"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id = db.Column(db.BigInteger, unique=True)

    user = db.relationship("Users")

    def thanks(self, start=None, end=None):
        return DiscordUserActivity.query.filter(
            DiscordUserActivity.type == "thanks",
            DiscordUserActivity.user_id == self.discord_id,
            DiscordUserActivity.message_timestamp >= start if start else True,
            DiscordUserActivity.message_timestamp <= end if end else True
        )

    def memes(self, start=None, end=None):
        return DiscordUserActivity.query.filter(
            DiscordUserActivity.user_id == self.discord_id,
            DiscordUserActivity.message_timestamp >= start if start else True,
            DiscordUserActivity.message_timestamp <= end if end else True,
            DiscordUserActivity.type == "memes",
        )

    __repr__ = columns_repr(["user", "discord_id"])


class Belts(Awards):
    __mapper_args__ = {"polymorphic_identity": "belt"}


class Emojis(Awards):
    __mapper_args__ = {"polymorphic_identity": "emoji"}


class WorkspaceTokens(db.Model):
    __tablename__ = "workspace_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    created = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    expiration = db.Column(
        db.DateTime,
        default=lambda: datetime.datetime.utcnow() + datetime.timedelta(days=30),
    )
    value = db.Column(db.String(128), unique=True)

    user = db.relationship("Users", foreign_keys="WorkspaceTokens.user_id", lazy="select")

    def __init__(self, *args, **kwargs):
        super(WorkspaceTokens, self).__init__(**kwargs)

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.id!r}>"


for deferral in deferred_definitions:
    deferral()
del deferred_definitions
