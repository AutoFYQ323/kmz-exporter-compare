# -*- coding: utf-8 -*-
"""The five job pages, laid out like LayerProcess and KMZVSQGIS."""

import json
import os

from qgis.PyQt.QtCore import QEvent, QRect, QSettings, Qt, QVariant
from qgis.PyQt.QtGui import QBrush, QColor, QFont
from qgis.PyQt.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsSpatialIndex,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
    Qgis,
)

from .compare_run import folder_compare_report, geometry_type_report
from .engine import (
    _kml_document_name,
    _kml_source_root_display_name,
    _kmz_get_kml_root,
    _kmz_style_replace,
    _kmz_style_replace_ref_structure,
    _style_map_collect_rows,
    _style_map_collect_tree_rows,
    export_project_kmz,
)
from .origin_export import KmzExportDialog
from .origin_style_map import KmzStyleMapDialog
from .qtutil import run_dialog
from .button_marks import decorate_button, styled_button
from .coord_match import keyword_score as _keyword_score
from .i18n import tr

_SETTINGS = "KMZExporterCompare"
_POPUP = """
QDialog { background-color: #ffffff; }
QLabel { color: #37474f; font-size: 13px; }
QPushButton { background: #81c784; color: #fff; padding: 8px 20px; border-radius: 8px; }
QPushButton:hover { background: #66bb6a; }
QLineEdit { color: #37474f; background: #f1f8e9; padding: 6px; border: 1px solid #c8e6c9; border-radius: 6px; }
"""


class KmzDropFrame(QFrame):
    def __init__(self, parent=None, on_drop=None, suffixes=(".kmz",)):
        super(KmzDropFrame, self).__init__(parent)
        self.on_drop = on_drop
        self.suffixes = tuple(item.lower() for item in suffixes)
        self.setAcceptDrops(True)
        self.setMinimumHeight(52)
        self.setStyleSheet(
            "KmzDropFrame { border: 2px dashed #81c784; border-radius: 10px;"
            " background-color: #f1f8e9; padding: 10px; }"
            "KmzDropFrame:hover { border-color: #66bb6a; background-color: #e8f5e9; }"
            "KmzDropFrame QLabel { background-color: transparent; padding: 2px 4px; }"
        )

    def childEvent(self, event):
        if event.type() == QEvent.Type.ChildAdded and event.child().isWidgetType():
            event.child().installEventFilter(self)
        super(KmzDropFrame, self).childEvent(event)

    def eventFilter(self, obj, event):
        if obj is not self and event.type() in (QEvent.Type.DragEnter, QEvent.Type.Drop):
            if event.type() == QEvent.Type.DragEnter:
                self.dragEnterEvent(event)
            else:
                self.dropEvent(event)
            return True
        return super(KmzDropFrame, self).eventFilter(obj, event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        event.acceptProposedAction()
        urls = event.mimeData().urls()
        if urls and self.on_drop:
            path = urls[0].toLocalFile()
            if path and path.strip().lower().endswith(self.suffixes):
                self.on_drop(path.strip())


def _store():
    settings = QSettings()
    settings.beginGroup(_SETTINGS)
    return settings


def _read(key, fallback=""):
    settings = _store()
    value = settings.value(key, "", type=str) or ""
    settings.endGroup()
    return value or fallback


def _write(key, value):
    settings = _store()
    settings.setValue(key, value)
    settings.endGroup()


def _msg(parent, title, text, warning=False):
    box = QMessageBox(parent)
    box.setStyleSheet(_POPUP)
    box.setWindowTitle(tr(title))
    box.setText(tr(text))
    box.setIcon(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information)
    run_dialog(box)
    if text:
        level = Qgis.MessageLevel.Warning if warning else Qgis.MessageLevel.Info
        QgsMessageLog.logMessage(tr(text), "KMZ Exporter & Compare", level)


def _hint(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    label.setStyleSheet("color: #5d7a8c; font-size: 11px;")
    return label


def _path_label(text):
    label = QLabel(text)
    label.setObjectName("pathValue")
    label.setWordWrap(True)
    label.setStyleSheet("color: #5d7a8c; font-size: 11px;")
    return label


def _show_phrase(text):
    """Translate a status line, including a few counted sentences."""
    import re

    if not isinstance(text, str) or text in ("", "—"):
        return text
    shown = tr(text)
    if shown != text:
        return shown
    match = re.fullmatch(r"已按参考写入\(已写入(\d+)条\)", text)
    if match:
        return tr("已按参考写入(已写入{0}条)").format(match.group(1))
    match = re.fullmatch(r"未找到映射图层 \[(.*)\]", text)
    if match:
        return tr("未找到映射图层 [{0}]").format(match.group(1))
    match = re.fullmatch(r"未匹配图层：(.*)", text)
    if match:
        return tr("未匹配图层：{0}").format(match.group(1))
    match = re.fullmatch(r"未成功图层：(.*)", text)
    if match:
        return tr("未成功图层：{0}").format(match.group(1))
    return text


def show_text_result(parent, text, title):
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr(title))
    dialog.setStyleSheet(_POPUP)
    dialog.setMinimumSize(480, 320)
    dialog.resize(560, 400)
    layout = QVBoxLayout(dialog)
    edit = QTextEdit()
    edit.setReadOnly(True)
    edit.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
    edit.setPlainText(text)
    layout.addWidget(edit)
    row = QHBoxLayout()
    copy = styled_button("复制结果")
    copy.clicked.connect(lambda: (QApplication.clipboard().setText(text), _msg(dialog, "提示", "已复制到剪贴板")))
    export = styled_button("导出报告")

    def _save_report():
        start = _read("namesReportDir") or ""
        path, selected = QFileDialog.getSaveFileName(
            dialog, tr("导出报告"), start, tr("文本 (*.txt);;CSV (*.csv);;所有文件 (*.*)")
        )
        if not path:
            return
        low = path.lower()
        if not low.endswith(".txt") and not low.endswith(".csv"):
            path += ".csv" if selected and "csv" in selected.lower() else ".txt"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as exc:
            _msg(dialog, "导出报告", "没有写成文件：{0}".format(exc), warning=True)
            return
        _write("namesReportDir", os.path.dirname(path))
        _msg(dialog, "导出报告", path)

    export.clicked.connect(_save_report)
    row.addWidget(copy)
    row.addWidget(export)
    row.addStretch(1)
    layout.addLayout(row)
    run_dialog(dialog)


def show_style_result(parent, report_rows, text_summary, title):
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr(title))
    dialog.setStyleSheet(_POPUP)
    dialog.setMinimumSize(720, 380)
    dialog.resize(820, 480)
    layout = QVBoxLayout(dialog)
    tabs = QTabWidget()
    table = QTableWidget()
    table.setColumnCount(8)
    headers = ["名称", "类型", "参考DOC样式", "DOC确认结果", "参考图标样式", "图标确认结果", "要素总数", "已导出"]
    table.setHorizontalHeaderLabels([tr(item) for item in headers])
    table.setRowCount(len(report_rows))
    table.setColumnWidth(0, 180)
    for row_index, row in enumerate(report_rows):
        name = (row.get("level") or 0) * "　" + (row.get("name") or "")
        values = [
            name,
            _show_phrase(row.get("type") or ""),
            tr("是") if row.get("doc_used") is True else (tr("否") if row.get("doc_used") is False else "—"),
            _show_phrase(row.get("doc_verify") or ""),
            tr("是") if row.get("icon_used") is True else (tr("否") if row.get("icon_used") is False else "—"),
            _show_phrase(row.get("icon_verify") or ""),
            str(row.get("total")) if row.get("total") is not None else "—",
            str(row.get("exported")) if row.get("exported") is not None else "—",
        ]
        icon_verify = row.get("icon_verify") or ""
        doc_used = row.get("doc_used")
        icon_used = row.get("icon_used")
        if row.get("type") == "图层":
            if doc_used is not None:
                green = doc_used is True and icon_used is True and "校验未生效" not in icon_verify and "DOC校验未生效" not in (row.get("doc_verify") or "")
                red = doc_used is False
            else:
                green = icon_used is True and "已替换" in icon_verify and "校验未生效" not in icon_verify
                red = icon_used is False and "未匹配（保留原样式）" not in icon_verify
            color = QColor(232, 245, 233) if green else (QColor(255, 235, 238) if red else QColor(255, 253, 231))
            brush = QBrush(color)
        else:
            brush = None
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if brush is not None:
                item.setBackground(brush)
            table.setItem(row_index, column, item)
    tabs.addTab(table, tr("结果表格"))
    detail = QTextEdit()
    detail.setReadOnly(True)
    detail.setPlainText("\n".join(_show_phrase(line) for line in (text_summary or "").split("\n")))
    tabs.addTab(detail, tr("详情"))
    layout.addWidget(tabs)
    buttons = QHBoxLayout()
    copy_table = styled_button("复制表格")

    def _copy_table():
        lines = ["\t".join(tr(item) for item in ("名称", "类型", "参考DOC样式", "DOC确认结果", "参考图标样式", "图标确认结果", "要素总数", "已导出"))]
        for row_index in range(table.rowCount()):
            lines.append("\t".join(table.item(row_index, column).text() for column in range(8)))
        QApplication.clipboard().setText("\n".join(lines))
        _msg(dialog, "提示", "表格已复制到剪贴板")

    copy_table.clicked.connect(_copy_table)
    copy_text = styled_button("复制详情")
    copy_text.clicked.connect(lambda: (QApplication.clipboard().setText(text_summary or ""), _msg(dialog, "提示", "已复制到剪贴板")))
    buttons.addWidget(copy_table)
    buttons.addWidget(copy_text)
    buttons.addStretch(1)
    layout.addLayout(buttons)
    run_dialog(dialog)


def _home_button(host):
    button = styled_button("返回主页面")
    button.clicked.connect(lambda: host.open_page("home"))
    return button


def disconnect_coord_page(host):
    slot = getattr(host, "_coord_crs_slot", None)
    if not slot:
        return
    try:
        QgsProject.instance().crsChanged.disconnect(slot)
    except Exception:  # nosec B110
        pass
    host._coord_crs_slot = None


def reset_saved_settings(host):
    from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox

    box = QMessageBox(host)
    box.setWindowTitle(tr("恢复全部配置"))
    box.setText(tr("将清除本插件记住的路径、导出选项、对比选项和窗口大小。界面语言保持不变。"))
    box.setIcon(QMessageBox.Icon.Warning)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    yes = box.button(QMessageBox.StandardButton.Yes)
    no = box.button(QMessageBox.StandardButton.No)
    if yes is not None:
        yes.setText(tr("确定"))
    if no is not None:
        no.setText(tr("取消"))
    if run_dialog(box) != QMessageBox.StandardButton.Yes:
        return
    text, ok = QInputDialog.getText(host, tr("二次确认"), tr("请输入 OK 确认清空配置："))
    if not ok or text.strip().upper() != "OK":
        return
    store = QSettings()
    store.beginGroup(_SETTINGS)
    for key in list(store.childKeys()):
        if key != "ui_language":
            store.remove(key)
    for group in list(store.childGroups()):
        store.remove(group)
    store.endGroup()
    panel = getattr(host, "_export_panel", None)
    if panel is not None:
        panel.chkSummary.setChecked(True)
        panel.chkEmpty.setChecked(True)
        panel.editNullName.setText("NULL")
    if getattr(host, "_tolerance", None) is not None:
        host._tolerance.setValue(0.00001)
        host._compare_type.setCurrentIndex(1)
        host._save_edit.setChecked(True)
        host._add_result.setChecked(True)
    host._apply_size(host._page_key)
    _msg(host, "提示", "已恢复默认配置。")


def restore_default_window_sizes(host):
    from .dialog import _LAYOUT_ID, _PAGE_SIZE

    store = _store()
    store.setValue("layout", _LAYOUT_ID)
    for key in _PAGE_SIZE:
        store.remove("size/" + key)
    store.remove("size/manualMatch")
    store.endGroup()
    disconnect_coord_page(host)
    host._apply_size(host._page_key)
    _msg(host, "提示", "已恢复各页的默认窗口大小。")


def _half_row(left, right):
    row = QHBoxLayout()
    row.setSpacing(8)
    row.setContentsMargins(0, 0, 0, 0)
    for button in (left, right):
        button.setMinimumHeight(36)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    row.addWidget(left, 1)
    row.addWidget(right, 1)
    return row


BUNDLE_PARTS = (
    ("all", "全部导出"),
    ("export", "导出 KMZ"),
    ("manual", "手动样式"),
    ("coords", "坐标对比"),
)
_BUNDLE_APP = "KMZExporterCompare"
_BUNDLE_NAMES = {
    "all": "全部配置.json",
    "export": "导出KMZ配置.json",
    "manual": "手动样式配置.json",
    "auto": "自动样式配置.json",
    "coords": "坐标对比配置.json",
    "names": "图层对比配置.json",
}


def _bundle_section(host, part):
    if part == "export":
        panel = getattr(host, "_export_panel", None)
        return panel._snapshot() if panel is not None else {}
    if part == "manual":
        return {
            "src": getattr(host, "_kmz_manual_a", "") or "",
            "ref": getattr(host, "_kmz_manual_b", "") or "",
            "map": getattr(host, "_kmz_manual_map_path", "") or "",
            "use_ref": bool(getattr(host, "_kmz_manual_use_ref", True)),
            "use_source_root": bool(getattr(host, "_kmz_manual_use_source_root", True)),
        }
    if part == "auto":
        return {
            "src": getattr(host, "_kmz_style_a", "") or "",
            "ref": getattr(host, "_kmz_style_b", "") or "",
        }
    if part == "coords":
        compare = getattr(host, "_compare_type", None)
        tolerance = getattr(host, "_tolerance", None)
        save_edit = getattr(host, "_save_edit", None)
        return {
            "path": getattr(host, "_coord_file_path", "") or "",
            "compare_type": compare.currentIndex() if compare is not None else 1,
            "tolerance": tolerance.value() if tolerance is not None else 0.00001,
            "save_edit": save_edit.isChecked() if save_edit is not None else True,
        }
    if part == "names":
        if getattr(host, "radioKmzByGeometry", None) is not None and host.radioKmzByGeometry.isChecked():
            mode = "geometry"
        elif getattr(host, "radioKmzName", None) is not None and host.radioKmzName.isChecked():
            mode = "name"
        elif getattr(host, "radioKmzBoth", None) is not None and host.radioKmzBoth.isChecked():
            mode = "both"
        else:
            mode = "count"
        zero = getattr(host, "chkTreatZeroAsNoData", None)
        return {
            "path": getattr(host, "_kmz_path", "") or "",
            "mode": mode,
            "zero": zero.isChecked() if zero is not None else False,
        }
    return {}


def bundle_document(host, part):
    parts = [key for key, _title in BUNDLE_PARTS if key != "all"] if part == "all" else [part]
    data = {"app": _BUNDLE_APP, "part": part}
    for key in parts:
        data[key] = _bundle_section(host, key)
    return data


def _apply_path_pair(setter, src, ref):
    if src and os.path.isfile(src):
        setter("a", src)
    if ref and os.path.isfile(ref):
        setter("b", ref)


def apply_bundle_data(host, data):
    if not isinstance(data, dict):
        return ""
    if data.get("app") != _BUNDLE_APP and isinstance(data.get("layers"), list):
        data = {"app": _BUNDLE_APP, "part": "export", "export": data}
    if data.get("app") != _BUNDLE_APP:
        return ""
    part = data.get("part") or "all"
    keys = [key for key, _title in BUNDLE_PARTS if key != "all"] if part == "all" else [part]
    applied = []
    for key in keys:
        section = data.get(key)
        if not isinstance(section, dict):
            continue
        if key == "export":
            panel = getattr(host, "_export_panel", None)
            if panel is not None and panel._apply_config(section, quiet=True):
                applied.append("导出 KMZ")
        elif key == "manual":
            _apply_path_pair(lambda which, path: _set_manual(host, which, path), section.get("src") or "", section.get("ref") or "")
            host._kmz_manual_map_path = section.get("map") or ""
            host._kmz_manual_use_ref = bool(section.get("use_ref", True))
            host._kmz_manual_use_source_root = bool(section.get("use_source_root", True))
            _write("kmzManualMapPath", host._kmz_manual_map_path)
            _write("kmzManualUseRefStructure", "true" if host._kmz_manual_use_ref else "false")
            _write("kmzManualUseSourceRoot", "true" if host._kmz_manual_use_source_root else "false")
            applied.append("手动样式")
        elif key == "auto":
            _apply_path_pair(lambda which, path: _set_style(host, which, path), section.get("src") or "", section.get("ref") or "")
            applied.append("自动样式")
        elif key == "coords":
            if getattr(host, "_compare_type", None) is not None:
                index = int(section.get("compare_type", 1) or 0)
                host._compare_type.setCurrentIndex(1 if index else 0)
            if getattr(host, "_tolerance", None) is not None:
                host._tolerance.setValue(float(section.get("tolerance", 0.00001) or 0))
            if getattr(host, "_save_edit", None) is not None:
                host._save_edit.setChecked(bool(section.get("save_edit", True)))
            path = section.get("path") or ""
            if path and os.path.isfile(path):
                _set_coord_file(host, path)
            applied.append("坐标对比")
        elif key == "names":
            mode = section.get("mode") or "count"
            radios = {
                "count": getattr(host, "radioKmzCount", None),
                "name": getattr(host, "radioKmzName", None),
                "both": getattr(host, "radioKmzBoth", None),
                "geometry": getattr(host, "radioKmzByGeometry", None),
            }
            radio = radios.get(mode) or radios["count"]
            if radio is not None:
                radio.setChecked(True)
            if getattr(host, "chkTreatZeroAsNoData", None) is not None:
                host.chkTreatZeroAsNoData.setChecked(bool(section.get("zero")))
            path = section.get("path") or ""
            if path and os.path.isfile(path):
                _set_compare_kmz(host, path)
            applied.append("图层对比")
    if not applied:
        return ""
    if part == "all":
        return "全部配置"
    return applied[0]


def save_bundle(host, part):
    start = _read("bundleDir")
    name = tr(_BUNDLE_NAMES.get(part, "配置.json"))
    initial = os.path.join(start, name) if start else name
    path, _selected = QFileDialog.getSaveFileName(host, tr("导出配置"), initial, "JSON (*.json)")
    if not path:
        return
    if not path.lower().endswith(".json"):
        path += ".json"
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(bundle_document(host, part), handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        _msg(host, "导出", tr("没有写成文件：{0}").format(exc), warning=True)
        return
    _write("bundleDir", os.path.dirname(path))
    _msg(host, "导出", path)


def load_bundle(host):
    start = _read("bundleDir")
    path, _selected = QFileDialog.getOpenFileName(host, tr("导入配置"), start, "JSON (*.json)")
    if not path:
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        _msg(host, "导入", tr("没有读成配置：{0}").format(exc), warning=True)
        return
    title = apply_bundle_data(host, data)
    if not title:
        _msg(host, "导入", "认不出这份配置。", warning=True)
        return
    _write("bundleDir", os.path.dirname(path))
    _msg(host, "导入", tr("已导入{0}").format(tr(title)))


def build_export_page(host):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    dialog = KmzExportDialog(
        page,
        embedded=True,
        on_home=lambda: host.open_page("home"),
        on_export=lambda panel: run_export(host, panel),
    )
    host._export_panel = dialog
    layout.addWidget(dialog, 1)
    return page


def run_export(host, dialog):
    selection = dialog.plan()
    if not selection.get("layers"):
        _msg(host, "导出 KMZ", "请至少勾选一个图层。", warning=True)
        return
    total = max(len(selection.get("layers") or {}), 1)
    progress = QProgressDialog(tr("正在导出 KMZ..."), tr("取消"), 0, total, host)
    progress.setWindowTitle(tr("导出 KMZ"))
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    canceled = {"stop": False}

    def on_progress(index, count, name):
        if progress.wasCanceled():
            canceled["stop"] = True
            return False
        progress.setMaximum(max(count, 1))
        progress.setValue(min(index, count))
        progress.setLabelText(tr("正在导出：{0}").format(name or ""))
        QApplication.processEvents()
        return True

    try:
        ok, message = export_project_kmz(
            dialog.output_path,
            bool(dialog.chkSummary.isChecked()),
            include_empty=bool(dialog.chkEmpty.isChecked()),
            on_progress=on_progress,
            selection=selection,
            empty_name=dialog.null_name(),
        )
    except Exception as exc:
        ok, message = False, str(exc)
    finally:
        progress.setValue(progress.maximum())
        progress.close()
    if canceled["stop"]:
        ok, message = False, tr("已取消导出。文件可能不完整。")
    _msg(host, "导出 KMZ" if ok else "导出 KMZ 失败", message, warning=not ok)


def build_names_page(host):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSpacing(10)
    layout.setContentsMargins(8, 8, 8, 8)
    group = QGroupBox("KMZ 图层对比")
    inner = QVBoxLayout(group)
    host.lblKmzPath = _path_label("未选择 KMZ 文件")
    button = styled_button("选择 KMZ 文件")
    button.clicked.connect(lambda: _pick_compare_kmz(host))
    frame = KmzDropFrame(on_drop=lambda path: _set_compare_kmz(host, path))
    frame.setToolTip("可将 KMZ 文件拖入下方虚线框内以自动填入路径")
    drop = QVBoxLayout(frame)
    drop.setSpacing(6)
    drop.setContentsMargins(8, 8, 8, 8)
    drop.addWidget(host.lblKmzPath)
    drop.addWidget(button)
    host.radioKmzCount = QRadioButton("图层的元素数量对比（需精确匹配图层名）")
    host.radioKmzCount.setChecked(True)
    host.radioKmzName = QRadioButton("图层的 Name 字段名称对比（需精确匹配图层名）")
    host.radioKmzBoth = QRadioButton("二者兼对比（需精确匹配图层名）")
    host.radioKmzByGeometry = QRadioButton("按几何类型统计对比（不看图层名）")
    host.chkTreatZeroAsNoData = QCheckBox("将要素数为 0 的图层视为无数据（不勾选时 0 与空均视为一致）")
    host.chkTreatZeroAsNoData.setChecked(False)
    start = styled_button("开始对比")
    start.clicked.connect(lambda: run_names(host))
    actions = _half_row(start, _home_button(host))
    inner.addWidget(frame)
    inner.addSpacing(6)
    inner.addWidget(host.radioKmzCount)
    inner.addWidget(host.radioKmzName)
    inner.addWidget(host.radioKmzBoth)
    inner.addWidget(host.radioKmzByGeometry)
    inner.addWidget(host.chkTreatZeroAsNoData)
    inner.addSpacing(4)
    inner.addLayout(actions)
    layout.addWidget(group)
    layout.addStretch(1)
    host._kmz_path = ""
    saved = _read("kmzPath") or _read("namesPath")
    if saved and os.path.isfile(saved):
        _set_compare_kmz(host, saved, remember=False)
    return page


def _pick_compare_kmz(host):
    start = os.path.dirname(host._kmz_path) if getattr(host, "_kmz_path", "") else ""
    path, _selected = QFileDialog.getOpenFileName(host, "选择 KMZ 文件", start, "KMZ (*.kmz)")
    if path:
        _set_compare_kmz(host, path)


def _set_compare_kmz(host, path, remember=True):
    if not path or not os.path.isfile(path):
        return
    host._kmz_path = path
    host.lblKmzPath.setText(path)
    host.lblKmzPath.setToolTip(path)
    if remember:
        _write("kmzPath", path)


def run_names(host):
    path = getattr(host, "_kmz_path", "")
    if not path or not os.path.isfile(path):
        _msg(host, "提示", "请先选择有效的 KMZ 文件。", warning=True)
        return
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        if host.radioKmzByGeometry.isChecked():
            text = geometry_type_report(path)
        else:
            if host.radioKmzCount.isChecked():
                mode = "count"
            elif host.radioKmzName.isChecked():
                mode = "name"
            else:
                mode = "both"
            text = folder_compare_report(path, mode, host.chkTreatZeroAsNoData.isChecked())
    finally:
        QApplication.restoreOverrideCursor()
    show_text_result(host, text, "KMZ 对比结果")


def _drop_block(title, button_text, on_click, on_drop):
    label = _path_label(title)
    button = styled_button(button_text)
    button.clicked.connect(on_click)
    frame = KmzDropFrame(on_drop=on_drop)
    layout = QVBoxLayout(frame)
    layout.setSpacing(6)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.addWidget(label)
    layout.addWidget(button)
    return frame, label


def build_auto_page(host):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSpacing(10)
    layout.setContentsMargins(8, 8, 8, 8)
    group = QGroupBox("自动样式")
    inner = QVBoxLayout(group)
    frame_a, host.lblKmzA = _drop_block(
        "未选择源图层", "选择源图层",
        lambda: _pick_style(host, "a"),
        lambda path: _set_style(host, "a", path),
    )
    frame_a.setToolTip("可将 KMZ 文件拖入此处作为源图层")
    frame_b, host.lblKmzB = _drop_block(
        "未选择参考图层", "选择参考图层",
        lambda: _pick_style(host, "b"),
        lambda path: _set_style(host, "b", path),
    )
    frame_b.setToolTip("可将 KMZ 文件拖入此处作为参考图层")
    run = styled_button("执行替换并导出（输出图层）", mark_key="export")
    run.clicked.connect(lambda: run_auto(host))
    actions = _half_row(run, _home_button(host))
    inner.addWidget(frame_a)
    inner.addSpacing(6)
    inner.addWidget(frame_b)
    inner.addSpacing(6)
    inner.addLayout(actions)
    layout.addWidget(group)
    host._kmz_style_a = None
    host._kmz_style_b = None
    saved_a = _read("kmzStyleAPath") or _read("autoSrc")
    saved_b = _read("kmzStyleBPath") or _read("autoRef") or _read("refPath")
    if saved_a and os.path.isfile(saved_a):
        _set_style(host, "a", saved_a, remember=False)
    if saved_b and os.path.isfile(saved_b):
        _set_style(host, "b", saved_b, remember=False)
    return page


def _pick_style(host, which):
    title = "选择源图层" if which == "a" else "选择参考图层"
    path, _selected = QFileDialog.getOpenFileName(host, title, "", "KMZ (*.kmz)")
    if path:
        _set_style(host, which, path)


def _set_style(host, which, path, remember=True):
    if not path or not os.path.isfile(path):
        return
    if which == "a":
        host._kmz_style_a = path
        host.lblKmzA.setText(path)
        host.lblKmzA.setToolTip(path)
        if remember:
            _write("kmzStyleAPath", path)
    else:
        host._kmz_style_b = path
        host.lblKmzB.setText(path)
        host.lblKmzB.setToolTip(path)
        if remember:
            _write("kmzStyleBPath", path)


def _pick_kmz_or_kml(parent, title, default_path=""):
    path, selected = QFileDialog.getSaveFileName(
        parent, title, default_path, "KMZ (*.kmz);;KML (*.kml)"
    )
    if not path:
        return ""
    low = path.lower()
    if low.endswith(".kmz") or low.endswith(".kml"):
        return path
    return path + (".kml" if str(selected).startswith("KML") else ".kmz")


def run_auto(host):
    if not host._kmz_style_a or not os.path.isfile(host._kmz_style_a):
        _msg(host, "提示", "请先选择源图层文件。", warning=True)
        return
    if not host._kmz_style_b or not os.path.isfile(host._kmz_style_b):
        _msg(host, "提示", "请先选择参考图层文件。", warning=True)
        return
    out_path = _pick_kmz_or_kml(host, "导出输出图层")
    if not out_path:
        return
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        result_lines, icon_by_folder, folder_names = _kmz_style_replace(
            host._kmz_style_a, host._kmz_style_b, out_path
        )
    except Exception as exc:
        QApplication.restoreOverrideCursor()
        _msg(host, "错误", tr("样式替换失败：{}").format(exc), warning=True)
        return
    QApplication.restoreOverrideCursor()
    rows = []
    for name in folder_names:
        info = icon_by_folder.get(name, {"used": False, "verify": "未参与"})
        rows.append({
            "name": name, "type": "图层", "level": 0,
            "doc_used": None, "doc_verify": "结构未改",
            "icon_used": info.get("used", False), "icon_verify": info.get("verify", ""),
            "total": None, "exported": None,
        })
    show_style_result(host, rows, "\n".join(result_lines), "自动样式 - 导出结果")


def build_manual_page(host):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSpacing(10)
    layout.setContentsMargins(8, 8, 8, 8)
    group = QGroupBox("手动样式")
    inner = QVBoxLayout(group)
    hint = _hint("图层名不一致时使用。点执行后先弹出匹配页。默认按参考的结构与名称输出，数据只来自源图层。")
    hint.setStyleSheet("color: #263238; font-size: 12px; font-weight: bold;")
    inner.addWidget(hint)
    frame_a, host.lblKmzManualA = _drop_block(
        "未选择源图层", "选择源图层",
        lambda: _pick_manual(host, "a"),
        lambda path: _set_manual(host, "a", path),
    )
    frame_a.setToolTip("可将 KMZ 文件拖入此处作为源图层")
    frame_b, host.lblKmzManualB = _drop_block(
        "未选择参考图层", "选择参考图层",
        lambda: _pick_manual(host, "b"),
        lambda path: _set_manual(host, "b", path),
    )
    frame_b.setToolTip("可将 KMZ 文件拖入此处作为参考图层")
    run = styled_button("执行替换", mark_key="manual")
    run.clicked.connect(lambda: run_manual(host))
    actions = _half_row(run, _home_button(host))
    inner.addWidget(frame_a)
    inner.addSpacing(6)
    inner.addWidget(frame_b)
    inner.addSpacing(6)
    inner.addLayout(actions)
    layout.addWidget(group)
    layout.addStretch(1)
    host._kmz_manual_a = None
    host._kmz_manual_b = None
    host._kmz_manual_map_path = _read("kmzManualMapPath")
    host._kmz_manual_use_ref = _read("kmzManualUseRefStructure", "true") != "false"
    host._kmz_manual_use_source_root = _read("kmzManualUseSourceRoot", "true") != "false"
    saved_a = _read("kmzManualAPath") or _read("manualSrc")
    saved_b = _read("kmzManualBPath") or _read("manualRef") or _read("refPath")
    if saved_a and os.path.isfile(saved_a):
        _set_manual(host, "a", saved_a, remember=False)
    if saved_b and os.path.isfile(saved_b):
        _set_manual(host, "b", saved_b, remember=False)
    return page


def _pick_manual(host, which):
    path, _selected = QFileDialog.getOpenFileName(host, "选择源图层" if which == "a" else "选择参考图层", "", "KMZ (*.kmz)")
    if path:
        _set_manual(host, which, path)


def _set_manual(host, which, path, remember=True):
    if not path or not os.path.isfile(path):
        return
    if which == "a":
        host._kmz_manual_a = path
        host.lblKmzManualA.setText(path)
        host.lblKmzManualA.setToolTip(path)
        if remember:
            _write("kmzManualAPath", path)
    else:
        host._kmz_manual_b = path
        host.lblKmzManualB.setText(path)
        host.lblKmzManualB.setToolTip(path)
        if remember:
            _write("kmzManualBPath", path)


def run_manual(host):
    if not host._kmz_manual_a or not os.path.isfile(host._kmz_manual_a):
        _msg(host, "提示", "请先选择源图层文件。", warning=True)
        return
    if not host._kmz_manual_b or not os.path.isfile(host._kmz_manual_b):
        _msg(host, "提示", "请先选择参考图层文件。", warning=True)
        return
    try:
        root_a, _zip_a = _kmz_get_kml_root(host._kmz_manual_a)
        root_b, _zip_b = _kmz_get_kml_root(host._kmz_manual_b)
    except Exception as exc:
        _msg(host, "错误", tr("无法读取 KMZ：{}").format(exc), warning=True)
        return
    if root_a is None or root_b is None:
        _msg(host, "错误", "无法读取 KMZ 的 KML 内容。", warning=True)
        return
    a_rows = _style_map_collect_rows(root_a)
    b_rows = _style_map_collect_tree_rows(root_b)
    if not a_rows:
        _msg(host, "提示", "源图层中没有可替换样式的图层（需有带几何的要素）。", warning=True)
        return
    if not any(row.get("is_layer") for row in b_rows):
        _msg(host, "提示", "参考图层中没有可用的样式图层（需有带几何的要素）。", warning=True)
        return
    dialog = KmzStyleMapDialog(
        host, a_rows, b_rows,
        last_map_path=host._kmz_manual_map_path,
        use_ref_structure=host._kmz_manual_use_ref,
        use_source_root_name=host._kmz_manual_use_source_root,
        source_root_name=_kml_source_root_display_name(root_a, host._kmz_manual_a),
        ref_root_name=_kml_document_name(root_b),
    )
    accepted = run_dialog(dialog) == QDialog.DialogCode.Accepted
    if not accepted:
        return
    out_path = _pick_kmz_or_kml(host, "导出输出图层")
    if not out_path:
        return
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        if dialog.use_ref_structure():
            result_lines, icon_by_folder, folder_names = _kmz_style_replace_ref_structure(
                host._kmz_manual_a, host._kmz_manual_b, out_path, dialog.name_map(),
                assignments=dialog.ref_layer_assignments(),
                use_source_root_name=dialog.use_source_root_name(),
            )
        else:
            result_lines, icon_by_folder, folder_names = _kmz_style_replace(
                host._kmz_manual_a, host._kmz_manual_b, out_path, name_map=dialog.name_map()
            )
    except Exception as exc:
        QApplication.restoreOverrideCursor()
        _msg(host, "错误", tr("样式替换失败：{}").format(exc), warning=True)
        return
    QApplication.restoreOverrideCursor()
    rows = []
    for name in folder_names:
        info = icon_by_folder.get(name, {"used": False, "verify": "未参与"})
        rows.append({
            "name": name, "type": "图层", "level": 0,
            "doc_used": None, "doc_verify": info.get("doc_verify") or "结构未改",
            "icon_used": info.get("used", False), "icon_verify": info.get("verify", ""),
            "total": info.get("total"), "exported": info.get("exported"),
        })
    show_style_result(host, rows, "\n".join(result_lines), "手动样式 - 导出结果")


def build_coords_page(host):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)
    top = QHBoxLayout()
    top.setSpacing(10)
    left_wrap = QWidget()
    left_top = QVBoxLayout(left_wrap)
    left_top.setContentsMargins(0, 0, 0, 0)
    left_top.setSpacing(4)
    switch = QHBoxLayout()
    switch.setSpacing(6)
    host._coord_mode = "file"
    host.btnCoordFile = styled_button("导入 KML / KMZ", mark_key="import_mode")
    host.btnCoordQgis = styled_button("在 QGIS 选择", mark_key="qgis_mode")
    for button in (host.btnCoordFile, host.btnCoordQgis):
        button.setCheckable(True)
        button.setStyleSheet(_FILTER_STYLE)
        button.setMinimumHeight(40)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    host.btnCoordFile.setChecked(True)
    host.btnCoordFile.clicked.connect(lambda: _set_coord_mode(host, "file"))
    host.btnCoordQgis.clicked.connect(lambda: _set_coord_mode(host, "qgis"))
    switch.addWidget(host.btnCoordFile, 1)
    switch.addWidget(host.btnCoordQgis, 1)
    left_top.addLayout(switch)
    host.lblCoordFile = _path_label("未选择 KML / KMZ")
    host.lblCoordFile.setWordWrap(False)
    host.lblCoordFile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    pick = styled_button("选择 KML / KMZ")
    pick.setMinimumHeight(36)
    pick.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    pick.clicked.connect(lambda: _pick_coord_file(host))
    frame = KmzDropFrame(on_drop=lambda path: _set_coord_file(host, path))
    frame.suffixes = (".kml", ".kmz")
    drop_row = QHBoxLayout(frame)
    drop_row.setContentsMargins(6, 2, 6, 2)
    drop_row.setSpacing(6)
    drop_row.addWidget(host.lblCoordFile, 1)
    drop_row.addWidget(pick)
    frame.setStyleSheet(
        "KmzDropFrame { border: 2px dashed #81c784; border-radius: 8px;"
        " background-color: #f1f8e9; padding: 2px 8px; }"
        "KmzDropFrame:hover { border-color: #66bb6a; background-color: #e8f5e9; }"
        "KmzDropFrame QLabel { background-color: transparent; padding: 0px; }"
    )
    frame.setMinimumHeight(56)
    frame.setMaximumHeight(88)
    frame.setToolTip("可将 KML 或 KMZ 拖入此处")
    host._coord_drop = frame
    left_top.addWidget(frame)
    top.addWidget(left_wrap, 1)
    right_top = QVBoxLayout()
    right_top.setContentsMargins(0, 0, 0, 0)
    right_top.setSpacing(0)
    host._compare_type = QComboBox()
    host._compare_type.addItems(["重叠部分", "不重叠部分"])
    host._compare_type.setCurrentIndex(1)
    host._tolerance = QDoubleSpinBox()
    host._tolerance.setDecimals(6)
    host._tolerance.setRange(0, 1)
    host._tolerance.setSingleStep(0.00001)
    host._tolerance.setValue(0.00001)
    host._save_edit = QCheckBox("保存编辑模式")
    host._save_edit.setChecked(True)
    host._save_edit.setToolTip("只保存并退出已配对图层的编辑")
    host._add_result = QCheckBox("加入工程")
    host._add_result.setChecked(True)
    host._add_result.setToolTip("把结果图层放进工程里的「KMZ对比」组")
    options = QHBoxLayout()
    options.setSpacing(6)
    options.addWidget(QLabel("对比类型："))
    options.addWidget(host._compare_type)
    host.lblTolerance = QLabel("容差(米)：")
    host.lblTolerance.setObjectName("dynamicText")
    options.addWidget(host.lblTolerance)
    options.addWidget(host._tolerance)
    options.addWidget(host._save_edit)
    options.addWidget(host._add_result)
    buttons = QHBoxLayout()
    run = styled_button("批量运行对比", mark_key="run")
    save = styled_button("保存配置", mark_key="save")
    cancel = styled_button("取消")
    run.setStyleSheet("QPushButton { padding: 4px 8px; min-height: 40px; background-color: #4CAF50; color: white; border: none; border-radius: 4px; } QPushButton:hover { background-color: #45a049; }")
    save.setStyleSheet("QPushButton { padding: 4px 8px; min-height: 40px; background-color: #1565c0; color: white; border: none; border-radius: 4px; } QPushButton:hover { background-color: #0d47a1; }")
    cancel.setStyleSheet("QPushButton { padding: 4px 8px; min-height: 40px; background-color: #f44336; color: white; border: none; border-radius: 4px; } QPushButton:hover { background-color: #d32f2f; }")
    home = _home_button(host)
    home.setStyleSheet("QPushButton { padding: 4px 8px; min-height: 40px; background-color: #607d8b; color: white; border: none; border-radius: 4px; } QPushButton:hover { background-color: #546e7a; }")
    run.clicked.connect(lambda: run_coords(host))
    save.clicked.connect(lambda: _save_coord_config(host))
    cancel.clicked.connect(lambda: host.open_page("home"))
    buttons.addWidget(run, 1)
    buttons.addWidget(save, 1)
    buttons.addWidget(cancel, 1)
    buttons.addWidget(home, 1)
    buttons.setSpacing(8)
    run_box = QFrame()
    run_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    run_box.setObjectName("coordRunBox")
    run_box.setStyleSheet(
        "QFrame#coordRunBox { border: 1px solid #66bb6a; border-radius: 8px; background: rgba(255,255,255,0.72); }"
    )
    run_layout = QVBoxLayout(run_box)
    run_layout.setContentsMargins(8, 6, 8, 6)
    run_layout.setSpacing(6)
    run_layout.addLayout(options)
    run_layout.addLayout(buttons)
    right_top.addWidget(run_box)
    right_wrap = QWidget()
    right_wrap.setLayout(right_top)
    top.addWidget(right_wrap, 1)
    band = max(left_wrap.sizeHint().height(), right_wrap.sizeHint().height(), 96)
    left_wrap.setMinimumHeight(band)
    right_wrap.setMinimumHeight(band)
    layout.addLayout(top)
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setHandleWidth(8)
    left = QWidget()
    left_layout = QVBoxLayout(left)
    left_layout.setSpacing(6)
    left_layout.setContentsMargins(4, 4, 4, 4)
    host.lblCoordLeft = QLabel("<b>导入的 KML / KMZ</b>")
    left_layout.addWidget(host.lblCoordLeft)
    host._coord_file_list = _coord_drag_list()
    host._coord_file_list.setToolTip("一次选一个图层，按住拖到右边同一类型的行上")
    left_layout.addWidget(host._coord_file_list, 1)
    right = QWidget()
    right_layout = QVBoxLayout(right)
    right_layout.setSpacing(6)
    right_layout.setContentsMargins(4, 4, 4, 4)
    right_layout.addWidget(QLabel("<b>当前工程图层</b>"))
    host._coord_qgis_list = _CoordDropList(host)
    host._coord_qgis_list.setItemDelegate(_CoordRightDelegate(host._coord_qgis_list))
    host._coord_qgis_list.setToolTip("把左边的图层拖到这里的某一行。类型必须相同。已匹配的行右边点 × 可以拆开。")
    right_layout.addWidget(host._coord_qgis_list, 1)
    splitter.addWidget(left)
    splitter.addWidget(right)
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 1)
    layout.addWidget(splitter, 1)
    layout.addLayout(_shared_filter_row(host))
    host._coord_block = False
    host._coord_file_path = ""
    host._coord_file_layers = []
    host._coord_qgis_layers = []
    host._coord_file_order = []
    host._coord_src_order = []
    host._coord_qgis_order = []
    host._coord_pairs = {}
    host._coord_geom_filter = "all"
    host._coord_match_filter = "all"
    host._coord_file_filter = "all"
    host._coord_qgis_filter = "all"
    reload_coord_project(host)
    _refresh_tolerance_label(host)
    disconnect_coord_page(host)
    host._coord_crs_slot = lambda: _refresh_tolerance_label(host)
    try:
        QgsProject.instance().crsChanged.connect(host._coord_crs_slot)
    except Exception:
        host._coord_crs_slot = None
    saved = _read("coordFile")
    if saved and os.path.isfile(saved):
        _set_coord_file(host, saved, remember=False)
    _apply_saved_coord(host)
    _refresh_tolerance_label(host)
    return page


_GEOM_FILTERS = (("all", "全部"), ("point", "点"), ("line", "线"), ("polygon", "面"))
_LIST_STYLE = "QListWidget { border: 1px solid #ccc; border-radius: 4px; } QListWidget::item { padding: 2px 4px; }"
_FILTER_STYLE = (
    "QPushButton { padding: 2px 10px; min-height: 22px; font-size: 11px; color: #263238; background: #f7f7f7; border: 1px solid #cfd8dc; border-radius: 4px; }"
    "QPushButton:checked { background: #2e7d32; color: white; border: 1px solid #2e7d32; }"
)
_MATCH_BTN = (
    "QPushButton { padding: 2px 10px; min-height: 22px; font-size: 11px; color: white; background: #1565c0; border: none; border-radius: 4px; }"
    "QPushButton:hover { background: #0d47a1; }"
)
_MATCHED_BG = QColor("#c8e6c9")
_MATCHED_FG = QColor("#1b5e20")


def _drop_point(event):
    if hasattr(event, "position"):
        point = event.position()
        return point.toPoint() if hasattr(point, "toPoint") else point
    return event.pos()


def _coord_drag_list():
    widget = QListWidget()
    widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
    widget.setDragEnabled(True)
    widget.setDragDropMode(QListWidget.DragDropMode.DragOnly)
    widget.setDefaultDropAction(Qt.DropAction.CopyAction)
    widget.setStyleSheet(_LIST_STYLE)
    return widget


class _CoordRightDelegate(QStyledItemDelegate):
    _CLEAR = 22

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        matched = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(rect, option.palette.highlight())
            base = option.palette.highlightedText().color()
        elif matched:
            painter.fillRect(rect, _MATCHED_BG)
            base = _MATCHED_FG
        else:
            base = QColor("#263238")
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        text_rect = QRect(rect)
        text_rect.adjust(6, 0, -6, 0)
        if matched:
            text_rect.setRight(text_rect.right() - self._CLEAR)
        painter.setFont(option.font)
        if matched and " VS " in text:
            head, tail = text.split(" VS ", 1)
            vs = " VS "
            metrics = painter.fontMetrics()
            head_width = _text_width(metrics, head)
            painter.setPen(base)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, head)
            vs_font = QFont(option.font)
            vs_font.setBold(True)
            painter.setFont(vs_font)
            painter.setPen(QColor("#c62828"))
            vs_rect = QRect(text_rect)
            vs_rect.setLeft(text_rect.left() + head_width)
            painter.drawText(vs_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, vs)
            vs_width = _text_width(painter.fontMetrics(), vs)
            painter.setFont(option.font)
            painter.setPen(base)
            tail_rect = QRect(text_rect)
            tail_rect.setLeft(text_rect.left() + head_width + vs_width)
            shown = metrics.elidedText(tail, Qt.TextElideMode.ElideRight, max(0, tail_rect.width()))
            painter.drawText(tail_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
            painter.setFont(vs_font)
            painter.setPen(QColor("#c62828"))
            clear = QRect(rect.right() - self._CLEAR, rect.top(), self._CLEAR, rect.height())
            painter.drawText(clear, Qt.AlignmentFlag.AlignCenter, "×")
        else:
            painter.setPen(base)
            shown = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(0, text_rect.width()))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
        painter.restore()


def _text_width(metrics, text):
    if hasattr(metrics, "horizontalAdvance"):
        return metrics.horizontalAdvance(text)
    return metrics.width(text)


class _CoordDropList(QListWidget):
    def __init__(self, host):
        super(_CoordDropList, self).__init__()
        self._host = host
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setStyleSheet(_LIST_STYLE)

    def mousePressEvent(self, event):
        point = _drop_point(event)
        item = self.itemAt(point)
        if item is not None and item.data(Qt.ItemDataRole.UserRole + 1):
            rect = self.visualItemRect(item)
            if point.x() >= rect.right() - _CoordRightDelegate._CLEAR:
                _clear_coord_pair(self._host, item.data(Qt.ItemDataRole.UserRole))
                event.accept()
                return
        super(_CoordDropList, self).mousePressEvent(event)

    def _from_left(self, event):
        left = getattr(self._host, "_coord_file_list", None)
        if left is None:
            return False
        source = event.source()
        return source is left or (source is None and bool(left.selectedItems()))

    def dragEnterEvent(self, event):
        if self._from_left(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._from_left(event):
            event.ignore()
            return
        item = self.itemAt(_drop_point(event))
        if item is None:
            event.ignore()
            return
        self.setCurrentItem(item)
        event.acceptProposedAction()

    def dropEvent(self, event):
        left = getattr(self._host, "_coord_file_list", None)
        if not self._from_left(event) or left is None:
            event.ignore()
            return
        chosen = left.selectedItems()
        target = self.itemAt(_drop_point(event))
        if not chosen or target is None:
            event.ignore()
            return
        _assign_coord_pair(self._host, chosen[0].data(Qt.ItemDataRole.UserRole), target.data(Qt.ItemDataRole.UserRole))
        event.acceptProposedAction()


def _shared_filter_row(host):
    """Two rows so translated labels are not squeezed into one strip."""
    top = QHBoxLayout()
    bottom = QHBoxLayout()
    for row in (top, bottom):
        row.setSpacing(4)
    group = QButtonGroup(host)
    group.setExclusive(True)
    buttons = []
    for key, title in _GEOM_FILTERS:
        button = styled_button(title, mark_key=key)
        button.setCheckable(True)
        button.setChecked(key == "all")
        button.setStyleSheet(_FILTER_STYLE)
        group.addButton(button)
        button.clicked.connect(lambda _checked=False, name=key: _set_coord_filter(host, name))
        buttons.append(button)
    refresh = styled_button("刷新图层", mark_key="refresh")
    refresh.setStyleSheet(_FILTER_STYLE)
    refresh.clicked.connect(lambda: _refresh_coord_layers(host))
    buttons.append(refresh)
    auto = styled_button("自动匹配", mark_key="auto")
    auto.setStyleSheet(_MATCH_BTN)
    auto.clicked.connect(lambda: _auto_match_coords(host))
    buttons.append(auto)
    host.btnCoordMatched = styled_button("已匹配", mark_key="matched")
    host.btnCoordUnmatched = styled_button("未匹配", mark_key="unmatched")
    for button, name in ((host.btnCoordMatched, "matched"), (host.btnCoordUnmatched, "unmatched")):
        button.setCheckable(True)
        button.setStyleSheet(_FILTER_STYLE)
        button.clicked.connect(lambda _checked=False, which=name: _set_match_filter(host, which))
        buttons.append(button)
    clear_pairs = styled_button("清空配对", mark_key="trash")
    clear_pairs.setStyleSheet(_FILTER_STYLE)
    clear_pairs.clicked.connect(lambda: _clear_all_coord_pairs(host))
    buttons.append(clear_pairs)
    host.btnCoordEmpty = styled_button("空图层", mark_key="empty")
    host.btnCoordEmpty.setCheckable(True)
    host.btnCoordEmpty.setChecked(True)
    host.btnCoordEmpty.setStyleSheet(_FILTER_STYLE)
    host.btnCoordEmpty.setToolTip("显示或隐藏要素数为 0 的图层，两边一起生效")
    host._coord_show_empty = True
    host.btnCoordEmpty.clicked.connect(lambda: _toggle_empty_layers(host))
    buttons.append(host.btnCoordEmpty)
    half = (len(buttons) + 1) // 2
    for button in buttons[:half]:
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        button.setMinimumHeight(32)
        top.addWidget(button, 1)
    for button in buttons[half:]:
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        button.setMinimumHeight(32)
        bottom.addWidget(button, 1)
    wrap = QVBoxLayout()
    wrap.setSpacing(4)
    wrap.addLayout(top)
    wrap.addLayout(bottom)
    return wrap


def _map_unit_name():
    names = {
        QgsUnitTypes.DistanceUnit.DistanceMeters: "米",
        QgsUnitTypes.DistanceUnit.DistanceKilometers: "千米",
        QgsUnitTypes.DistanceUnit.DistanceCentimeters: "厘米",
        QgsUnitTypes.DistanceUnit.DistanceMillimeters: "毫米",
        QgsUnitTypes.DistanceUnit.DistanceFeet: "英尺",
        QgsUnitTypes.DistanceUnit.DistanceYards: "码",
        QgsUnitTypes.DistanceUnit.DistanceMiles: "英里",
        QgsUnitTypes.DistanceUnit.DistanceDegrees: "度",
    }
    nautical = getattr(QgsUnitTypes, "DistanceNauticalMiles", None)
    if nautical is not None:
        names[nautical] = "海里"
    survey = getattr(QgsUnitTypes, "DistanceUSFeet", None)
    if survey is not None:
        names[survey] = "英尺"
    try:
        unit = QgsProject.instance().crs().mapUnits()
    except Exception:
        unit = None
    return tr(names.get(unit, "未知"))


def _refresh_tolerance_label(host):
    label = getattr(host, "lblTolerance", None)
    if label is None:
        return
    unit = _map_unit_name()
    label.setText(tr("容差({0})：").format(unit))
    label.setToolTip(tr("按当前工程坐标系的长度单位，现在是{0}。").format(unit))


def _refresh_coord_layers(host):
    reload_coord_project(host)
    _fill_coord_list(host, "file")
    _refresh_tolerance_label(host)


def _set_coord_filter(host, name):
    host._coord_geom_filter = name
    host._coord_file_filter = name
    host._coord_qgis_filter = name
    _fill_coord_list(host, "file")
    _fill_coord_list(host, "qgis")


def _set_match_filter(host, name):
    host._coord_match_filter = "all" if host._coord_match_filter == name else name
    host.btnCoordMatched.setChecked(host._coord_match_filter == "matched")
    host.btnCoordUnmatched.setChecked(host._coord_match_filter == "unmatched")
    _fill_coord_list(host, "file")
    _fill_coord_list(host, "qgis")


def _is_folder_layer(layer):
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return True
    try:
        kind = layer.wkbType()
    except Exception:
        return True
    if kind in (QgsWkbTypes.Type.NoGeometry, QgsWkbTypes.Type.Unknown):
        return True
    return _geom_key(layer) == "other"


def _hide_coord_layer(host, layer):
    if _is_folder_layer(layer):
        return True
    if not getattr(host, "_coord_show_empty", True) and _feature_count(layer) <= 0:
        return True
    return False


def _toggle_empty_layers(host):
    host._coord_show_empty = not getattr(host, "_coord_show_empty", True)
    if getattr(host, "btnCoordEmpty", None) is not None:
        host.btnCoordEmpty.setChecked(host._coord_show_empty)
    _fill_coord_list(host, "file")
    _fill_coord_list(host, "qgis")


def _clear_all_coord_pairs(host):
    if not getattr(host, "_coord_pairs", None):
        _msg(host, "坐标对比", "没有配对。", warning=True)
        return
    host._coord_pairs = {}
    _fill_coord_list(host, "file")
    _fill_coord_list(host, "qgis")
    _msg(host, "坐标对比", "已清空配对。")


def _geom_key(layer):
    kind = QgsWkbTypes.geometryType(layer.wkbType())
    if kind == QgsWkbTypes.GeometryType.PointGeometry:
        return "point"
    if kind == QgsWkbTypes.GeometryType.LineGeometry:
        return "line"
    if kind == QgsWkbTypes.GeometryType.PolygonGeometry:
        return "polygon"
    return "other"


def _feature_count(layer):
    try:
        count = layer.featureCount()
    except Exception:
        count = -1
    if count is None or count < 0:
        try:
            count = layer.dataProvider().featureCount()
        except Exception:
            count = 0
    return int(count or 0)


def _layer_label(layer):
    return "{0}（{1}）".format(layer.name() or "图层", _feature_count(layer))


def _find_layer(layers, layer_id):
    for layer in layers:
        if layer.id() == layer_id:
            return layer
    return None


def _prune_coord_pairs(host):
    left_ids = {layer.id() for layer in _left_source(host)[0]}
    right_ids = {layer.id() for layer in host._coord_qgis_layers}
    host._coord_pairs = {
        right_id: left_id
        for right_id, left_id in host._coord_pairs.items()
        if right_id in right_ids and left_id in left_ids and right_id != left_id
    }


def _pair_error(left, right):
    if left is None or right is None:
        return "找不到图层。"
    if left.id() == right.id():
        return "不能把图层配给自己。"
    if _geom_key(left) == "other" or _geom_key(left) != _geom_key(right):
        return "几何类型要一致，点对点、线对线、面对面。"
    return ""


def _clear_coord_pair(host, right_id):
    if right_id not in host._coord_pairs:
        return
    del host._coord_pairs[right_id]
    _fill_coord_list(host, "file")
    _fill_coord_list(host, "qgis")


def _assign_coord_pair(host, left_id, right_id):
    left = _find_layer(_left_source(host)[0], left_id)
    right = _find_layer(host._coord_qgis_layers, right_id)
    error = _pair_error(left, right)
    if error:
        _msg(host, "坐标对比", error, warning=True)
        return False
    pairs = dict(host._coord_pairs)
    for rid, lid in list(pairs.items()):
        if lid == left_id or rid == right_id:
            del pairs[rid]
    pairs[right_id] = left_id
    host._coord_pairs = pairs
    _fill_coord_list(host, "file")
    _fill_coord_list(host, "qgis")
    return True


def _auto_match_coords(host):
    geom_filter = getattr(host, "_coord_geom_filter", "all")
    left_layers = []
    for layer in _left_source(host)[0]:
        if _hide_coord_layer(host, layer):
            continue
        if geom_filter != "all" and _geom_key(layer) != geom_filter:
            continue
        left_layers.append(layer)
    right_layers = []
    for layer in host._coord_qgis_layers:
        if _hide_coord_layer(host, layer):
            continue
        if geom_filter != "all" and _geom_key(layer) != geom_filter:
            continue
        right_layers.append(layer)
    used_left = set(host._coord_pairs.values())
    used_right = set(host._coord_pairs.keys())
    found = []
    for right in right_layers:
        if right.id() in used_right:
            continue
        for left in left_layers:
            if left.id() in used_left or left.id() == right.id():
                continue
            if _geom_key(left) != _geom_key(right) or _is_folder_layer(left) or _is_folder_layer(right):
                continue
            if _hide_coord_layer(host, left) or _hide_coord_layer(host, right):
                continue
            left_name = left.name()
            right_name = right.name()
            if (left_name or "").strip().casefold() == (right_name or "").strip().casefold():
                found.append((10000, right.id(), left.id()))
                continue
            score = _keyword_score(left_name, right_name)
            if score:
                found.append((score, right.id(), left.id()))
    found.sort(key=lambda item: item[0], reverse=True)
    added = 0
    pairs = dict(host._coord_pairs)
    for _score, right_id, left_id in found:
        if right_id in used_right or left_id in used_left:
            continue
        pairs[right_id] = left_id
        used_right.add(right_id)
        used_left.add(left_id)
        added += 1
    host._coord_pairs = pairs
    _fill_coord_list(host, "file")
    _fill_coord_list(host, "qgis")
    if added:
        _msg(host, "坐标对比", tr("新配上 {0} 组。").format(added))
    else:
        _msg(host, "坐标对比", "没有对上的图层。", warning=True)


def _open_ogr_layers(path):
    from qgis.core import QgsProviderRegistry, QgsVectorLayer as VectorLayer

    found = []
    metadata = None
    try:
        metadata = QgsProviderRegistry.instance().providerMetadata("ogr")
    except Exception:
        metadata = None
    subs = []
    if metadata is not None:
        try:
            subs = list(metadata.querySublayers(path) or [])
        except Exception:
            subs = []
    for sub in subs:
        uri = ""
        try:
            raw_uri = sub.uri
            uri = raw_uri() if callable(raw_uri) else raw_uri
        except Exception:
            uri = ""
        try:
            name = sub.name()
        except Exception:
            name = ""
        if not uri:
            continue
        layer = VectorLayer(uri, name or "图层", "ogr")
        if layer.isValid():
            found.append(layer)
    if found:
        return found
    layer = VectorLayer(path, os.path.splitext(os.path.basename(path))[0], "ogr")
    if layer.isValid():
        provider = layer.dataProvider()
        raw = []
        try:
            raw = list(provider.subLayers() or []) if provider is not None else []
        except Exception:
            raw = []
        if not raw:
            return [layer]
        for line in raw:
            parts = str(line).split(":")
            if len(parts) < 2:
                continue
            uri = "{0}|layerid={1}".format(path, parts[0])
            child = VectorLayer(uri, parts[1] or "图层", "ogr")
            if child.isValid():
                found.append(child)
    return found


def _pick_coord_file(host):
    start = os.path.dirname(host._coord_file_path) if getattr(host, "_coord_file_path", "") else ""
    path, _selected = QFileDialog.getOpenFileName(host, "选择 KML / KMZ", start, "KML/KMZ (*.kml *.kmz)")
    if path:
        _set_coord_file(host, path)


def _set_coord_file(host, path, remember=True):
    if not path or not os.path.isfile(path):
        return
    low = path.lower()
    if not low.endswith((".kml", ".kmz")):
        _msg(host, "坐标对比", "请选择 KML 或 KMZ。", warning=True)
        return
    layers = _open_ogr_layers(path)
    if not layers:
        _msg(host, "坐标对比", "这个文件里没有读出图层。", warning=True)
        return
    host._coord_file_path = path
    host._coord_file_layers = layers
    host._coord_file_order = []
    host._coord_pairs = {}
    host.lblCoordFile.setText(path)
    host.lblCoordFile.setToolTip(path)
    if remember:
        pass
    _fill_coord_list(host, "file")


def reload_coord_project(host):
    if not hasattr(host, "_coord_qgis_list"):
        return
    host._coord_qgis_layers = [
        layer for layer in QgsProject.instance().mapLayers().values()
        if isinstance(layer, QgsVectorLayer) and layer.isValid()
    ]
    host._coord_qgis_layers.sort(key=lambda layer: layer.name())
    alive = {layer.id() for layer in host._coord_qgis_layers}
    host._coord_qgis_order = [item for item in host._coord_qgis_order if item in alive]
    host._coord_src_order = [item for item in host._coord_src_order if item in alive]
    _fill_coord_list(host, "qgis")
    if getattr(host, "_coord_mode", "file") == "qgis":
        _fill_coord_list(host, "file")


def _left_source(host):
    if getattr(host, "_coord_mode", "file") == "qgis":
        return host._coord_qgis_layers, "_coord_src_order"
    return host._coord_file_layers, "_coord_file_order"


def _save_coord_config(host):
    _write("coordFile", getattr(host, "_coord_file_path", "") or "")
    compare = getattr(host, "_compare_type", None)
    tolerance = getattr(host, "_tolerance", None)
    _write("coordCompareType", compare.currentIndex() if compare is not None else 1)
    _write("coordTolerance", tolerance.value() if tolerance is not None else 0.00001)
    _write("coordSaveEdit", "true" if host._save_edit.isChecked() else "false")
    _write("coordAddResult", "true" if host._add_result.isChecked() else "false")
    _write("coordShowEmpty", "true" if getattr(host, "_coord_show_empty", True) else "false")
    _msg(host, "保存配置", "已保存")


def _apply_saved_coord(host):
    compare = _read("coordCompareType", "")
    if compare != "" and getattr(host, "_compare_type", None) is not None:
        try:
            host._compare_type.setCurrentIndex(1 if int(compare) else 0)
        except ValueError:
            pass
    tolerance = _read("coordTolerance", "")
    if tolerance != "" and getattr(host, "_tolerance", None) is not None:
        try:
            host._tolerance.setValue(float(tolerance))
        except ValueError:
            pass
    if _read("coordSaveEdit", "") != "":
        host._save_edit.setChecked(_read("coordSaveEdit") != "false")
    if _read("coordAddResult", "") != "":
        host._add_result.setChecked(_read("coordAddResult") != "false")
    show_empty = _read("coordShowEmpty", "true") != "false"
    host._coord_show_empty = show_empty
    if getattr(host, "btnCoordEmpty", None) is not None:
        host.btnCoordEmpty.setChecked(show_empty)


def _set_coord_mode(host, mode):
    host._coord_mode = "qgis" if mode == "qgis" else "file"
    host.btnCoordFile.setChecked(host._coord_mode == "file")
    host.btnCoordQgis.setChecked(host._coord_mode == "qgis")
    host._coord_drop.setVisible(host._coord_mode != "qgis")
    title = tr("在 QGIS 选择") if host._coord_mode == "qgis" else tr("导入的 KML / KMZ")
    host.lblCoordLeft.setText("<b>{0}</b>".format(title))
    _fill_coord_list(host, "file")


def _fill_coord_list(host, side):
    if not hasattr(host, "_coord_pairs"):
        host._coord_pairs = {}
    _prune_coord_pairs(host)
    geom_filter = getattr(host, "_coord_geom_filter", "all")
    match_filter = getattr(host, "_coord_match_filter", "all")
    matched_left = set(host._coord_pairs.values())
    matched_right = set(host._coord_pairs.keys())
    if side == "file":
        widget = host._coord_file_list
        layers = _left_source(host)[0]
        paired_ids = matched_left
    else:
        widget = host._coord_qgis_list
        layers = host._coord_qgis_layers
        paired_ids = matched_right
    host._coord_block = True
    widget.clear()
    for layer in layers:
        if _hide_coord_layer(host, layer):
            continue
        if geom_filter != "all" and _geom_key(layer) != geom_filter:
            continue
        paired = layer.id() in paired_ids
        if match_filter == "matched" and not paired:
            continue
        if match_filter == "unmatched" and paired:
            continue
        if side == "qgis":
            text = _layer_label(layer)
            left_id = host._coord_pairs.get(layer.id())
            left = _find_layer(_left_source(host)[0], left_id) if left_id else None
            if left is not None:
                text = "{0} VS {1}".format(text, _layer_label(left))
        else:
            text = _layer_label(layer)
            left = None
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, layer.id())
        item.setData(Qt.ItemDataRole.UserRole + 1, _layer_label(left) if left is not None else "")
        if paired:
            item.setBackground(QBrush(_MATCHED_BG))
            item.setForeground(QBrush(_MATCHED_FG))
        widget.addItem(item)
    host._coord_block = False


def _remember_coord_order(host, side):
    if host._coord_block:
        return
    widget = host._coord_file_list if side == "file" else host._coord_qgis_list
    if side == "file":
        _layers, order_name = _left_source(host)
    else:
        order_name = "_coord_qgis_order"
    order = list(getattr(host, order_name))
    selected = [item.data(Qt.ItemDataRole.UserRole) for item in widget.selectedItems()]
    order = [item for item in order if item in selected]
    for item in selected:
        if item not in order:
            order.append(item)
    setattr(host, order_name, order)


def _layers_in_order(layers, order):
    by_id = {layer.id(): layer for layer in layers}
    return [by_id[item] for item in order if item in by_id]


def _chosen_layers(host, side):
    if side == "file":
        widget = host._coord_file_list
        layers, order_name = _left_source(host)
        order = getattr(host, order_name)
    else:
        widget = host._coord_qgis_list
        layers = host._coord_qgis_layers
        order = host._coord_qgis_order
    selected = {item.data(Qt.ItemDataRole.UserRole) for item in widget.selectedItems()}
    return _layers_in_order(layers, [item for item in order if item in selected])


def run_coords(host):
    _prune_coord_pairs(host)
    right_order = [layer.id() for layer in host._coord_qgis_layers]
    pairs = []
    for right_id in right_order:
        left_id = host._coord_pairs.get(right_id)
        if not left_id:
            continue
        source = _find_layer(_left_source(host)[0], left_id)
        target = _find_layer(host._coord_qgis_layers, right_id)
        if source is None or target is None:
            continue
        pairs.append((source, target))
    if not pairs:
        _msg(host, "提示", "请把左边的图层拖到右边对应的行上。", warning=True)
        return
    layer_ids = set()
    for source, target in pairs:
        layer_ids.add(source.id())
        layer_ids.add(target.id())
    ok, edit_error = _commit_coord_edits(layer_ids, host._save_edit.isChecked())
    if not ok:
        _msg(host, "提示", edit_error, warning=True)
        return
    lines = [tr("批量对比已全部完成！"), ""]
    total_features = 0
    for source, target in pairs:
        total_features += _feature_count(source) + _feature_count(target)
    lines.append(tr("共 {0} 组，约 {1} 个要素。").format(len(pairs), total_features))
    lines.append("")
    progress = QProgressDialog(tr("正在对比..."), tr("取消"), 0, len(pairs), host)
    progress.setWindowTitle(tr("坐标对比"))
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    stopped = False
    for index, (source, target) in enumerate(pairs, start=1):
        if progress.wasCanceled():
            stopped = True
            lines.append(tr("已取消，已完成 {0} 组。").format(index - 1))
            break
        progress.setValue(index - 1)
        progress.setLabelText(tr("正在对比：{0}").format(target.name() or ""))
        QApplication.processEvents()
        result = _compare_pair(
            target,
            source,
            host._compare_type.currentIndex(),
            host._tolerance.value(),
            bool(host._add_result.isChecked()) if getattr(host, "_add_result", None) is not None else True,
        )
        lines.append(tr("组{0}/{1}：").format(index, len(pairs)))
        lines.append(tr("  左侧：{0}").format(source.name()))
        lines.append(tr("  工程图层：{0}").format(target.name()))
        lines.append(tr("  结果：{0}").format(result))
        lines.append("")
    progress.setValue(len(pairs))
    progress.close()
    if stopped and lines[-1] != "":
        pass
    show_text_result(host, "\n".join(lines).strip(), tr("批量运行汇总"))


def _commit_coord_edits(layer_ids, save_edit):
    editing = []
    for layer_id in layer_ids:
        layer = QgsProject.instance().mapLayer(layer_id)
        if isinstance(layer, QgsVectorLayer) and layer.isEditable():
            editing.append(layer)
    if not editing:
        return True, ""
    if not save_edit:
        names = "、".join(layer.name() or "图层" for layer in editing)
        return False, "参与对比的图层「{0}」还在编辑，请先退出或勾选保存编辑模式。".format(names)
    for layer in editing:
        if not layer.commitChanges():
            return False, "失败：图层「{}」保存失败".format(layer.name())
    return True, ""


def _geometry_in_project_crs(geometry, layer):
    if geometry is None or geometry.isEmpty():
        return None
    copy = QgsGeometry(geometry)
    dest = QgsProject.instance().crs()
    src = layer.crs()
    if not dest.isValid() or not src.isValid() or src == dest:
        return copy
    try:
        transform = QgsCoordinateTransform(src, dest, QgsProject.instance().transformContext())
        copy.transform(transform)
    except Exception:
        return None
    return copy


def _add_result_layer(layer):
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    name = tr("KMZ对比")
    group = root.findGroup(name)
    if group is None:
        group = root.insertGroup(0, name)
    project.addMapLayer(layer, False)
    group.addLayer(layer)


def _compare_pair(main_layer, kmz_layer, compare_type, tolerance, add_result=True):
    if not (main_layer.isValid() and kmz_layer.isValid()):
        return tr("失败：选中的图层无效")
    main_type = QgsWkbTypes.geometryType(main_layer.wkbType())
    if main_type != QgsWkbTypes.geometryType(kmz_layer.wkbType()):
        return tr("失败：原图层与KMZ导回层几何类型不匹配")
    main_features = [feature for feature in main_layer.getFeatures() if feature.hasGeometry()]
    kmz_features = [feature for feature in kmz_layer.getFeatures() if feature.hasGeometry()]
    skipped = 0
    kmz_geom = {}
    index = QgsSpatialIndex()
    for kmz_index, kmz_feature in enumerate(kmz_features):
        geom = _geometry_in_project_crs(kmz_feature.geometry(), kmz_layer)
        if geom is None or geom.isEmpty():
            skipped += 1
            continue
        kmz_geom[kmz_index] = geom
        probe = QgsFeature()
        probe.setId(kmz_index)
        probe.setGeometry(geom)
        index.addFeature(probe)
    main_geom = {}
    for main_index, main_feature in enumerate(main_features):
        geom = _geometry_in_project_crs(main_feature.geometry(), main_layer)
        if geom is None or geom.isEmpty():
            skipped += 1
            continue
        main_geom[main_index] = geom
    main_hit = set()
    kmz_hit = set()
    reach = float(tolerance or 0)
    for main_index, geom in main_geom.items():
        box = geom.boundingBox()
        box.grow(reach)
        for kmz_index in index.intersects(box):
            other = kmz_geom.get(kmz_index)
            if other is None:
                continue
            try:
                near = geom.distance(other) <= reach
            except Exception:
                near = False
            if near:
                main_hit.add(main_index)
                kmz_hit.add(kmz_index)
    chosen = []
    if compare_type == 0:
        title = tr("重叠检测结果")
        for index_hit, geom in main_geom.items():
            if index_hit in main_hit:
                chosen.append((QgsGeometry(geom), "main"))
    else:
        title = tr("不重叠检测结果")
        for index_hit, geom in main_geom.items():
            if index_hit not in main_hit:
                chosen.append((QgsGeometry(geom), "main"))
        for index_hit, geom in kmz_geom.items():
            if index_hit not in kmz_hit:
                chosen.append((QgsGeometry(geom), "kmz"))
    note = ""
    if skipped:
        note = tr("变换失败已跳过 {0} 个要素。").format(skipped)
    if not chosen:
        empty = tr("无重叠结果") if compare_type == 0 else tr("无不重叠结果")
        return empty if not note else empty + " " + note
    result_name = "{0}_{1}".format(main_layer.name(), title)
    project_crs = QgsProject.instance().crs()
    auth = project_crs.authid() if project_crs.isValid() and project_crs.authid() else main_layer.crs().authid()
    result = QgsVectorLayer(
        "{0}?crs={1}".format(QgsWkbTypes.displayString(main_layer.wkbType()), auth or ""),
        result_name,
        "memory",
    )
    if project_crs.isValid():
        result.setCrs(project_crs)
    provider = result.dataProvider()
    if compare_type == 0:
        provider.addAttributes([QgsField("Name", QVariant.String, "text", 100)])
    else:
        provider.addAttributes([
            QgsField("Name1", QVariant.String, "text", 100),
            QgsField("Name2", QVariant.String, "text", 100),
        ])
    result.updateFields()
    for geometry, tag in chosen:
        feature = QgsFeature(result.fields())
        feature.setGeometry(geometry)
        if compare_type == 0:
            feature.setAttributes([main_layer.name()])
        elif tag == "main":
            feature.setAttributes(["", main_layer.name()])
        else:
            feature.setAttributes([kmz_layer.name(), ""])
        provider.addFeature(feature)
    result.updateExtents()
    if add_result:
        _add_result_layer(result)
        text = tr("成功：结果图层「{0}」已添加").format(result_name)
    else:
        text = tr("成功：未加入工程。结果「{0}」。").format(result_name)
    return text if not note else text + " " + note
