import pytest

from utils import DOJO_URL, db_sql, get_user_id, login
from test_accounts import account_case, rand_name, second_user


def patch_me(session, **body):
    return session.patch(f"{DOJO_URL}/pwncollege_api/v1/users/me", json=body)


def user_column(user_id, column):
    return db_sql(f"SELECT {column} FROM users WHERE id = {user_id}").strip()


def test_profile_email_change_requires_current_password(random_user):
    name, session = random_user
    user_id = get_user_id(name)
    new_email = f"{rand_name()}@example.com"

    response = patch_me(session, email=new_email)
    assert response.status_code == 400, response.text
    assert response.json()["errors"] == {"confirm": ["Please confirm your current password"]}
    assert user_column(user_id, "email") == f"{name}@example.com"

    response = patch_me(session, email=new_email, confirm="wrong")
    assert response.status_code == 400, response.text
    assert response.json()["errors"] == {"confirm": ["Your previous password is incorrect"]}
    assert user_column(user_id, "email") == f"{name}@example.com"

    response = patch_me(session, email=new_email, confirm=name)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["email"] == new_email
    assert user_column(user_id, "email") == new_email


def test_profile_password_change_requires_current_password(random_user):
    name, session = random_user
    user_id = get_user_id(name)
    new_password = "newpw-xyz"
    original_hash = user_column(user_id, "password")

    response = patch_me(session, password=new_password)
    assert response.status_code == 400, response.text
    assert response.json()["errors"] == {"confirm": ["Please confirm your current password"]}

    response = patch_me(session, password=new_password, confirm="wrong")
    assert response.status_code == 400, response.text
    assert response.json()["errors"] == {"confirm": ["Your previous password is incorrect"]}
    assert user_column(user_id, "password") == original_hash

    response = patch_me(session, password=new_password, confirm=name)
    assert response.status_code == 200, response.text
    assert user_column(user_id, "password") != original_hash

    new_session = login(name, new_password)
    assert new_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()["name"] == name
    login(name, name, success=False)


def test_profile_name_must_be_unique(random_user, second_user):
    name, session = random_user
    other_name, _ = second_user

    response = patch_me(session, name=other_name)
    assert response.status_code == 400, response.text
    assert response.json()["errors"] == {"name": ["User name has already been taken"]}
    assert user_column(get_user_id(name), "name") == name


@pytest.mark.parametrize("body,error_key,column", [
    ({"website": "ftp://x"}, "website", "website"),
    ({"country": "ZZ"}, "country", "country"),
    ({"affiliation": "a" * 129}, "affiliation", "affiliation"),
    ({"hidden": "maybe"}, "hidden", "hidden"),
    ({"name": 5}, "name", "name"),
    ({"email": 5}, "email", "email"),
    ({"password": "new", "confirm": 5}, "confirm", "password"),
])
def test_profile_field_validation(random_user, body, error_key, column):
    name, session = random_user
    user_id = get_user_id(name)
    original = user_column(user_id, column)

    response = patch_me(session, **body)
    assert response.status_code == 400, response.text
    assert error_key in response.json()["errors"], response.json()
    assert user_column(user_id, column) == original


def test_profile_rejects_non_object_body(random_user):
    _, session = random_user
    response = session.patch(f"{DOJO_URL}/pwncollege_api/v1/users/me", json=["not", "an", "object"])
    assert response.status_code == 400, response.text
    assert response.json()["errors"] == {"_schema": ["Invalid input type."]}


def test_admin_profile_patch_skips_confirmation(admin_session):
    original_email = db_sql("SELECT email FROM users WHERE name = 'admin'").strip()
    temporary_email = f"{rand_name()}@example.com"

    try:
        response = admin_session.patch(f"{DOJO_URL}/pwncollege_api/v1/users/me", json={"email": temporary_email})
        assert response.status_code == 200, response.text
        assert db_sql("SELECT email FROM users WHERE name = 'admin'").strip() == temporary_email
    finally:
        restored = admin_session.patch(f"{DOJO_URL}/pwncollege_api/v1/users/me", json={"email": original_email})
        assert restored.status_code == 200, restored.text
        assert db_sql("SELECT email FROM users WHERE name = 'admin'").strip() == original_email


def test_profile_name_changes_disabled(random_user):
    name, session = random_user
    user_id = get_user_id(name)
    new_name = rand_name()

    account_case(session, f"""
        from dojo_plugin import models
        from dojo_plugin.api.v1 import user as user_api

        real_get_config = models.get_config
        name_changes_disabled = lambda key, *args, **kwargs: False if key == "name_changes" else real_get_config(key, *args, **kwargs)
        with patch.object(user_api, "get_config", side_effect=name_changes_disabled):
            response = client.patch("/pwncollege_api/v1/users/me", json={{"name": {new_name!r}}})
        assert response.status_code == 400, response.get_data(as_text=True)
        assert response.get_json()["errors"] == {{"name": ["Name changes are disabled"]}}, response.get_json()
    """)
    assert user_column(user_id, "name") == name
