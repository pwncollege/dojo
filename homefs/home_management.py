import errno
import gzip
import io
import os
from contextlib import contextmanager
from pathlib import Path
import shutil
import stat
import tarfile

from utils import file_lock


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
    with file_lock(volume_path / ".active.lock", blocking=False):
        yield home


def home_paths(path):
    yield path
    if path.is_dir() and not path.is_symlink():
        for child in path.iterdir():
            yield from home_paths(child)


def backup_home(volume_path):
    with locked_home(volume_path) as home:
        output = io.BytesIO()
        with gzip.GzipFile(fileobj=LimitedWriter(output), mode="wb", compresslevel=6) as compressed:
            with tarfile.open(fileobj=LimitedWriter(compressed), mode="w|") as archive:
                for path in home_paths(home):
                    info = path.lstat()
                    if stat.S_ISREG(info.st_mode) and info.st_size > MAX_FILE_SIZE:
                        continue
                    archive.add(path, arcname=str(Path("home/hacker") / path.relative_to(home)), recursive=False)
                    chunk = output.getvalue()
                    output.seek(0)
                    output.truncate()
                    if chunk:
                        yield chunk
        yield output.getvalue()


def reset_home(volume_path):
    with locked_home(volume_path) as home:
        for entry in home.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        os.chown(home, 1000, 1000)
        os.chmod(home, 0o755)
