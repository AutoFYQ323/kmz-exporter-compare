# -*- coding: utf-8 -*-
"""Clear and edit-mode actions for the home page."""

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import QMessageBox

from .i18n import tr
from .qtutil import run_dialog


def _rollback(layer):
    try:
        if layer.isEditable():
            layer.rollBack()
    except Exception:  # nosec B110
        pass


def vector_layers(only_current=False):
    if only_current:
        try:
            from qgis.utils import iface

            layer = iface.activeLayer()
        except Exception:
            layer = None
        if isinstance(layer, QgsVectorLayer) and layer.isValid():
            return [layer]
        return []
    layers = []
    for layer in QgsProject.instance().mapLayers().values():
        if isinstance(layer, QgsVectorLayer) and layer.isValid():
            layers.append(layer)
    layers.sort(key=lambda layer: (layer.name() or "").casefold())
    return layers


def clear_all_features(only_current=False):
    layers = vector_layers(only_current)
    if not layers:
        return False, tr("当前没有可处理的矢量图层。")
    failed = []
    for layer in layers:
        try:
            if not layer.isEditable():
                layer.startEditing()
            layer.selectAll()
            layer.deleteSelectedFeatures()
            if not layer.commitChanges():
                _rollback(layer)
                failed.append(layer.name() or "")
        except Exception:
            _rollback(layer)
            failed.append(layer.name() or "")
    if failed:
        return False, tr("以下图层清空失败：\n{0}").format("\n".join(failed))
    return True, tr("所有图层数据已清空")


def editing_on(only_current=False):
    layers = vector_layers(only_current)
    if not layers:
        return False, tr("当前没有可处理的矢量图层。")
    failed = []
    for layer in layers:
        if layer.isEditable():
            continue
        try:
            if not layer.startEditing():
                failed.append(layer.name() or "")
        except Exception:
            failed.append(layer.name() or "")
    if failed:
        return False, tr("以下图层未能打开编辑：\n{0}").format("\n".join(failed))
    return True, tr("所有图层编辑模式已打开")


def editing_off(only_current=False):
    layers = vector_layers(only_current)
    if not layers:
        return False, tr("当前没有可处理的矢量图层。")
    failed = []
    for layer in layers:
        if not layer.isEditable():
            continue
        try:
            if not layer.commitChanges():
                _rollback(layer)
                failed.append(layer.name() or "")
        except Exception:
            _rollback(layer)
            failed.append(layer.name() or "")
    if failed:
        return False, tr("以下图层保存失败：\n{0}").format("\n".join(failed))
    return True, tr("所有图层已保存并退出编辑模式")


def confirm_clear(parent, only_current=False):
    from qgis.PyQt.QtWidgets import QInputDialog

    prompt = tr("将删除当前工程里全部矢量图层的全部要素。图层还在，要素删掉后不能恢复。\n请输入 OK 确认：")
    if only_current:
        prompt = tr("将只删除图层面板里当前选中的矢量图层的全部要素。图层还在，要素删掉后不能恢复。\n请输入 OK 确认：")
    text, ok = QInputDialog.getText(
        parent,
        tr("确认清空"),
        prompt,
    )
    if not ok or text.strip().upper() != "OK":
        return False
    box = QMessageBox(parent)
    box.setWindowTitle(tr("二次确认"))
    box.setText(tr("确认删除全部要素？这一步不能返回，也不能撤销。"))
    box.setIcon(QMessageBox.Icon.Warning)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    yes = box.button(QMessageBox.StandardButton.Yes)
    no = box.button(QMessageBox.StandardButton.No)
    if yes is not None:
        yes.setText(tr("删除全部"))
    if no is not None:
        no.setText(tr("取消"))
    return run_dialog(box) == QMessageBox.StandardButton.Yes


_FORMATS = (
    ("ESRI Shapefile", "ESRI Shapefile", ".shp"),
    ("GeoPackage", "GPKG", ".gpkg"),
    ("GeoJSON", "GeoJSON", ".geojson"),
    ("KML", "KML", ".kml"),
    ("MapInfo TAB", "MapInfo File", ".tab"),
    ("FlatGeobuf", "FlatGeobuf", ".fgb"),
    ("CSV", "CSV", ".csv"),
)


def active_vector():
    try:
        from qgis.utils import iface
        layer = iface.activeLayer() if iface is not None else None
    except Exception:
        layer = None
    if isinstance(layer, QgsVectorLayer) and layer.isValid():
        return layer
    return None


def _source_file(layer):
    raw = (layer.source() or "").split("|")[0].strip().strip('"')
    if raw.lower().startswith("file:"):
        from qgis.PyQt.QtCore import QUrl
        raw = QUrl(raw).toLocalFile()
    return raw


def _format_index(layer):
    storage = (layer.storageType() or "").lower()
    path = _source_file(layer).lower()
    blob = storage + " " + path
    if "shape" in blob or path.endswith(".shp"):
        return 0
    if "gpkg" in blob or path.endswith(".gpkg"):
        return 1
    if "json" in blob or path.endswith(".geojson") or path.endswith(".json"):
        return 2
    if "kml" in blob or "kmz" in blob or path.endswith(".kml") or path.endswith(".kmz"):
        return 3
    if "mapinfo" in blob or path.endswith(".tab"):
        return 4
    if "flatgeobuf" in blob or path.endswith(".fgb"):
        return 5
    if "csv" in blob or path.endswith(".csv"):
        return 6
    return 1


def copy_current_layer(parent, with_features):
    """Copy the active layer. None means the user cancelled."""
    import os

    from qgis.core import QgsFeature, QgsMapLayerStyle, QgsVectorFileWriter, QgsWkbTypes
    from qgis.PyQt.QtWidgets import QFileDialog

    layer = active_vector()
    if layer is None:
        return False, tr("请先在图层面板选中一个矢量图层。")
    name = layer.name() or tr("图层")
    source = _source_file(layer)
    folder = os.path.dirname(source) if source and os.path.dirname(source) else ""
    if not folder or not os.path.isdir(folder):
        project = QgsProject.instance()
        folder = os.path.dirname(project.fileName() or "") or (project.homePath() or "")
    index = _format_index(layer)
    label, driver, ext = _FORMATS[index]
    kind = tr("连同全部要素一起复制，样式与所选图层相同。") if with_features else tr("不复制要素，只保留字段和样式。")
    where = source or tr("这个图层没有文件路径，默认保存到工程所在文件夹。")
    box = QMessageBox(parent)
    box.setWindowTitle(tr("复制当前图层") if with_features else tr("复制当前图层为空"))
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(tr("当前所选图层：{0}\n路径：{1}\n原格式：{2}\n{3}\n\n下一步选择保存位置。默认就在这个文件夹，格式默认与原图层相同。").format(
        name, where, label, kind
    ))
    box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
    ok_button = box.button(QMessageBox.StandardButton.Ok)
    cancel_button = box.button(QMessageBox.StandardButton.Cancel)
    if ok_button is not None:
        ok_button.setText(tr("继续"))
    if cancel_button is not None:
        cancel_button.setText(tr("取消"))
    if run_dialog(box) != QMessageBox.StandardButton.Ok:
        return None
    filters = ";;".join("{0} (*{1})".format(item[0], item[2]) for item in _FORMATS)
    initial = "{0} (*{1})".format(label, ext)
    stem = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in name).strip() or "layer"
    stem += "" if with_features else "_空"
    default_path = os.path.join(folder, stem + ext) if folder else (stem + ext)
    path, chosen = QFileDialog.getSaveFileName(parent, tr("保存复制图层"), default_path, filters, initial)
    if not path:
        return None
    chosen_index = index
    for item_index, item in enumerate(_FORMATS):
        if chosen.startswith(item[0]):
            chosen_index = item_index
            break
    label, driver, ext = _FORMATS[chosen_index]
    if not path.lower().endswith(ext):
        path += ext
    crs = ""
    try:
        if layer.crs().isValid() and layer.crs().authid():
            crs = layer.crs().authid()
    except Exception:
        crs = ""
    uri = QgsWkbTypes.displayString(layer.wkbType())
    if crs:
        uri += "?crs=" + crs
    memory = QgsVectorLayer(uri, name, "memory")
    provider = memory.dataProvider()
    provider.addAttributes(layer.fields())
    memory.updateFields()
    if with_features:
        features = []
        for source_feature in layer.getFeatures():
            feature = QgsFeature(memory.fields())
            feature.setGeometry(source_feature.geometry())
            feature.setAttributes(source_feature.attributes())
            features.append(feature)
        if features:
            provider.addFeatures(features)
    memory.updateExtents()
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    options.layerName = os.path.splitext(os.path.basename(path))[0]
    try:
        options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    except Exception:  # nosec B110
        pass
    writer = getattr(QgsVectorFileWriter, "writeAsVectorFormatV3", None)
    result = writer(memory, path, QgsProject.instance().transformContext(), options)
    error = result[0] if isinstance(result, tuple) else result
    message = result[1] if isinstance(result, tuple) and len(result) > 1 else ""
    if error != getattr(QgsVectorFileWriter, "NoError", 0):
        return False, message or tr("没有写成文件。")
    loaded_uri = path
    if driver == "GPKG":
        loaded_uri = path + "|layername=" + options.layerName
    loaded = QgsVectorLayer(loaded_uri, os.path.splitext(os.path.basename(path))[0], "ogr")
    if not loaded.isValid():
        return True, tr("文件已保存：{0}").format(path)
    style = QgsMapLayerStyle()
    style.readFromLayer(layer)
    if style.isValid():
        style.writeToLayer(loaded)
    QgsProject.instance().addMapLayer(loaded, False)
    root = QgsProject.instance().layerTreeRoot()
    node = root.findLayer(layer.id())
    if node is not None and node.parent() is not None:
        parent_node = node.parent()
        try:
            parent_node.insertLayer(parent_node.children().index(node) + 1, loaded)
        except Exception:
            root.addLayer(loaded)
    else:
        root.addLayer(loaded)
    loaded.triggerRepaint()
    return True, tr("已复制图层「{0}」到：\n{1}").format(name, path)
