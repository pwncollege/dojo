import re
from urllib.parse import urlencode

from flask import g, has_request_context, request


DEFAULT_LANGUAGE = "en"

LANGUAGES = {
    "en": "English",
    "ko": "한국어",
}

LANGUAGE_COOKIE = "dojo_language"
LANGUAGE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60

LANGUAGE_PATTERN = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$"
LANGUAGE_RE = re.compile(LANGUAGE_PATTERN)

# Content the platform generates rather than the dojo author, but which is stored as dojo
# content and so needs translating the same way authored content does.
UI_STRINGS = {
    "challenges_header": {
        "ko": "챌린지",
    },
}


def normalize_language(language):
    if not isinstance(language, str):
        return None
    language = language.strip()
    if not LANGUAGE_RE.match(language.lower()):
        return None
    primary, *subtags = language.split("-")
    return "-".join([primary.lower(),
                     *(subtag.upper() if len(subtag) == 2 else subtag.title() for subtag in subtags)])


def language_candidates(language):
    language = normalize_language(language)
    if not language:
        return []
    subtags = language.split("-")
    return ["-".join(subtags[:length]) for length in range(len(subtags), 0, -1)]


def ui_string(key, language=None):
    translations = UI_STRINGS.get(key, {})
    for candidate in language_candidates(language or current_language()):
        if candidate in translations:
            return translations[candidate]
    return None


def ui_string_translations(key):
    return {language: {"content": content} for language, content in UI_STRINGS.get(key, {}).items()}


def selectable_language(language):
    for candidate in language_candidates(language):
        if candidate in LANGUAGES:
            return candidate
    return None


def _stored_language():
    from .models import UserPreferences
    from CTFd.utils.user import authed, get_current_user

    if not authed():
        return None
    user = get_current_user()
    if not user:
        return None
    preferences = UserPreferences.query.filter_by(user_id=user.id).first()
    return preferences.language if preferences else None


def _accept_language():
    for language, _ in request.accept_languages:
        selected = selectable_language(language)
        if selected:
            return selected
    return None


def select_language():
    sources = [
        lambda: request.args.get("lang"),
        _stored_language,
        lambda: request.cookies.get(LANGUAGE_COOKIE),
    ]
    for source in sources:
        selected = selectable_language(source())
        if selected:
            return selected
    return _accept_language() or DEFAULT_LANGUAGE


def language_switch_next():
    # a `lang` already in the URL would out-rank the cookie the switcher is about to set
    query = [(key, value) for key, value in request.args.items(multi=True) if key != "lang"]
    return request.path + ("?" + urlencode(query) if query else "")


def current_language():
    if not has_request_context():
        return DEFAULT_LANGUAGE
    if "language" not in g:
        g.language = select_language()
    return g.language


def init_language(app):
    @app.before_request
    def set_request_language():
        g.language = select_language()

    @app.context_processor
    def inject_language():
        return dict(current_language=current_language(),
                    languages=LANGUAGES,
                    language_switch_next=language_switch_next())
