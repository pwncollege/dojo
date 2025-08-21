import time
import logging
import threading
import traceback
from pathlib import Path
from sqlalchemy import event
from sqlalchemy.engine import Engine
from CTFd.utils.user import get_current_user

logger = logging.getLogger("dojo.query_timer")
logger.setLevel(logging.INFO)

thread_local = threading.local()

SLOW_QUERY_THRESHOLD = 0.5
DOJO_PLUGIN_PATH = Path(__file__).parent.parent.resolve()


@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    if not hasattr(thread_local, "query_start_times"):
        thread_local.query_start_times = []
    thread_local.query_start_times.append(time.time())


@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    if not hasattr(thread_local, "query_start_times") or not thread_local.query_start_times:
        return
    
    start_time = thread_local.query_start_times.pop()
    query_time = time.time() - start_time
    
    if query_time < SLOW_QUERY_THRESHOLD:
        return
    
    stack = traceback.extract_stack()
    dojo_frames = []
    
    for frame in stack:
        frame_path = Path(frame.filename).resolve()
        try:
            if frame_path.is_relative_to(DOJO_PLUGIN_PATH) and "query_timer" not in frame.filename:
                relative_path = frame_path.relative_to(DOJO_PLUGIN_PATH.parent)
                dojo_frames.append(f"{relative_path}:{frame.lineno}")
        except (ValueError, OSError):
            pass
    
    traceback_str = " ".join(reversed(dojo_frames)) if dojo_frames else "no_dojo_frames"
    
    try:
        current_user = get_current_user()
        user_info = f"user_id={current_user.id}" if current_user else "user_id=None"
    except Exception:
        user_info = "user_id=error"
    
    logger.info(
        f"Slow query: time={query_time=:.3f}s {user_info=} {traceback_str=}"
    )


def init_query_timer():
    pass
