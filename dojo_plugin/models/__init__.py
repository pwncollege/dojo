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
from CTFd.models import db, get_class_by_tablename, Challenges, Solves, Flags, Users
from CTFd.utils.user import get_current_user


class Referenceable:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if set(cls.__mro__) & set(Referenceable.__subclasses__()) - set((cls,)):
            return

        primary_key = {
            attr: value
            for attr, value in vars(cls).items()
            if isinstance(value, db.Column) and value.primary_key
        }
        reference_key = {
            f"reference_{name}": f"{cls.__tablename__}.{name}"
            for name in primary_key
        }
        reference_columns = [
            db.Column(f"reference_{name}", key.type)
            for name, key in primary_key.items()
        ]

        for column in reference_columns:
            setattr(cls, column.name, column)
        cls.reference = db.relationship(cls.__name__,
                                        remote_side=primary_key.values(),
                                        lazy="immediate")
        cls.__table_args__ = getattr(cls, "__table_args__", tuple())
        # cls.__table_args__ += (db.Index(*reference_columns),)
        cls.__table_args__ += ((db.ForeignKeyConstraint(reference_key.keys(),
                                                        reference_key.values(),
                                                        ondelete="CASCADE")),)

        shadowed_columns = [
            value
            for attr, value in vars(cls).items()
            if isinstance(value, db.Column) and getattr(value, "shadowed", None)
        ]

        for shadowed_column in shadowed_columns:
            @hybrid_property
            def shadowed_property(self, *, shadowed_column=shadowed_column):
                value = getattr(self, f"_{shadowed_column.name}")
                if value is None and self.reference:
                    return getattr(self.reference, shadowed_column.name)
                return value

            @shadowed_property.setter
            def shadowed_property(self, value, *, shadowed_column=shadowed_column):
                setattr(self, f"_{shadowed_column.name}", value)

            setattr(cls, f"_{shadowed_column.name}", shadowed_column)
            setattr(cls, shadowed_column.name, shadowed_property)

    @staticmethod
    def shadowed(column):
        column.shadowed = True
        return column


def columns_repr(column_names):
    def __repr__(self):
        description = " ".join(f"{name}={getattr(self, name)!r}" for name in column_names)
        return f"<{self.__class__.__name__} {description}>"
    return __repr__


class Dojos(Referenceable, db.Model):
    __tablename__ = "dojos"
    __mapper_args__ = {"polymorphic_on": "type"}

    id = db.Column(db.Integer, primary_key=True)
    repository = db.Column(db.String(256))
    hash = db.Column(db.String(80))
    type = db.Column(db.String(80), index=True)
    _name = Referenceable.shadowed(db.Column("name", db.String(256)))
    _description = Referenceable.shadowed(db.Column("description", db.Text))

    users = db.relationship("DojoUsers", back_populates="dojo")
    members = db.relationship("DojoMembers", back_populates="dojo")
    admins = db.relationship("DojoAdmins", back_populates="dojo")
    students = db.relationship("DojoStudents", back_populates="dojo")
    modules = db.relationship("DojoModules", back_populates="dojo")
    challenges = db.relationship("DojoChallenges", back_populates="dojo")

    __repr__ = columns_repr(["name", "id"])

    @classmethod
    def viewable(cls, user_id):
        return cls.query.filter(or_(
            cls.type=="official",
            cls.id.in_(db.session.query(DojoUsers.dojo_id)
                       .filter_by(user_id=user_id)
                       .subquery())))



class OfficialDojos(Dojos):
    __mapper_args__ = {"polymorphic_identity": "official"}


class PublicDojos(Dojos):
    __mapper_args__ = {"polymorphic_identity": "public"}


class PrivateDojos(Dojos):
    __mapper_args__ = {"polymorphic_identity": "private"}

    password = db.Column(db.String(128))


class ArchiveDojos(Dojos):
    __mapper_args__ = {"polymorphic_identity": "archive"}


class DojoUsers(db.Model):
    __tablename__ = "dojo_users"
    __mapper_args__ = {"polymorphic_on": "type"}

    dojo_id = db.Column(db.Integer, db.ForeignKey("dojos.id", ondelete="CASCADE"), primary_key=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    type = db.Column(db.String(80), index=True)

    dojo = db.relationship("Dojos", back_populates="users")
    user = db.relationship("Users")

    __repr__ = columns_repr(["dojo", "user"])

    @property
    def solves(self):
        pass
        # db.session.query(Solves).filter(Solves.user==self.user,
        #                                 self.dojo.challenges.has(
        #                                 Solves.challenge.has(Solves.


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


class DojoModules(Referenceable, db.Model):
    __tablename__ = "dojo_modules"
    __table_args__ = (db.UniqueConstraint("dojo_id", "name"),)

    dojo_id = db.Column(db.Integer, db.ForeignKey("dojos.id", ondelete="CASCADE"), primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)
    _name = Referenceable.shadowed(db.Column("name", db.String(256)))
    _description = Referenceable.shadowed(db.Column("description", db.Text))

    dojo = db.relationship("Dojos", back_populates="modules")
    challenges = db.relationship("DojoChallenges", back_populates="module")

    @hybrid_property
    def solves(self):
        return db.session.query(Solves).filter(Solves)
        return Solves.query.filter_by(challenge=self.challenge)


    __repr__ = columns_repr(["dojo", "name", "module_index"])


class DojoChallenges(Referenceable, db.Model):
    __tablename__ = "dojo_challenges"
    __table_args__ = (
        db.ForeignKeyConstraint(["dojo_id", "module_index"],
                                ["dojo_modules.dojo_id", "dojo_modules.module_index"],
                                ondelete="CASCADE"),
        db.UniqueConstraint("dojo_id", "name"),
    )

    dojo_id = db.Column(db.Integer, db.ForeignKey("dojos.id", ondelete="CASCADE"), primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)
    challenge_index = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"))
    _name = Referenceable.shadowed(db.Column("name", db.String(256)))
    _description = Referenceable.shadowed(db.Column("description", db.Text))

    challenge = db.relationship("Challenges")
    dojo = db.relationship("Dojos", back_populates="challenges")
    module = db.relationship("DojoModules", back_populates="challenges")
    runtime = db.relationship("DojoChallengeRuntimes", back_populates="challenge")
    duration = db.relationship("DojoChallengeDurations", back_populates="challenge")

    @hybrid_property
    def solves(self):
        return Solves.query.filter_by(challenge=self.challenge)

    __repr__ = columns_repr(["dojo", "name", "module_index", "challenge_index", "challenge_id"])


class DojoChallengeRuntimes(db.Model):
    __tablename__ = "dojo_challenge_runtimes"
    __table_args__ = (
        db.ForeignKeyConstraint(["dojo_id", "module_index", "challenge_index"],
                                ["dojo_challenges.dojo_id", "dojo_challenges.module_index", "dojo_challenges.challenge_index"],
                                ondelete="CASCADE"),
    )

    dojo_id = db.Column(db.Integer, primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)
    challenge_index = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.String(256))
    path = db.Column(db.String(256))

    challenge = db.relationship("DojoChallenges", back_populates="runtime")

    __repr__ = columns_repr(["challenge", "path"])


class DojoChallengeDurations(db.Model):
    __tablename__ = "dojo_challenge_durations"
    __table_args__ = (
        db.ForeignKeyConstraint(["dojo_id", "module_index", "challenge_index"],
                                ["dojo_challenges.dojo_id", "dojo_challenges.module_index", "dojo_challenges.challenge_index"],
                                ondelete="CASCADE"),
    )

    dojo_id = db.Column(db.Integer, primary_key=True)
    module_index = db.Column(db.Integer, primary_key=True)
    challenge_index = db.Column(db.Integer, primary_key=True)
    start = db.Column(db.DateTime(), index=True)
    stop = db.Column(db.DateTime(), index=True)

    challenge = db.relationship("DojoChallenges", back_populates="duration")

    __repr__ = columns_repr(["challenge", "start", "stop"])


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
