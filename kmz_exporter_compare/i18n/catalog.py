# -*- coding: utf-8 -*-
"""Language codes and translation tables.

Chinese source strings are the keys. EN, ES, FR and AR catalogs are filled in
catalog_data.py. IT, DE, JA and KO are filled in catalog_extra.py.
text_for() returns "" when a line is not translated yet. For non-Chinese UI,
tr() falls back to English, then to the Chinese source if English is missing too.
"""

LANG_ZH = "zh"
LANG_EN = "en"
LANG_ES = "es"
LANG_FR = "fr"
LANG_AR = "ar"
LANG_IT = "it"
LANG_DE = "de"
LANG_JA = "ja"
LANG_KO = "ko"

_LOCALE_PREFIX = (
    ("zh", LANG_ZH),
    ("es", LANG_ES),
    ("fr", LANG_FR),
    ("ar", LANG_AR),
    ("it", LANG_IT),
    ("de", LANG_DE),
    ("ja", LANG_JA),
    ("ko", LANG_KO),
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

from .catalog_extra import DE as DATA_DE
from .catalog_extra import IT as DATA_IT
from .catalog_extra import JA as DATA_JA
from .catalog_extra import KO as DATA_KO

EN = dict(DATA_EN)
EN.update(GAP_EN)
ES = dict(DATA_ES)
ES.update(GAP_ES)
FR = dict(DATA_FR)
FR.update(GAP_FR)
AR = dict(DATA_AR)
AR.update(GAP_AR)
IT = dict(DATA_IT)
DE = dict(DATA_DE)
JA = dict(DATA_JA)
KO = dict(DATA_KO)

_TABLES = {
    LANG_EN: EN,
    LANG_ES: ES,
    LANG_FR: FR,
    LANG_AR: AR,
    LANG_IT: IT,
    LANG_DE: DE,
    LANG_JA: JA,
    LANG_KO: KO,
}


def known_languages():
    return (LANG_EN, LANG_ZH, LANG_ES, LANG_FR, LANG_AR, LANG_IT, LANG_DE, LANG_JA, LANG_KO)


def detect_initial_language(qgis_locale=None, system_locale=None):
    """Prefer QGIS locale, then the system locale.

    A supported code (en / zh / es / fr / ar / it / de / ja / ko) is used as-is.
    Any other non-empty locale uses English.
    When both locales are empty or cannot be read, English is the fallback.
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
    return LANG_EN


def text_for(language, msgid):
    if language == LANG_ZH or not msgid:
        return ""
    table = _TABLES.get(language) or {}
    return table.get(msgid) or ""
