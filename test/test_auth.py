import datetime
import email.utils
import random
import string
import time
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import pytest
import requests

from utils import DOJO_URL, db_sql, get_user_id, login, parse_csrf_token
from test_accounts import (
    account_case,
    anon_session,
    count_users,
    mint_signed_token,
    password_hash,
    rand_name,
    second_user,
    server_config,
)


def post_form(session, path, data, **kwargs):
    while True:
        response = session.post(f"{DOJO_URL}{path}", data=data, **kwargs)
        if response.status_code != 429:
            return response
        time.sleep(1)


IN_PROCESS_FORM_POST = """
import time

def post_retrying(path, data):
    for _ in range(70):
        response = client.post(path, data=data)
        if response.status_code != 429:
            return response
        time.sleep(1)
    return response
"""


@pytest.mark.parametrize("endpoint", ["/", "/dojos", "/login", "/register"])
def test_unauthenticated_return_200(endpoint):
    response = requests.get(f"{DOJO_URL}{endpoint}")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"


def test_login():
    login("admin", "incorrect_password", success=False)
    login("admin", "admin")


def test_register():
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    login(random_id, random_id, register=True)


def test_reset_password_page_without_mail():
    page = requests.get(f"{DOJO_URL}/reset_password")
    assert page.status_code == 200
    assert "not configured to send email" in page.text

    session = requests.Session()
    nonce = parse_csrf_token(session.get(f"{DOJO_URL}/reset_password").text)
    submitted = post_form(session, "/reset_password", {"email": "x@example.com", "nonce": nonce})
    assert submitted.status_code == 200
    assert "not configured to send email" in submitted.text


def test_confirm_page_redirects_when_verification_disabled(random_user_session):
    response = random_user_session.get(f"{DOJO_URL}/confirm", allow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/challenges"), response.headers


def test_html_password_reset_flow_with_mail(random_user, second_user):
    name, _ = random_user
    uid = get_user_id(name)
    evicted = login(name, name)
    oauth_name, _ = second_user
    oauth_uid = get_user_id(oauth_name)
    anon = anon_session()
    nonce = anon.headers["CSRF-Token"]

    account_case(anon, IN_PROCESS_FORM_POST + f"""
from dojo_plugin.pages import auth as auth_page
from dojo_plugin.utils import serialize
from dojo_plugin.models import verify_password

uid = {uid}
oauth_uid = {oauth_uid}
nonce = {nonce!r}
user_email = Users.query.get(uid).email
original_password = Users.query.get(uid).password
oauth_email = Users.query.get(oauth_uid).email
oauth_hash = Users.query.get(oauth_uid).password
oauth_user = Users.query.get(oauth_uid)
oauth_user.oauth_id = oauth_uid
db.session.commit()
deliveries = []
alerts = []
try:
    with patch.object(auth_page, "can_send_mail", return_value=True), \\
         patch.object(auth_page.email, "forgot_password", side_effect=deliveries.append), \\
         patch.object(auth_page.email, "password_change_alert", side_effect=alerts.append):
        requested = post_retrying("/reset_password", {{"email": user_email, "nonce": nonce}})
        assert requested.status_code == 200, requested.status_code
        requested_body = requested.get_data(as_text=True)
        assert "If that account exists you will receive an email" in requested_body, requested_body
        assert deliveries == [user_email], deliveries

        unknown = post_retrying("/reset_password", {{"email": {rand_name() + "@example.com"!r}, "nonce": nonce}})
        assert unknown.status_code == 200, unknown.status_code
        assert unknown.get_data(as_text=True) == requested_body
        assert deliveries == [user_email], deliveries

        token = serialize(user_email)
        set_page = client.get(f"/reset_password/{{token}}")
        assert set_page.status_code == 200, set_page.status_code
        set_body = set_page.get_data(as_text=True)
        assert 'id="password"' in set_body, set_body
        assert "reset the password for your account" in set_body, set_body

        empty = post_retrying(f"/reset_password/{{token}}", {{"password": "   ", "nonce": nonce}})
        assert empty.status_code == 200, empty.status_code
        assert "Please pick a longer password" in empty.get_data(as_text=True)
        assert Users.query.get(uid).password == original_password
        assert alerts == [], alerts

        reset = post_retrying(f"/reset_password/{{token}}", {{"password": "replacement-pw", "nonce": nonce}})
        assert reset.status_code == 302, (reset.status_code, reset.get_data(as_text=True))
        assert reset.headers["Location"].endswith("/login"), reset.headers
        assert alerts == [user_email], alerts
        assert verify_password("replacement-pw", Users.query.get(uid).password)

        guarded = post_retrying(f"/reset_password/{{serialize(oauth_email)}}", {{"password": "x", "nonce": nonce}})
        assert guarded.status_code == 200, guarded.status_code
        assert "registered via an authentication provider" in guarded.get_data(as_text=True)
        assert Users.query.get(oauth_uid).password == oauth_hash
        assert alerts == [user_email], alerts
finally:
    Users.query.get(oauth_uid).oauth_id = None
    db.session.commit()
""")

    stale = evicted.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", allow_redirects=False)
    assert stale.status_code == 302, "a password reset must evict sessions established with the old password"
    reauthenticated = login(name, "replacement-pw")
    assert reauthenticated.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()["name"] == name


def test_html_email_confirmation_flow(random_user):
    name, session = random_user
    uid = get_user_id(name)
    expired_token = mint_signed_token(f"{name}@example.com", age=10000)
    nonce = session.headers["CSRF-Token"]

    account_case(session, IN_PROCESS_FORM_POST + f"""
import contextlib
from dojo_plugin.models import get_config as real_get_config
from dojo_plugin.pages import auth as auth_page
from dojo_plugin.pages import settings as settings_page
from dojo_plugin.utils import decorators, serialize
from dojo_plugin.utils import user as user_utils
from dojo_plugin.utils.user import clear_user_session

def configured(key, *args, **kwargs):
    return True if key == "verify_emails" else real_get_config(key, *args, **kwargs)

uid = {uid}
original_verified = Users.query.get(uid).verified
user_email = Users.query.get(uid).email
assert user_email == {name + "@example.com"!r}, user_email
unverified = Users.query.get(uid)
unverified.verified = False
db.session.commit()
clear_user_session(user_id=uid)
welcomes = []
verifications = []
try:
    with contextlib.ExitStack() as patches:
        for module in (decorators, user_utils, settings_page, auth_page):
            patches.enter_context(patch.object(module, "get_config", side_effect=configured))
        patches.enter_context(patch.object(auth_page.email, "successful_registration_notification", side_effect=welcomes.append))
        patches.enter_context(patch.object(auth_page.email, "verify_email_address", side_effect=verifications.append))

        pending = client.get("/confirm")
        assert pending.status_code == 200, pending.status_code
        assert "We've sent a confirmation email" in pending.get_data(as_text=True)

        resent = post_retrying("/confirm", {{"nonce": {nonce!r}}})
        assert resent.status_code == 200, resent.status_code
        assert f"Confirmation email sent to {{user_email}}!" in resent.get_data(as_text=True)
        assert verifications == [user_email], verifications

        token = serialize(user_email)
        confirmed = client.get(f"/confirm/{{token}}")
        assert confirmed.status_code == 302, confirmed.status_code
        assert confirmed.headers["Location"].endswith("/challenges"), confirmed.headers
        assert Users.query.get(uid).verified is True
        assert welcomes == [user_email], welcomes

        repeated = client.get(f"/confirm/{{token}}")
        assert repeated.status_code == 302, repeated.status_code
        assert repeated.headers["Location"].endswith("/settings"), repeated.headers
        assert welcomes == [user_email], welcomes
        assert verifications == [user_email], verifications

        invalid = client.get("/confirm/not-a-token")
        assert invalid.status_code == 200, invalid.status_code
        assert "Your confirmation token is invalid" in invalid.get_data(as_text=True)

        expired = client.get({"/confirm/" + expired_token!r})
        assert expired.status_code == 200, expired.status_code
        assert "Your confirmation link has expired" in expired.get_data(as_text=True)
finally:
    Users.query.get(uid).verified = original_verified
    db.session.commit()
    clear_user_session(user_id=uid)
""")


def test_login_regenerates_session_and_nonce(random_user_name):
    session = requests.Session()
    page = session.get(f"{DOJO_URL}/login")
    old_cookie = session.cookies.get("session")
    old_nonce = parse_csrf_token(page.text)

    logged_in = post_form(session, "/login", {"name": random_user_name, "password": random_user_name, "nonce": old_nonce},
                          allow_redirects=False)
    assert logged_in.status_code == 302, logged_in.text
    new_cookie = session.cookies.get("session")
    assert new_cookie != old_cookie

    stale = requests.Session()
    stale.cookies.set("session", old_cookie)
    stale_me = stale.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", headers={"Content-Type": "application/json"})
    assert stale_me.status_code == 403, "the pre-login session id must not survive login"

    old_nonce_post = requests.post(f"{DOJO_URL}/pwncollege_api/v1/ssh_key", json={"ssh_key": ""},
                                   headers={"CSRF-Token": old_nonce}, cookies={"session": new_cookie})
    assert old_nonce_post.status_code == 403, "login must rotate the CSRF nonce"

    new_nonce = parse_csrf_token(session.get(f"{DOJO_URL}/").text)
    assert new_nonce != old_nonce
    new_nonce_post = requests.post(f"{DOJO_URL}/pwncollege_api/v1/ssh_key", json={"ssh_key": ""},
                                   headers={"CSRF-Token": new_nonce}, cookies={"session": new_cookie})
    assert new_nonce_post.status_code != 403, new_nonce_post.text


def test_tampered_session_cookie_is_anonymous(random_user_name):
    valid_cookie = login(random_user_name, random_user_name).cookies.get("session")
    authenticated = requests.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", cookies={"session": valid_cookie},
                                 headers={"Content-Type": "application/json"})
    assert authenticated.status_code == 200, authenticated.status_code
    assert authenticated.json()["name"] == random_user_name, authenticated.json()

    for bad in ["garbage", valid_cookie + "x"]:
        page = requests.get(f"{DOJO_URL}/dojos", cookies={"session": bad})
        assert page.status_code == 200, page.status_code
        assert "session=" in page.headers.get("Set-Cookie", ""), page.headers
        assert 'href="/logout"' not in page.text

        me = requests.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", cookies={"session": bad},
                          headers={"Content-Type": "application/json"})
        assert me.status_code == 403, (bad, me.status_code)


def test_password_change_evicts_other_sessions(random_user):
    name, _ = random_user
    changer = login(name, name)
    html_client = login(name, name)
    json_client = login(name, name)

    changed = changer.patch(f"{DOJO_URL}/pwncollege_api/v1/users/me", json={"password": "newpw-123", "confirm": name})
    assert changed.status_code == 200, changed.text
    assert changer.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").status_code == 200

    evicted_cookie = html_client.cookies.get("session")
    html_evicted = html_client.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", allow_redirects=False)
    assert html_evicted.status_code == 302, html_evicted.status_code
    assert "/login" in html_evicted.headers["Location"], html_evicted.headers
    assert "session" not in html_client.cookies, "eviction must delete the session cookie"

    json_evicted = json_client.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", headers={"Content-Type": "application/json"})
    assert json_evicted.status_code == 401, json_evicted.status_code

    after = html_client.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", allow_redirects=False)
    assert after.status_code == 302, after.status_code

    replayed = requests.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", cookies={"session": evicted_cookie},
                            headers={"Content-Type": "application/json"})
    assert replayed.status_code == 403, "an evicted session id must stay anonymous when replayed"


def test_session_cookie_flags(random_user_name):
    session = requests.Session()
    nonce = parse_csrf_token(session.get(f"{DOJO_URL}/login").text)
    response = post_form(session, "/login", {"name": random_user_name, "password": random_user_name, "nonce": nonce},
                         allow_redirects=False)
    assert response.status_code == 302, response.text

    jar = SimpleCookie()
    jar.load(response.headers["Set-Cookie"])
    morsel = jar["session"]
    assert morsel["httponly"]
    assert morsel["samesite"].lower() == "lax"
    expires = email.utils.parsedate_to_datetime(morsel["expires"])
    expected = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=180)
    assert abs(expires - expected) < datetime.timedelta(days=2), morsel["expires"]


def test_login_follows_safe_next_only(random_user_name):
    def login_next(next_value):
        session = requests.Session()
        nonce = parse_csrf_token(session.get(f"{DOJO_URL}/login").text)
        response = post_form(session, "/login", {"name": random_user_name, "password": random_user_name, "nonce": nonce},
                             params={"next": next_value}, allow_redirects=False)
        assert response.status_code == 302, (next_value, response.status_code)
        return urlparse(response.headers["Location"])

    assert login_next("/settings").path.endswith("/settings")
    for unsafe in ["https://evil.example/", "//evil.example/", "javascript:alert(1)"]:
        location = login_next(unsafe)
        assert location.path.endswith("/challenges"), (unsafe, location)
        assert location.netloc != "evil.example", (unsafe, location)


def test_navbar_logout_ends_session(random_user):
    _, session = random_user
    assert 'href="/logout"' in session.get(f"{DOJO_URL}/dojos").text

    logged_out = session.get(f"{DOJO_URL}/logout", allow_redirects=False)
    assert logged_out.status_code == 302, logged_out.status_code
    assert urlparse(logged_out.headers["Location"]).path == "/"

    me = session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", allow_redirects=False)
    assert me.status_code == 302, me.status_code
    assert 'href="/logout"' not in session.get(f"{DOJO_URL}/dojos").text


def test_register_form_rejections(random_user):
    name, session = random_user

    logged_in = session.get(f"{DOJO_URL}/register", allow_redirects=False)
    assert logged_in.status_code == 302, logged_in.status_code
    assert logged_in.headers["Location"].endswith("/challenges"), logged_in.headers

    duplicate_session = requests.Session()
    nonce = parse_csrf_token(duplicate_session.get(f"{DOJO_URL}/register").text)
    duplicate = post_form(duplicate_session, "/register", {
        "name": name, "email": f"{rand_name()}@example.com", "password": "pw",
        "nonce": nonce, "commitment_verified": "verified",
    })
    assert duplicate.status_code == 200, duplicate.status_code
    assert "That user name is already taken" in duplicate.text

    code_session = requests.Session()
    code_nonce = parse_csrf_token(code_session.get(f"{DOJO_URL}/register").text)
    fresh = rand_name()
    code_form = {
        "name": fresh, "email": f"{fresh}@example.com", "password": fresh, "registration_code": "wrong",
        "nonce": code_nonce, "commitment_verified": "verified",
    }
    with server_config(registration_code="SeCrEt"):
        wrong_code = post_form(code_session, "/register", code_form)
    assert wrong_code.status_code == 200, wrong_code.status_code
    assert "The registration code you entered was incorrect" in wrong_code.text
    assert count_users(fresh) == 0

    limit = int(db_sql("SELECT count(*) FROM users WHERE banned = false AND hidden = false").strip())
    with server_config(num_users=limit):
        capped = requests.get(f"{DOJO_URL}/register")
    assert capped.status_code == 403, capped.status_code
    assert "Reached the maximum number of users" in capped.text

    original_hash = password_hash(name)
    db_sql(f"UPDATE users SET password = NULL WHERE name = '{name}'")
    try:
        oauth_session = requests.Session()
        oauth_nonce = parse_csrf_token(oauth_session.get(f"{DOJO_URL}/login").text)
        oauth_login = post_form(oauth_session, "/login", {"name": name, "password": name, "nonce": oauth_nonce})
        assert oauth_login.status_code == 200, oauth_login.status_code
        assert "3rd party authentication provider" in oauth_login.text
    finally:
        db_sql(f"UPDATE users SET password = '{original_hash}' WHERE name = '{name}'")
