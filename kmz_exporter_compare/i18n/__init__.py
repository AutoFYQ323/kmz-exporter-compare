# -*- coding: utf-8 -*-
"""UI strings. Chinese is the source text. Other languages are filled in later.

Five languages, matching Field Remarks Table: zh, en, es, fr, ar.
Other languages are in catalog_data.py; untranslated lines still show Chinese.
Do not hard-code labels in dialogs; call tr() so a language menu can be added
without rewriting the windows.
"""

from qgis.PyQt.QtCore import QLocale, QObject, QSettings, pyqtSignal

from .catalog import (
    LANG_AR,
    LANG_EN,
    LANG_ES,
    LANG_FR,
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
    except Exception:
        pass
    return lang


def set_language(lang):
    text = str(lang or "").strip().lower().replace("_", "-")
    primary = text.split("-", 1)[0]
    if primary not in known_languages():
        primary = LANG_ZH
    try:
        QSettings().setValue(_SETTINGS, primary)
    except Exception:
        pass
    hub().changed.emit(primary)
    return primary


def tr(msgid, *args, **kwargs):
    text = msgid if isinstance(msgid, str) else str(msgid)
    mapped = text_for(current_language(), text)
    if mapped:
        text = mapped
    if args or kwargs:
        try:
            text = text % (args if args else kwargs) if args else text % kwargs
        except Exception:
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
        (QDialogButtonBox.Ok, "确定"),
        (QDialogButtonBox.Cancel, "取消"),
        (QDialogButtonBox.Close, "关闭"),
        (QDialogButtonBox.Yes, "是"),
        (QDialogButtonBox.No, "否"),
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
    "LANG_EN",
    "LANG_ES",
    "LANG_FR",
    "LANG_ZH",
    "current_language",
    "language_changed",
    "localize_button_box",
    "set_language",
    "tr",
]
