import base64
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
from sqlalchemy import String, DateTime
from sqlalchemy.orm import synonym
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.session import object_session
from sqlalchemy.sql import or_, and_
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from sqlalchemy.ext.associationproxy import association_proxy
from CTFd.models import db, get_class_by_tablename, Challenges, Solves, Flags, Users
from CTFd.utils.user import get_current_user

from ..utils import DOJOS_DIR


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
    data_fields = []

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
            return self.data.get(name)
        raise AttributeError()

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

    @property
    def path(self):
        return DOJOS_DIR / self.hex_dojo_id

    @property
    def hash(self):
        from ..utils.dojo import dojo_git_command
        return dojo_git_command(self, "rev-parse", "HEAD").stdout.decode().strip()

    @classmethod
    def viewable(cls, id=None, user=None):
        return (
            (cls.from_id(id) if id is not None else cls.query)
            .filter(or_(cls.official,
                        cls.dojo_id.in_(db.session.query(DojoUsers.dojo_id)
                                        .filter_by(user=user)
                                        .subquery())))
        )

    def solves(self, *, user=None):
        return DojoChallenges.solves(user=user, dojo=self)

    __repr__ = columns_repr(["name", "id"])


class DojoUsers(db.Model):
    __tablename__ = "dojo_users"
    __mapper_args__ = {"polymorphic_on": "type"}

    dojo_id = db.Column(db.Integer, db.ForeignKey("dojos.dojo_id", ondelete="CASCADE"), primary_key=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)

    type = db.Column(db.String(80), index=True)

    dojo = db.relationship("Dojos", back_populates="users")
    user = db.relationship("Users")

    def solves(self, *, module=None):
        return DojoChallenges.solves(user=self.user, dojo=self.dojo, module=module)

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
    data_fields = []

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
            ([DojoChallenges(default=challenge) for challenge in default.challenges] if default else [])
        )
        kwargs["resources"] = (
            kwargs.pop("resources", None) or
            ([DojoResources(default=resource) for resource in default.resources] if default else [])
        )

        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name in self.data_fields:
            return self.data.get(name)
        raise AttributeError()

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

    def solves(self, *, user=None):
        return DojoChallenges.solves(user=user, module=self)

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
    data_fields = ["path_override"]

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

            kwargs["data"]["path_override"] = str(default.path)

        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name in self.data_fields:
            return self.data.get(name)
        raise AttributeError()

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
    def solves(self, *, user=None, dojo=None, module=None):
        solves_filter = {
            Solves.user: user
        }
        challenges_filter = {
            self.challenge_id: Solves.challenge_id,
            self.dojo: dojo,
            self.module: module,
        }
        return (
            Solves.query
            .filter(*(k == v for k, v in solves_filter.items() if v is not None))
            .join(DojoChallenges, and_(*(k == v for k, v in challenges_filter.items() if v is not None)))
        )

    @property
    def path(self):
        return (self.module.path / self.id
                if not self.path_override else
                pathlib.Path(self.path_override))

    @property
    def image(self):
        return "pwncollege-challenge"

    def challenge_paths(self, user):
        secret = current_app.config["SECRET_KEY"]

        for path in self.path.iterdir():
            if path.name.startswith("_"):
                continue
            yield path.resolve()

        option_paths = sorted(path for path in self.path.iterdir() if path.name.startswith("_"))
        if option_paths:
            option_hash = hashlib.sha256(f"{secret}_{user.id}_{self.challenge.challenge_id}".encode()).digest()
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

            for field in ["type", "name", "data"]:
                kwargs[field] = kwargs[field] if kwargs.get(field) is not None else getattr(default, field, None)

        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name in self.data_fields:
            return self.data.get(name)
        raise AttributeError()

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

    __repr__ = columns_repr(["module"])


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
