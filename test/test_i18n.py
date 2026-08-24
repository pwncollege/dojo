import random
import string

import pytest
import requests

from utils import (DOJO_URL, TEST_DOJOS_LOCATION, create_dojo_yml, login,
                   make_dojo_official, parse_csrf_token)


@pytest.fixture(scope="session")
def i18n_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "i18n_dojo.yml").read(), session=admin_session)


@pytest.fixture(scope="session")
def i18n_import_dojo(admin_session, i18n_dojo):
    make_dojo_official(i18n_dojo, admin_session)
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "i18n_import_dojo.yml").read(), session=admin_session)


def module_page(session, dojo, language=None):
    params = {"lang": language} if language else {}
    response = session.get(f"{DOJO_URL}/{dojo}/translated/", params=params)
    assert response.status_code == 200
    return response.text


def switch_language(session, language, next_url="/"):
    nonce = parse_csrf_token(session.get(f"{DOJO_URL}/").text)
    return session.post(f"{DOJO_URL}/language",
                        data={"language": language, "next": next_url, "nonce": nonce},
                        allow_redirects=False)


def test_dojo_page_uses_query_language(i18n_dojo, admin_session):
    korean = admin_session.get(f"{DOJO_URL}/{i18n_dojo}/", params={"lang": "ko"}).text
    assert "국제화 시험 도장" in korean
    assert "DOJODESC_KO" in korean
    assert "DOJODESC_EN" not in korean

    english = admin_session.get(f"{DOJO_URL}/{i18n_dojo}/", params={"lang": "en"}).text
    assert "I18n Test Dojo" in english
    assert "DOJODESC_EN" in english
    assert "DOJODESC_KO" not in english


def test_module_page_translates_every_level(i18n_dojo, admin_session):
    korean = module_page(admin_session, i18n_dojo, "ko")
    for expected in ["번역된 모듈", "MODDESC_KO", "한국어 자료 이름", "RESOURCE_KO",
                     "한국어 헤더", "번역된 챌린지", "CHALDESC_KO"]:
        assert expected in korean, f"missing translation: {expected}"
    for unexpected in ["MODDESC_EN", "RESOURCE_EN", "CHALDESC_EN", "English Header"]:
        assert unexpected not in korean, f"untranslated leftover: {unexpected}"


def test_untranslated_content_falls_back(i18n_dojo, admin_session):
    korean = module_page(admin_session, i18n_dojo, "ko")
    assert "Untranslated Challenge" in korean
    assert "UNTRANSLATED_EN" in korean


def test_unsupported_language_falls_back_to_source(i18n_dojo, admin_session):
    page = module_page(admin_session, i18n_dojo, "xx")
    assert "MODDESC_EN" in page
    assert "MODDESC_KO" not in page


def test_html_lang_attribute(i18n_dojo, admin_session):
    assert '<html lang="ko">' in module_page(admin_session, i18n_dojo, "ko")
    assert '<html lang="en">' in module_page(admin_session, i18n_dojo, "en")


def test_language_switcher_rendered(i18n_dojo):
    anonymous = requests.Session()
    page = anonymous.get(f"{DOJO_URL}/").text
    assert 'class="nav-item dropdown language-switcher"' in page
    for code, label in [("en", "English"), ("ko", "한국어"), ("zh-CN", "简体中文"),
                        ("zh-TW", "繁體中文"), ("it", "Italiano")]:
        assert f'value="{code}"' in page, f"switcher is missing {code}"
        assert label in page, f"switcher is missing the label for {code}"


def test_browser_language_variants_resolve_to_an_offered_language(i18n_dojo, admin_session):
    for tag, expected in [("zh-Hans-CN", "zh-CN"), ("zh", "zh-CN"), ("zh-SG", "zh-CN"),
                          ("zh-Hant-TW", "zh-TW"), ("zh-HK", "zh-TW"),
                          ("it-CH", "it"), ("ko-KR", "ko"), ("fr", "en")]:
        page = admin_session.get(f"{DOJO_URL}/{i18n_dojo}/", params={"lang": tag}).text
        assert f'<html lang="{expected}">' in page, f"{tag} did not resolve to {expected}"


def test_switcher_sets_cookie_and_sticks(i18n_dojo, admin_session):
    session = requests.Session()
    response = switch_language(session, "ko", f"/{i18n_dojo}/translated/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/{i18n_dojo}/translated/")
    assert session.cookies.get("dojo_language") == "ko"

    assert "MODDESC_KO" in module_page(session, i18n_dojo)

    switch_language(session, "en")
    assert "MODDESC_EN" in module_page(session, i18n_dojo)


def test_switcher_ignores_unsupported_language(i18n_dojo):
    session = requests.Session()
    response = switch_language(session, "xx")
    assert response.status_code == 302
    assert session.cookies.get("dojo_language") is None


def test_switcher_rejects_offsite_next(i18n_dojo):
    session = requests.Session()
    for target in ["https://example.com/evil", "//example.com/evil", "/\\example.com"]:
        response = switch_language(session, "ko", target)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/"), f"redirected off-site for {target}"


def test_language_is_per_session_not_per_account(i18n_dojo):
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(name, name, register=True)
    switch_language(session, "ko")
    assert "MODDESC_KO" in module_page(session, i18n_dojo)

    fresh = login(name, name)
    assert fresh.cookies.get("dojo_language") is None
    assert "MODDESC_EN" in module_page(fresh, i18n_dojo)


def test_accept_language_header_is_honored(i18n_dojo):
    session = requests.Session()
    session.headers["Accept-Language"] = "ko-KR,ko;q=0.9,en;q=0.8"
    assert "MODDESC_KO" in module_page(session, i18n_dojo)

    session.headers["Accept-Language"] = "fr-FR,fr;q=0.9"
    assert "MODDESC_EN" in module_page(session, i18n_dojo)


def test_api_returns_localized_content(i18n_dojo, admin_session):
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{i18n_dojo}/modules"

    modules = admin_session.get(url, params={"lang": "ko"}).json()["modules"]
    module = next(m for m in modules if m["id"] == "translated")
    assert module["name"] == "번역된 모듈"
    assert "MODDESC_KO" in module["description"]
    assert any("CHALDESC_KO" in (c["description"] or "") for c in module["challenges"])

    modules = admin_session.get(url, params={"lang": "en"}).json()["modules"]
    module = next(m for m in modules if m["id"] == "translated")
    assert module["name"] == "Translated Module"
    assert "MODDESC_EN" in module["description"]


def test_search_matches_translations(i18n_dojo, admin_session):
    url = f"{DOJO_URL}/pwncollege_api/v1/search"

    results = admin_session.get(url, params={"q": "MODDESC_KO", "lang": "ko"}).json()["results"]
    assert any(m["name"] == "번역된 모듈" for m in results["modules"])

    results = admin_session.get(url, params={"q": "MODDESC_KO", "lang": "en"}).json()["results"]
    assert not results["modules"], "English search should not match Korean translations"


def test_import_inherits_translations(i18n_import_dojo, admin_session):
    korean = admin_session.get(f"{DOJO_URL}/{i18n_import_dojo}/reimporting/",
                               params={"lang": "ko"}).text
    assert "번역된 챌린지" in korean, "an import with no local translation should inherit the source's"
    assert "CHALDESC_KO" in korean, "an import should inherit the source's translated description"


def test_local_translation_does_not_discard_inherited_fields(i18n_import_dojo, admin_session):
    korean = admin_session.get(f"{DOJO_URL}/{i18n_import_dojo}/reimporting/",
                               params={"lang": "ko"}).text
    assert "이름을 바꾼 챌린지" in korean, "a local translated name should win over the inherited one"
    assert korean.count("CHALDESC_KO") == 2, (
        "translating only the name must not discard the inherited translated description")
    assert "CHALDESC_EN" not in korean


def main_content(text):
    return text.split('<main role="main">', 1)[1].split("</main>", 1)[0]


def test_untranslated_dojo_is_unaffected(example_dojo, admin_session):
    english = admin_session.get(f"{DOJO_URL}/{example_dojo}/", params={"lang": "en"}).text
    korean = admin_session.get(f"{DOJO_URL}/{example_dojo}/", params={"lang": "ko"}).text
    assert main_content(english) == main_content(korean)
