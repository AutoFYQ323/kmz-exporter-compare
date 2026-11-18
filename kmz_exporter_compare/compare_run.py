# -*- coding: utf-8 -*-
"""Read a KMZ back and compare it with QGIS layers."""

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from .compare_core import (
    STATUS_MOVED,
    STATUS_ONLY_KMZ,
    STATUS_ONLY_QGIS,
    classify,
    layer_field_issues,
)
from .engine import (
    _get_b_all_folder_names,
    _get_b_folders_placemarks,
    _kml_extended_data_element_field_name,
    _kml_has_geometry,
    _kml_local_name,
    _kml_placemark_name,
    _kmz_get_kml_root,
)
from .i18n import tr


def folder_name_stats(path):
    """folder name -> (placemark count, set of placemark names)."""
    root, _ = _kmz_get_kml_root(path)
    if root is None:
        return None
    folders = _get_b_folders_placemarks(root)
    stats = {}
    for name, placemarks in folders.items():
        names = set()
        for placemark in placemarks:
            text = (_kml_placemark_name(placemark) or "").strip()
            if text:
                names.add(text)
        stats[name] = (len(placemarks), names)
    return stats


def _find_folder(stats, export_name):
    if export_name in stats:
        return export_name
    folded = export_name.casefold()
    for name in stats:
        if name.casefold() == folded:
            return name
    return None


def count_and_name_report(qgis_rows, kmz_path):
    """qgis_rows: list of (export_name, feature_count, set of names or None)."""
    stats = folder_name_stats(kmz_path)
    if stats is None:
        return tr("无法读取这份 KMZ。")
    lines = [tr("【数量和 Name】"), ""]
    only_qgis = []
    only_kmz = []
    count_diff = []
    name_diff = []
    same = []
    seen = set()
    for export_name, count, names in qgis_rows:
        key = (export_name or "").strip()
        seen.add(key.casefold())
        match = _find_folder(stats, key)
        if match is None:
            only_qgis.append((key, count))
            continue
        k_count, k_names = stats[match]
        if count != k_count:
            count_diff.append((key, count, k_count))
        if names is None:
            if count == k_count:
                same.append(key)
            continue
        missing = names - k_names
        extra = k_names - names
        if missing or extra:
            name_diff.append((key, missing, extra))
        elif count == k_count:
            same.append(key)
    for folder_name in stats:
        if folder_name.casefold() not in seen:
            only_kmz.append((folder_name, stats[folder_name][0]))
    lines.append(tr("QGIS 图层 {0} 个，KMZ 文件夹 {1} 个。").format(len(qgis_rows), len(stats)))
    if only_qgis:
        lines.append(tr("仅 QGIS 有："))
        for name, count in only_qgis:
            lines.append(tr("{0}（{1} 个要素）").format(name, count))
    if only_kmz:
        lines.append(tr("仅 KMZ 有："))
        for name, count in only_kmz:
            lines.append(tr("{0}（{1} 个要素）").format(name, count))
    if count_diff:
        lines.append(tr("数量不一致："))
        for name, left, right in count_diff:
            lines.append(tr("{0}：QGIS {1}，KMZ {2}").format(name, left, right))
    if name_diff:
        lines.append(tr("Name 不一致："))
        for name, missing, extra in name_diff:
            if missing:
                lines.append(tr("{0} 仅 QGIS：{1}").format(name, "、".join(sorted(missing))))
            if extra:
                lines.append(tr("{0} 仅 KMZ：{1}").format(name, "、".join(sorted(extra))))
    if not (only_qgis or only_kmz or count_diff or name_diff):
        lines.append(tr("数量和 Name 都一致。"))
    else:
        lines.append(tr("其余 {0} 个一致。").format(len(same)))
    return "\n".join(lines)


def project_layers_by_name():
    """Layer name -> (feature count, Name values or None when the field is absent)."""
    out = {}
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            continue
        name = (layer.name() or "").strip()
        try:
            count = layer.featureCount()
        except Exception:
            count = -1
        if count < 0:
            count = sum(1 for _feature in layer.getFeatures())
        names = None
        index = layer.fields().indexFromName("Name")
        if index < 0:
            index = layer.fields().indexFromName("name")
        if index >= 0:
            field = layer.fields().at(index).name()
            names = set()
            for feature in layer.getFeatures():
                value = feature[field]
                text = "" if value is None else str(value).strip()
                if text:
                    names.add(text)
        out[name] = (count, names)
    return out


def _geom_label(wkb_type):
    kind = QgsWkbTypes.geometryType(wkb_type)
    return {0: "点", 1: "线", 2: "面"}.get(kind)


def geometry_type_report(kmz_path):
    """Point / line / polygon totals. Folder names are not compared."""
    qgis_stats = {"点": (0, 0), "线": (0, 0), "面": (0, 0)}
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            continue
        label = _geom_label(layer.wkbType())
        if label is None:
            continue
        try:
            count = layer.featureCount()
        except Exception:
            count = -1
        if count < 0:
            count = sum(1 for _feature in layer.getFeatures())
        if count <= 0:
            continue
        layers, total = qgis_stats[label]
        qgis_stats[label] = (layers + 1, total + count)
    folders = kmz_features_by_folder(kmz_path)
    if folders is None:
        return tr("无法读取这份 KMZ。")
    kmz_stats = {"点": (0, 0), "线": (0, 0), "面": (0, 0)}
    for rows in folders.values():
        if not rows:
            continue
        label = _geom_label(rows[0]["geometry"].wkbType())
        if label is None:
            continue
        layers, total = kmz_stats[label]
        kmz_stats[label] = (layers + 1, total + len(rows))
    lines = [tr("【按几何类型统计对比】"), ""]
    lines.append(tr("类型\tQGIS图层\tKMZ图层\t图层一致\tQGIS要素\tKMZ要素\t要素一致"))
    for label in ("点", "线", "面"):
        q_layers, q_total = qgis_stats[label]
        k_layers, k_total = kmz_stats[label]
        lines.append("{0}\t{1}\t{2}\t{3}\t{4}\t{5}\t{6}".format(
            tr(label),
            q_layers,
            k_layers,
            tr("是") if q_layers == k_layers else tr("否"),
            q_total,
            k_total,
            tr("是") if q_total == k_total else tr("否"),
        ))
    q_layers = sum(item[0] for item in qgis_stats.values())
    k_layers = sum(item[0] for item in kmz_stats.values())
    q_total = sum(item[1] for item in qgis_stats.values())
    k_total = sum(item[1] for item in kmz_stats.values())
    lines.append("")
    lines.append(tr("合计：QGIS 有数据图层 {0} 个、要素 {1} 个；KMZ 有数据图层 {2} 个、要素 {3} 个。").format(
        q_layers, q_total, k_layers, k_total
    ))
    if q_layers == k_layers and q_total == k_total:
        lines.append(tr("整体一致。"))
    else:
        lines.append(tr("整体不一致。"))
    return "\n".join(lines)


def folder_compare_report(kmz_path, mode, zero_counts):
    """Compare every project layer with a KMZ folder of the same name.

    mode is count, name, or both. zero_counts False treats a count of 0 like a missing layer.
    """
    stats = folder_name_stats(kmz_path)
    if stats is None:
        return tr("无法读取这份 KMZ。")
    qgis_layers = project_layers_by_name()
    lines = []
    if mode in ("count", "both"):
        lines.extend(_count_lines(qgis_layers, stats, zero_counts))
    if mode in ("name", "both"):
        if lines:
            lines.append("")
        lines.extend(_name_lines(qgis_layers, stats, zero_counts))
    text = "\n".join(lines).strip()
    return text or tr("无对比结果")


def _schema_map(root):
    schemas = {}
    if root is None:
        return schemas
    for element in root.iter():
        if _kml_local_name(element.tag) != "Schema":
            continue
        sid = (element.get("id") or element.get("name") or "").strip()
        fields = []
        for child in list(element):
            if _kml_local_name(child.tag) != "SimpleField":
                continue
            name = (child.get("name") or "").strip()
            if name:
                fields.append(name)
        if not sid:
            continue
        schemas[sid] = fields
        schemas["#" + sid] = fields
    return schemas


def _placemark_field_names(placemark, schemas):
    ordered = []
    seen = set()
    if placemark is None:
        return ordered
    for child in list(placemark):
        if _kml_local_name(child.tag) != "ExtendedData":
            continue
        for data_el in list(child):
            local = _kml_local_name(data_el.tag)
            if local == "SchemaData":
                url = (data_el.get("schemaUrl") or "").strip()
                schema_fields = schemas.get(url) or schemas.get(url.lstrip("#")) or []
                for name in schema_fields:
                    key = name.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    ordered.append(name)
                for simple in list(data_el):
                    if _kml_local_name(simple.tag) != "SimpleData":
                        continue
                    name = (simple.get("name") or "").strip()
                    if not name:
                        continue
                    key = name.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    ordered.append(name)
            elif local == "Data":
                name = (_kml_extended_data_element_field_name(data_el, "Data") or "").strip()
                if not name:
                    continue
                key = name.casefold()
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(name)
    return ordered


def folder_field_lists(kmz_path):
    """folder name -> ordered field names from Schema / ExtendedData."""
    root, _ = _kmz_get_kml_root(kmz_path)
    if root is None:
        return None
    schemas = _schema_map(root)
    folders = _get_b_folders_placemarks(root)
    out = {}
    for name, placemarks in folders.items():
        fields = []
        for placemark in placemarks:
            fields = _placemark_field_names(placemark, schemas)
            if fields:
                break
        out[name] = fields
    for name in _get_b_all_folder_names(root):
        out.setdefault(name, [])
    return out


def project_layer_fields():
    """Layer name -> ordered field names."""
    out = {}
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            continue
        name = (layer.name() or "").strip()
        if not name:
            continue
        fields = []
        for field in layer.fields():
            field_name = (field.name() or "").strip()
            if field_name:
                fields.append(field_name)
        out[name] = fields
    return out


def _field_issue_labels():
    return {
        "only_qgis": tr("仅 QGIS 有此图层"),
        "only_kmz": tr("仅 KMZ 有此文件夹"),
        "fields_only_qgis": tr("仅 QGIS 有这些字段"),
        "fields_only_kmz": tr("仅 KMZ 有这些字段"),
        "field_order": tr("字段顺序不一致"),
    }


def _field_issue_type(kind):
    if kind in ("only_qgis", "only_kmz"):
        return tr("图层")
    if kind == "field_order":
        return tr("字段顺序")
    return tr("字段")


def layer_fields_table(kmz_path):
    """Return (rows, summary_text). rows are dicts: qgis, kmz, type, result."""
    kmz_fields = folder_field_lists(kmz_path)
    if kmz_fields is None:
        return None, tr("无法读取这份 KMZ。")
    qgis_fields = project_layer_fields()
    issues = layer_field_issues(qgis_fields, kmz_fields)
    labels = _field_issue_labels()
    rows = []
    for issue in issues:
        kind = issue.get("kind")
        detail = (issue.get("detail") or "").strip()
        result = labels.get(kind, kind or "")
        if detail:
            result = "{0}：{1}".format(result, detail)
        rows.append({
            "qgis": issue.get("qgis") or "—",
            "kmz": issue.get("kmz") or "—",
            "type": _field_issue_type(kind),
            "result": result,
        })
    lines = [tr("【图层名称与字段对比】"), ""]
    lines.append(tr("QGIS 图层 {0} 个，KMZ 文件夹 {1} 个。").format(len(qgis_fields), len(kmz_fields)))
    if not rows:
        lines.append(tr("图层名称与字段（含顺序）均一致。"))
    else:
        for row in rows:
            lines.append("{0}\t{1}\t{2}\t{3}".format(
                row["qgis"], row["kmz"], row["type"], row["result"]
            ))
        lines.append("")
        lines.append(tr("共 {0} 处不一致。").format(len(rows)))
    return rows, "\n".join(lines)


def layer_fields_report(kmz_path):
    """Compare KMZ folder names and fields with QGIS layers, including field order."""
    _rows, text = layer_fields_table(kmz_path)
    return text


def _effective_count(count, zero_counts):
    if count is None:
        return None
    if not zero_counts and count == 0:
        return None
    return count


def _count_lines(qgis_layers, stats, zero_counts):
    lines = [tr("【数量对比】"), tr("图层名\tQGIS数量\tKMZ数量\t是否一致")]
    only_qgis = []
    only_kmz = []
    diff = []
    same = []
    names = set(qgis_layers) | set(stats)
    for name in sorted(names):
        q_count = qgis_layers[name][0] if name in qgis_layers else None
        k_count = stats[name][0] if name in stats else None
        q_count = _effective_count(q_count, zero_counts)
        k_count = _effective_count(k_count, zero_counts)
        if q_count is None and k_count is None:
            continue
        if q_count is None:
            only_kmz.append((name, k_count))
        elif k_count is None:
            only_qgis.append((name, q_count))
        elif q_count != k_count:
            diff.append((name, q_count, k_count))
        else:
            same.append((name, q_count, k_count))
    for name, count in only_qgis:
        lines.append("{0}\t{1}\t-\t{2}".format(name, count, tr("仅QGIS有")))
    for name, count in only_kmz:
        lines.append("{0}\t-\t{1}\t{2}".format(name, count, tr("仅KMZ有")))
    for name, left, right in diff:
        lines.append("{0}\t{1}\t{2}\t{3}".format(name, left, right, tr("不一致")))
    for name, left, right in same:
        lines.append("{0}\t{1}\t{2}\t{3}".format(name, left, right, tr("一致")))
    total = len(only_qgis) + len(only_kmz) + len(diff) + len(same)
    lines.append("")
    lines.append(tr("共 {0} 个图层：{1} 个数量不一致，{2} 个仅QGIS有，{3} 个仅KMZ有，其余 {4} 个一致。").format(
        total, len(diff), len(only_qgis), len(only_kmz), len(same)
    ))
    return lines


def _name_lines(qgis_layers, stats, zero_counts):
    lines = [tr("【Name 字段对比】")]
    skipped = 0
    consistent = 0
    inconsistent = 0
    common = sorted(set(qgis_layers) & set(stats))
    if not zero_counts:
        common = [
            name for name in common
            if qgis_layers[name][0] > 0 and stats[name][0] > 0
        ]
    for name in common:
        q_names = qgis_layers[name][1]
        k_names = stats[name][1]
        if q_names is None or k_names is None:
            lines.append(tr("图层 [{0}]: 无 Name 字段，已跳过").format(name))
            skipped += 1
            continue
        only_qgis = q_names - k_names
        only_kmz = k_names - q_names
        if not only_qgis and not only_kmz:
            lines.append(tr("图层 [{0}]: Name 集合一致").format(name))
            consistent += 1
            continue
        lines.append(tr("图层 [{0}]: 不一致").format(name))
        inconsistent += 1
        if only_qgis:
            lines.append(tr("  仅在 QGIS 中出现的 Name: {0}").format(", ".join(sorted(only_qgis))))
        if only_kmz:
            lines.append(tr("  仅在 KMZ 中出现的 Name: {0}").format(", ".join(sorted(only_kmz))))
    total = skipped + consistent + inconsistent
    lines.append("")
    lines.append(tr("共 {0} 个图层参与 Name 对比：{1} 个一致，{2} 个不一致，{3} 个无 Name 字段已跳过。").format(
        total, consistent, inconsistent, skipped
    ))
    return lines


def _child_text(element, local_name):
    for child in list(element):
        if _kml_local_name(child.tag) == local_name:
            return child.text or ""
    return ""


def _coordinates(element):
    points = []
    for token in _child_text(element, "coordinates").replace("\n", " ").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            points.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return points


def geometry_from_kml(element):
    local = _kml_local_name(element.tag)
    if local == "Point":
        points = _coordinates(element)
        if not points:
            return None
        return QgsGeometry.fromPointXY(QgsPointXY(points[0][0], points[0][1]))
    if local == "LineString":
        points = _coordinates(element)
        if len(points) < 2:
            return None
        return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points])
    if local == "Polygon":
        rings = []
        for child in list(element):
            name = _kml_local_name(child.tag)
            if name not in ("outerBoundaryIs", "innerBoundaryIs"):
                continue
            for ring in list(child):
                if _kml_local_name(ring.tag) != "LinearRing":
                    continue
                points = _coordinates(ring)
                if len(points) >= 4:
                    rings.append([QgsPointXY(x, y) for x, y in points])
        if not rings:
            return None
        return QgsGeometry.fromPolygonXY(rings)
    if local == "MultiGeometry":
        parts = []
        for child in list(element):
            part = geometry_from_kml(child)
            if part is not None and not part.isEmpty():
                parts.append(part)
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        return QgsGeometry.collectGeometry(parts)
    for child in list(element):
        geom = geometry_from_kml(child)
        if geom is not None and not geom.isEmpty():
            return geom
    return None


def placemark_geometry(placemark):
    if not _kml_has_geometry(placemark):
        return None
    for child in list(placemark):
        geom = geometry_from_kml(child)
        if geom is not None and not geom.isEmpty():
            return geom
    return None


def kmz_features_by_folder(path):
    root, _ = _kmz_get_kml_root(path)
    if root is None:
        return None
    folders = _get_b_folders_placemarks(root)
    out = {}
    for name, placemarks in folders.items():
        rows = []
        for index, placemark in enumerate(placemarks):
            geom = placemark_geometry(placemark)
            if geom is None or geom.isEmpty():
                continue
            rows.append({
                "id": index,
                "name": (_kml_placemark_name(placemark) or "").strip(),
                "geometry": geom,
            })
        out[name] = rows
    return out


def _to_layer_crs(geometry, layer):
    source = QgsCoordinateReferenceSystem("EPSG:4326")
    dest = layer.crs()
    cloned = QgsGeometry(geometry)
    if dest.isValid() and source != dest:
        transform = QgsCoordinateTransform(
            source, dest, QgsProject.instance().transformContext()
        )
        cloned.transform(transform)
    return cloned


def _item(fid, name, geometry):
    box = geometry.boundingBox()
    return {
        "id": fid,
        "name": name or "",
        "payload": geometry,
        "bbox": (box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum()),
    }


def _feature_name(feature, field_name):
    if not field_name:
        return ""
    try:
        value = feature.attribute(field_name)
    except Exception:
        return ""
    if value is None:
        return ""
    return str(value).strip()


def compare_layer(layer, kmz_rows, tolerance, name_field):
    src = []
    for feature in layer.getFeatures():
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            continue
        src.append(_item(feature.id(), _feature_name(feature, name_field), QgsGeometry(geom)))
    dst = []
    for row in kmz_rows:
        try:
            geom = _to_layer_crs(row["geometry"], layer)
        except Exception:  # nosec B112
            continue
        if geom.isEmpty():
            continue
        dst.append(_item(row["id"], row["name"], geom))
    return classify(src, dst, tolerance, lambda left, right: left.distance(right))


def _status_label(code):
    return {
        STATUS_ONLY_QGIS: tr("仅 QGIS"),
        STATUS_ONLY_KMZ: tr("仅 KMZ"),
        STATUS_MOVED: tr("同名已移动"),
    }.get(code, code)


def write_result_layer(layer, only_src, only_dst, moved):
    geom_name = QgsWkbTypes.displayString(layer.wkbType())
    title = tr("{0} 坐标对比").format(layer.name() or tr("图层"))
    memory = QgsVectorLayer(geom_name, title, "memory")
    if layer.crs().isValid():
        memory.setCrs(layer.crs())
    provider = memory.dataProvider()
    provider.addAttributes([
        QgsField("code", QVariant.String, "text", 20),
        QgsField("status", QVariant.String, "text", 20),
        QgsField("name", QVariant.String, "text", 254),
        QgsField("other_name", QVariant.String, "text", 254),
        QgsField("distance", QVariant.Double, "double", 20, 6),
    ])
    memory.updateFields()
    rows = []
    for item in only_src:
        rows.append((STATUS_ONLY_QGIS, item["name"], "", None, item["payload"]))
    for item in only_dst:
        rows.append((STATUS_ONLY_KMZ, item["name"], "", None, item["payload"]))
    for item in moved:
        rows.append((
            STATUS_MOVED,
            item["src"]["name"],
            item["dst"]["name"],
            item["distance"],
            item["src"]["payload"],
        ))
    features = []
    for code, name, other, distance, geom in rows:
        feature = QgsFeature(memory.fields())
        feature.setGeometry(geom)
        feature.setAttributes([code, _status_label(code), name, other, distance])
        features.append(feature)
    if features:
        provider.addFeatures(features)
    memory.updateExtents()
    return memory, len(only_src), len(only_dst), len(moved)


def compare_project(layers, kmz_path, tolerance):
    """layers: list of (export_name, QgsVectorLayer, name_field). Returns (text, result layers)."""
    folders = kmz_features_by_folder(kmz_path)
    if folders is None:
        return tr("无法读取这份 KMZ。"), []
    lines = [tr("【坐标对比】"), ""]
    results = []
    matched = set()
    for export_name, layer, name_field in layers:
        folder = _find_folder(folders, (export_name or "").strip())
        if folder is None:
            lines.append(tr("{0}：KMZ 里没有同名文件夹。").format(export_name))
            continue
        matched.add(folder.casefold())
        only_src, only_dst, moved = compare_layer(
            layer, folders[folder], tolerance, name_field
        )
        if not only_src and not only_dst and not moved:
            lines.append(tr("{0}：坐标一致。").format(export_name))
            continue
        memory, n_src, n_dst, n_moved = write_result_layer(layer, only_src, only_dst, moved)
        results.append(memory)
        lines.append(tr(
            "{0}：仅 QGIS {1}，仅 KMZ {2}，同名已移动 {3}。结果图层「{4}」。"
        ).format(export_name, n_src, n_dst, n_moved, memory.name()))
    for folder_name in folders:
        if folder_name.casefold() not in matched:
            lines.append(tr("{0}：QGIS 里没有同名图层。").format(folder_name))
    return "\n".join(lines), results


def add_results(layers):
    if not layers:
        return
    root = QgsProject.instance().layerTreeRoot()
    group_name = tr("KMZ对比")
    group = root.findGroup(group_name)
    if group is None:
        group = root.insertGroup(0, group_name)
    for layer in layers:
        QgsProject.instance().addMapLayer(layer, False)
        group.addLayer(layer)
