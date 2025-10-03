import threading
import logging
import json
import time
from flask import request, g, has_request_context
from CTFd.utils.user import get_current_user

_trace_id_storage = threading.local()
logger = logging.getLogger(__name__)

def log_exception(error, event_type="exception"):
    event = event_type
    error_type = type(error).__name__
    error_message = str(error)
    method = request.method
    endpoint = request.path
    full_path = request.full_path
    base_url = request.base_url
    ip_address = request.remote_addr
    user_agent = request.user_agent.string if request.user_agent else None
    referrer = request.referrer
    query_params = json.dumps(dict(request.args)) if request.args else None
    form_data = json.dumps(dict(request.form)) if request.form else None
    json_data = json.dumps(request.get_json(silent=True)) if request.get_json(silent=True) else None
    content_type = request.content_type
    content_length = request.content_length

    prefix = event_type.upper()

    logger.error(
        f"{prefix} {event=} {error_type=} {error_message=} "
        f"{method=} {endpoint=} {full_path=} {base_url=} {ip_address=} {user_agent=} {referrer=} "
        f"{query_params=} {form_data=} {json_data=} {content_type=} {content_length=}",
        exc_info=True
    )

def get_tracked_attr(attr, default="NONE"):
    try:
        if has_request_context():
            return getattr(g, attr)
    except (RuntimeError, AttributeError):
        pass

    try:
        return getattr(_trace_id_storage, attr)
    except AttributeError:
        pass

    return default


def get_trace_id():
    return get_tracked_attr("trace_id", default="NONE")

def get_user_id():
    try:
        user = get_current_user()
        return user.id if user else None
    except RuntimeError:
        return getattr(_trace_id_storage, "user_id", None)

def get_ip_address():
    try:
        return request.remote_addr
    except RuntimeError:
        return getattr(_trace_id_storage, "remote_addr", None)

class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = get_trace_id()
        record.user_id = get_user_id()
        record.remote_addr = get_ip_address()
        record.reltime = "%.2f" % (time.time() - get_tracked_attr("start_time", time.time()))
        record.name = record.name.replace("CTFd.plugins.dojo_plugin", "dojo_plugin")
        return True


def setup_uncaught_error_logging(app):
    @app.errorhandler(Exception)
    def handle_page_exception(error):
        if hasattr(error, 'code') and error.code == 404:
            raise

        log_exception(error, event_type="page_exception")
        raise

def setup_trace_id_tracking(app):
    def before_request_handler():
        # not all requests are via nginx (health checks, direct access)
        trace_id = request.headers.get('PWN-Trace-ID') or "LOCAL"
        user = get_current_user()
        start_time = time.time()

        # save stuff to request object because it might have a tighter lifespan?
        try:
            if has_request_context():
                g.trace_id = trace_id
                g.start_time = start_time
        except RuntimeError:
            pass

        # werkzeug's logger doesn't have access to the flask requests or g objects
        _trace_id_storage.trace_id = trace_id
        _trace_id_storage.user_id = user.id if user else None
        _trace_id_storage.remote_addr = request.remote_addr
        _trace_id_storage.start_time = start_time

    def teardown_request_handler(exception=None):
        try:
            if has_request_context() and hasattr(g, 'trace_id'):
                delattr(g, 'trace_id')
        except RuntimeError:
            pass
        # Don't clear thread-local storage - let it persist for werkzeug logging
        # It will be overwritten on the next request anyway

    app.before_request(before_request_handler)
    app.teardown_request(teardown_request_handler)


def log_generator_output(prefix, generator, start_time=None, last_time=None):
    start_time = start_time or time.time()
    last_msg = last_time or time.time()
    for message in generator:
        since_start = time.time() - start_time
        since_last_msg = time.time() - last_msg
        logger.info(f"generator output: {prefix}{since_start=:.1f} {since_last_msg=:.1f} {message=}")
        yield message
        last_msg = time.time()


def setup_logging(app):
    # Create a single shared filter instance
    trace_id_filter = RequestIdFilter()

    # Create a custom handler that includes trace_id
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('time="%(asctime)s" trace_id=%(trace_id)s request_reltime=%(reltime)s remote_ip=%(remote_addr)s user_id=%(user_id)s logger=%(name)s %(levelname)s %(message)s'))
    handler.addFilter(trace_id_filter)

    # Remove existing handlers and add our custom one
    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.addHandler(handler)

    # Also configure Flask's app logger
    app.logger.handlers = []
    app.logger.addHandler(handler)

    # Hook CTFd's logger specifically
    ctfd_logger = logging.getLogger('CTFd')
    ctfd_logger.handlers = []
    ctfd_logger.addHandler(handler)
    ctfd_logger = logging.getLogger('submissions')
    ctfd_logger.handlers = []
    ctfd_logger.addHandler(handler)
    ctfd_logger = logging.getLogger('registrations')
    ctfd_logger.handlers = []
    ctfd_logger.addHandler(handler)
    ctfd_logger = logging.getLogger('logins')
    ctfd_logger.handlers = []
    ctfd_logger.addHandler(handler)

    # inherit stuff from root
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.handlers = []

    gunicorn_error_logger = logging.getLogger('gunicorn.error')
    gunicorn_error_logger.handlers = []
    gunicorn_error_logger.propagate = True

    gunicorn_access_logger = logging.getLogger('gunicorn.access')
    gunicorn_access_logger.handlers = []
    gunicorn_access_logger.propagate = True
