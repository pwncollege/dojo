from CTFd.models import db, Challenges


class DojoChallenges(Challenges):
    __tablename__ = "dojo_challenges"
    __mapper_args__ = {"polymorphic_identity": "dojo"}
    id = db.Column(None, db.ForeignKey("challenges.id"), primary_key=True)
    docker_image_name = db.Column(db.String(256))


class PrivateDojos(db.Model):
    __tablename__ = "private_dojos"
    id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name = db.Column(db.Text)
    code = db.Column(db.Text, unique=True)
    data = db.Column(db.Text)


class PrivateDojoMembers(db.Model):
    __tablename__ = "private_dojo_members"
    dojo_id = db.Column(db.Integer, db.ForeignKey("private_dojos.id", ondelete="CASCADE"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class PrivateDojoActives(db.Model):
    __tablename__ = "private_dojo_actives"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    dojo_id = db.Column(db.Integer, db.ForeignKey("private_dojos.id", ondelete="CASCADE"))


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
