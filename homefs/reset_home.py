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


@contextmanager
def locked_home(volume_path):
    home = volume_path / "active"
    if home.is_symlink() or not home.is_dir():
        raise FileNotFoundError(errno.ENOENT, "Home volume is not active", str(home))
    with (volume_path / ".active.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield home


def backup_home(volume_path, output):
    with locked_home(volume_path) as home:
        skipped = 0
        def include(member):
            nonlocal skipped
            if (member.isfile() or member.islnk()) and (home / Path(member.name).relative_to("home/hacker")).stat().st_size > MAX_FILE_SIZE:
                skipped += 1
                return None
            return member

        writer = LimitedWriter(output)
        with gzip.GzipFile(fileobj=writer, mode="wb", compresslevel=6) as compressed:
            with tarfile.open(fileobj=LimitedWriter(compressed), mode="w|") as archive:
                archive.add(home, arcname="home/hacker", filter=include)
        output.flush()
        return {"size": writer.size, "skipped": skipped}


def reset_home(volume_path):
    with locked_home(volume_path) as home:
        for entry in home.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        os.chown(home, 1000, 1000)
        os.chmod(home, 0o755)
    return {}


def main():
    try:
        if len(sys.argv) != 3 or not sys.argv[1].isascii() or not sys.argv[1].isdigit() or int(sys.argv[1]) <= 0:
            raise ValueError("Invalid user ID")
        volume_path = Path(os.environ.get("STORAGE_ROOT", "/data")) / str(int(sys.argv[1]))
        if sys.argv[2] == "backup":
            detail = backup_home(volume_path, sys.stdout.buffer)
        elif sys.argv[2] == "reset":
            detail = reset_home(volume_path)
        else:
            raise ValueError("Invalid home operation")
    except Exception as error:
        status = {errno.EAGAIN: 409, errno.ENOENT: 404, errno.EFBIG: 413}.get(getattr(error, "errno", None), 500)
        print(json.dumps({"event": "failed", "status": status, "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps({"event": "complete", **detail}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
