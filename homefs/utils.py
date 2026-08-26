import fcntl
import os
from contextlib import contextmanager


CONTROL_REQUEST_TIMEOUT = (5, 10)
TRANSFER_REQUEST_TIMEOUT = (5, 300)


@contextmanager
def file_lock(path, *, blocking=True):
    lock_fd = os.open(path, os.O_CREAT | os.O_RDWR)
    try:
        yield fcntl.flock(lock_fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if not blocking else 0))
    except BlockingIOError:
        raise
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
