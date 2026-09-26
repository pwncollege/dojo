import hashlib
import hmac as _hmac
import logging
import os
import re
import time
from collections import namedtuple

from flask import abort, current_app, redirect, request, session, url_for

from ..models import Users, cache, get_config

TRUSTED_PROXIES = re.compile(r"^127\.0\.0\.1$|^::1$|^fc00:|^10\.|^172\.(1[6-9]|2[0-9]|3[0-1])\.|^192\.168\.")
UserAttrs = namedtuple("UserAttrs", ["type", "banned", "verified"])


def hmac(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _hmac.new(key=current_app.config["SECRET_KEY"].encode("utf-8"), msg=data, digestmod=hashlib.sha1).hexdigest()


def generate_nonce():
    return os.urandom(32).hex()


def authed():
    return bool(session.get("id", False))


def get_current_user():
    if not authed():
        return None
    user = Users.query.filter_by(id=session["id"]).first()
    session_hash = session.get("hash")
    if user is None or (session_hash and session_hash != hmac(user.password)):
        logout_user()
        if request.content_type == "application/json":
            abort(401)
        abort(redirect(url_for("auth.login", next=request.full_path)))
    return user


def get_current_user_attrs():
    if not authed():
        return None
    try:
        return get_user_attrs(user_id=session["id"])
    except TypeError:
        clear_user_session(user_id=session["id"])
        return get_user_attrs(user_id=session["id"])


@cache.memoize(timeout=300)
def get_user_attrs(user_id):
    user = Users.query.filter_by(id=user_id).first()
    return UserAttrs(user.type, user.banned, user.verified) if user else None


def clear_user_session(user_id):
    cache.delete_memoized(get_user_attrs, user_id=user_id)


def is_admin():
    return authed() and get_current_user_attrs().type == "admin"


def is_verified():
    if not get_config("verify_emails"):
        return True
    user = get_current_user_attrs()
    return user.verified if user else False


def get_ip(req=None):
    if req is None:
        req = request
    for addr in reversed(req.access_route + [req.remote_addr]):
        if not TRUSTED_PROXIES.match(addr):
            return addr
    return req.remote_addr


def audit_log(logger, message):
    logging.getLogger(logger).info(f"[{time.strftime('%m/%d/%Y %X')}] {get_ip()} - {message}")


def update_user(user):
    session["id"] = user.id
    session["hash"] = hmac(user.password)
    session.permanent = True
    clear_user_session(user_id=user.id)


def login_user(user):
    session["nonce"] = generate_nonce()
    update_user(user)


def logout_user():
    session.clear()
