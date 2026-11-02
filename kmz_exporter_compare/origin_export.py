# -*- coding: utf-8 -*-
import json
import os

from qgis.PyQt.QtCore import QEvent, QRect, QSettings, QSize, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from qgis.core import QgsProject, QgsSymbolLayerUtils, QgsVectorLayer

from .qtutil import header_mode, run_dialog
from .button_marks import decorate_button, styled_button
from .i18n import tr

from .engine import (
    _export_vector_tree,
    _kmz_feature_count,
    _kmz_layer_classified,
    _kmz_field_for_key,
    _kmz_match_name_field,
    _kmz_path_key,
    _kmz_stamp_tree,
    _style_map_auto_match,
    _style_map_geom_filter_ok,
    _style_map_norm_name,
    _style_map_tokens,
    _style_map_token_strong,
    _style_map_unique_assign,
)

SETTINGS_KEY = "KMZExporterCompare"


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


def _kmz_legend_pixmap(layer, max_icons=4, size=22):
    """图例预览。符号必须先 clone，不能用渲染器里那个临时对象。"""
    symbols = []
    renderer = None
    try:
        renderer = layer.renderer() if layer is not None else None
    except Exception:
        renderer = None
    if renderer is not None:
        try:
            for item in renderer.legendSymbolItems():
                sym = item.symbol()
                if sym is not None:
                    symbols.append(sym.clone())
        except Exception:
            symbols = []
    shown = symbols[:max_icons]
    if not shown:
        empty = QPixmap(1, size)
        empty.fill(Qt.transparent)
        return empty
    gap = 3
    extra = 28 if len(symbols) > max_icons else 0
    pm = QPixmap(len(shown) * (size + gap) + extra, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    try:
        x = 0
        for sym in shown:
            icon = None
            try:
                icon = QgsSymbolLayerUtils.symbolPreviewPixmap(sym, QSize(size, size), 1)
            except Exception:
                icon = None
            if icon is not None and not icon.isNull():
                painter.drawPixmap(x, 0, icon)
            x += size + gap
        if extra:
            painter.setPen(QColor("#607d8b"))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(QRect(x, 0, extra, size), Qt.AlignVCenter | Qt.AlignLeft, "+{}".format(len(symbols) - max_icons))
    finally:
        painter.end()
    return pm


def _kmz_merge_field_specs(field_names, saved):
    by_name = {}
    for item in saved or []:
        src = (item.get("source") or "").strip()
        if src and src not in by_name:
            by_name[src] = item
    out = []
    for name in field_names or []:
        old = by_name.get(name)
        if old:
            export = (old.get("export") or name).strip() or name
            out.append({"source": name, "export": export, "on": bool(old.get("on", True))})
        else:
            out.append({"source": name, "export": name, "on": True})
    return out


class KmzFieldDialog(QDialog):
    """一个图层要导出哪些字段，以及写出时的字段名。"""

    def __init__(self, specs, parent=None):
        super(KmzFieldDialog, self).__init__(parent)
        self.setWindowTitle(tr("导出字段"))
        self.setStyleSheet(KmzExportDialog._PLAIN_BTN)
        self.resize(480, 380)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(len(specs), 3)
        self.table.setHorizontalHeaderLabels([tr("导出"), tr("原字段"), tr("导出名称")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 56)
        self.table.setColumnWidth(1, 170)
        for row, spec in enumerate(specs):
            check = QTableWidgetItem("")
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if spec.get("on", True) else Qt.Unchecked)
            self.table.setItem(row, 0, check)
            src = QTableWidgetItem(spec.get("source") or "")
            src.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 1, src)
            name = QTableWidgetItem((spec.get("export") or spec.get("source") or ""))
            self.table.setItem(row, 2, name)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        btn_all = styled_button("全选")
        btn_none = styled_button("全不选")
        btn_all.clicked.connect(lambda: self._set_checks(Qt.Checked))
        btn_none.clicked.connect(lambda: self._set_checks(Qt.Unchecked))
        row.addWidget(btn_all)
        row.addWidget(btn_none)
        row.addStretch(1)
        cancel = styled_button("取消")
        ok = styled_button("确定")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        from .button_marks import watch_button_fit
        watch_button_fit(self)

    def _set_checks(self, state):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(state)

    def specs(self):
        out = []
        for row in range(self.table.rowCount()):
            src_item = self.table.item(row, 1)
            name_item = self.table.item(row, 2)
            check = self.table.item(row, 0)
            src = src_item.text() if src_item is not None else ""
            export = name_item.text().strip() if name_item is not None else ""
            on = check is not None and check.checkState() == Qt.Checked
            out.append({"source": src, "export": export or src, "on": on})
        return out


class KmzExportDialog(QWidget):
    """导出 KMZ 前的图层清单。只记这个窗口自己的大小。"""

    _PLAIN_BTN = (
        "QPushButton {"
        " background: #f7f7f7;"
        " color: #263238;"
        " border: 1px solid #bdbdbd;"
        " border-radius: 2px;"
        " padding: 4px 12px;"
        " min-width: 0px;"
        " min-height: 0px;"
        " font-size: 12px;"
        " font-weight: normal;"
        "}"
        "QPushButton:hover { background: #eeeeee; }"
        "QPushButton:pressed { background: #e0e0e0; }"
        "QPushButton:disabled { color: #9e9e9e; }"
    )
    _BAR_BTN = (
        "QPushButton {"
        " background: #ffffff;"
        " color: #1b5e20;"
        " border: 1px solid #81c784;"
        " border-radius: 6px;"
        " padding: 4px 8px;"
        " min-width: 0px;"
        " min-height: 0px;"
        " font-size: 13px;"
        " font-weight: bold;"
        "}"
        "QPushButton:hover { background: #f1f8e9; }"
        "QPushButton:pressed { background: #dcedc8; }"
    )

    def __init__(self, parent=None, embedded=False, on_home=None, on_export=None):
        super(KmzExportDialog, self).__init__(parent)
        self._embedded = embedded
        self._on_home = on_home
        self._on_export = on_export
        self.setObjectName("KmzExportPage")
        self.setWindowTitle("导出 KMZ")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            self._PLAIN_BTN
            + "QWidget#KmzExportPage { background: #ffffff; color: #263238; }"
            + "QWidget#KmzExportPage QLabel { color: #37474f; background: transparent; }"
            + "QWidget#KmzExportPage QTreeWidget { color: #263238; background: #ffffff; }"
            + "QWidget#KmzExportPage QHeaderView::section { color: #263238; background: #eeeeee; font-weight: bold; }"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(0, 0)
        self.output_path = ""
        self._block = False
        self._unconfigured_full = ""
        self._applied_size = True
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["导出", "图例", "预览", "导出名称", "显示字段", "分类", "字段"])
        self.tree.setColumnWidth(0, 52)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 72)
        self.tree.setColumnWidth(3, 96)
        self.tree.setColumnWidth(4, 108)
        self.tree.setColumnWidth(5, 96)
        self.tree.setColumnWidth(6, 64)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(header_mode("Interactive"))
        header.setSectionResizeMode(1, header_mode("Stretch"))
        header.setSectionResizeMode(3, header_mode("Interactive"))
        header_font = header.font()
        header_font.setBold(True)
        header.setFont(header_font)
        self.tree.setStyleSheet(
            "QTreeWidget { color: #263238; background: #ffffff; }"
            "QTreeWidget::item { min-height: 32px; color: #263238; }"
            "QHeaderView::section { color: #263238; background: #eeeeee; font-weight: bold; }"
            "QComboBox { min-width: 0px; padding: 2px 6px; min-height: 24px; color: #263238; background: #ffffff; }"
        )
        self.tree.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.tree, 1)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        shared_box = QWidget()
        shared = QHBoxLayout(shared_box)
        shared.setContentsMargins(0, 0, 0, 0)
        shared.setSpacing(8)
        shared.addWidget(QLabel("共用字段"))
        self.comboShared = NoWheelComboBox()
        self.comboShared.setMinimumContentsLength(6)
        self.comboShared.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.comboShared.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.comboShared.setToolTip("只差大小写的字段算同一个，例如 Name 和 NAME。选中后，每个图层的显示字段改成它自己的写法；没有的留空并标红。最多 5 个。")
        shared.addWidget(self.comboShared, 1)
        self.lblUnconfiguredTitle = QLabel("未配置显示字段：")
        self.lblUnconfiguredTitle.setStyleSheet("color: #c62828; font-weight: bold;")
        self.lblUnconfiguredTitle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lblUnconfiguredTitle.setObjectName("keepText")
        self.lblUnconfigured = QLabel("无")
        self.lblUnconfigured.setObjectName("dynamicText")
        self.lblUnconfigured.setStyleSheet("color: #c62828; font-weight: bold;")
        self.lblUnconfigured.setWordWrap(False)
        self.lblUnconfigured.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.lblUnconfigured.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        info_box = QWidget()
        info = QHBoxLayout(info_box)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(0)
        info.addWidget(self.lblUnconfiguredTitle)
        info.addWidget(self.lblUnconfigured, 1)
        self._shared_box = shared_box
        self._unconfigured_box = info_box
        head.addWidget(shared_box, 4)
        head.addWidget(info_box, 6)
        root.addLayout(head)
        self.chkSummary = QCheckBox("显示摘要")
        self.chkSummary.setToolTip("字段总会写入 KMZ。勾选后，说明里再放一张字段表，供 Google Earth 左侧列表使用。")
        self.chkEmpty = QCheckBox("导出空图层")
        self.chkEmpty.setToolTip("勾选：没有要素的图层也写成空文件夹。不勾选：跳过这些图层。")
        self.editNullName = QLineEdit("NULL")
        self.editNullName.setFixedWidth(56)
        self.editNullName.setToolTip("没有显示字段，或这个字段的值为空时，要素名称写成这里的文字。")
        self._load_options()
        self.comboShared.currentIndexChanged.connect(self._apply_shared_field)
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        checks = QWidget()
        check_row = QHBoxLayout(checks)
        check_row.setContentsMargins(0, 0, 0, 0)
        check_row.setSpacing(10)
        check_row.addWidget(self.chkSummary)
        check_row.addWidget(self.chkEmpty)
        check_row.addStretch(1)
        null_box = QWidget()
        null_row = QHBoxLayout(null_box)
        null_row.setContentsMargins(0, 0, 0, 0)
        null_row.setSpacing(6)
        null_row.addWidget(QLabel("空名称"))
        null_row.addWidget(self.editNullName, 0)
        null_row.addStretch(1)
        grid.addWidget(checks, 0, 0)
        grid.addWidget(null_box, 1, 0)
        btn_toggle = styled_button("全选/全不选")
        btn_ok = styled_button("导出KMZ")
        btn_home = styled_button("返回主页面")
        btn_cancel = styled_button("取消")
        btn_save = styled_button("保存配置", mark_key="save")
        for btn in (btn_toggle, btn_ok, btn_home, btn_cancel, btn_save):
            btn.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Expanding)
            btn.setStyleSheet(self._BAR_BTN)
            btn.setMinimumHeight(48)
        btn_toggle.setMinimumWidth(156)
        btn_ok.setStyleSheet(
            self._BAR_BTN + "QPushButton { color: #0d47a1; }"
        )
        btn_toggle.clicked.connect(self._toggle_all)
        btn_ok.clicked.connect(self._accept_export)
        btn_cancel.clicked.connect(self._go_home)
        btn_home.clicked.connect(self._go_home)
        btn_save.clicked.connect(self._save_page_config)
        for column, btn in enumerate((btn_toggle, btn_ok, btn_home, btn_cancel, btn_save), start=1):
            grid.addWidget(btn, 0, column, 2, 1)
            grid.setColumnStretch(column, 4 if btn is btn_toggle else 3)
        grid.setColumnStretch(0, 2)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        root.addLayout(grid)
        self._fill()
        self._sync_info_height()

    def _settings(self):
        if not QSettings:
            return None
        s = QSettings()
        s.beginGroup(SETTINGS_KEY)
        return s

    def _save_page_config(self):
        self._remember(True)
        QMessageBox.information(self, tr("保存配置"), tr("已保存"))

    def _load_size(self):
        w, h = 800, 600
        s = self._settings()
        if s is not None:
            w = s.value("kmzExportDlgWidth", 800, type=int)
            h = s.value("kmzExportDlgHeight", 600, type=int)
            s.endGroup()
        try:
            w = int(w)
            h = int(h)
        except Exception:
            w, h = 800, 600
        if w < 640:
            w = 800
        if h < 420:
            h = 600
        self._want_w = w
        self._want_h = h
        self._applied_size = False
        self.resize(w, h)

    def _go_home(self):
        if self._on_home is not None:
            self._on_home()

    def showEvent(self, event):
        super(KmzExportDialog, self).showEvent(event)
        if self._embedded:
            self._sync_info_height()
            self._elide_unconfigured()
            return
        if not self._applied_size:
            self._applied_size = True
            self.resize(self._want_w, self._want_h)
        self._sync_info_height()
        self._elide_unconfigured()

    def resizeEvent(self, event):
        super(KmzExportDialog, self).resizeEvent(event)
        self._elide_unconfigured()

    def _load_options(self):
        summary, empty = True, True
        null_name = "NULL"
        s = self._settings()
        if s is not None:
            raw = s.value("kmzExportShowSummary", True)
            raw_empty = s.value("kmzExportIncludeEmpty", True)
            raw_null = s.value("kmzExportNullName", "NULL")
            s.endGroup()
            summary = self._as_bool(raw, True)
            empty = self._as_bool(raw_empty, True)
            null_name = "NULL" if raw_null is None else str(raw_null)
        self.chkSummary.setChecked(summary)
        self.chkEmpty.setChecked(empty)
        self.editNullName.setText(null_name.strip() or "NULL")

    def null_name(self):
        text = self.editNullName.text().strip()
        return text or "NULL"

    @staticmethod
    def _as_bool(raw, default):
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return default
        return str(raw).strip().lower() not in ("0", "false", "no")

    def _remember(self, save_config):
        if not save_config:
            return
        s = self._settings()
        if s is None:
            return
        s.setValue("kmzExportShowSummary", bool(self.chkSummary.isChecked()))
        s.setValue("kmzExportIncludeEmpty", bool(self.chkEmpty.isChecked()))
        s.setValue("kmzExportNullName", self.null_name())
        if save_config:
            try:
                s.setValue("kmzExportLastConfig", json.dumps(self._snapshot(), ensure_ascii=False))
            except Exception:
                pass
        s.endGroup()

    _FOLDER_COLOR = QColor("#0d47a1")
    _LAYER_COLOR = QColor("#37474f")
    _MISSING_COLOR = QColor("#c62828")

    def _fill(self):
        self._block = True
        self.tree.clear()
        self._key_order = []
        self._key_layers = {}
        self._key_spellings = {}
        nodes = _kmz_stamp_tree(_export_vector_tree())

        def add(parent, items):
            total = 0
            for item in items:
                node = QTreeWidgetItem(parent)
                legend = item.get("name") or ""
                node.setText(0, "")
                node.setFlags((node.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled) & ~Qt.ItemIsEditable)
                node.setCheckState(0, Qt.Checked)
                node.setData(0, Qt.UserRole, _kmz_path_key(item.get("path")))
                node.setData(0, Qt.UserRole + 7, legend)
                name_edit = QLineEdit(legend)
                self.tree.setItemWidget(node, 3, name_edit)
                if item.get("type") == "group":
                    node.setFlags(node.flags() | Qt.ItemIsAutoTristate)
                    node.setData(0, Qt.UserRole + 1, "group")
                    count = add(node, item.get("children") or [])
                    node.setExpanded(True)
                    font = node.font(1)
                    font.setBold(True)
                    node.setFont(1, font)
                    node.setForeground(1, QBrush(self._FOLDER_COLOR))
                else:
                    layer = item.get("layer")
                    count = _kmz_feature_count(layer)
                    layer_id = ""
                    try:
                        layer_id = layer.id() if layer is not None else ""
                    except Exception:
                        layer_id = ""
                    fields = []
                    if layer is not None:
                        try:
                            fields = [field.name() for field in layer.fields()]
                        except Exception:
                            fields = []
                    unique = []
                    seen = set()
                    for fname in fields:
                        if not fname or fname in seen:
                            continue
                        seen.add(fname)
                        unique.append(fname)
                        key = fname.casefold()
                        layer_ids = self._key_layers.setdefault(key, set())
                        layer_ids.add(layer_id or legend)
                        if key not in self._key_spellings:
                            self._key_order.append(key)
                            self._key_spellings[key] = []
                        if fname not in self._key_spellings[key]:
                            self._key_spellings[key].append(fname)
                    fields = unique
                    node.setData(0, Qt.UserRole + 1, "layer")
                    node.setData(0, Qt.UserRole + 2, layer_id)
                    node.setData(0, Qt.UserRole + 3, fields)
                    matched = _kmz_match_name_field(layer, "Name") if layer is not None else None
                    node.setData(0, Qt.UserRole + 4, matched or "")
                    node.setData(0, Qt.UserRole + 6, [
                        {"source": fname, "export": fname, "on": True} for fname in fields
                    ])
                    node.setForeground(1, QBrush(self._LAYER_COLOR))
                    preview = QLabel()
                    preview.setPixmap(_kmz_legend_pixmap(layer))
                    preview.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    self.tree.setItemWidget(node, 2, preview)
                    combo = NoWheelComboBox()
                    combo.setEditable(False)
                    combo.addItem("（空）", "")
                    for fname in fields:
                        combo.addItem(fname, fname)
                    self._select_combo(combo, matched or "")
                    combo.currentIndexChanged.connect(
                        lambda _i, one=node: self._on_field_picked(one)
                    )
                    self.tree.setItemWidget(node, 4, combo)
                    has_class = _kmz_layer_classified(layer)
                    node.setData(0, Qt.UserRole + 8, bool(has_class))
                    split = NoWheelComboBox()
                    split.setEditable(False)
                    split.addItem("按QGIS分类", "qgis")
                    split.addItem("（不拆分）", "")
                    for fname in fields:
                        split.addItem(fname, "f:" + fname)
                    self._mark_qgis_split(split, has_class)
                    self._select_split(split, "")
                    split.setToolTip(
                        "默认不拆分。按 QGIS 分类：用符号化里的分类或分级做子文件夹，没有分类时不可选。"
                        "选某个字段：用这个字段的不同值做子文件夹。"
                    )
                    self.tree.setItemWidget(node, 5, split)
                    btn = styled_button("字段")
                    btn.setFocusPolicy(Qt.NoFocus)
                    btn.setStyleSheet(self._PLAIN_BTN)
                    btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                    btn.setToolTip("选择要导出的字段，以及写出时的字段名。不打开则全部按原名导出。")
                    btn.clicked.connect(lambda _c=False, one=node: self._edit_fields(one))
                    self.tree.setColumnWidth(6, max(self.tree.columnWidth(6), btn.sizeHint().width() + 12))
                    self.tree.setItemWidget(node, 6, btn)
                node.setData(0, Qt.UserRole + 5, count)
                node.setText(1, "{} ({})".format(legend, count))
                total += count
            return total

        add(self.tree.invisibleRootItem(), nodes)
        self.tree.expandAll()
        self.comboShared.blockSignals(True)
        self.comboShared.clear()
        self.comboShared.addItem("（不统一）", "")
        shared_keys = [key for key in self._key_order if len(self._key_layers.get(key) or ()) >= 2][:5]
        for key in shared_keys:
            spellings = self._key_spellings.get(key) or [key]
            shown = spellings[0] if len(spellings) == 1 else " / ".join(spellings[:3])
            self.comboShared.addItem("{}（{}层）".format(shown, len(self._key_layers.get(key) or ())), key)
        self.comboShared.blockSignals(False)
        self._restore_last()
        self._block = False
        self._refresh_marks()
        self._refresh_unconfigured()

    def _select_combo(self, combo, field_name):
        if combo is None:
            return
        combo.blockSignals(True)
        idx = combo.findData(field_name or "")
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _mark_field(self, node, missing):
        kind = node.data(0, Qt.UserRole + 1)
        if kind == "group":
            node.setForeground(1, QBrush(self._FOLDER_COLOR))
            return
        node.setForeground(1, QBrush(self._MISSING_COLOR if missing else self._LAYER_COLOR))
        combo = self.tree.itemWidget(node, 4)
        if combo is not None:
            combo.setStyleSheet("QComboBox { color: #c62828; }" if missing else "")

    def _apply_shared_field(self, _index=None):
        if self._block:
            return
        chosen = self.comboShared.currentData() or ""

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.data(0, Qt.UserRole + 1) == "group":
                    walk(child)
                    continue
                fields = list(child.data(0, Qt.UserRole + 3) or [])
                combo = self.tree.itemWidget(child, 4)
                if not chosen:
                    default = child.data(0, Qt.UserRole + 4) or ""
                    self._select_combo(combo, default if default in fields else "")
                    picked = combo.currentData() if combo is not None else ""
                    self._mark_field(child, not picked)
                    continue
                actual = _kmz_field_for_key(fields, chosen)
                if actual:
                    self._select_combo(combo, actual)
                    self._mark_field(child, False)
                else:
                    self._select_combo(combo, "")
                    self._mark_field(child, True)

        walk(self.tree.invisibleRootItem())
        self._refresh_unconfigured()

    def _on_field_picked(self, node):
        if self._block:
            return
        combo = self.tree.itemWidget(node, 4)
        picked = combo.currentData() if combo is not None else ""
        self._mark_field(node, not picked)
        self._refresh_unconfigured()

    def _on_item_changed(self, item, column):
        if self._block or column != 0:
            return
        self._block = True
        state = item.checkState(0)
        if item.childCount():
            self._set_children(item, state)
        parent = item.parent()
        while parent is not None:
            self._sync_parent(parent)
            parent = parent.parent()
        self._block = False

    def _set_children(self, item, state):
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            if child.childCount():
                self._set_children(child, state)

    def _sync_parent(self, item):
        total = item.childCount()
        checked = 0
        partial = False
        for i in range(total):
            state = item.child(i).checkState(0)
            if state == Qt.Checked:
                checked += 1
            elif state == Qt.PartiallyChecked:
                partial = True
        if partial or (0 < checked < total):
            item.setCheckState(0, Qt.PartiallyChecked)
        elif checked == 0:
            item.setCheckState(0, Qt.Unchecked)
        else:
            item.setCheckState(0, Qt.Checked)

    def _set_all(self, state):
        self._block = True

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                child.setCheckState(0, state)
                walk(child)

        walk(self.tree.invisibleRootItem())
        self._block = False
        self._refresh_unconfigured()

    def _toggle_all(self):
        all_on = True

        def walk(item):
            nonlocal all_on
            for i in range(item.childCount()):
                child = item.child(i)
                if child.data(0, Qt.UserRole + 1) != "group" and child.checkState(0) != Qt.Checked:
                    all_on = False
                walk(child)

        walk(self.tree.invisibleRootItem())
        self._set_all(Qt.Unchecked if all_on else Qt.Checked)

    def _sync_info_height(self):
        height = max(
            self.comboShared.sizeHint().height(),
            self.chkSummary.sizeHint().height(),
            self.editNullName.sizeHint().height(),
            24,
        )
        self.lblUnconfiguredTitle.setFixedHeight(height)
        self.lblUnconfigured.setFixedHeight(height)

    def _refresh_unconfigured(self):
        names = []

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.data(0, Qt.UserRole + 1) == "group":
                    walk(child)
                    continue
                combo = self.tree.itemWidget(child, 4)
                field = combo.currentData() if combo is not None else ""
                if not field:
                    names.append(child.data(0, Qt.UserRole + 7) or child.text(1) or "图层")

        walk(self.tree.invisibleRootItem())
        self._unconfigured_full = "、".join(names) if names else tr("无")
        color = "#2e7d32" if not names else "#c62828"
        style = "color: {0}; font-weight: bold;".format(color)
        self.lblUnconfiguredTitle.setStyleSheet(style)
        self.lblUnconfigured.setStyleSheet(style)
        self.lblUnconfigured.setToolTip(tr("未配置显示字段：") + self._unconfigured_full)
        self._elide_unconfigured()

    def _elide_unconfigured(self):
        if not hasattr(self, "lblUnconfigured"):
            return
        width = self.lblUnconfigured.width()
        title_w = self.lblUnconfiguredTitle.sizeHint().width() if hasattr(self, "lblUnconfiguredTitle") else 120
        if width < 40:
            width = max(self.width() - title_w - 36, 40)
        self.lblUnconfigured.setText(
            self.lblUnconfigured.fontMetrics().elidedText(self._unconfigured_full, Qt.ElideRight, width)
        )

    def _mark_qgis_split(self, combo, enabled):
        if combo is None:
            return
        model = combo.model()
        item = model.item(0) if model is not None and hasattr(model, "item") else None
        if item is None:
            return
        item.setEnabled(bool(enabled))
        item.setForeground(QBrush(self._LAYER_COLOR if enabled else self._MISSING_COLOR))

    def _sync_all_parents(self):
        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                walk(child)
                if child.data(0, Qt.UserRole + 1) == "group":
                    self._sync_parent(child)

        walk(self.tree.invisibleRootItem())

    def _refresh_marks(self):
        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.data(0, Qt.UserRole + 1) == "group":
                    walk(child)
                    continue
                combo = self.tree.itemWidget(child, 4)
                picked = combo.currentData() if combo is not None else ""
                self._mark_field(child, not picked)

        walk(self.tree.invisibleRootItem())

    def _split_value(self, node):
        combo = self.tree.itemWidget(node, 5)
        if combo is None:
            return "qgis"
        data = combo.currentData()
        if data is None or data == "":
            return ""
        text = str(data)
        if text == "qgis":
            return "qgis"
        if text.startswith("f:"):
            return text[2:]
        return text

    def _select_split(self, combo, mode):
        if combo is None:
            return
        if mode == "qgis":
            token = "qgis"
        elif not mode:
            token = ""
        else:
            token = "f:" + str(mode)
        combo.blockSignals(True)
        idx = combo.findData(token)
        if idx < 0 and mode and mode != "qgis":
            folded = str(mode).casefold()
            for i in range(combo.count()):
                data = combo.itemData(i) or ""
                if str(data).startswith("f:") and str(data)[2:].casefold() == folded:
                    idx = i
                    break
        if idx >= 0 and token == "qgis":
            model = combo.model()
            item = model.item(idx) if model is not None and hasattr(model, "item") else None
            if item is not None and not item.isEnabled():
                idx = combo.findData("")
        if idx < 0:
            idx = combo.findData("")
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _edit_fields(self, node):
        specs = list(node.data(0, Qt.UserRole + 6) or [])
        dlg = KmzFieldDialog(specs, self)
        if run_dialog(dlg) != QDialog.Accepted:
            return
        node.setData(0, Qt.UserRole + 6, dlg.specs())

    def _name_text(self, node):
        edit = self.tree.itemWidget(node, 3)
        if edit is None:
            return ""
        return edit.text()

    def plan(self):
        layers = {}
        groups = {}

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                kind = child.data(0, Qt.UserRole + 1)
                export_name = self._name_text(child).strip()
                if kind == "group":
                    groups[child.data(0, Qt.UserRole)] = export_name
                    walk(child)
                    continue
                if child.checkState(0) != Qt.Checked:
                    continue
                combo = self.tree.itemWidget(child, 4)
                field = ""
                if combo is not None:
                    field = combo.currentData()
                    if field is None:
                        field = ""
                layers[child.data(0, Qt.UserRole + 2) or ""] = {
                    "export_name": export_name,
                    "name_field": str(field or "").strip(),
                    "split": self._split_value(child),
                    "fields": list(child.data(0, Qt.UserRole + 6) or []),
                }

        walk(self.tree.invisibleRootItem())
        return {"layers": layers, "groups": groups}

    def _snapshot(self):
        layers = []
        groups = []

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                kind = child.data(0, Qt.UserRole + 1)
                legend = child.data(0, Qt.UserRole + 7) or ""
                export_name = self._name_text(child)
                if kind == "group":
                    groups.append({
                        "path": child.data(0, Qt.UserRole) or "",
                        "legend": legend,
                        "export_name": export_name,
                    })
                    walk(child)
                    continue
                combo = self.tree.itemWidget(child, 4)
                field = combo.currentData() if combo is not None else ""
                layers.append({
                    "legend": legend,
                    "checked": child.checkState(0) == Qt.Checked,
                    "export_name": export_name,
                    "display_field": str(field or ""),
                    "split": self._split_value(child),
                    "fields": list(child.data(0, Qt.UserRole + 6) or []),
                })

        walk(self.tree.invisibleRootItem())
        return {
            "version": 1,
            "summary": bool(self.chkSummary.isChecked()),
            "empty": bool(self.chkEmpty.isChecked()),
            "null_name": self.null_name(),
            "shared": self.comboShared.currentData() or "",
            "layers": layers,
            "groups": groups,
        }

    def _apply_config(self, data, quiet=False):
        if not isinstance(data, dict) or not isinstance(data.get("layers"), list):
            if not quiet:
                QMessageBox.warning(self, tr("导入配置"), tr("这个文件不是导出 KMZ 的配置。"))
            return False
        self._block = True
        unmatched = []
        try:
            if "summary" in data:
                self.chkSummary.setChecked(bool(data.get("summary")))
            if "empty" in data:
                self.chkEmpty.setChecked(bool(data.get("empty")))
            if data.get("null_name"):
                self.editNullName.setText(str(data.get("null_name")).strip() or "NULL")
            pending = {}
            for rec in data.get("layers") or []:
                if isinstance(rec, dict):
                    pending.setdefault(rec.get("legend") or "", []).append(rec)
            group_by_path = {}
            group_by_name = {}
            for rec in data.get("groups") or []:
                if not isinstance(rec, dict):
                    continue
                group_by_path.setdefault(rec.get("path") or "", []).append(rec)
                group_by_name.setdefault(rec.get("legend") or "", []).append(rec)

            def take(bucket, key):
                items = bucket.get(key) or []
                if not items:
                    return None
                return items.pop(0)

            def take_group(path, legend):
                rec = take(group_by_path, path)
                if rec is not None:
                    names = group_by_name.get(rec.get("legend") or "") or []
                    if rec in names:
                        names.remove(rec)
                    return rec
                return take(group_by_name, legend)

            def walk(item):
                for i in range(item.childCount()):
                    child = item.child(i)
                    kind = child.data(0, Qt.UserRole + 1)
                    legend = child.data(0, Qt.UserRole + 7) or ""
                    if kind == "group":
                        rec = take_group(child.data(0, Qt.UserRole) or "", legend)
                        if rec is not None and "export_name" in rec:
                            edit = self.tree.itemWidget(child, 3)
                            if edit is not None:
                                edit.setText(rec.get("export_name") or "")
                        walk(child)
                        continue
                    rec = take(pending, legend)
                    if rec is None:
                        continue
                    child.setCheckState(0, Qt.Checked if rec.get("checked", True) else Qt.Unchecked)
                    if "export_name" in rec:
                        edit = self.tree.itemWidget(child, 3)
                        if edit is not None:
                            edit.setText(rec.get("export_name") or "")
                    fields = list(child.data(0, Qt.UserRole + 3) or [])
                    display = rec.get("display_field") or ""
                    actual = display if display in fields else (_kmz_field_for_key(fields, display) or "")
                    self._select_combo(self.tree.itemWidget(child, 4), actual)
                    split = rec.get("split")
                    if split is None:
                        split = ""
                    if split and split != "qgis" and split not in fields:
                        split = _kmz_field_for_key(fields, split) or ""
                    if split == "qgis" and not child.data(0, Qt.UserRole + 8):
                        split = ""
                    self._select_split(self.tree.itemWidget(child, 5), split)
                    child.setData(0, Qt.UserRole + 6, _kmz_merge_field_specs(fields, rec.get("fields")))

            walk(self.tree.invisibleRootItem())
            for leftover in pending.values():
                for rec in leftover:
                    name = rec.get("legend") or ""
                    if name and name not in unmatched:
                        unmatched.append(name)
            shared = data.get("shared") or ""
            idx = self.comboShared.findData(shared)
            if idx < 0 and shared:
                idx = self.comboShared.findData(str(shared).casefold())
            self.comboShared.blockSignals(True)
            self.comboShared.setCurrentIndex(idx if idx >= 0 else 0)
            self.comboShared.blockSignals(False)
            self._sync_all_parents()
            self._refresh_marks()
            self._refresh_unconfigured()
        finally:
            self._block = False
        if quiet:
            return True
        if unmatched:
            QMessageBox.information(
                self,
                tr("导入配置"),
                tr("这些图层当前工程里没有，已跳过：\n{0}").format("\n".join(unmatched[:12])),
            )
        else:
            QMessageBox.information(self, tr("导入配置"), tr("配置已套用。"))
        return True

    def _restore_last(self):
        s = self._settings()
        if s is None:
            return
        raw = s.value("kmzExportLastConfig", "")
        s.endGroup()
        if not raw:
            return
        try:
            data = json.loads(str(raw))
        except Exception:
            return
        self._apply_config(data, quiet=True)

    def _config_start(self, filename):
        parent = self.parent()
        start_dir = ""
        if parent is not None and hasattr(parent, "_project_home_dir"):
            start_dir = parent._project_home_dir() or ""
        if start_dir:
            return os.path.join(start_dir, filename)
        return filename

    def _export_config(self):
        path, _selected = QFileDialog.getSaveFileName(
            self, "导出配置", self._config_start("导出KMZ配置.json"), "JSON (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._snapshot(), handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.warning(self, tr("导出配置"), tr("没有写成文件：{0}").format(exc))
            return
        QMessageBox.information(self, tr("导出配置"), path)

    def _import_config(self):
        path, _selected = QFileDialog.getOpenFileName(
            self, "导入配置", self._config_start(""), "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            QMessageBox.warning(self, tr("导入配置"), tr("没有读成配置：{0}").format(exc))
            return
        self._apply_config(data, quiet=False)

    def _accept_export(self):
        if not self.plan()["layers"]:
            QMessageBox.warning(self, tr("导出 KMZ"), tr("请至少勾选一个图层。"))
            return
        proj = QgsProject.instance()
        base_name = (proj.baseName() or "导出").strip() or "导出"
        parent = self.parent()
        start_dir = ""
        if parent is not None and hasattr(parent, "_project_home_dir"):
            start_dir = parent._project_home_dir() or ""
        s = self._settings()
        last_dir = ""
        if s is not None:
            last_dir = str(s.value("kmzExportDir", "") or "")
            s.endGroup()
        if last_dir and os.path.isdir(last_dir):
            default_path = os.path.join(last_dir, base_name + ".kmz")
        else:
            default_path = os.path.join(start_dir, base_name + ".kmz") if start_dir else (base_name + ".kmz")
        out_path, selected = QFileDialog.getSaveFileName(
            self, tr("导出 KMZ / KML"), default_path, "KMZ (*.kmz);;KML (*.kml)"
        )
        if not out_path:
            return
        low = out_path.lower()
        if not low.endswith(".kmz") and not low.endswith(".kml"):
            out_path += ".kml" if (selected or "").startswith("KML") else ".kmz"
        folder = os.path.dirname(out_path) or "."
        if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
            QMessageBox.warning(self, tr("导出 KMZ"), tr("这个文件夹不能写入。"))
            return
        self.output_path = out_path
        saved = self._settings()
        if saved is not None:
            saved.setValue("kmzExportDir", folder)
            saved.endGroup()
        self._remember(False)
        if self._on_export is not None:
            self._on_export(self)

