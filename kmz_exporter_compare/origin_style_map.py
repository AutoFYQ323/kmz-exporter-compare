# -*- coding: utf-8 -*-
import html
import json
import os

from qgis.PyQt.QtCore import QEvent, QRect, QSettings, QSize, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStyle, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import QgsProject, QgsSymbolLayerUtils, QgsVectorLayer

from .qtutil import header_mode, run_dialog
from .button_marks import decorate_button
from .i18n import tr

from .engine import (
    _export_vector_tree,
    _kmz_feature_count,
    _kmz_layer_classified,
    _kmz_match_name_field,
    _kmz_path_key,
    _kmz_stamp_tree,
    _style_map_auto_match,
    _style_map_path_text,
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


class _OneLineCheck(QCheckBox):
    """One row of options. A title that does not fit is shortened; hover shows it all."""

    def __init__(self, text, parent=None):
        super(_OneLineCheck, self).__init__(text, parent)
        self._full = text
        self._note = ""
        self._applying = False
        self.setMinimumWidth(48)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_full(self, text, note=""):
        self._full = text or ""
        self._note = note or ""
        self._apply()

    def minimumSizeHint(self):
        hint = super(_OneLineCheck, self).minimumSizeHint()
        return QSize(48, hint.height())

    def resizeEvent(self, event):
        super(_OneLineCheck, self).resizeEvent(event)
        self._apply()

    def _apply(self):
        if self._applying or not self._full:
            return
        self._applying = True
        width = self.contentsRect().width() - 34
        if width < 16:
            width = max(16, self.width() - 30)
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width)
        if self.text() != shown:
            self.setText(shown)
        tip = self._full
        if self._note and self._note != self._full:
            tip = self._full + "\n" + self._note
        self.setToolTip(tip)
        self._applying = False


class KmzStyleMapDialog(QDialog):
    """A/B 图层名匹配页：一参考行选一个源图层；自动（含模糊、须唯一）+ 手改 + 保存。"""

    _SOURCE_COLORS = {
        "精确": QColor("#e8f5e9"),
        "去尾": QColor("#e8f5e9"),
        "模糊": QColor("#fff8e1"),
        "手动": QColor("#e3f2fd"),
        "已保存": QColor("#e3f2fd"),
    }
    _UNMATCHED_COLOR = QColor("#ffebee")
    _COMBO_STYLE = (
        "QComboBox { padding: 1px 8px; min-height: 22px; max-height: 26px;"
        " min-width: 0px; border: 1px solid #c8e6c9; border-radius: 4px; background: #fff; }"
        "QComboBox::drop-down { width: 18px; border: none; }"
    )

    _FOLDER_NAME_BG = QColor("#90caf9")
    _FOLDER_ROW_BG = QColor("#e3f2fd")
    _FOLDER_NAME_FG = QColor("#0d47a1")

    def __init__(self, parent, a_rows, b_rows, last_map_path=None, use_ref_structure=True,
                 use_source_root_name=True, source_root_name="", ref_root_name=""):
        super(KmzStyleMapDialog, self).__init__(parent)
        self.setWindowTitle("图层名称匹配")
        self.setSizeGripEnabled(True)
        popup = getattr(parent, "POPUP_STYLE", "") if parent is not None else ""
        self.setStyleSheet(popup + """
            QTableWidget { gridline-color: #e0f2e0; }
            QHeaderView::section { background: #e8f5e9; padding: 6px 8px; border: none; }
        """)
        self.setMinimumSize(640, 420)
        self.resize(800, 700)
        self._load_match_size()
        self._a_rows = list(a_rows or [])
        self._source_root_name = (source_root_name or "").strip()
        self._ref_root_name = (ref_root_name or "").strip()
        self._b_rows = list(b_rows or [])
        if not any(r.get("is_doc_root") for r in self._b_rows):
            self._b_rows.insert(0, {
                "name": "最外层",
                "display": "最外层",
                "path": (),
                "level": -1,
                "geom": "—",
                "count": 0,
                "is_layer": False,
                "is_doc_root": True,
            })
        self._combos = []
        self._source_items = []
        self._filling = False
        self.map_path = last_map_path or ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.chkRefStructure = _OneLineCheck("按参考的结构与名称输出")
        self.chkRefStructure.setChecked(bool(use_ref_structure))
        self.chkRefStructure.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.chkRefStructure.setToolTip(
            "开启：输出的文件夹结构与图层名与参考一致；数据只来自源图层；"
            "未匹配的源图层不导出；参考中没有对应源数据的图层保留空文件夹和样式，不含参考原要素。"
            "关闭：结构与图层名仍来自源图层。"
        )

        self.lblUnused = QLabel("未匹配源图层：")
        self.lblUnused.setWordWrap(True)
        self.lblUnused.setTextFormat(Qt.TextFormat.RichText)
        self.lblUnused.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lblUnused.setStyleSheet(
            "background:#fafafa; border: none; padding: 6px 8px; color:#37474f;"
        )
        unusedBox = QScrollArea()
        unusedBox.setWidget(self.lblUnused)
        unusedBox.setWidgetResizable(True)
        unusedBox.setMinimumHeight(56)
        unusedBox.setMaximumHeight(96)
        unusedBox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        unusedBox.setFrameShape(QFrame.Shape.StyledPanel)
        unusedBox.setStyleSheet(
            "QScrollArea { background:#fafafa; border: 1px solid #c8e6c9; border-radius: 6px; }"
        )
        layout.addWidget(unusedBox)

        self.chkFuzzy = _OneLineCheck("模糊匹配")
        self.chkFuzzy.setChecked(True)
        self.chkFuzzy.setToolTip("用于「自动匹配」：共有足够长的词，或一方名称包含另一方，且只能唯一配对时才自动填入。")
        self.chkGeomFilter = _OneLineCheck("仅显示同类型源图层")
        self.chkGeomFilter.setChecked(True)
        self.chkGeomFilter.setToolTip("开启时：左边是线，右边下拉只列出线；点、面同理。关闭后列出全部源图层。")
        self.chkGeomFilter.toggled.connect(self._on_geom_filter_toggled)
        self.chkHideMatched = _OneLineCheck("隐藏已匹配源图层")
        self.chkHideMatched.setChecked(True)
        self.chkHideMatched.setToolTip("开启时：已经配给某一参考图层的源图层，不再出现在其它行的下拉里。")
        self.chkHideMatched.toggled.connect(self._on_geom_filter_toggled)
        self.chkSourceRoot = _OneLineCheck("最外层名称用源KMZ")
        self.chkSourceRoot.setChecked(bool(use_source_root_name))
        self.chkSourceRoot.setToolTip(
            "开启：输出最外层用源 KMZ 的文件名（你选的那个源图层文件）。"
            "关闭：沿用参考 KMZ 的名称（如 QGIS Export）。"
        )
        self.chkSourceRoot.toggled.connect(self._on_source_root_toggled)
        self._load_saved_flags()
        from .i18n import tr
        for box in (
            self.chkRefStructure, self.chkFuzzy, self.chkGeomFilter,
            self.chkHideMatched, self.chkSourceRoot,
        ):
            source = box.text()
            box.setProperty("msgid", source)
            note = box.toolTip()
            if note:
                box.setProperty("tip", note)
                note = tr(note)
            box.set_full(tr(source), note)
        self.setWindowTitle(tr("图层名称匹配"))
        from .i18n import language_changed
        language_changed().connect(self._refresh_option_labels)

        chkRow = QHBoxLayout()
        chkRow.setSpacing(8)
        for box in (
            self.chkRefStructure, self.chkFuzzy, self.chkGeomFilter,
            self.chkHideMatched, self.chkSourceRoot,
        ):
            chkRow.addWidget(box, 1)
        layout.addLayout(chkRow)

        btnAuto = self._make_action_button("自动匹配", "#1976d2", "#1565c0", QStyle.StandardPixmap.SP_BrowserReload)
        btnAuto.clicked.connect(self._auto_match)
        btnSave = self._make_action_button("保存配置", "#1565c0", "#0d47a1", QStyle.StandardPixmap.SP_DialogSaveButton)
        btnSave.clicked.connect(self._save_page_config)
        btnOk = self._make_action_button("导出KMZ/KML", "#43a047", "#2e7d32", QStyle.StandardPixmap.SP_DialogOkButton)
        btnOk.clicked.connect(self._on_accept)
        for button in (btnAuto, btnSave, btnOk):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            button.setMinimumHeight(44)
        btnRow = QHBoxLayout()
        btnRow.setSpacing(8)
        btnRow.addWidget(btnAuto, 1)
        btnRow.addWidget(btnSave, 1)
        btnRow.addWidget(btnOk, 1)
        layout.addLayout(btnRow)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            tr("参考图层"), tr("几何"), tr("要素"), tr("源图层"), tr("来源"),
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setMinimumHeight(180)
        self.table.setShowGrid(True)
        try:
            self.table.setSizeAdjustPolicy(QAbstractItemView.SizeAdjustPolicy.AdjustIgnored)
        except Exception:  # nosec B110
            pass
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, header_mode("Stretch"))
        header.setSectionResizeMode(1, header_mode("ResizeToContents"))
        header.setSectionResizeMode(2, header_mode("ResizeToContents"))
        header.setSectionResizeMode(3, header_mode("Stretch"))
        header.setSectionResizeMode(4, header_mode("Fixed"))
        self.table.setColumnWidth(4, 64)
        layout.addWidget(self.table, 1)

        self.lblSummary = QLabel("")
        self.lblSummary.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(self.lblSummary)

        self._build_rows()
        self._auto_match()
        from .button_marks import watch_button_fit
        watch_button_fit(self)

    def _load_saved_flags(self):
        settings = QSettings()
        settings.beginGroup("KMZExporterCompare")

        def flag(key, default):
            raw = settings.value(key, None)
            if raw is None or raw == "":
                return default
            return str(raw).strip().lower() not in ("0", "false", "no")

        self.chkFuzzy.setChecked(flag("kmzManualFuzzy", True))
        self.chkGeomFilter.setChecked(flag("kmzManualGeomFilter", True))
        self.chkHideMatched.setChecked(flag("kmzManualHideMatched", True))
        settings.endGroup()

    def _make_action_button(self, text, bg, hover, icon_std):
        from .button_marks import plain_button_text, wrap_button_text
        from .i18n import tr

        shown = plain_button_text(tr(text))
        btn = QPushButton(wrap_button_text(shown))
        btn.setProperty("msgid", text)
        btn.setProperty("fullText", shown)
        btn.setIcon(self.style().standardIcon(icon_std))
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setAutoDefault(False)
        btn.setDefault(False)
        btn.setStyleSheet(
            "QPushButton {{ background: {bg}; color: #fff; padding: 6px 10px;"
            " border: none; border-radius: 8px; font-weight: bold; min-width: 0px; }}"
            "QPushButton:hover {{ background: {hover}; }}"
            "QPushButton:pressed {{ background: {hover}; }}".format(bg=bg, hover=hover)
        )
        decorate_button(btn, text=text)
        return btn

    def _load_match_size(self):
        settings = QSettings()
        settings.beginGroup("KMZExporterCompare")
        raw = str(settings.value("size/manualMatch", "") or "")
        settings.endGroup()
        parts = raw.split(",")
        if len(parts) == 2:
            try:
                self.resize(max(640, int(parts[0])), max(420, int(parts[1])))
            except ValueError:
                pass

    def _save_match_size(self):
        settings = QSettings()
        settings.beginGroup("KMZExporterCompare")
        settings.setValue("size/manualMatch", "{0},{1}".format(self.width(), self.height()))
        settings.endGroup()

    def closeEvent(self, event):
        self._save_match_size()
        super(KmzStyleMapDialog, self).closeEvent(event)

    def showEvent(self, event):
        super(KmzStyleMapDialog, self).showEvent(event)
        self._fit_option_labels()

    def resizeEvent(self, event):
        super(KmzStyleMapDialog, self).resizeEvent(event)
        self._fit_option_labels()

    def _option_boxes(self):
        return (
            self.chkRefStructure, self.chkFuzzy, self.chkGeomFilter,
            self.chkHideMatched, self.chkSourceRoot,
        )

    def _refresh_option_labels(self, *_args):
        from .i18n import tr

        for box in self._option_boxes():
            source = str(box.property("msgid") or "")
            note = str(box.property("tip") or "")
            box.set_full(tr(source) if source else box._full, tr(note) if note else "")

    def _fit_option_labels(self):
        for box in self._option_boxes():
            box._apply()

    def _save_page_config(self):
        from .i18n import tr

        parent = self.parent()
        if parent is not None:
            parent._kmz_manual_use_ref = self.chkRefStructure.isChecked()
            parent._kmz_manual_use_source_root = self.chkSourceRoot.isChecked()
        settings = QSettings()
        settings.beginGroup("KMZExporterCompare")
        settings.setValue("kmzManualUseRefStructure", "true" if self.chkRefStructure.isChecked() else "false")
        settings.setValue("kmzManualUseSourceRoot", "true" if self.chkSourceRoot.isChecked() else "false")
        settings.setValue("kmzManualFuzzy", "true" if self.chkFuzzy.isChecked() else "false")
        settings.setValue("kmzManualGeomFilter", "true" if self.chkGeomFilter.isChecked() else "false")
        settings.setValue("kmzManualHideMatched", "true" if self.chkHideMatched.isChecked() else "false")
        settings.endGroup()
        QMessageBox.information(self, tr("保存配置"), tr("已保存"))

    def _a_combo_label(self, row):
        return "{}  [{}·{}]".format(row["name"], row.get("geom") or "—", row.get("count") or 0)

    def _folder_right_text(self, brow):
        if brow.get("is_doc_root"):
            if self.chkSourceRoot.isChecked():
                return self._source_root_name or tr("（源KMZ文件名）")
            return self._ref_root_name or tr("（沿用参考）")
        return tr("（文件夹）")

    def _folder_label_style(self, brow):
        if brow.get("is_doc_root") and self.chkSourceRoot.isChecked():
            return (
                "color: #1b5e20; padding-left: 8px; font-weight: bold; background: #c8e6c9;"
            )
        return "color: #0d47a1; padding-left: 8px; font-weight: bold; background: #e3f2fd;"

    def _on_source_root_toggled(self, _checked=None):
        for i, brow in enumerate(self._b_rows):
            if not brow.get("is_doc_root"):
                continue
            w = self.table.cellWidget(i, 3)
            if isinstance(w, QLabel):
                w.setText(self._folder_right_text(brow))
                w.setStyleSheet(self._folder_label_style(brow))
                w.setToolTip(self._folder_right_text(brow))

    def _layer_b_rows(self):
        return [r for r in self._b_rows if r.get("is_layer", False)]

    def _a_row_by_name(self, name):
        for r in self._a_rows:
            if r.get("name") == name:
                return r
        return None

    def _fill_source_combo(self, combo, b_geom=None, keep_name="", used_others=None):
        """Refill an existing source combo in place. Recreating cell widgets
        leaves orphan QComboBoxes at the table viewport origin (top-left)."""
        filter_on = bool(getattr(self, "chkGeomFilter", None) and self.chkGeomFilter.isChecked())
        hide_used = bool(getattr(self, "chkHideMatched", None) and self.chkHideMatched.isChecked())
        used_others = used_others or set()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("（不匹配）", "")
        for arow in self._a_rows:
            a_name = arow.get("name") or ""
            if hide_used and a_name and a_name != keep_name and a_name in used_others:
                continue
            if filter_on and a_name != keep_name and not _style_map_geom_filter_ok(b_geom, arow.get("geom")):
                continue
            combo.addItem(self._a_combo_label(arow), a_name)
        if keep_name and combo.findData(keep_name) < 0:
            arow = self._a_row_by_name(keep_name)
            if arow:
                combo.addItem(self._a_combo_label(arow), keep_name)
            else:
                combo.addItem(keep_name, keep_name)
        idx = combo.findData(keep_name) if keep_name else 0
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _make_source_combo(self, b_geom=None, keep_name="", used_others=None):
        combo = NoWheelComboBox(self.table)
        combo.setStyleSheet(self._COMBO_STYLE)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setFixedHeight(26)
        combo.setMaxVisibleItems(16)
        self._fill_source_combo(combo, b_geom, keep_name, used_others)
        combo.currentIndexChanged.connect(self._on_combo_changed)
        return combo

    def _purge_orphan_combos(self):
        keep = []
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 3)
            if isinstance(w, QComboBox):
                keep.append(w)
        vp = self.table.viewport()
        if vp is None:
            return
        for child in list(vp.findChildren(QComboBox)):
            if child in keep:
                continue
            child.hide()
            child.setParent(None)
            child.deleteLater()

    def _on_geom_filter_toggled(self, _checked=None):
        self._rebuild_source_combos()

    def _rebuild_source_combos(self):
        used_by_row = []
        for combo in self._combos:
            if combo is None:
                used_by_row.append("")
            elif combo.currentIndex() >= 0:
                used_by_row.append(combo.currentData() or "")
            else:
                used_by_row.append("")
        self._filling = True
        for i, combo in enumerate(self._combos):
            if combo is None:
                continue
            keep = used_by_row[i] or ""
            used_others = set(n for j, n in enumerate(used_by_row) if j != i and n)
            self._fill_source_combo(
                combo, self._b_rows[i].get("geom"), keep_name=keep, used_others=used_others
            )
        self._filling = False
        self._purge_orphan_combos()
        self._refresh_summary()

    def _build_rows(self):
        self.table.setRowCount(len(self._b_rows))
        self._combos = []
        self._source_items = []
        for i, brow in enumerate(self._b_rows):
            is_layer = brow.get("is_layer", False)
            item_name = QTableWidgetItem(brow.get("display") or brow.get("name") or "")
            item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if brow.get("is_doc_root"):
                item_name.setText(tr("最外层"))
                item_name.setToolTip(tr("输出 KMZ 最外层（Document）名称，不参与图层匹配。"))
            else:
                path_tip = _style_map_path_text(brow.get("path") or (brow.get("name"),))
                item_name.setToolTip(path_tip)
            self.table.setItem(i, 0, item_name)
            item_geom = QTableWidgetItem(tr(brow.get("geom") or "—") if is_layer else tr("文件夹"))
            item_geom.setFlags(item_geom.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 1, item_geom)
            item_cnt = QTableWidgetItem(str(brow.get("count") or 0) if is_layer else "")
            item_cnt.setFlags(item_cnt.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 2, item_cnt)

            if is_layer:
                combo = self._make_source_combo(brow.get("geom"))
                self.table.setCellWidget(i, 3, combo)
                self._combos.append(combo)
            else:
                folder_lbl = QLabel(self._folder_right_text(brow))
                folder_lbl.setStyleSheet(self._folder_label_style(brow))
                folder_lbl.setToolTip(self._folder_right_text(brow))
                self.table.setCellWidget(i, 3, folder_lbl)
                self._combos.append(None)

            src_item = QTableWidgetItem("" if is_layer else "")
            src_item.setFlags(src_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            src_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 4, src_item)
            self._source_items.append(src_item)
            self.table.setRowHeight(i, 30)
            if not is_layer:
                self._paint_folder_row(i)
        self._purge_orphan_combos()
        self._refresh_summary()

    def _on_combo_changed(self, _idx=None):
        if self._filling:
            return
        combo = self.sender()
        if combo not in self._combos or combo is None:
            return
        row = self._combos.index(combo)
        a_name = combo.currentData() if combo.currentIndex() >= 0 else ""
        if a_name:
            self._filling = True
            for i, other in enumerate(self._combos):
                if other is None or i == row:
                    continue
                if other.currentData() == a_name:
                    self._set_row(i, "", "")
            self._filling = False
        self._source_items[row].setText(tr("手动") if a_name else "")
        self._color_row(row)
        self._rebuild_source_combos()

    def _set_row(self, row, a_name, source):
        combo = self._combos[row]
        if combo is None:
            return
        combo.blockSignals(True)
        idx = combo.findData(a_name) if a_name else 0
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)
        self._source_items[row].setText(tr(source) if a_name else "")
        self._color_row(row)

    def _paint_folder_row(self, row):
        name_item = self.table.item(row, 0)
        if name_item is not None:
            name_item.setBackground(QBrush(self._FOLDER_NAME_BG))
            name_item.setForeground(QBrush(self._FOLDER_NAME_FG))
            font = QFont(name_item.font())
            font.setBold(True)
            name_item.setFont(font)
        rest = QBrush(self._FOLDER_ROW_BG)
        for col in (1, 2, 4):
            it = self.table.item(row, col)
            if it is not None:
                it.setBackground(rest)
                it.setForeground(QBrush(self._FOLDER_NAME_FG))

    def _color_row(self, row):
        if not (self._b_rows[row].get("is_layer", False)):
            self._paint_folder_row(row)
            return
        source = (self._source_items[row].text() or "").strip()
        combo = self._combos[row]
        a_name = combo.currentData() if combo is not None and combo.currentIndex() >= 0 else ""
        if a_name:
            color = self._SOURCE_COLORS.get(source, QColor("#ffffff"))
        else:
            color = QColor("#ffffff")
        brush = QBrush(color)
        for col in (0, 1, 2, 4):
            item = self.table.item(row, col)
            if item is not None:
                item.setBackground(brush)

    def _refresh_summary(self):
        matched = 0
        used_a = set()
        layer_count = 0
        for i, combo in enumerate(self._combos):
            if combo is None:
                continue
            layer_count += 1
            a_name = combo.currentData()
            if a_name:
                matched += 1
                used_a.add(a_name)
        empty_b = layer_count - matched
        unused_a = len(self._a_rows) - len(used_a)
        self.lblSummary.setText(
            tr("参考图层 {0} 个，已匹配 {1}，空 {2}；源图层 {3} 个，未使用 {4}。").format(
                layer_count, matched, empty_b, len(self._a_rows), unused_a
            )
        )
        self._refresh_unused_box()

    def _refresh_unused_box(self):
        unused = self.unmatched_names()
        dups = set(r.get("name") for r in self._a_rows if r.get("duplicate"))
        if not unused:
            self.lblUnused.setText(tr("未匹配源图层：无"))
            return
        parts = []
        for name in unused:
            esc = html.escape(name)
            if name in dups:
                parts.append(
                    '<span style="color:#c62828; font-weight:bold;">{0}{1}</span>'.format(esc, tr("（重复）"))
                )
            else:
                parts.append('<span style="color:#37474f;">{}</span>'.format(esc))
        self.lblUnused.setText(tr("未匹配源图层（{0}）：{1}").format(len(unused), "、".join(parts)))

    def _auto_match(self):
        mapping = _style_map_auto_match(
            self._a_rows, self._layer_b_rows(), fuzzy=self.chkFuzzy.isChecked()
        )
        used_a = set()
        self._filling = True
        for i, brow in enumerate(self._b_rows):
            if not brow.get("is_layer", False):
                continue
            a_hit = None
            reason = ""
            filter_on = bool(getattr(self, "chkGeomFilter", None) and self.chkGeomFilter.isChecked())
            for a_name, pair in mapping.items():
                b_name, rsn = pair
                if b_name != brow["name"] or a_name in used_a:
                    continue
                arow = self._a_row_by_name(a_name)
                if filter_on and arow and not _style_map_geom_filter_ok(brow.get("geom"), arow.get("geom")):
                    continue
                a_hit, reason = a_name, rsn
                break
            if a_hit:
                used_a.add(a_hit)
                self._set_row(i, a_hit, reason)
            else:
                self._set_row(i, "", "")
        self._filling = False
        self._rebuild_source_combos()

    def name_map(self):
        out = {}
        for arow in self._a_rows:
            out[arow["name"]] = ""
        for i, brow in enumerate(self._b_rows):
            combo = self._combos[i]
            if combo is None:
                continue
            a_name = combo.currentData() if combo.currentIndex() >= 0 else ""
            if a_name:
                out[a_name] = brow["name"]
        return out

    def ref_layer_assignments(self):
        out = []
        for i, brow in enumerate(self._b_rows):
            if not brow.get("is_layer", False):
                continue
            combo = self._combos[i]
            a_name = combo.currentData() if combo is not None and combo.currentIndex() >= 0 else ""
            out.append({
                "path": list(brow.get("path") or (brow.get("name"),)),
                "name": brow.get("name") or "",
                "source": a_name or "",
            })
        return out

    def unmatched_count(self):
        return len(self.unmatched_names())

    def unmatched_names(self):
        used_a = set()
        for combo in self._combos:
            if combo is None:
                continue
            a_name = combo.currentData()
            if a_name:
                used_a.add(a_name)
        return [r.get("name") or "" for r in self._a_rows if (r.get("name") or "") not in used_a]

    def empty_ref_names(self):
        names = []
        for i, brow in enumerate(self._b_rows):
            if not brow.get("is_layer", False):
                continue
            combo = self._combos[i]
            a_name = combo.currentData() if combo is not None and combo.currentIndex() >= 0 else ""
            if not a_name:
                names.append(_style_map_path_text(brow.get("path") or (brow.get("name"),)) or (brow.get("name") or ""))
        return names

    def use_ref_structure(self):
        return self.chkRefStructure.isChecked()

    def use_source_root_name(self):
        return self.chkSourceRoot.isChecked()

    def _pairs_payload(self):
        pairs = []
        for i, brow in enumerate(self._b_rows):
            combo = self._combos[i]
            if combo is None:
                continue
            src = combo.currentData() if combo.currentIndex() >= 0 else ""
            if src:
                pairs.append({
                    "source": src,
                    "ref": brow.get("name") or "",
                    "ref_path": list(brow.get("path") or (brow.get("name"),)),
                })
        return {"version": 1, "pairs": pairs}

    def _apply_pairs(self, pairs, source_label="已保存"):
        a_names = set(r["name"] for r in self._a_rows)
        path_index = {}
        name_index = {}
        for i, r in enumerate(self._b_rows):
            if not r.get("is_layer", False):
                continue
            path_index[tuple(r.get("path") or (r.get("name"),))] = i
            name_index.setdefault(r.get("name") or "", i)
        assigned_rows = set()
        used_src = set()
        extra_src = []
        missing_src = []
        missing_ref = []
        planned = []
        for p in pairs or []:
            src = (p.get("source") or "").strip()
            ref = (p.get("ref") or "").strip()
            ref_path = p.get("ref_path")
            if not src:
                continue
            if src not in a_names:
                missing_src.append(src)
                continue
            row = None
            if isinstance(ref_path, (list, tuple)) and ref_path:
                row = path_index.get(tuple(ref_path))
            if row is None and ref:
                row = name_index.get(ref)
            if row is None:
                missing_ref.append("{} → {}".format(src, ref or ref_path))
                continue
            if row in assigned_rows or src in used_src:
                extra_src.append("{} → {}".format(src, ref))
                continue
            assigned_rows.add(row)
            used_src.add(src)
            planned.append((row, src))
        self._filling = True
        for i, _brow in enumerate(self._b_rows):
            self._set_row(i, "", "")
        for row, src in planned:
            self._set_row(row, src, source_label)
        self._filling = False
        self._rebuild_source_combos()
        notes = []
        if missing_src:
            notes.append(tr("当前源图层中不存在：{0}").format("、".join(missing_src)))
        if missing_ref:
            notes.append(tr("当前参考图层中不存在：{0}").format("、".join(missing_ref)))
        if extra_src:
            notes.append(tr("同一参考图层有多个源，已只保留一个：{0}").format("、".join(extra_src)))
        return notes

    def _save_map(self):
        start = self.map_path or ""
        path, _ = QFileDialog.getSaveFileName(self, tr("保存匹配表"), start, "JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path = path + ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._pairs_payload(), f, ensure_ascii=False, indent=2)
            self.map_path = path
            mb = QMessageBox(self)
            mb.setWindowTitle(tr("提示"))
            mb.setText(tr("已保存匹配表。"))
            mb.setIcon(QMessageBox.Icon.Information)
            run_dialog(mb)
        except Exception as e:
            mb = QMessageBox(self)
            mb.setWindowTitle(tr("错误"))
            mb.setText(tr("保存失败：{}").format(str(e)))
            mb.setIcon(QMessageBox.Icon.Warning)
            run_dialog(mb)

    def _load_map(self):
        start = self.map_path or ""
        path, _ = QFileDialog.getOpenFileName(self, tr("读取匹配表"), start, "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pairs = data.get("pairs") if isinstance(data, dict) else None
            if not isinstance(pairs, list):
                raise ValueError(tr("文件格式无效，缺少 pairs"))
            notes = self._apply_pairs(pairs, "已保存")
            self.map_path = path
            if notes:
                mb = QMessageBox(self)
                mb.setWindowTitle(tr("提示"))
                mb.setText(tr("已读取匹配表，部分条目未能套用：\n{0}").format("\n".join(notes)))
                mb.setIcon(QMessageBox.Icon.Warning)
                run_dialog(mb)
        except Exception as e:
            mb = QMessageBox(self)
            mb.setWindowTitle(tr("错误"))
            mb.setText(tr("读取失败：{}").format(str(e)))
            mb.setIcon(QMessageBox.Icon.Warning)
            run_dialog(mb)

    def _on_accept(self):
        unmatched = self.unmatched_names()
        if self.chkRefStructure.isChecked():
            empty_b = self.empty_ref_names()
            if unmatched or empty_b:
                lines = [
                    tr("已开启「按参考的结构与名称输出」。"),
                    tr("输出目录与图层名与参考一致；数据只来自源图层，参考原要素不会保留。"),
                ]
                if unmatched:
                    lines.append(tr("未匹配的源图层将不导出：{0}").format("、".join(unmatched)))
                if empty_b:
                    lines.append(tr("参考中无源数据的图层将为空（仅保留样式与名称）：{0}").format("、".join(empty_b)))
                lines.append(tr("是否继续？"))
                mb = QMessageBox(self)
                mb.setWindowTitle(tr("确认输出"))
                mb.setIcon(QMessageBox.Icon.Question)
                mb.setText("\n".join(lines))
                btn_yes = mb.addButton(tr("继续"), QMessageBox.ButtonRole.YesRole)
                mb.addButton(tr("返回修改"), QMessageBox.ButtonRole.NoRole)
                mb.setDefaultButton(btn_yes)
                run_dialog(mb)
                if mb.clickedButton() != btn_yes:
                    return
        elif unmatched:
            mb = QMessageBox(self)
            mb.setWindowTitle(tr("未匹配图层"))
            mb.setIcon(QMessageBox.Icon.Question)
            mb.setText(tr("有 {0} 个源图层未匹配，将保留原样式。是否继续？").format(len(unmatched)))
            btn_yes = mb.addButton(tr("继续"), QMessageBox.ButtonRole.YesRole)
            mb.addButton(tr("返回修改"), QMessageBox.ButtonRole.NoRole)
            mb.setDefaultButton(btn_yes)
            run_dialog(mb)
            if mb.clickedButton() != btn_yes:
                return
        self.accept()
