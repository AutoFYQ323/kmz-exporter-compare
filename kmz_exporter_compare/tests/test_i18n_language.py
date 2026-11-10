# -*- coding: utf-8 -*-
import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
I18N = ROOT / "i18n"


def _load_catalog():
    pkg = types.ModuleType("i18n")
    pkg.__path__ = [str(I18N)]
    sys.modules.setdefault("i18n", pkg)

    def _one(name):
        path = I18N / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"i18n.{name}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"i18n.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod

    _one("catalog_data")
    _one("catalog_gap")
    _one("catalog_extra")
    return _one("catalog")


_catalog = _load_catalog()
LANG_EN = _catalog.LANG_EN
LANG_ES = _catalog.LANG_ES
LANG_ZH = _catalog.LANG_ZH
detect_initial_language = _catalog.detect_initial_language
text_for = _catalog.text_for


def text_in(language, msgid):
    text = msgid if isinstance(msgid, str) else str(msgid)
    if language in (LANG_ZH, "", None):
        return text
    mapped = text_for(language, text)
    if mapped:
        return mapped
    return text_for(LANG_EN, text) or text


class TestDetectInitialLanguage(unittest.TestCase):
    def test_both_empty_defaults_english(self):
        self.assertEqual(detect_initial_language("", ""), LANG_EN)
        self.assertEqual(detect_initial_language(None, None), LANG_EN)

    def test_unsupported_locale_defaults_english(self):
        self.assertEqual(detect_initial_language("pt_BR", ""), LANG_EN)

    def test_chinese_locale(self):
        self.assertEqual(detect_initial_language("zh_CN", ""), LANG_ZH)


class TestTranslationFallback(unittest.TestCase):
    def test_known_key_not_shown_in_chinese_for_spanish(self):
        mapped = text_in(LANG_ES, "默认样式")
        self.assertNotEqual(mapped, "默认样式")
        self.assertTrue(mapped)

    def test_chinese_stays_source(self):
        self.assertEqual(text_in(LANG_ZH, "默认样式"), "默认样式")


if __name__ == "__main__":
    unittest.main()
