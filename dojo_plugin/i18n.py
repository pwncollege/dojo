import re

from flask import g, has_request_context, request


DEFAULT_LANGUAGE = "en"

LANGUAGES = {
    "en": "English",
    "ko": "한국어",
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
    "it": "Italiano",
}

# Browsers name Chinese by script (`zh-Hans`) or generically (`zh`) as often as they name
# it by region, and none of those truncate down to a tag offered above.
LANGUAGE_ALIASES = {
    "zh": "zh-CN",
    "zh-Hans": "zh-CN",
    "zh-SG": "zh-CN",
    "zh-Hant": "zh-TW",
    "zh-HK": "zh-TW",
    "zh-MO": "zh-TW",
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
        "zh-CN": "挑战",
        "zh-TW": "挑戰",
        "it": "Sfide",
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
        if candidate in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[candidate]
    return None


def _accept_language():
    for language, _ in request.accept_languages:
        selected = selectable_language(language)
        if selected:
            return selected
    return None


def select_language():
    for source in [request.args.get("lang"), request.cookies.get(LANGUAGE_COOKIE)]:
        selected = selectable_language(source)
        if selected:
            return selected
    return _accept_language() or DEFAULT_LANGUAGE


def language_switch_next():
    if not has_request_context():
        return "/"
    # The path only. This renders into every page's navbar, error pages included, so
    # echoing the query string back would make two error responses differ by whatever the
    # caller passed. Dropping it also drops any `lang`, which would otherwise out-rank the
    # cookie the switcher is about to set.
    return request.path


def current_language():
    if not has_request_context():
        return DEFAULT_LANGUAGE
    if "language" not in g:
        g.language = select_language()
    return g.language


def init_language(app):
    @app.context_processor
    def inject_language():
        return dict(current_language=current_language(),
                    languages=LANGUAGES,
                    language_switch_next=language_switch_next())
