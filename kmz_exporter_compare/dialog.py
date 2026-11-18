# -*- coding: utf-8 -*-
"""One home page, then a page for each export or compare job."""

import os

from qgis.PyQt.QtCore import QSettings, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont, QFontMetrics, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from .help_dialog import show_help
from .qtutil import apply_taskbar_window, pointer_pos, run_menu
from .button_marks import decorate_button, mark_icon
from .i18n import current_language, known_languages, language_changed, set_language, text_in, tr
from .i18n.stamp import retranslate_tree, stamp_tree

_SETTINGS = "KMZExporterCompare"
_KIND = Qt.ItemDataRole.UserRole
_PATH = Qt.ItemDataRole.UserRole + 1
_LAYER = Qt.ItemDataRole.UserRole + 2
_FIELDS = Qt.ItemDataRole.UserRole + 3

_STYLE = """
#KmzMainDialog {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #e8f5e9, stop:0.5 #f1f8e9, stop:1 #fffde7);
}
#KmzMainDialog QToolBar {
    background: transparent;
    border: none;
    spacing: 2px;
    padding: 0;
}
#KmzMainDialog QToolBar QToolButton {
    background: transparent;
    border: none;
    padding: 2px;
    min-width: 0px;
    border-radius: 4px;
}
#KmzMainDialog QToolBar QToolButton:hover {
    background: #ffffff;
}
QGroupBox {
    font-size: 13px;
    font-weight: bold;
    border: 1px solid #c8e6c9;
    border-radius: 10px;
    margin-top: 10px;
    padding: 14px 12px 12px 12px;
    background: #fafafa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    padding: 4px 12px;
    color: #2e7d32;
    background: #e8f5e9;
    border-radius: 8px;
    font-size: 12px;
}
QRadioButton, QCheckBox {
    spacing: 10px;
    color: #37474f;
    font-size: 12px;
    padding: 4px 0;
}
QRadioButton::indicator, QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid #81c784;
    background: #fff;
}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    background: #66bb6a;
    border-color: #66bb6a;
}
QPushButton {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #81c784, stop:1 #66bb6a);
    color: #fff;
    border: none;
    padding: 8px 12px;
    border-radius: 10px;
    min-width: 0px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #a5d6a7, stop:1 #81c784);
}
QPushButton:pressed { background: #4caf50; }
#KmzMainDialog QFrame#hubBtn {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #81c784, stop:1 #66bb6a);
    border: 1px solid #43a047;
    border-bottom: 2px solid #2e7d32;
    border-radius: 8px;
    min-height: 36px;
    min-width: 0px;
}
#KmzMainDialog QFrame#hubBtn:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #a5d6a7, stop:1 #81c784);
}
#KmzMainDialog QFrame#hubBtn[pressed="true"] {
    background: #4caf50;
    border-bottom: 1px solid #2e7d32;
}
#opList {
    background: transparent;
    border: none;
    font-size: 12px;
    outline: none;
}
#opList::item {
    padding: 6px 4px;
    min-height: 22px;
}
#opList::item:selected {
    background: #c8e6c9;
    color: #1b5e20;
    border-radius: 4px;
}
#KmzMainDialog QPushButton#homeOk {
    min-height: 26px;
    max-height: 28px;
    padding: 2px 8px;
    font-size: 12px;
}
#opFrame {
    border: 1px solid #c8e6c9;
    border-radius: 10px;
    background: #fafafa;
}
#pageTitle {
    color: #1b5e20;
    font-size: 15px;
    font-weight: bold;
    background: transparent;
}
QTreeWidget, QTextEdit, QLineEdit, QComboBox {
    background: #fff;
    border: 1px solid #c8e6c9;
    border-radius: 8px;
    padding: 4px;
    font-size: 12px;
    color: #37474f;
}
QLabel { color: #37474f; font-size: 12px; background: transparent; }
#hintLabel { color: #5d7a8c; font-size: 11px; }
"""

_LANGUAGES = (
    ("en", "English"),
    ("zh", "中文"),
    ("es", "Español"),
    ("fr", "Français"),
    ("ar", "العربية"),
    ("it", "Italiano"),
    ("de", "Deutsch"),
    ("ja", "日本語"),
    ("ko", "한국어"),
)
_HUB_CARDS = (
    ("导出 KMZ", "按组写出，可另存 KML"),
    ("手动样式", "配对后再替换样式"),
    ("自动样式", "按文件夹名套参考样式"),
    ("坐标对比", "仅一侧，或同名移动"),
    ("图层对比", "数量与 Name、字段或点线面"),
)


def _plugin_version():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata.txt")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("version="):
                    return line.split("=", 1)[1].strip()
    except Exception:  # nosec B110
        pass
    return ""


_PAGE_SIZE = {
    "home": (220, 320),
    "export": (800, 700),
    "names": (640, 520),
    "auto": (560, 460),
    "manual": (560, 480),
    "coords": (800, 700),
}
_LAYOUT_ID = "15"


def _page_size(key, raw):
    parts = (raw or "").split(",")
    if len(parts) == 2:
        try:
            width = int(parts[0])
            height = int(parts[1])
        except ValueError:
            width = height = 0
        if width >= 320 and height >= 240:
            return width, height
    return _PAGE_SIZE.get(key, (350, 320))


def _advance(metrics, text):
    if hasattr(metrics, "horizontalAdvance"):
        return metrics.horizontalAdvance(text)
    return metrics.boundingRect(text).width()


_HOME_EDGE = 16  # dialog left/right margins


def home_column_mins(title_font, desc_font):
    """Minimum home width from the five hub buttons alone."""
    title_metrics = QFontMetrics(title_font)
    desc_metrics = QFontMetrics(desc_font)
    right = 0
    for lang in known_languages():
        for title, desc in _HUB_CARDS:
            title_w = _advance(title_metrics, text_in(lang, title)) + 20 + 6
            desc_w = _advance(desc_metrics, text_in(lang, desc))
            right = max(right, title_w, desc_w)
    # hub frame margins 6+6 and a little room so French titles are not clipped
    right += 12 + 12 + 8
    total = right + _HOME_EDGE
    return right, total


def _settings():
    store = QSettings()
    store.beginGroup(_SETTINGS)
    return store


class FieldDialog(QDialog):
    def __init__(self, layer, specs, parent=None):
        super(FieldDialog, self).__init__(parent)
        apply_taskbar_window(self)
        self.setWindowTitle(tr("导出字段"))
        self.resize(420, 360)
        root = QVBoxLayout(self)
        self.rows = []
        saved = {}
        for spec in specs or []:
            saved[spec.get("source")] = spec
        for field in layer.fields():
            name = field.name()
            if not name:
                continue
            row = QHBoxLayout()
            check = QCheckBox(name)
            previous = saved.get(name)
            check.setChecked(True if previous is None else bool(previous.get("on", True)))
            edit = QLineEdit(name if previous is None else (previous.get("export") or name))
            row.addWidget(check)
            row.addWidget(edit, 1)
            root.addLayout(row)
            self.rows.append((name, check, edit))
        buttons = QHBoxLayout()
        ok = QPushButton(tr("确定"))
        cancel = QPushButton(tr("取消"))
        decorate_button(ok, mark_key="ok")
        decorate_button(cancel, mark_key="cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def specs(self):
        out = []
        for name, check, edit in self.rows:
            out.append({
                "source": name,
                "export": edit.text().strip() or name,
                "on": check.isChecked(),
            })
        return out


class PairDialog(QDialog):
    def __init__(self, source_names, ref_names, parent=None):
        super(PairDialog, self).__init__(parent)
        apply_taskbar_window(self)
        self.setWindowTitle(tr("手动配对"))
        self.resize(560, 360)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(tr("左边是刚导出的文件夹，右边选参考 KMZ 里的文件夹。")))
        self.combos = []
        ref_names = list(ref_names)
        for name in source_names:
            row = QHBoxLayout()
            row.addWidget(QLabel(name), 1)
            combo = QComboBox()
            combo.addItem(tr("不套用"))
            combo.addItems(ref_names)
            if name in ref_names:
                combo.setCurrentText(name)
            row.addWidget(combo, 1)
            root.addLayout(row)
            self.combos.append((name, combo))
        buttons = QHBoxLayout()
        ok = QPushButton(tr("确定"))
        cancel = QPushButton(tr("取消"))
        decorate_button(ok, mark_key="ok")
        decorate_button(cancel, mark_key="cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def mapping(self):
        out = {}
        skip = tr("不套用")
        for name, combo in self.combos:
            chosen = combo.currentText()
            out[name] = "" if chosen == skip else chosen
        return out


class _HubButton(QFrame):
    clicked = pyqtSignal()

    def __init__(self, title, desc, mark_key=None, parent=None):
        super(_HubButton, self).__init__(parent)
        self.setObjectName("hubBtn")
        self.setProperty("hubDesc", desc)
        self.setProperty("pressed", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addStretch(1)
        if mark_key:
            icon_label = QLabel()
            icon_label.setPixmap(mark_icon(mark_key, 20).pixmap(20, 20))
            icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            title_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.title_label = QLabel(tr(title))
        self.title_label.setObjectName("hubTitle")
        self.title_label.setProperty("msgid", title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.title_label.setStyleSheet(
            "color: #ffffff; font-size: 13px; font-weight: bold; background: transparent;"
        )
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        layout.addLayout(title_row)
        self.desc_label = QLabel(tr(desc))
        self.desc_label.setObjectName("hubDesc")
        self.desc_label.setProperty("msgid", desc)
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.desc_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.desc_label.setWordWrap(False)
        self.title_label.setWordWrap(False)
        self.desc_label.setStyleSheet(
            "color: #102418; font-size: 10px; font-weight: normal; background: transparent;"
        )
        self.desc_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.desc_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        self.setToolTip(tr(desc))

    def _paint_pressed(self, pressed):
        self.setProperty("pressed", pressed)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._paint_pressed(True)
        super(_HubButton, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._paint_pressed(False)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(pointer_pos(event)):
            self.clicked.emit()
        super(_HubButton, self).mouseReleaseEvent(event)


class _PageStack(QStackedWidget):
    """Size follows the visible page, so the home page can stay narrow."""

    def sizeHint(self):
        current = self.currentWidget()
        if current is not None:
            return current.sizeHint()
        return QSize(350, 320)

    def minimumSizeHint(self):
        return QSize(280, 220)


class MainDialog(QDialog):
    def __init__(self, parent=None):
        super(MainDialog, self).__init__(parent)
        apply_taskbar_window(self)
        self.setObjectName("KmzMainDialog")
        self.setStyleSheet(_STYLE)
        self.setWindowTitle(self._title())
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")))
        self.resize(220, 320)
        self._block = False
        self._page_key = "home"
        self._shown = False
        self._home_pos = None
        self._home_min_w = 220
        self._home_right_min = 0
        self._pages = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)
        self.toolbar = QToolBar()
        self.toolbar.setObjectName("KmzIconBar")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setIconSize(QSize(24, 24))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.act_language = QAction(self._language_icon(), "", self)
        self.act_language.setToolTip(tr("语言"))
        self.act_language.triggered.connect(self._show_language_menu)
        self.act_help = QAction(self._icon_file("help"), "", self)
        self.act_help.setToolTip(tr("帮助"))
        self.act_help.triggered.connect(lambda: show_help(self))
        self.act_import = QAction(self._theme_action_icon("mActionSharingImport.svg", "入", "#1565c0"), "", self)
        self.act_import.setToolTip(tr("导入"))
        self.act_import.triggered.connect(self._import_bundle)
        self.act_export_icon = QAction(self._theme_action_icon("mActionSharingExport.svg", "出", "#2e7d32"), "", self)
        self.act_export_icon.setToolTip(tr("导出"))
        self.act_export_icon.triggered.connect(self._show_export_menu)
        self.act_settings = QAction(self._theme_action_icon("mActionOptions.svg", "设", "#455a64"), "", self)
        self.act_settings.setToolTip(tr("设置"))
        self.act_settings.triggered.connect(self._show_settings_menu)
        # Language and Help swapped; five icons evenly spaced across the home top bar.
        home_actions = (
            self.act_language,
            self.act_import,
            self.act_export_icon,
            self.act_help,
            self.act_settings,
        )
        lead = QWidget()
        lead.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(lead)
        for index, action in enumerate(home_actions):
            if index:
                gap = QWidget()
                gap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                self.toolbar.addWidget(gap)
            self.toolbar.addAction(action)
        trail = QWidget()
        trail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(trail)
        root.addWidget(self.toolbar)
        self.stack = _PageStack()
        root.addWidget(self.stack, 1)
        self._build_home()
        self._build_export_page()
        self._build_names_page()
        self._build_auto_page()
        self._build_manual_page()
        self._build_coords_page()
        self._load_settings()
        stamp_tree(self)
        from .button_marks import watch_button_fit
        watch_button_fit(self)
        language_changed().connect(self._retranslate)

    def showEvent(self, event):
        super(MainDialog, self).showEvent(event)
        if not self._shown:
            self._shown = True
            self._apply_size(self._page_key)
            if self._page_key == "home":
                self._remember_home_pos()
            else:
                self._center_on_qgis()

    def closeEvent(self, event):
        from .origin_pages import disconnect_coord_page

        disconnect_coord_page(self)
        self._store_size(self._page_key)
        self._save_settings()
        super(MainDialog, self).closeEvent(event)

    def open_page(self, key):
        if key not in self._pages:
            key = "home"
        leaving = self._page_key
        if self.isVisible():
            self._store_size(leaving)
            if leaving == "home":
                self._remember_home_pos()
        self._page_key = key
        self.stack.setCurrentWidget(self._pages[key])
        self.toolbar.setVisible(key == "home")
        if key == "coords":
            from .origin_pages import reload_coord_project
            reload_coord_project(self)
        if self.isVisible() or self._shown:
            self._apply_size(key)
            if key == "home":
                self._restore_home_pos()
            else:
                self._center_on_qgis()
            from .button_marks import refit_buttons
            refit_buttons(self)

    def _remember_home_pos(self):
        self._home_pos = self.pos()

    def _restore_home_pos(self):
        if self._home_pos is not None:
            self.move(self._home_pos)

    def _center_on_qgis(self):
        host = self.parentWidget()
        try:
            from qgis.utils import iface
            main = iface.mainWindow()
            if main is not None:
                host = main
        except Exception:  # nosec B110
            pass
        if host is not None:
            frame = host.frameGeometry()
        else:
            screen = self.screen()
            frame = screen.availableGeometry() if screen is not None else None
        if frame is None:
            return
        geo = self.frameGeometry()
        geo.moveCenter(frame.center())
        screen = self.screen() if self.screen() is not None else (host.screen() if host is not None else None)
        if screen is not None:
            avail = screen.availableGeometry()
            if geo.width() >= avail.width():
                geo.moveLeft(avail.left())
            elif geo.left() < avail.left():
                geo.moveLeft(avail.left())
            elif geo.right() > avail.right():
                geo.moveRight(avail.right())
            if geo.height() >= avail.height():
                geo.moveTop(avail.top())
            elif geo.top() < avail.top():
                geo.moveTop(avail.top())
            elif geo.bottom() > avail.bottom():
                geo.moveBottom(avail.bottom())
        self.move(geo.topLeft())

    def _store_size(self, key):
        store = _settings()
        store.setValue("size/" + key, "{0},{1}".format(self.width(), self.height()))
        store.endGroup()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._page_key != "home":
            self.open_page("home")
            return
        super(MainDialog, self).keyPressEvent(event)

    def minimumSizeHint(self):
        return QSize(300, 260)

    def _apply_size(self, key):
        store = _settings()
        layout_id = store.value("layout", "", type=str) or ""
        raw = store.value("size/" + key, "", type=str) or ""
        if layout_id != _LAYOUT_ID:
            store.setValue("layout", _LAYOUT_ID)
            for name in ("export", "names", "auto", "manual", "coords", "manualMatch"):
                store.remove("size/" + name)
            if key != "home":
                raw = ""
        store.endGroup()
        width, height = _page_size(key, raw)
        if key == "home":
            width = max(width, self._home_min_w)
            self.setMinimumWidth(self._home_min_w)
        else:
            self.setMinimumWidth(320)
        self.resize(width, height)

    def _build_home(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        cards = (
            ("export", "导出 KMZ", "按组写出，可另存 KML", "hub_export"),
            ("manual", "手动样式", "配对后再替换样式", "hub_manual"),
            ("auto", "自动样式", "按文件夹名套参考样式", "hub_auto"),
            ("coords", "坐标对比", "仅一侧，或同名移动", "hub_coords"),
            ("names", "图层对比", "数量与 Name、字段或点线面", "hub_names"),
        )
        for key, title, desc, hub_mark in cards:
            button = _HubButton(title, desc, hub_mark)
            button.clicked.connect(lambda page=key: self.open_page(page))
            layout.addWidget(button, 1)
        self._apply_home_mins()
        self._add_page("home", page)

    def _apply_home_mins(self):
        title_font = QFont(self.font())
        title_font.setPixelSize(13)
        title_font.setBold(True)
        desc_font = QFont(self.font())
        desc_font.setPixelSize(10)
        right, total = home_column_mins(title_font, desc_font)
        self._home_right_min = right
        self._home_min_w = max(180, total)
        for button in self.findChildren(QFrame):
            if button.objectName() == "hubBtn":
                button.setMinimumWidth(right)
        if self._page_key == "home":
            width = max(self.width(), self._home_min_w)
            if width != self.width():
                self.resize(width, self.height())

    def _build_export_page(self):
        from .origin_pages import build_export_page
        self._add_page("export", build_export_page(self))

    def _build_names_page(self):
        from .origin_pages import build_names_page
        self._add_page("names", build_names_page(self))

    def _build_auto_page(self):
        from .origin_pages import build_auto_page
        self._add_page("auto", build_auto_page(self))

    def _build_manual_page(self):
        from .origin_pages import build_manual_page
        self._add_page("manual", build_manual_page(self))

    def _build_coords_page(self):
        from .origin_pages import build_coords_page
        self._add_page("coords", build_coords_page(self))

    def _add_page(self, key, page):
        page.setMinimumSize(0, 0)
        page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._pages[key] = page
        self.stack.addWidget(page)

    def _sub_header(self, title):
        row = QHBoxLayout()
        label = self._label(title)
        label.setObjectName("pageTitle")
        row.addWidget(label)
        row.addStretch(1)
        return row

    def _label(self, msgid):
        widget = QLabel(tr(msgid))
        widget.setProperty("msgid", msgid)
        return widget

    def _button(self, msgid, slot=None, mark_key=None):
        from .button_marks import plain_button_text, wrap_button_text

        shown = plain_button_text(tr(msgid))
        widget = QPushButton(wrap_button_text(shown))
        widget.setProperty("msgid", msgid)
        widget.setProperty("fullText", shown)
        widget.setAutoDefault(False)
        widget.setDefault(False)
        decorate_button(widget, mark_key=mark_key, text=msgid)
        if slot is not None:
            widget.clicked.connect(slot)
        return widget

    def _check(self, msgid):
        widget = QCheckBox(tr(msgid))
        widget.setProperty("msgid", msgid)
        return widget

    def _radio(self, msgid):
        widget = QRadioButton(tr(msgid))
        widget.setProperty("msgid", msgid)
        return widget

    def _title(self):
        return "{0} {1}".format(tr("KMZ Exporter & Compare"), _plugin_version())

    def _icon_file(self, name):
        if name == "help":
            from .icons import tool_icon
            return tool_icon("mActionHelpContents.svg", "?", "#455a64")
        return QIcon()

    def _theme_action_icon(self, theme_name, letter, color):
        from .icons import tool_icon
        return tool_icon(theme_name, letter, color)

    def _language_icon(self, lang=None):
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
        code = lang or current_language()
        if code == "zh":
            name = "lang_zh_24.png"
            search = folder
        else:
            name = "lang_24.png"
            lang_dir = os.path.join(folder, code)
            search = lang_dir if os.path.exists(os.path.join(lang_dir, name)) else folder
        path = os.path.join(search, name)
        icon = QIcon()
        if os.path.exists(path):
            icon.addFile(path)
            path32 = os.path.join(search, name.replace("_24.png", "_32.png"))
            if os.path.exists(path32):
                icon.addFile(path32, QSize(32, 32))
        if icon.isNull():
            from .icons import tool_icon
            return tool_icon("", "文", "#6a1b9a")
        return icon

    def _show_export_menu(self):
        from .origin_pages import BUNDLE_PARTS, save_bundle

        menu = QMenu(self)
        icons = {
            "all": self.act_export_icon.icon(),
            "export": mark_icon("hub_export", 16),
            "manual": mark_icon("hub_manual", 16),
            "coords": mark_icon("hub_coords", 16),
        }
        for key, title in BUNDLE_PARTS:
            action = menu.addAction(icons.get(key, QIcon()), tr(title))
            action.triggered.connect(lambda _checked=False, part=key: save_bundle(self, part))
        anchor = self.toolbar.widgetForAction(self.act_export_icon)
        if anchor is not None:
            run_menu(menu, anchor.mapToGlobal(anchor.rect().bottomLeft()))
        else:
            from qgis.PyQt.QtGui import QCursor
            run_menu(menu, QCursor.pos())

    def _import_bundle(self):
        from .origin_pages import load_bundle
        load_bundle(self)

    def _show_settings_menu(self):
        menu = QMenu(self)
        reset = menu.addAction(tr("恢复默认窗口"))
        reset.triggered.connect(self._restore_default_sizes)
        wipe = menu.addAction(tr("恢复全部配置"))
        wipe.triggered.connect(self._reset_all_settings)
        anchor = self.toolbar.widgetForAction(self.act_settings)
        if anchor is not None:
            run_menu(menu, anchor.mapToGlobal(anchor.rect().bottomLeft()))
        else:
            from qgis.PyQt.QtGui import QCursor
            run_menu(menu, QCursor.pos())

    def _restore_default_sizes(self):
        from .origin_pages import restore_default_window_sizes
        restore_default_window_sizes(self)

    def _reset_all_settings(self):
        from .origin_pages import reset_saved_settings
        reset_saved_settings(self)

    def _show_language_menu(self):
        menu = QMenu(self)
        current = current_language()
        for key, label in _LANGUAGES:
            action = menu.addAction(self._language_icon(key), label)
            action.setCheckable(True)
            action.setChecked(key == current)
            action.triggered.connect(lambda _checked=False, lang=key: set_language(lang))
        anchor = self.toolbar.widgetForAction(self.act_language)
        if anchor is not None:
            run_menu(menu, anchor.mapToGlobal(anchor.rect().bottomLeft()))
        else:
            from qgis.PyQt.QtGui import QCursor
            run_menu(menu, QCursor.pos())

    def _retranslate(self, *_args):
        self.setWindowTitle(self._title())
        self.act_language.setToolTip(tr("语言"))
        self.act_language.setIcon(self._language_icon())
        self.act_help.setToolTip(tr("帮助"))
        self.act_import.setToolTip(tr("导入"))
        self.act_export_icon.setToolTip(tr("导出"))
        if getattr(self, "act_settings", None) is not None:
            self.act_settings.setToolTip(tr("设置"))
        retranslate_tree(self)
        from .button_marks import refit_buttons
        refit_buttons(self)
        panel = getattr(self, "_export_panel", None)
        if panel is not None and hasattr(panel, "_refresh_unconfigured"):
            panel._refresh_unconfigured()
        if panel is not None and hasattr(panel, "refresh_empty_group_tips"):
            panel.refresh_empty_group_tips()
        from .origin_pages import _refresh_tolerance_label, _set_coord_mode
        if getattr(self, "_coord_mode", None):
            _set_coord_mode(self, self._coord_mode)
        _refresh_tolerance_label(self)
        for widget in self.findChildren(QWidget):
            if widget.objectName() == "hubBtn":
                desc = widget.property("hubDesc")
                if desc:
                    widget.setToolTip(tr(str(desc)))
        self._apply_home_mins()

    def _load_settings(self):
        return

    def _save_settings(self):
        return
