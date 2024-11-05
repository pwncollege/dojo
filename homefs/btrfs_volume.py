import io
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import requests

from utils import file_lock


STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/data"))
VOLUME_SIZE = os.environ.get("VOLUME_SIZE", "1G")


def btrfs(*args, **kwargs):
    kwargs.setdefault("check", True)
    return subprocess.run(["btrfs", *args], **kwargs)


def check_volume_storage():
    mounts = Path("/proc/mounts").read_text().splitlines()
    for mount in reversed(mounts):
        _, mount_point, fs_type, *__ = mount.split()
        if mount_point == str(STORAGE_ROOT):
            if fs_type != "btrfs":
                print(f"Error: mount point {STORAGE_ROOT} is not a btrfs filesystem", file=sys.stderr)
                exit(1)
            break
    else:
        print(f"Error: mount point {STORAGE_ROOT} does not exist", file=sys.stderr)
        exit(1)


class BTRFSVolume:
    def __init__(self, name):
        self.name = name
        for path in (self.path, self.snapshots_path, self.overlays_path):
            if not path.exists():
                btrfs("subvolume", "create", path)


    @contextmanager
    def active_lock(self, *, timeout=None):
        with file_lock(self.path / ".active.lock", timeout=timeout):
            yield

    def activate(self, host, *, locked=False):
        if not locked:
            with self.active_lock():
                return self.activate(host, locked=True)

        if self.active:
            return

        snapshot_path = self.fetch(host)

        response = requests.post(f"http://{host}:4201/volume/{self.name}/activate")
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            raise RuntimeError("Failed to activate")

        btrfs("subvolume", "snapshot", snapshot_path, self.active_path)
        btrfs("qgroup", "limit", VOLUME_SIZE, self.active_path)
        return snapshot_path

    def deactivate(self, *, locked=False):
        if not locked:
            with self.active_lock():
                return self.deactivate(locked=True)

        if not self.active:
            return

        snapshot_path = self.snapshot(locked=True)
        btrfs("subvolume", "delete", self.active_path)
        return snapshot_path

    def snapshot(self, *, locked=False):
        now_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        snapshot_path = self.snapshots_path / now_id

        def active_snapshot():
            prev_snapshot_path = self.latest_snapshot_path
            btrfs("subvolume", "snapshot", "-r", self.active_path, snapshot_path)
            diff = self.diff(prev_snapshot_path, snapshot_path)
            if len(diff) == 1:
                btrfs("subvolume", "delete", snapshot_path)
                return prev_snapshot_path
            return snapshot_path

        if self.active:
            if locked:
                return active_snapshot()
            try:
                with self.active_lock(timeout=0):
                    return active_snapshot()
            except TimeoutError:
                pass

        if not self.latest_snapshot_path:
            btrfs("subvolume", "create", snapshot_path)
            btrfs("property", "set", snapshot_path, "ro", "true")

        return self.latest_snapshot_path

    def overlay(self, overlay_name, snapshot_path=None):
        snapshot_path = snapshot_path or self.snapshot()
        self.remove_overlay(overlay_name)
        overlay_path = self.overlays_path / overlay_name
        btrfs("subvolume", "snapshot", snapshot_path, overlay_path)
        return overlay_path

    def remove_overlay(self, overlay_name):
        overlay_path = self.overlays_path / overlay_name
        if not overlay_path.exists():
            return
        btrfs("subvolume", "delete", overlay_path)

    def diff(self, snapshot_a, snapshot_b):
        stream_process = subprocess.Popen(["btrfs", "send", "--no-data", "-p", snapshot_a, snapshot_b],
                                          stdout=subprocess.PIPE)
        try:
            return subprocess.check_output(["btrfs", "receive", "--dump"],
                                           stdin=stream_process.stdout,
                                           text=True).strip().splitlines()
        finally:
            stream_process.wait()

    def send(self, snapshot_path=None, incremental_from=None):
        snapshot_path = snapshot_path or self.snapshot()
        btrfs_send_args = ["btrfs", "send"]
        if incremental_from and (incremental_from_path := self.snapshots_path / incremental_from).exists():
            btrfs_send_args.extend(["-p", incremental_from_path])
        btrfs_send_args.append(snapshot_path)
        return subprocess.check_output(btrfs_send_args)

    def receive(self, stream):
        receive_process = subprocess.Popen(["btrfs", "receive", str(self.snapshots_path)],
                                           stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
        while True:
            chunk = stream.read(0x1000)
            if not chunk:
                break
            receive_process.stdin.write(chunk)
        stdout, stderr = receive_process.communicate()
        if receive_process.returncode != 0:
            raise RuntimeError(stderr.decode())
        if match := re.match(r"At subvol (?P<subvol>\S+)", stderr.decode()):
            return self.snapshots_path / match["subvol"]

    def fetch(self, host):
        headers = {}
        if self.latest_snapshot_path:
            headers["If-None-Match"] = self.latest_snapshot_path.name
        response = requests.get(f"http://{host}:4201/volume/{self.name}", headers=headers)
        etag_path = self.snapshots_path / response.headers["ETag"]
        if response.status_code == 304 or etag_path.exists():
            # We already have the latest snapshot (we may have requested the volume from ourselves)
            return etag_path
        elif response.status_code == 200:
            return self.receive(io.BytesIO(response.content))
        else:
            raise RuntimeError(f"Failed to get snapshot: {response.status_code}")

    @property
    def path(self):
        return STORAGE_ROOT / self.name

    @property
    def active_path(self):
        return self.path / "active"

    @property
    def active(self):
        return self.active_path.exists()

    @property
    def snapshots_path(self):
        return self.path / "snapshots"

    @property
    def overlays_path(self):
        return self.path / "overlays"

    @property
    def latest_snapshot_path(self):
        try:
            return next(reversed(sorted(self.snapshots_path.iterdir())))
        except StopIteration:
            return None
