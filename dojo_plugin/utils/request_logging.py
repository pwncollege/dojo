import logging
import threading
from flask import request, g, has_request_context

_trace_id_storage = threading.local()


def get_trace_id():
    try:
        if has_request_context() and hasattr(g, 'trace_id'):
            return g.trace_id
    except RuntimeError:
        pass

    if hasattr(_trace_id_storage, 'trace_id'):
        return _trace_id_storage.trace_id

    return None


def set_trace_id(trace_id):
    try:
        if has_request_context():
            g.trace_id = trace_id
    except RuntimeError:
        pass
    _trace_id_storage.trace_id = trace_id


def clear_trace_id():
    try:
        if has_request_context() and hasattr(g, 'trace_id'):
            delattr(g, 'trace_id')
    except RuntimeError:
        pass
    # Don't clear thread-local storage - let it persist for werkzeug logging
    # It will be overwritten on the next request anyway


def init_trace_id():
    trace_id = request.headers.get('PWN-Trace-ID')
    if not trace_id:
        # Mark requests not from nginx (health checks, direct access)
        trace_id = "LOCAL"
    set_trace_id(trace_id)
    return trace_id


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = get_trace_id() or 'NONE-SET'
        return True


def setup_trace_id_tracking(app):
    def before_request_handler():
        init_trace_id()
    app.before_request(before_request_handler)

    def teardown_request_handler(exception=None):
        clear_trace_id()
    app.teardown_request(teardown_request_handler)


def setup_logging(app):
    # Create a single shared filter instance
    trace_id_filter = RequestIdFilter()

    # Create a custom handler that includes trace_id
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('time=%(asctime)s trace_id=%(trace_id)s %(levelname)s logger=%(name)s %(message)s'))
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

    # Make sure werkzeug inherits from root
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.handlers = []  # Remove any existing handlers
    # Don't set propagate=False, let it use root logger's handler
