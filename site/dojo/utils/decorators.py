import functools

from flask import abort, jsonify, redirect, request, url_for

from ..models import cache, get_config
from .user import authed, get_ip, is_admin, is_verified


def deny():
    if request.content_type == "application/json" or request.accept_mimetypes.best == "text/event-stream":
        abort(403)
    return redirect(url_for("auth.login", next=request.full_path))


def authed_only(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs) if authed() else deny()
    return wrapper


def admins_only(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs) if is_admin() else deny()
    return wrapper


def require_verified_emails(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if get_config("verify_emails") and authed() and not is_admin() and not is_verified():
            if request.content_type == "application/json":
                abort(403)
            return redirect(url_for("auth.confirm"))
        return f(*args, **kwargs)
    return wrapper


def ratelimit(method="POST", limit=50, interval=300, key_prefix="rl"):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if request.method == method:
                key = f"{key_prefix}:{get_ip()}:{request.endpoint}"
                current = cache.get(key)
                if current and int(current) > limit - 1:
                    response = jsonify({"code": 429, "message": f"Too many requests. Limit is {limit} requests in {interval} seconds"})
                    response.status_code = 429
                    return response
                cache.set(key, int(current or 0) + 1, timeout=interval)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def check_account_visibility(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        visibility = get_config("account_visibility", "public")
        if visibility == "private" and not authed():
            return deny()
        if visibility == "admins" and not is_admin():
            abort(404)
        return f(*args, **kwargs)
    return wrapper


def bypass_csrf_protection(f):
    f._bypass_csrf = True
    return f
