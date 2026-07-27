import hashlib
import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from utils import DOJO_URL


ASSET_PATH = Path(__file__).parents[1] / "dojo_theme/static/css/custom.css"


def custom_css_url():
    response = requests.get(DOJO_URL)
    response.raise_for_status()
    match = re.search(r'href="([^"]*/themes/dojo_theme/static/css/custom\.(?:dev|min)\.css\?[^"]+)"', response.text)
    assert match
    return html.unescape(match.group(1))


def asset_version(url):
    return parse_qs(urlparse(url).query)["v"][0]


def test_theme_asset_version_changes_without_restart():
    original = ASSET_PATH.read_bytes()
    initial_url = custom_css_url()
    initial_response = requests.get(urljoin(DOJO_URL, initial_url))
    assert initial_response.status_code == 200
    assert asset_version(initial_url) == hashlib.sha256(initial_response.content).hexdigest()[:8]
    assert "max-age=3600" in initial_response.headers.get("Cache-Control", "")

    try:
        ASSET_PATH.write_bytes(original + b"\n")
        changed_url = custom_css_url()
        assert asset_version(changed_url) != asset_version(initial_url)
        changed_response = requests.get(urljoin(DOJO_URL, changed_url))
        assert asset_version(changed_url) == hashlib.sha256(changed_response.content).hexdigest()[:8]
    finally:
        ASSET_PATH.write_bytes(original)

    assert asset_version(custom_css_url()) == asset_version(initial_url)
