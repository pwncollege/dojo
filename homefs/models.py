from flask_sqlalchemy import SQLAlchemy

from btrfs_volume import BTRFSVolume


db = SQLAlchemy()


class ActiveVolumes(db.Model):
    name = db.Column(db.String, primary_key=True)
    host = db.Column(db.String)
    created = db.Column(db.DateTime, server_default=db.func.now())


class DockerVolumes(db.Model):
    __tablename__ = "docker_volumes"
    name = db.Column(db.String, primary_key=True)
    created = db.Column(db.DateTime, server_default=db.func.now())
    overlay = db.Column(db.String, default=None)

    @property
    def btrfs(self):
        return BTRFSVolume(self.name) if not self.overlay else BTRFSVolume(self.overlay)

    @property
    def mountpoint(self):
        return self.btrfs.active_path if not self.overlay else self.btrfs.overlays_path / self.name
