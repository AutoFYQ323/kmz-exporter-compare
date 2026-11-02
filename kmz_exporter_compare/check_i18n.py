# -*- coding: utf-8 -*-
"""Fail when a visible string has no English, Spanish, French, or Arabic line.

Same idea as the Super Attribute Table check: every tr() key must exist in all
four catalogs, and the placeholders must match. Chinese literals on the job
pages must be catalog keys too, so a language switch does not leave Chinese on
screen.

    python check_i18n.py
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP = {"__pycache__", "tests", "catalog_data.py", "catalog_gap.py", "catalog.py", "check_i18n.py"}
UI_FILES = {
    "origin_export.py",
    "origin_pages.py",
    "origin_style_map.py",
    "dialog.py",
    "layer_ops.py",
    "help_dialog.py",
    "plugin.py",
    "button_marks.py",
}
_HAN = re.compile(r"[\u4e00-\u9fff]")
_BRACE = re.compile(r"\{[^{}]*\}")


def _load(name):
    import importlib.util

    path = ROOT / "i18n" / name
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalogs():
    data = _load("catalog_data.py")
    gap = _load("catalog_gap.py")
    en, es, fr, ar = dict(data.EN), dict(data.ES), dict(data.FR), dict(data.AR)
    en.update(gap.EN)
    es.update(gap.ES)
    fr.update(gap.FR)
    ar.update(gap.AR)
    return en, es, fr, ar


def _docstrings(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                found.add(doc)
    return found


def _tr_strings(tree):
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "tr":
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            found.append(arg.value)
    return found


def _ui_literals(tree):
    docs = _docstrings(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        text = node.value
        if text in docs or len(text) <= 1 or text.startswith("_") or "\\" in text or ".*" in text or not _HAN.search(text):
            continue
        found.append(text)
    return found


def main():
    en, es, fr, ar = _catalogs()
    catalogs = (("en", en), ("es", es), ("fr", fr), ("ar", ar))
    missing = []
    bad_place = []
    seen = set()
    for path in ROOT.rglob("*.py"):
        if SKIP.intersection(path.parts) or path.name in SKIP:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        keys = list(_tr_strings(tree))
        if path.name in UI_FILES:
            keys.extend(_ui_literals(tree))
        for text in keys:
            mark = (path.name, text)
            if mark in seen:
                continue
            seen.add(mark)
            absent = [name for name, table in catalogs if text not in table]
            if absent:
                missing.append("{0} [{1}]: {2}".format(path.name, ",".join(absent), text[:140]))
                continue
            origin = _BRACE.findall(text)
            for name, table in catalogs:
                if _BRACE.findall(table[text]) != origin:
                    bad_place.append("{0} {1}: {2}".format(path.name, name, text[:80]))
    if missing or bad_place:
        print("Missing translations: {0}".format(len(missing)))
        for line in missing:
            print(line)
        if bad_place:
            print("Placeholder mismatch: {0}".format(len(bad_place)))
            for line in bad_place:
                print(line)
        return 1
    print("i18n ok: {0} English entries".format(len(en)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
