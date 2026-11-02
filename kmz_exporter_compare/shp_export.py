# -*- coding: utf-8 -*-
"""Write the same folder tree as the KMZ export into shapefiles."""

import os
import re

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .engine import _kmz_export_columns


def safe_part(name, fallback):
    text = re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip())
    text = text.rstrip(". ")
    return text or fallback


def clip_dbf_name(name, encoding, used):
    raw = name or "F"
    data = raw.encode(encoding, errors="replace")[:10]
    while data:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            data = data[:-1]
    else:
        text = "F"
    text = text or "F"
    base = text
    number = 2
    while text.upper() in used:
        suffix = str(number)
        room = max(1, 10 - len(suffix.encode(encoding, errors="replace")))
        stem = base.encode(encoding, errors="replace")[:room].decode(encoding, errors="ignore") or "F"
        text = (stem + suffix)[:10]
        number += 1
    used.add(text.upper())
    return text


def _memory_copy(layer, columns, encoding):
    geom_name = QgsWkbTypes.displayString(layer.wkbType())
    memory = QgsVectorLayer(geom_name, layer.name() or "layer", "memory")
    if layer.crs().isValid():
        memory.setCrs(layer.crs())
    fields = QgsFields()
    used = set()
    mapping = []
    notes = []
    for source, export in columns:
        index = layer.fields().indexFromName(source)
        if index < 0:
            continue
        original = layer.fields().at(index)
        short = clip_dbf_name(export or source, encoding, used)
        if short != (export or source):
            notes.append((export or source, short))
        field = QgsField(original)
        field.setName(short)
        fields.append(field)
        mapping.append(index)
    provider = memory.dataProvider()
    provider.addAttributes(list(fields))
    memory.updateFields()
    features = []
    for feature in layer.getFeatures():
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            continue
        out = QgsFeature(memory.fields())
        out.setGeometry(geom)
        out.setAttributes([feature.attribute(index) for index in mapping])
        features.append(out)
    if features:
        provider.addFeatures(features)
    memory.updateExtents()
    return memory, notes


def _writer_error(result):
    if isinstance(result, tuple):
        code = result[0]
        message = result[1] if len(result) > 1 else str(result)
    else:
        code = result
        message = str(result)
    if code == QgsVectorFileWriter.NoError:
        return ""
    return message or "写出失败"


def write_shapefiles(jobs, directory, encoding, include_empty):
    """jobs: dicts with parts, filename, layer, field_specs.

    Returns (written count, notes).
    """
    os.makedirs(directory, exist_ok=True)
    written = 0
    notes = []
    for job in jobs:
        layer = job["layer"]
        if layer is None or not layer.isValid():
            continue
        try:
            empty = layer.featureCount() == 0
        except Exception:
            empty = False
        if empty and not include_empty:
            continue
        folder = directory
        for part in job.get("parts") or []:
            folder = os.path.join(folder, safe_part(part, "group"))
        os.makedirs(folder, exist_ok=True)
        filename = safe_part(job.get("filename") or layer.name(), "layer") + ".shp"
        path = os.path.join(folder, filename)
        columns = _kmz_export_columns(layer, job.get("field_specs"))
        memory, renamed = _memory_copy(layer, columns, encoding)
        for source, short in renamed:
            notes.append("{0} → {1}".format(source, short))
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "ESRI Shapefile"
        options.fileEncoding = encoding
        if encoding.upper().replace("-", "") in ("GBK", "CP936"):
            options.layerOptions = ["ENCODING=GBK"]
        else:
            options.layerOptions = ["ENCODING=UTF-8"]
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            memory,
            path,
            QgsProject.instance().transformContext(),
            options,
        )
        error = _writer_error(result)
        if error:
            notes.append("{0}: {1}".format(filename, error))
            continue
        written += 1
    return written, notes
