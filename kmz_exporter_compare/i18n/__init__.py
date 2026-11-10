# -*- coding: utf-8 -*-
"""UI strings. Chinese is the source text.

Nine languages: en, zh, es, fr, ar, it, de, ja, ko.
Non-Chinese UI falls back to English when a line has no translation.
Do not hard-code labels in dialogs; call tr() so a language menu can be added
without rewriting the windows. Language names in the menu are endonyms and
are not passed through tr().
"""

from qgis.PyQt.QtCore import QLocale, QObject, QSettings, pyqtSignal

from .catalog import (
    LANG_AR,
    LANG_DE,
    LANG_EN,
    LANG_ES,
    LANG_FR,
    LANG_IT,
    LANG_JA,
    LANG_KO,
    LANG_ZH,
    detect_initial_language,
    known_languages,
    text_for,
)

_SETTINGS = "KMZExporterCompare/ui_language"
_hub = None


class LanguageHub(QObject):
    changed = pyqtSignal(str)


def hub():
    global _hub
    if _hub is None:
        _hub = LanguageHub()
    return _hub


def language_changed():
    return hub().changed


def _stored():
    try:
        return str(QSettings().value(_SETTINGS, "") or "").strip().lower()
    except Exception:
        return ""


def current_language():
    stored = _stored()
    if stored in known_languages():
        return stored
    qloc = ""
    try:
        from qgis.core import QgsApplication

        qloc = QgsApplication.locale() or ""
    except Exception:
        qloc = ""
    try:
        sysloc = QLocale.system().name()
    except Exception:
        sysloc = ""
    lang = detect_initial_language(qloc, sysloc)
    try:
        QSettings().setValue(_SETTINGS, lang)
    except Exception:  # nosec B110
        pass
    return lang


def set_language(lang):
    text = str(lang or "").strip().lower().replace("_", "-")
    primary = text.split("-", 1)[0]
    if primary not in known_languages():
        primary = LANG_EN
    try:
        QSettings().setValue(_SETTINGS, primary)
    except Exception:  # nosec B110
        pass
    hub().changed.emit(primary)
    return primary


def _resolved_text(language, msgid):
    text = msgid if isinstance(msgid, str) else str(msgid)
    if language in (LANG_ZH, "", None):
        return text
    mapped = text_for(language, text)
    if mapped:
        return mapped
    return text_for(LANG_EN, text) or text


def text_in(language, msgid):
    """Return msgid in language. Non-Chinese falls back to English."""
    return _resolved_text(language, msgid)


def tr(msgid, *args, **kwargs):
    text = _resolved_text(current_language(), msgid if isinstance(msgid, str) else str(msgid))
    if args or kwargs:
        try:
            text = text % (args if args else kwargs) if args else text % kwargs
        except Exception:  # nosec B110
            pass
    return text


def localize_button_box(box):
    if box is None:
        return box
    try:
        from qgis.PyQt.QtWidgets import QDialogButtonBox
    except Exception:
        return box
    mapping = (
        (QDialogButtonBox.StandardButton.Ok, "确定"),
        (QDialogButtonBox.StandardButton.Cancel, "取消"),
        (QDialogButtonBox.StandardButton.Close, "关闭"),
        (QDialogButtonBox.StandardButton.Yes, "是"),
        (QDialogButtonBox.StandardButton.No, "否"),
    )
    for flag, msgid in mapping:
        try:
            button = box.button(flag)
        except Exception:
            button = None
        if button is not None:
            button.setText(tr(msgid))
    return box


__all__ = [
    "LANG_AR",
    "LANG_DE",
    "LANG_EN",
    "LANG_ES",
    "LANG_FR",
    "LANG_IT",
    "LANG_JA",
    "LANG_KO",
    "LANG_ZH",
    "current_language",
    "known_languages",
    "language_changed",
    "localize_button_box",
    "set_language",
    "text_in",
    "tr",
]
