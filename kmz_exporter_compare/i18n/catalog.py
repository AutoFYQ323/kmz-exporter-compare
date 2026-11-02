# -*- coding: utf-8 -*-
"""Language codes and translation tables.

Chinese source strings are the keys. EN, ES, FR and AR catalogs are filled in
catalog_data.py. text_for() returns "" when a line is not translated yet,
and tr() keeps the Chinese source.
"""

LANG_ZH = "zh"
LANG_EN = "en"
LANG_ES = "es"
LANG_FR = "fr"
LANG_AR = "ar"

_LOCALE_PREFIX = (
    ("zh", LANG_ZH),
    ("es", LANG_ES),
    ("fr", LANG_FR),
    ("ar", LANG_AR),
    ("en", LANG_EN),
)

from .catalog_data import AR as DATA_AR
from .catalog_data import EN as DATA_EN
from .catalog_data import ES as DATA_ES
from .catalog_data import FR as DATA_FR

try:
    from .catalog_gap import AR as GAP_AR
    from .catalog_gap import EN as GAP_EN
    from .catalog_gap import ES as GAP_ES
    from .catalog_gap import FR as GAP_FR
except ImportError:
    GAP_EN = GAP_ES = GAP_FR = GAP_AR = {}

EN = dict(DATA_EN)
EN.update(GAP_EN)
ES = dict(DATA_ES)
ES.update(GAP_ES)
FR = dict(DATA_FR)
FR.update(GAP_FR)
AR = dict(DATA_AR)
AR.update(GAP_AR)

_TABLES = {
    LANG_EN: EN,
    LANG_ES: ES,
    LANG_FR: FR,
    LANG_AR: AR,
}


def known_languages():
    return (LANG_ZH, LANG_EN, LANG_ES, LANG_FR, LANG_AR)


def detect_initial_language(qgis_locale=None, system_locale=None):
    """Prefer QGIS locale, then the system locale.

    A supported code (zh / en / es / fr / ar) is used as-is.
    Any other non-empty locale, such as German, uses English.
    When both locales are empty, Chinese is the fallback.
    """
    saw = False
    for raw in (qgis_locale, system_locale):
        text = str(raw or "").strip().lower().replace("_", "-")
        if not text:
            continue
        saw = True
        primary = text.split("-", 1)[0]
        for prefix, lang in _LOCALE_PREFIX:
            if primary == prefix:
                return lang
        return LANG_EN
    return LANG_ZH if not saw else LANG_EN


def text_for(language, msgid):
    if language == LANG_ZH or not msgid:
        return ""
    table = _TABLES.get(language) or {}
    return table.get(msgid) or ""
