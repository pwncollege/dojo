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

    id = db.Column(db.String(32), index=True)
    name = db.Column(db.String(128))
    description = db.Column(db.Text)

    official = db.Column(db.Boolean, index=True)
    password = db.Column(db.String(128))

    data = db.Column(db.JSON)
    data_fields = ["type", "award", "comparator", "course", "importable"]
    data_defaults = {
        "importable": True
    }

    users = db.relationship("DojoUsers", back_populates="dojo")
    members = db.relationship("DojoMembers", back_populates="dojo")
    admins = db.relationship("DojoAdmins", back_populates="dojo")
    students = db.relationship("DojoStudents", back_populates="dojo")
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
            return self.data.get(name, self.data_defaults.get(name))
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
        return self.id + "~" + self.hex_dojo_id

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
            cast(case([(cls.data["comparator"] == None, 1000)], else_=cls.data["comparator"]), Numeric()),
            cls.name,
        )

    @classmethod
    def viewable(cls, id=None, user=None):
        return (
            (cls.from_id(id) if id is not None else cls.query)
            .filter(or_(cls.official,
                        and_(cls.data["type"] == "public", cls.password == None),
                        cls.dojo_id.in_(db.session.query(DojoUsers.dojo_id)
                                        .filter_by(user=user)
                                        .subquery())))
            .order_by(*cls.ordering())
        )

    def solves(self, **kwargs):
        return DojoChallenges.solves(dojo=self, **kwargs)

    def completions(self):
        """
        Returns a list of (User, completion_timestamp) tuples for users, sorted by time in ascending order.
        """
        sq = Solves.query.join(DojoChallenges, Solves.challenge_id == DojoChallenges.challenge_id).add_columns(
            Solves.user_id.label("solve_user_id"), db.func.count().label("solve_count"), db.func.max(Solves.date).label("last_solve")
        ).filter(DojoChallenges.dojo == self).group_by(Solves.user_id).subquery()
        return Users.query.join(sq).filter_by(
            solve_count=len(self.challenges)
        ).add_column(sq.columns.last_solve).order_by(sq.columns.last_solve).all()

    def completed(self, user):
        return self.solves(user=user, ignore_visibility=True, ignore_admins=False).count() == len(self.challenges)

    def is_admin(self, user=None):
        if user is None:
            user = get_current_user()
        dojo_admin = DojoAdmins.query.filter_by(dojo=self, user=user).first()
        return dojo_admin is not None or is_admin()

    __repr__ = columns_repr(["name", "id"])


class DojoUsers(db.Model):
    __tablename__ = "dojo_users"
    __mapper_args__ = {"polymorphic_on": "type"}

    dojo_id = db.Column(db.Integer, db.ForeignKey("dojos.dojo_id", ondelete="CASCADE"), primary_key=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)

    type = db.Column(db.String(80), index=True)

    dojo = db.relationship("Dojos", back_populates="users")
    user = db.relationship("Users")

    def solves(self, **kwargs):
        return DojoChallenges.solves(user=self.user, dojo=self.dojo, **kwargs)

    __repr__ = columns_repr(["dojo", "user"])


class DojoMembers(DojoUsers):
    __mapper_args__ = {"polymorphic_identity": "member", "polymorphic_on": "type"}

    dojo = db.relationship("Dojos", back_populates="members")


class DojoAdmins(DojoUsers):
    __mapper_args__ = {"polymorphic_identity": "admin"}

    dojo = db.relationship("Dojos", back_populates="admins")


class DojoStudents(DojoUsers):
    __mapper_args__ = {"polymorphic_identity": "student"}

    token = db.Column(db.String(256))

    dojo = db.relationship("Dojos", back_populates="students")

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

    id = db.Column(db.String(32), index=True)
    name = db.Column(db.String(128))
    description = db.Column(db.Text)

    data = db.Column(db.JSON)
    data_fields = ["importable"]
    data_defaults = {
        "importable": True
    }

    dojo = db.relationship("Dojos", back_populates="_modules")
    _challenges = db.relationship("DojoChallenges",
                                  order_by=lambda: DojoChallenges.challenge_index,
                                  cascade="all, delete-orphan",
                                  back_populates="module")
    _resources = db.relationship("DojoResources",
                                 cascade="all, delete-orphan",
                                 back_populates="module")

    def __init__(self, *args, **kwargs):
        default = kwargs.pop("default", None)
        default_visibility = kwargs.pop("default_visibility", None)

        data = kwargs.pop("data", {})
        for field in self.data_fields:
            if field in kwargs:
                data[field] = kwargs.pop(field)
        kwargs["data"] = data

        if default:
            for field in ["id", "name", "description"]:
                kwargs[field] = kwargs[field] if kwargs.get(field) is not None else getattr(default, field, None)

        kwargs["challenges"] = (
            kwargs.pop("challenges", None) or
            ([DojoChallenges(
                default=challenge,
                visibility=(DojoChallengeVisibilities(**default_visibility) if default_visibility else None),
            ) for challenge in default.challenges] if default else [])
        )
        kwargs["resources"] = (
            kwargs.pop("resources", None) or
            ([DojoResources(
                default=resource,
                visibility=(DojoResourceVisibilities(**default_visibility) if default_visibility else None),
            ) for resource in default.resources] if default else [])
        )

        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name in self.data_fields:
            return self.data.get(name, self.data_defaults.get(name))
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
            resource.resource_index = resource_index
        self._resources = value

    @property
    def path(self):
        return self.dojo.path / self.id

    @property
    def assessments(self):
        return [assessment for assessment in (self.dojo.course or {}).get("assessments", []) if assessment.get("id") == self.id]

    def visible_challenges(self, user=None):
        return [challenge for challenge in self.challenges if challenge.visible() or self.dojo.is_admin(user=user)]

    def solves(self, **kwargs):
        return DojoChallenges.solves(module=self, **kwargs)

    __repr__ = columns_repr(["dojo", "id"])


class DojoChallenges(db.Model):
    __tablename__ = "dojo_challenges"
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

    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"))
    id = db.Column(db.String(32), index=True)
    name = db.Column(db.String(128))
    description = db.Column(db.Text)

    data = db.Column(db.JSON)
    data_fields = ["image", "path_override", "importable", "allow_privileged"]
    data_defaults = {
        "importable": True,
        "allow_privileged": True
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

        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name in self.data_fields:
            return self.data.get(name, self.data_defaults.get(name))
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

    @hybrid_method
    def solves(self, *, user=None, dojo=None, module=None, ignore_visibility=False, ignore_admins=True):
        result = (
            Solves.query
            .join(DojoChallenges, and_(
                DojoChallenges.challenge_id==Solves.challenge_id,
                ))
            .outerjoin(DojoUsers, and_(
                DojoUsers.user_id == Solves.user_id,
                DojoUsers.dojo_id == DojoChallenges.dojo_id,
                ))
            .join(Dojos, and_(
                Dojos.dojo_id == DojoChallenges.dojo_id,
                or_(Dojos.official, Dojos.data["type"] == "public", DojoUsers.user_id != None),
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
                .filter(Users.hidden == False)
            )

        if ignore_admins:
            result = result.filter(or_(DojoUsers.type == None, DojoUsers.type != "admin"))

        if user:
            result = result.filter(Solves.user == user)
        if dojo:
            result = result.filter(DojoChallenges.dojo == dojo)
        if module:
            result = result.filter(DojoChallenges.module == module)

        return result

    @property
    def path(self):
        return (self.module.path / self.id
                if not self.path_override else
                pathlib.Path(self.path_override))

    @property
    def image(self):
        if self.data.get("image"):
            assert any(isinstance(dojo_admin.user, Admins) for dojo_admin in self.dojo.admins), "Custom images are only allowed for admin dojos"
            return self.data["image"]
        return "pwncollege-challenge"

    def challenge_paths(self, user):
        secret = current_app.config["SECRET_KEY"]

        for path in self.path.iterdir():
            if path.name.startswith("_"):
                continue
            yield path.resolve()

        option_paths = sorted(path for path in self.path.iterdir() if path.name.startswith("_"))
        if option_paths:
            option_hash = hashlib.sha256(f"{secret}_{user.id}_{self.challenge_id}".encode()).digest()
            option = option_paths[int.from_bytes(option_hash[:8], "little") % len(option_paths)]
            for path in option.iterdir():
                yield path.resolve()

    __repr__ = columns_repr(["module", "id", "challenge_id"])


class DojoResources(db.Model):
    __tablename__ = "dojo_resources"

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

    data = db.Column(db.JSON)
    data_fields = ["content", "video", "playlist", "slides"]

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

            for field in ["type", "name"]:
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
            return self.data.get(name)
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


class SSHKeys(db.Model):
    __tablename__ = "ssh_keys"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    value = db.Column(db.Text, unique=True)

    user = db.relationship("Users")

    __repr__ = columns_repr(["user", "value"])


class DiscordUsers(db.Model):
    __tablename__ = "discord_users"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id = db.Column(db.Text, unique=True)

    user = db.relationship("Users")

    __repr__ = columns_repr(["user", "discord_id"])

class Belts(Awards):
    __mapper_args__ = {"polymorphic_identity": "belt"}

class Emojis(Awards):
    __mapper_args__ = {"polymorphic_identity": "emoji"}


for deferral in deferred_definitions:
    deferral()
del deferred_definitions