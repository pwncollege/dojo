import requests
import pytest
import string

UNAUTHENTICATED_URLS = ["/", "/dojos", "/login", "/register"]
HOST="localhost.pwn.college"
PROTO="http"

def hexstring(text, length=64):
    all_strings = [ w for w in text.split('"') if len(w) == length and set(w).issubset(set(string.hexdigits)) ]
    assert len(set(all_strings)) == 1
    return all_strings[0]

def login(username="admin", password="admin", success=True):
    s = requests.Session()
    nonce = hexstring(s.get(f"{PROTO}://{HOST}/login").text)
    r = s.post(f"{PROTO}://{HOST}/login", data={
        "name": username, "password": password, "_submit": "Submit", "nonce": nonce
    })
    assert r.reason == "OK"
    assert "incorrect" not in r.text or not success
    s.headers["CSRF-Token"] = hexstring(r.text)
    return s

@pytest.mark.parametrize("endpoint", UNAUTHENTICATED_URLS)
def test_unauthenticated_return_200(endpoint):
    response = requests.get(f"{PROTO}://{HOST}{endpoint}")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"

def test_login():
    unauth = login("admen", "admen", success=False)
    assert "Admin Panel" not in unauth.get(f"{PROTO}://{HOST}").text
    authed = login("admin", "admin")
    assert "Admin Panel" in authed.get(f"{PROTO}://{HOST}").text

def test_create_dojo():
    s = login("admin", "admin")
    r = s.post(
        "http://localhost.pwn.college/pwncollege_api/v1/dojo/create",
        json={ "repository": "pwncollege/example-dojo", "public_key": "", "private_key": "" }
    )
    assert r.reason == "OK"
