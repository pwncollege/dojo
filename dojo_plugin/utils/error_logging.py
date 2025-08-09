import json
import logging
from flask import request
from CTFd.utils.user import get_current_user

logger = logging.getLogger(__name__)


def log_exception(error, event_type="exception"):
    user = get_current_user()
    user_id = user.id if user else None
    user_name = user.name if user else "anonymous"
    user_email = user.email if user else None
    
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
        f"{prefix} {event=} {error_type=} {error_message=} {user_id=} {user_name=} {user_email=} "
        f"{method=} {endpoint=} {full_path=} {base_url=} {ip_address=} {user_agent=} {referrer=} "
        f"{query_params=} {form_data=} {json_data=} {content_type=} {content_length=}",
        exc_info=True
    )