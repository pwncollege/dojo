import fcntl
import os
import time
from contextlib import contextmanager


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
