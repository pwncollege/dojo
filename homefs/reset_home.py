import fcntl
import gzip
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile


class HomeResetFailure(Exception):
    def __init__(self, message, *, phase, backup=None):
        super().__init__(message)
        self.phase = phase
        self.backup = backup


def verify_backup(path):
    with gzip.open(path, "rb") as stream:
        while stream.read(1024 * 1024):
            pass
    with tarfile.open(path, "r:gz") as archive:
        archive.getmembers()


def reset_home(volume_path):
    home = volume_path / "active"
    if home.is_symlink() or not home.is_dir():
        raise HomeResetFailure("Home volume is not active", phase="backup")

    with (volume_path / ".active.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise HomeResetFailure("Home volume is busy", phase="lock") from error

        backups = volume_path / "reset-backups"
        backups.mkdir(mode=0o700, exist_ok=True)
        backup_fd, partial_name = tempfile.mkstemp(prefix="home-backup-", suffix=".partial", dir=backups)
        partial = Path(partial_name)
        backup = partial.with_suffix(".tar.gz")
        phase = "backup"
        verified = False
        restored = None
        try:
            with os.fdopen(backup_fd, "wb") as stream:
                with tarfile.open(fileobj=stream, mode="w:gz", compresslevel=6) as archive:
                    archive.add(home, arcname="home/hacker")
                stream.flush()
                os.fsync(stream.fileno())
            verify_backup(partial)
            partial.rename(backup)
            sync_directory(backups)
            verified = True
            print(json.dumps({"event": "backup_ready", "backup": str(backup)}), flush=True)

            phase = "delete"
            for entry in home.iterdir():
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()

            phase = "restore"
            os.chown(home, 1000, 1000)
            os.chmod(home, 0o755)
            restore_fd, restored_name = tempfile.mkstemp(prefix=".home-backup-", dir=home)
            restored = Path(restored_name)
            with os.fdopen(restore_fd, "wb") as destination, backup.open("rb") as source:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
                destination.flush()
                os.fchown(destination.fileno(), 1000, 1000)
                os.fsync(destination.fileno())
            restored.replace(home / "home-backup.tar.gz")
            sync_directory(home)
        except Exception as error:
            for temporary in (partial, restored):
                if temporary is None:
                    continue
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    print(json.dumps({"event": "cleanup_failed", "path": str(temporary),
                                      "error": str(cleanup_error)}), file=sys.stderr)
            raise HomeResetFailure(str(error), phase=phase, backup=backup if verified else None) from error
        try:
            backup.unlink()
            sync_directory(backups)
        except OSError as error:
            print(json.dumps({"event": "cleanup_failed", "backup": str(backup), "error": str(error)}), file=sys.stderr)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    try:
        if len(sys.argv) != 2 or not sys.argv[1].isascii() or not sys.argv[1].isdigit() or int(sys.argv[1]) <= 0:
            raise HomeResetFailure("Invalid user ID", phase="backup")
        volume_path = Path(os.environ.get("STORAGE_ROOT", "/data")) / str(int(sys.argv[1]))
        reset_home(volume_path)
    except HomeResetFailure as error:
        print(json.dumps({"event": "failed", "phase": error.phase, "error": str(error),
                          "backup": str(error.backup) if error.backup else None}), file=sys.stderr)
        return 1
    print(json.dumps({"event": "complete"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
