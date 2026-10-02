import errno
import fcntl
import gzip
import json
import os
from contextlib import contextmanager
from pathlib import Path
import shutil
import sys
import tarfile


MAX_FILE_SIZE = 10_000_000
MAX_ARCHIVE_SIZE = 1024 * 1024 * 1024


class HomeResetFailure(Exception):
    def __init__(self, message, *, phase, backup=None):
        super().__init__(message)
        self.phase = phase
        self.backup = backup


class LimitedWriter:
    def __init__(self, stream):
        self.stream = stream
        self.size = 0

    def write(self, data):
        if self.size + len(data) > MAX_ARCHIVE_SIZE:
            raise OSError(errno.EFBIG, "Home backup exceeds the 1 GiB archive limit")
        written = self.stream.write(data)
        self.size += written
        return written

    def __getattr__(self, name):
        return getattr(self.stream, name)


def verify_backup(path):
    with gzip.open(path, "rb") as stream:
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ARCHIVE_SIZE:
                raise OSError(errno.EFBIG, "Home backup exceeds the 1 GiB archive limit")
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            archive.members.clear()


@contextmanager
def locked_home(volume_path, *, require_active=True):
    home = volume_path / "active"
    if not volume_path.is_dir():
        raise HomeResetFailure("Home volume is not active", phase="backup" if require_active else "missing")
    with (volume_path / ".active.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise HomeResetFailure("Home volume is busy", phase="lock") from error
        if require_active and (home.is_symlink() or not home.is_dir()):
            raise HomeResetFailure("Home volume is not active", phase="backup")
        yield home


def archive_path(volume_path):
    return volume_path / "home-backups" / "backup.tar.gz"


def backup_home(volume_path):
    with locked_home(volume_path) as home:
        backup = archive_path(volume_path)
        backup.parent.mkdir(mode=0o700, exist_ok=True)
        partial = backup.with_suffix(".partial")
        skipped = 0

        def include(member):
            nonlocal skipped
            if (member.isfile() or member.islnk()) and (home / Path(member.name).relative_to("home/hacker")).stat().st_size > MAX_FILE_SIZE:
                skipped += 1
                return None
            return member

        try:
            partial.unlink(missing_ok=True)
            with partial.open("xb", buffering=0) as stream:
                os.chmod(partial, 0o600)
                with gzip.GzipFile(fileobj=LimitedWriter(stream), mode="wb", compresslevel=6) as compressed:
                    with tarfile.open(fileobj=LimitedWriter(compressed), mode="w|") as archive:
                        archive.add(home, arcname="home/hacker", filter=include)
                os.fsync(stream.fileno())
            verify_backup(partial)
            partial.replace(backup)
            sync_directory(backup.parent)
        except Exception as error:
            try:
                partial.unlink(missing_ok=True)
            except OSError as cleanup_error:
                print(json.dumps({"event": "cleanup_failed", "error": str(cleanup_error)}), file=sys.stderr)
            raise HomeResetFailure(str(error), phase="backup") from error
        return {"backup": str(backup), "size": backup.stat().st_size, "skipped": skipped}


def reset_home(volume_path):
    with locked_home(volume_path) as home:
        backup = archive_path(volume_path)
        try:
            verify_backup(backup)
        except Exception as error:
            raise HomeResetFailure(str(error), phase="backup") from error
        try:
            for entry in home.iterdir():
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            os.chown(home, 1000, 1000)
            os.chmod(home, 0o755)
            sync_directory(home)
        except Exception as error:
            raise HomeResetFailure(str(error), phase="reset", backup=backup) from error
        return {}


def latest_backup(volume_path):
    with locked_home(volume_path, require_active=False):
        backup = archive_path(volume_path)
        if not backup.is_file():
            raise HomeResetFailure("No home backup is available", phase="missing")
        return {"backup": str(backup), "size": backup.stat().st_size}


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    try:
        if len(sys.argv) != 3 or not sys.argv[1].isascii() or not sys.argv[1].isdigit() or int(sys.argv[1]) <= 0:
            raise HomeResetFailure("Invalid user ID", phase="backup")
        actions = {"backup": backup_home, "reset": reset_home, "latest": latest_backup}
        if sys.argv[2] not in actions:
            raise HomeResetFailure("Invalid home operation", phase="backup")
        volume_path = Path(os.environ.get("STORAGE_ROOT", "/data")) / str(int(sys.argv[1]))
        detail = actions[sys.argv[2]](volume_path)
    except HomeResetFailure as error:
        print(json.dumps({"event": "failed", "phase": error.phase, "error": str(error),
                          "backup": str(error.backup) if error.backup else None}), file=sys.stderr)
        return 1
    print(json.dumps({"event": "complete", **detail}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
