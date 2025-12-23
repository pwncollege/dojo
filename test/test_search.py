import pytest

from utils import DOJO_HOST


def test_searchable_content(searchable_dojo, admin_session):
    search_url = f"http://{DOJO_HOST}/pwncollege_api/v1/search"

    cases = [
        # Matches in name only — verify name field
        ("searchable", lambda r: any("searchable dojo" in d["name"].lower() for d in r["dojos"])),
        ("hello", lambda r: any("hello module" in m["name"].lower() for m in r["modules"])),
        ("Apple Challenge", lambda r: any("apple challenge" in c["name"].lower() for c in r["challenges"])),

        # Matches in description — verify description contains the query
        ("search test content", lambda r: any("search test content" in (d.get("description") or "").lower() for d in r["dojos"])),
        ("search testing", lambda r: any("search testing" in (m.get("description") or "").lower() for m in r["modules"])),
        ("about apples", lambda r: any("about apples" in (c.get("description") or "").lower() for c in r["challenges"])),
    ]

    for query, validate in cases:
        response = admin_session.get(search_url, params={"q": query})
        assert response.status_code == 200, f"Request failed for query: {query}"
        data = response.json()
        assert data["success"]
        assert validate(data["results"]), f"No expected match found for query: {query}"


def test_search_no_results(admin_session):
    search_url = f"http://{DOJO_HOST}/pwncollege_api/v1/search"
    query = "qwertyuiopasdfgh"  # something unlikely to match anything

    response = admin_session.get(search_url, params={"q": query})
    assert response.status_code == 200
    data = response.json()

    assert data["success"]
    assert not data["results"]["dojos"], "Expected no dojo matches"
    assert not data["results"]["modules"], "Expected no module matches"
    assert not data["results"]["challenges"], "Expected no challenge matches"


def test_search_returns_description_for_client_snippets(searchable_xss_dojo, admin_session):
    search_url = f"{DOJO_URL}/pwncollege_api/v1/search"
    response = admin_session.get(search_url, params={"q": "search"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"]

    descriptions = [
        *(item.get("description") for item in data["results"]["dojos"]),
        *(item.get("description") for item in data["results"]["modules"]),
        *(item.get("description") for item in data["results"]["challenges"]),
    ]
    descriptions = [description for description in descriptions if description]
    assert descriptions
    assert any("<img" in description for description in descriptions)
    assert any("<script" in description for description in descriptions)
    assert any("<svg" in description for description in descriptions)
