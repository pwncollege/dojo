import re
from urllib.parse import urljoin, urlparse

from flask import request

from .countries import lookup_country_code

EMAIL_REGEX = r"(^[^@\s]+@[^@\s]+\.[^@\s]+$)"


class ValidationError(Exception):
    pass


def is_safe_url(target):
    # Browsers read "\\" as "/", drop control characters and collapse "///" into a host
    if re.search(r"[\\\x00-\x1f\x7f]", target) or target.startswith("///"):
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def validate_url(url):
    return urlparse(url).scheme.startswith("http")


def validate_email(email):
    return bool(re.match(EMAIL_REGEX, email))


def validate_country_code(country_code):
    if country_code.strip() == "":
        return
    if lookup_country_code(country_code) is None:
        raise ValidationError("Invalid Country")
