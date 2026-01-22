from flask import Blueprint
from CTFd.utils.decorators import authed_only
from CTFd.plugins import bypass_csrf_protection

test_error_pages = Blueprint("test_error_pages", __name__)

@test_error_pages.route("/test_page_error", methods=["GET", "POST"])
@authed_only
@bypass_csrf_protection
def test_page_error():
    raise Exception("Test page error: This is a deliberate test of the page error handler!")