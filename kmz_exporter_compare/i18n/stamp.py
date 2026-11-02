# -*- coding: utf-8 -*-
"""Mark Chinese UI text so a language change can refresh every page."""

import re

from qgis.PyQt.QtWidgets import QComboBox, QGroupBox, QPushButton, QTableWidget, QTreeWidget, QWidget

from . import tr

_HAN = re.compile(r"[\u4e00-\u9fff]")
_LAYER_COUNT = re.compile(r"^(.+?)（(\d+)层）$")


def translate_label(text):
    raw = str(text or "")
    match = _LAYER_COUNT.match(raw)
    if match:
        return tr("{0}（{1}层）").format(match.group(1), match.group(2))
    return tr(raw)


def _has_han(text):
    return bool(text) and bool(_HAN.search(str(text)))


def _widgets(root):
    found = [root]
    found.extend(root.findChildren(QWidget))
    return found


def stamp_tree(root):
    """Remember the Chinese source on each control. Safe to call once."""
    if root is None or root.property("i18nStamped"):
        return
    root.setProperty("i18nStamped", True)
    for widget in _widgets(root):
        if widget.objectName() == "dynamicText":
            continue
        if not widget.property("msgid") and hasattr(widget, "text") and hasattr(widget, "setText"):
            try:
                text = widget.text()
            except Exception:
                text = ""
            if isinstance(text, str) and _has_han(text) and widget.objectName() != "pathValue":
                widget.setProperty("msgid", text)
                widget.setText(tr(text))
            elif isinstance(text, str) and _has_han(text) and widget.objectName() == "pathValue":
                widget.setProperty("msgid", text)
                widget.setText(tr(text))
        if not widget.property("tip") and hasattr(widget, "toolTip"):
            tip = widget.toolTip() or ""
            if _has_han(tip):
                widget.setProperty("tip", tip)
                widget.setToolTip(tr(tip))
        if isinstance(widget, QGroupBox) and not widget.property("boxTitle"):
            box_title = widget.title() or ""
            if _has_han(box_title):
                widget.setProperty("boxTitle", box_title)
                widget.setTitle(tr(box_title))
        if not widget.property("titleMsgid") and hasattr(widget, "windowTitle"):
            title = widget.windowTitle() or ""
            if _has_han(title):
                widget.setProperty("titleMsgid", title)
                widget.setWindowTitle(tr(title))
        if isinstance(widget, QComboBox) and not widget.property("itemMsgids"):
            texts = [widget.itemText(i) for i in range(widget.count())]
            if any(_has_han(item) for item in texts):
                widget.setProperty("itemMsgids", texts)
                index = widget.currentIndex()
                widget.blockSignals(True)
                for row, source in enumerate(texts):
                    widget.setItemText(row, translate_label(source))
                if index >= 0:
                    widget.setCurrentIndex(index)
                widget.blockSignals(False)
        if isinstance(widget, QTreeWidget) and not widget.property("headerMsgids"):
            header = widget.headerItem()
            if header is not None:
                texts = [header.text(i) for i in range(widget.columnCount())]
                if any(_has_han(item) for item in texts):
                    widget.setProperty("headerMsgids", texts)
                    widget.setHeaderLabels([translate_label(item) for item in texts])
        if isinstance(widget, QTableWidget) and not widget.property("headerMsgids"):
            header = widget.horizontalHeaderItem
            texts = []
            for index in range(widget.columnCount()):
                item = header(index)
                texts.append(item.text() if item is not None else "")
            if any(_has_han(item) for item in texts):
                widget.setProperty("headerMsgids", texts)
                widget.setHorizontalHeaderLabels([translate_label(item) for item in texts])


def retranslate_tree(root):
    if root is None:
        return
    for widget in _widgets(root):
        if widget.objectName() == "dynamicText":
            continue
        if widget.objectName() == "pathValue":
            msgid = widget.property("msgid")
            if msgid and hasattr(widget, "text") and hasattr(widget, "setText"):
                current = widget.text()
                source = str(msgid)
                if current in (source, tr(source)):
                    widget.setText(tr(source))
            continue
        msgid = widget.property("msgid")
        if msgid and isinstance(widget, QPushButton):
            try:
                from ..button_marks import fit_button_label, plain_button_text, wrap_button_text

                full = plain_button_text(tr(str(msgid)))
                widget.setProperty("fullText", full)
                widget.setText(wrap_button_text(full))
                fit_button_label(widget)
            except Exception:  # nosec B110
                pass
        elif msgid and hasattr(widget, "setText"):
            try:
                widget.setText(translate_label(str(msgid)))
            except Exception:  # nosec B110
                pass
        tip = widget.property("tip")
        if tip and hasattr(widget, "setToolTip"):
            widget.setToolTip(tr(str(tip)))
        box_title = widget.property("boxTitle")
        if box_title and isinstance(widget, QGroupBox):
            widget.setTitle(tr(str(box_title)))
        title = widget.property("titleMsgid")
        if title and hasattr(widget, "setWindowTitle"):
            widget.setWindowTitle(tr(str(title)))
        items = widget.property("itemMsgids")
        if items and isinstance(widget, QComboBox):
            index = widget.currentIndex()
            widget.blockSignals(True)
            for row, source in enumerate(list(items)):
                if row < widget.count():
                    widget.setItemText(row, translate_label(str(source)))
            if index >= 0:
                widget.setCurrentIndex(index)
            widget.blockSignals(False)
        headers = widget.property("headerMsgids")
        if headers and isinstance(widget, QTreeWidget):
            widget.setHeaderLabels([translate_label(str(item)) for item in list(headers)])
        if headers and isinstance(widget, QTableWidget):
            widget.setHorizontalHeaderLabels([translate_label(str(item)) for item in list(headers)])
