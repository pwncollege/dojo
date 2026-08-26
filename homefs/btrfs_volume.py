import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import requests

from utils import file_lock, CONTROL_REQUEST_TIMEOUT, TRANSFER_REQUEST_TIMEOUT


STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/data"))
VOLUME_SIZE = os.environ.get("VOLUME_SIZE", "1G")
SNAPSHOT_NAME_PATTERN = re.compile(r"[0-9]{8}-[0-9]{6}-[0-9]{6}")


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
    def active_lock(self, *, blocking=True):
        with file_lock(self.path / ".active.lock", blocking=blocking):
            yield

    def activate(self, host, *, locked=False):
        if not locked:
            with self.active_lock():
                return self.activate(host, locked=True)

        if self.active:
            return

        snapshot_path = self.fetch(host)

        with requests.post(
            f"http://{host}:4201/volume/{self.name}/activate",
            allow_redirects=False,
            stream=True,
            timeout=CONTROL_REQUEST_TIMEOUT,
        ) as response:
            if response.status_code != 201:
                raise RuntimeError(f"Failed to activate: {response.status_code}")

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
                with self.active_lock(blocking=False):
                    return active_snapshot()
            except BlockingIOError:
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

        error_file = tempfile.TemporaryFile()
        send_process = subprocess.Popen(
            btrfs_send_args,
            stdout=subprocess.PIPE,
            stderr=error_file,
        )

        def chunks():
            try:
                while chunk := send_process.stdout.read(0x10000):
                    yield chunk
                if send_process.wait() != 0:
                    error_file.seek(0)
                    raise RuntimeError(error_file.read().decode())
            finally:
                send_process.stdout.close()
                if send_process.poll() is None:
                    send_process.terminate()
                    try:
                        send_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        send_process.kill()
                        send_process.wait()
                error_file.close()

        return chunks()

    def receive(self, stream):
        receive_process = subprocess.Popen(["btrfs", "receive", str(self.snapshots_path)],
                                           stdin=subprocess.PIPE,
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.PIPE)
        try:
            while True:
                chunk = stream.read(0x1000)
                if not chunk:
                    break
                receive_process.stdin.write(chunk)
        except BrokenPipeError:
            pass
        except BaseException:
            try:
                receive_process.stdin.close()
            except OSError:
                pass
            receive_process.stdin = None
            if receive_process.poll() is None:
                receive_process.terminate()
            try:
                receive_process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                receive_process.kill()
                receive_process.communicate()
            raise
        _, stderr = receive_process.communicate()
        if receive_process.returncode != 0:
            raise RuntimeError(stderr.decode())
        if match := re.match(r"At subvol (?P<subvol>\S+)", stderr.decode()):
            return self.snapshots_path / match["subvol"]

    def fetch(self, host):
        headers = {}
        if self.latest_snapshot_path:
            headers["If-None-Match"] = self.latest_snapshot_path.name
        with requests.get(
            f"http://{host}:4201/volume/{self.name}",
            allow_redirects=False,
            headers=headers,
            stream=True,
            timeout=TRANSFER_REQUEST_TIMEOUT,
        ) as response:
            if response.status_code not in (200, 304):
                raise RuntimeError(f"Failed to get snapshot: {response.status_code}")

            etag = response.headers.get("ETag")
            if not etag or not SNAPSHOT_NAME_PATTERN.fullmatch(etag):
                raise RuntimeError("Failed to get snapshot: invalid ETag")
            etag_path = self.snapshots_path / etag

            if response.status_code == 304:
                if not etag_path.exists():
                    raise RuntimeError("Failed to get snapshot: missing cached snapshot")
                return etag_path
            if etag_path.exists():
                return etag_path
            snapshot_path = self.receive(response.raw)
            if snapshot_path != etag_path:
                raise RuntimeError("Failed to get snapshot: mismatched snapshot")
            return snapshot_path

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
