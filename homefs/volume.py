import fcntl
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import time


STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/data"))
STORAGE_SIZE = os.environ.get("STORAGE_SIZE", "256G")
VOLUME_SIZE = os.environ.get("VOLUME_SIZE", "1G")


def btrfs(*args, **kwargs):
    kwargs.setdefault("check", True)
    return subprocess.run(["btrfs", *args], **kwargs)


@contextmanager
def file_lock(path, *, timeout=None):
    lock_fd = os.open(path, os.O_CREAT | os.O_RDWR)
    try:
        if timeout is None:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        else:
            start_time = time.time()
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if timeout >= 0 and time.time() - start_time > timeout:
                    raise TimeoutError
                time.sleep(0.1)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def check_volume_storage():
    lock = file_lock("/run/homefs.lock")
    lock.__enter__()
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


class Volume:
    def __init__(self, name):
        self.name = name
        if not self.path.exists():
            btrfs("subvolume", "create", self.path)
            btrfs("subvolume", "create", self.snapshots_path)

    @contextmanager
    def active_lock(self, *, timeout=None):
        with file_lock(self.path / ".active.lock", timeout=timeout):
            yield

    def activate(self, from_snapshot=None, *, locked=False):
        if not locked:
            with self.active_lock():
                return self.activate(from_snapshot, locked=True)
        if self.active:
            btrfs("subvolume", "delete", self.active_path)
        from_snapshot = from_snapshot or self.latest_snapshot_path
        if from_snapshot:
            btrfs("subvolume", "snapshot", from_snapshot, self.active_path)
        else:
            btrfs("subvolume", "create", self.active_path)
        btrfs("qgroup", "limit", VOLUME_SIZE, self.active_path)

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

    def diff(self, snapshot_a, snapshot_b):
        stream = subprocess.Popen(["btrfs", "send", "--no-data", "-p", snapshot_a, snapshot_b],
                                  stdout=subprocess.PIPE).stdout
        return (subprocess.check_output(["btrfs", "receive", "--dump"], stdin=stream, encoding="latin")
                .strip().splitlines())

    def send(self, snapshot_path=None, parents=None):
        snapshot_path = snapshot_path or self.snapshot()
        btrfs_send_args = ["btrfs", "send"]
        parents = set(parents or []) & set(path.name for path in self.snapshots_path.iterdir())
        if parents:
            btrfs_send_args.extend(["-p", max(parents)])
        btrfs_send_args.append(snapshot_path)
        return subprocess.Popen(btrfs_send_args, stdout=subprocess.PIPE).stdout

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
    def latest_snapshot_path(self):
        try:
            return next(reversed(sorted(self.snapshots_path.iterdir())))
        except StopIteration:
            return None
