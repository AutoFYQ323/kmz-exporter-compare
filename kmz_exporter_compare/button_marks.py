# -*- coding: utf-8 -*-
"""Colored square icons for push buttons (same family as the home action list)."""

from qgis.PyQt.QtCore import QSize

from .icons import glyph_icon, letter_icon

# kind, background color
MARKS = {
    "home": ("home", "#607d8b"),
    "cancel": ("cancel", "#c62828"),
    "ok": ("save", "#2e7d32"),
    "export": ("export", "#1565c0"),
    "export_kmz": ("export", "#0d47a1"),
    "select": ("folder", "#2e7d32"),
    "run": ("run", "#43a047"),
    "compare": ("compare", "#6a1b9a"),
    "copy": ("copy", "#ef6c00"),
    "report": ("doc", "#455a64"),
    "refresh": ("refresh", "#00897b"),
    "match": ("link", "#1565c0"),
    "field": ("field", "#5d4037"),
    "toggle": ("select_all", "#546e7a"),
    "import_file": ("folder", "#1565c0"),
    "import_mode": ("import_mode", "#2e7d32"),
    "qgis_mode": ("qgis_mode", "#1565c0"),
    "reset": ("reset", "#6d4c41"),
    "auto": ("auto", "#1976d2"),
    "matched": ("matched", "#2e7d32"),
    "unmatched": ("unmatched", "#ef6c00"),
    "all": ("all", "#546e7a"),
    "point": ("point", "#1565c0"),
    "line": ("line", "#ef6c00"),
    "polygon": ("polygon", "#6a1b9a"),
    "manual": ("pencil", "#1565c0"),
    "trash": ("trash", "#c62828"),
    "pencil": ("pencil", "#1565c0"),
    "save": ("save", "#2e7d32"),
    "empty": ("empty", "#ef6c00"),
    "layer_copy": ("copy", "#6a1b9a"),
    "hub_export": ("export", "#2e7d32"),
    "hub_manual": ("pencil", "#1565c0"),
    "hub_auto": ("auto", "#1976d2"),
    "hub_coords": ("compare", "#6a1b9a"),
    "hub_names": ("doc", "#455a64"),
}

TEXT_TO_MARK = {
    "确定": "ok",
    "取消": "cancel",
    "返回主页面": "home",
    "全选/全不选": "toggle",
    "全选": "toggle",
    "全不选": "toggle",
    "导出KMZ": "export_kmz",
    "导出KMZ/KML": "export_kmz",
    "字段": "field",
    "复制结果": "copy",
    "复制表格": "copy",
    "复制详情": "copy",
    "导出报告": "report",
    "选择 KMZ 文件": "select",
    "选择 KML / KMZ": "select",
    "选择源图层": "select",
    "选择参考图层": "select",
    "开始对比": "compare",
    "批量运行对比": "run",
    "执行替换": "manual",
    "执行替换并导出（输出图层）": "export",
    "自动匹配": "match",
    "刷新图层": "refresh",
    "已匹配": "matched",
    "未匹配": "unmatched",
    "导入 KML / KMZ": "import_mode",
    "在 QGIS 选择": "qgis_mode",
    "全部": "all",
    "点": "point",
    "线": "line",
    "面": "polygon",
    "恢复默认窗口": "reset",
}


def mark_icon(mark_key, size=18):
    spec = MARKS.get(mark_key)
    if not spec:
        return letter_icon(str(mark_key)[:1].upper(), "#607d8b", size)
    kind, color = spec
    return glyph_icon(kind, color, size)


def decorate_button(button, mark_key=None, text=None):
    key = mark_key or TEXT_TO_MARK.get(text or button.text())
    if not key:
        return button
    button.setIcon(mark_icon(key, 18))
    button.setIconSize(QSize(18, 18))
    return button


def plain_button_text(text):
    return " ".join(str(text or "").replace("\n", " ").split())


def wrap_button_text(text):
    """Two-line fallback used before the button knows its width."""
    raw = plain_button_text(text)
    if not raw:
        return ""
    if " / " in raw:
        left, right = raw.split(" / ", 1)
        if left.strip() and right.strip():
            return left.strip() + "\n" + right.strip()
    if "/" in raw and " / " not in raw:
        left, right = raw.split("/", 1)
        if left.strip() and right.strip() and len(raw) >= 6:
            return left.strip() + "\n" + right.strip()
    if " " not in raw or len(raw) <= 18:
        return raw
    split_at = None
    mid = len(raw) // 2
    for index, char in enumerate(raw):
        if char == " " and 4 <= index <= len(raw) - 4:
            if split_at is None or abs(index - mid) < abs(split_at - mid):
                split_at = index
    if not split_at:
        return raw
    left = raw[:split_at].strip()
    right = raw[split_at:].strip()
    if not left or not right:
        return raw
    return left + "\n" + right


def _text_width(metrics, text):
    if hasattr(metrics, "horizontalAdvance"):
        return metrics.horizontalAdvance(text)
    return metrics.boundingRect(text).width()


def _line_pairs(text):
    pairs = []
    seen = set()

    def add(left, right):
        left = left.strip().strip("/")
        right = right.strip().strip("/")
        if not left or not right:
            return
        key = (left, right)
        if key in seen:
            return
        seen.add(key)
        pairs.append(key)

    if " / " in text:
        cut = text.find(" / ")
        add(text[:cut], text[cut + 3:])
    if "/" in text:
        cut = text.find("/")
        add(text[:cut], text[cut + 1:])
    for index, char in enumerate(text):
        if char == " " and 0 < index < len(text) - 1:
            add(text[:index], text[index + 1:])
    return pairs


def split_to_width(text, metrics, avail):
    """Keep one line when it fits. Otherwise break at / or a space."""
    raw = plain_button_text(text)
    if not raw or avail < 24:
        return wrap_button_text(raw)
    if _text_width(metrics, raw) <= avail:
        return raw
    best = None
    best_score = None
    for left, right in _line_pairs(raw):
        overflow = max(0, _text_width(metrics, left) - avail) + max(0, _text_width(metrics, right) - avail)
        balance = abs(_text_width(metrics, left) - _text_width(metrics, right))
        score = (overflow, balance)
        if best_score is None or score < best_score:
            best_score = score
            best = left + "\n" + right
    if best is not None and best_score[0] == 0:
        return best
    if best is not None and " " not in raw and " / " not in raw:
        return best
    if " " not in raw:
        cut = max(1, len(raw) // 2)
        return raw[:cut] + "\n" + raw[cut:]
    return best or raw


def _icon_gap(button):
    if button.icon().isNull():
        return 0
    return button.iconSize().width() + 10


def fit_button_label(button):
    """Rewrap from the full label. The icon in front is not part of the text width."""
    from qgis.PyQt.QtGui import QFontMetrics

    full = button.property("fullText")
    if not full:
        return
    full = plain_button_text(full)
    icon = _icon_gap(button)
    width = button.contentsRect().width()
    if width < 8:
        width = button.width()
    if width < 24:
        shown = wrap_button_text(full)
    else:
        metrics = QFontMetrics(button.font())
        shown = split_to_width(full, metrics, max(16, width - icon))
        if button.text() != shown:
            button.setText(shown)
        lines = shown.split("\n")
        line_w = max(_text_width(metrics, line) for line in lines) if lines else 0
        if "\n" in shown:
            need = line_w + icon + 12
            if button.minimumWidth() < need:
                button.setMinimumWidth(need)
            height = metrics.lineSpacing() * len(lines) + 14
            if button.minimumHeight() < height:
                button.setMinimumHeight(height)
        return
    if button.text() != shown:
        button.setText(shown)
    if "\n" in shown and button.minimumHeight() < 40:
        button.setMinimumHeight(40)


def refit_buttons(root):
    from qgis.PyQt.QtWidgets import QPushButton

    if root is None:
        return
    for button in root.findChildren(QPushButton):
        fit_button_label(button)


def watch_button_fit(widget):
    """Refit after show and after the user resizes."""
    from qgis.PyQt.QtCore import QEvent, QObject, QTimer

    class _Fit(QObject):
        def eventFilter(self, watched, event):
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                if not getattr(watched, "_fit_pending", False):
                    watched._fit_pending = True

                    def _run(target=watched):
                        target._fit_pending = False
                        refit_buttons(target)

                    QTimer.singleShot(0, _run)
            return False

    filt = _Fit(widget)
    widget.installEventFilter(filt)
    widget._button_fit_filter = filt
    return widget


def styled_button(text, mark_key=None, parent=None):
    from qgis.PyQt.QtWidgets import QPushButton

    from .i18n import tr

    shown = plain_button_text(tr(text))
    button = QPushButton(wrap_button_text(shown), parent)
    button.setProperty("msgid", text)
    button.setProperty("fullText", shown)
    decorate_button(button, mark_key=mark_key, text=text)
    if "\n" in button.text():
        button.setMinimumHeight(max(button.minimumHeight(), 40))
    return button
