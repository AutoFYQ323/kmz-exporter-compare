# -*- coding: utf-8 -*-
"""KMZ read, write, and reference-style tools moved out of LayerProcess.

UI text added in this plugin goes through i18n.tr. Messages in this file are
the exported report text from the existing writer.
"""
import datetime
import html
import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET  # nosec B405
from io import BytesIO

from qgis.PyQt.QtCore import QDate, QDateTime, QPointF, QSize, Qt, QTime
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QComboBox
from .i18n import tr
from qgis.core import (
    NULL,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsGeometry,
    QgsMapSettings,
    QgsProject,
    QgsRenderContext,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

SETTINGS_KEY = "ITTP"
KML_NS = "{http://www.opengis.net/kml/2.2}"
KML_NS_ALT = "{http://earth.google.com/kml/2.0}"
ET.register_namespace("", "http://www.opengis.net/kml/2.2")
ET.register_namespace("gx", "http://www.google.com/kml/ext/2.2")
ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
ET.register_namespace("xal", "urn:oasis:names:tc:ciq:xsdschema:xAL:2.0")


def _kml_normalize_ns(element):
    """Recursively convert all KML-related namespace variants to the standard KML 2.2 namespace.
    This ensures elements from different KML files (which may use kml/2.0 or no namespace) are unified."""
    std_ns = "http://www.opengis.net/kml/2.2"
    alt_ns_exact = {
        "http://earth.google.com/kml/2.0",
        "http://earth.google.com/kml/2.1",
        "http://earth.google.com/kml/2.2",
        "http://www.opengis.net/kml/2.1",
        "http://www.opengis.net/kml/2.3",
    }
    kml_tags = {
        "kml", "Document", "Folder", "Placemark", "name", "description", "visibility",
        "open", "Style", "StyleMap", "Pair", "key", "styleUrl",
        "IconStyle", "Icon", "href", "hotSpot", "scale",
        "LineStyle", "color", "width", "colorMode",
        "PolyStyle", "fill", "outline",
        "LabelStyle",
        "BalloonStyle", "text", "bgColor", "textColor",
        "ListStyle", "ItemIcon", "listItemType", "state",
        "Point", "LineString", "Polygon", "LinearRing",
        "MultiGeometry", "MultiTrack", "Track",
        "coordinates", "outerBoundaryIs", "innerBoundaryIs",
        "altitudeMode", "extrude", "tessellate",
        "ExtendedData", "Data", "value", "displayName", "SimpleData",
        "SchemaData", "SimpleField", "Schema",
        "Region", "LatLonAltBox", "Lod",
        "LookAt", "Camera", "TimeStamp", "TimeSpan", "when", "begin", "end",
        "NetworkLink", "Link", "NetworkLinkControl",
        "GroundOverlay", "ScreenOverlay", "PhotoOverlay",
        "LatLonBox", "north", "south", "east", "west", "rotation",
        "heading", "tilt", "range", "longitude", "latitude", "altitude",
        "refreshVisibility", "flyToView",
        "Snippet", "address", "phoneNumber",
        "minLodPixels", "maxLodPixels", "minFadeExtent", "maxFadeExtent",
    }
    for el in element.iter():
        tag = el.tag
        if not isinstance(tag, str):
            continue
        if tag.startswith("{"):
            uri, local = tag[1:].split("}", 1)
            if uri != std_ns and (
                uri in alt_ns_exact
                or uri.startswith("http://earth.google.com/kml/")
                or uri.startswith("http://www.opengis.net/kml/")
            ):
                el.tag = "{" + std_ns + "}" + local
        elif tag in kml_tags:
            el.tag = "{" + std_ns + "}" + tag
    return element


def _kmz_get_kml_root(path):
    """Return (root Element, original kml bytes for re-use) from a KMZ or KML path."""
    if str(path).lower().endswith(".kml"):
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            root = ET.fromstring(data)  # nosec B314
            _kml_normalize_ns(root)
            return root, data
        except Exception:
            return None, None
    with zipfile.ZipFile(path, "r") as z:
        for name in ["doc.kml", "Doc.kml", "document.kml"]:
            if name in z.namelist():
                with z.open(name) as f:
                    data = f.read()
                root = ET.fromstring(data)  # nosec B314
                _kml_normalize_ns(root)
                return root, data
        cand = [n for n in z.namelist() if n.lower().endswith(".kml")]
        if cand:
            with z.open(cand[0]) as f:
                data = f.read()
            root = ET.fromstring(data)  # nosec B314
            _kml_normalize_ns(root)
            return root, data
    return None, None


def _kmz_get_all_folder_names(path):
    """打开 KMZ，递归收集 Document 下所有 Folder 的 name，返回 set。用于判断输出中是否包含某文件夹。"""
    root, _ = _kmz_get_kml_root(path)
    if root is None:
        return set()
    doc = root.find(".//" + KML_NS + "Document")
    if doc is None:
        doc = root.find(".//" + KML_NS_ALT + "Document")
    if doc is None:
        doc = root
    names = set()

    def recurse(parent):
        for folder in _kml_find_folders(parent):
            name = _kml_folder_name(folder)
            if name:
                names.add(name)
            recurse(folder)

    recurse(doc)
    return names


def _kml_has_geometry(placemark):
    for tag in ("Point", "LineString", "Polygon", "MultiGeometry", "MultiTrack", "Track"):
        for uri in (KML_NS, KML_NS_ALT, ""):
            pre = uri if uri else ""
            if placemark.find(".//{}".format(pre + tag)) is not None:
                return True
    return False


def _kml_placemark_has_point(placemark):
    """True if placemark has Point geometry (so we prefer IconStyle when falling back)."""
    for uri in (KML_NS, KML_NS_ALT, ""):
        tag = (uri + "Point") if uri else "Point"
        if placemark.find(".//" + tag) is not None:
            return True
    return False


def _kml_local_tag(el):
    if el is None or not isinstance(getattr(el, "tag", None), str):
        return ""
    tag = el.tag
    return tag.split("}")[-1] if "}" in tag else tag


def _kml_placemark_geom_kind(placemark):
    """Return 点/线/面/混合/'' for a Placemark."""
    kinds = set()
    for el in placemark.iter():
        local = _kml_local_tag(el)
        if local == "Point":
            kinds.add("点")
        elif local in ("LineString", "LinearRing", "Track"):
            kinds.add("线")
        elif local == "Polygon":
            kinds.add("面")
    if not kinds:
        return ""
    if len(kinds) > 1:
        return "混合"
    return kinds.pop()


def _kml_placemarks_geom_kind(placemarks):
    kinds = set()
    for pm in placemarks or []:
        k = _kml_placemark_geom_kind(pm)
        if k:
            kinds.add(k)
    if not kinds:
        return "—"
    if "混合" in kinds or len(kinds) > 1:
        return "混合"
    return kinds.pop()


def _kml_find_document(root):
    if root is None:
        return None
    if _kml_local_tag(root) == "Document":
        return root
    for el in root.iter():
        if isinstance(el.tag, str) and _kml_local_tag(el) == "Document":
            return el
    return root


def _kml_is_generic_root_name(name):
    n = (name or "").strip().lower()
    return (not n) or n in (
        "qgis export", "untitled", "kml", "document",
        "my places", "temporary places", "google earth",
    )


def _kml_source_root_display_name(root, path):
    """Outermost Document name when using the source KMZ.

    Use the source file name (what the user selected as 源图层). Both QGIS
    exports usually have Document name 'QGIS Export', so copying that looks
    like the switch did nothing.
    """
    file_stem = os.path.splitext(os.path.basename(path or ""))[0].strip()
    if file_stem:
        return file_stem
    doc_name = _kml_document_name(root)
    if not _kml_is_generic_root_name(doc_name):
        return doc_name
    return doc_name or ""


def _kml_folder_name(folder):
    name_el = folder.find(KML_NS + "name")
    if name_el is None:
        name_el = folder.find(KML_NS_ALT + "name")
    if name_el is None:
        name_el = folder.find("name")
    if name_el is not None and name_el.text is not None:
        return name_el.text.strip()
    for child in folder:
        if child.tag is None:
            continue
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "name" and child.text is not None:
            return child.text.strip()
    return ""


def _kml_document_name(root):
    if root is None:
        return ""
    doc = _kml_find_document(root)
    if doc is None:
        return ""
    return _kml_folder_name(doc)


def _kml_set_document_name(root_or_doc, name):
    if root_or_doc is None or not name:
        return
    doc = root_or_doc
    if _kml_local_tag(root_or_doc) != "Document":
        found = _kml_find_document(root_or_doc)
        if found is not None:
            doc = found
    for ch in list(doc):
        if _kml_local_tag(ch) == "name":
            ch.text = name
            return
    el = ET.Element(KML_NS + "name")
    el.text = name
    doc.insert(0, el)


def _kml_placemark_name(pm):
    """Get name element text from a Placemark (for style matching)."""
    for uri in (KML_NS, KML_NS_ALT, ""):
        name_el = pm.find(uri + "name") if uri else pm.find("name")
        if name_el is not None and name_el.text is not None:
            return (name_el.text or "").strip()
    return ""


def _kml_child_elements(parent, local_name):
    out = []
    seen = set()
    for ch in list(parent):
        if _kml_local_tag(ch) != local_name:
            continue
        i = id(ch)
        if i in seen:
            continue
        seen.add(i)
        out.append(ch)
    return out


def _kml_find_folders(parent):
    """Return list of direct child Folder elements (any namespace)."""
    return _kml_child_elements(parent, "Folder")


def _kml_find_placemarks(parent):
    return _kml_child_elements(parent, "Placemark")


def _kml_folder_has_nested_container(folder):
    for ch in list(folder):
        if _kml_local_tag(ch) in ("Folder", "Document", "NetworkLink"):
            return True
    return False


def _kml_folder_at_path(parent, path_tuple):
    """Return Folder element at path (tuple of folder names from parent). Returns None if not found."""
    if not path_tuple:
        return None
    for folder in _kml_find_folders(parent):
        if _kml_folder_name(folder) != path_tuple[0]:
            continue
        if len(path_tuple) == 1:
            return folder
        child = _kml_folder_at_path(folder, path_tuple[1:])
        if child is not None:
            return child
    return None


def _kml_placemark_geometry_tag_local(el):
    """Return True if element is a geometry tag (Point, LineString, Polygon, MultiGeometry, etc.)."""
    if el.tag is None:
        return False
    t = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    return t in ("Point", "LineString", "Polygon", "MultiGeometry", "MultiTrack", "Track")


def _kml_placemark_remove_geometry(placemark):
    """Remove geometry child from placemark (Point/LineString/Polygon/MultiGeometry). Modifies in place."""
    to_remove = []
    for child in placemark:
        if _kml_placemark_geometry_tag_local(child):
            to_remove.append(child)
    for el in to_remove:
        placemark.remove(el)






def _get_a_folders_with_placemarks(root):
    """Recursively return list of (folder_name, placemarks_list, folder_element) for every Folder
    that directly contains at least one Placemark with geometry. So A 的嵌套结构下每一层「图层」
    （有要素的 Folder）都会按图层名参与匹配，与 B 是否带文件夹无关。"""
    out = []
    doc = root.find(".//" + KML_NS + "Document")
    if doc is None:
        doc = root.find(".//" + KML_NS_ALT + "Document")
    if doc is None:
        doc = root

    def recurse(parent):
        for folder in _kml_find_folders(parent):
            with_geom = [p for p in _kml_find_placemarks(folder) if _kml_has_geometry(p)]
            if with_geom:
                name = _kml_folder_name(folder)
                out.append((name, with_geom, folder))
            recurse(folder)

    recurse(doc)
    return out


def _get_styles_from_element(parent):
    """Return list of (style_id, style_element) from Style and StyleMap children."""
    styles = []
    for style in parent.findall(KML_NS + "Style") + parent.findall(KML_NS_ALT + "Style") + parent.findall("Style"):
        sid = style.get("id") or ("style_" + str(len(styles)))
        styles.append((sid, style))
    for sm in parent.findall(KML_NS + "StyleMap") + parent.findall(KML_NS_ALT + "StyleMap") + parent.findall("StyleMap"):
        sid = sm.get("id") or ("stylemap_" + str(len(styles)))
        styles.append((sid, sm))
    return styles


def _get_b_styles_by_folder(root):
    """Return dict: folder_name -> list of (style_id, style_element). Recursively collect
    so that nested folders (e.g. FYQ > A, B, C) are all matched by layer name like A."""
    doc = root.find(".//" + KML_NS + "Document")
    if doc is None:
        doc = root.find(".//" + KML_NS_ALT + "Document")
    if doc is None:
        doc = root
    doc_styles = _get_styles_from_element(doc)
    result = {}

    def recurse(parent):
        for folder in _kml_find_folders(parent):
            name = _kml_folder_name(folder)
            folder_styles = _get_styles_from_element(folder)
            if folder_styles:
                result[name] = folder_styles
            elif doc_styles:
                result[name] = list(doc_styles)
            recurse(folder)

    recurse(doc)
    return result


def _get_all_styles_by_id(root):
    """Return dict: style_id -> style_element for every Style/StyleMap in the tree."""
    out = {}
    for el in root.iter():
        if el.tag is None:
            continue
        tag_lower = (el.tag.lower() if isinstance(el.tag, str) else "")
        if "style" not in tag_lower and "stylemap" not in tag_lower:
            continue
        sid = el.get("id") or ""
        if sid:
            out[sid] = el
    return out


def _style_url_refs(element):
    """Yield all #styleId from styleUrl children in element (e.g. StyleMap Pair/styleUrl)."""
    for el in element.iter():
        if el.tag is None:
            continue
        if "styleurl" not in (el.tag.lower() if isinstance(el.tag, str) else ""):
            continue
        t = (el.text or "").strip()
        if t.startswith("#"):
            yield t[1:].strip()


def _expand_style_list_with_refs(style_list, all_styles_by_id):
    """Ensure every styleUrl #id referenced by a StyleMap is in the list (so we copy and assign new id).
    Returns expanded list: referenced styles first, then originals. Caller should dedupe by sid before use."""
    seen = set()
    expanded = []
    to_process = list(style_list)
    while to_process:
        sid, el = to_process.pop(0)
        if sid in seen:
            continue
        seen.add(sid)
        tag_lower = (el.tag or "").lower() if isinstance(el.tag, str) else ""
        if "stylemap" in tag_lower:
            for ref_id in _style_url_refs(el):
                if ref_id and ref_id not in seen and ref_id in all_styles_by_id:
                    to_process.append((ref_id, all_styles_by_id[ref_id]))
        expanded.append((sid, el))
    return expanded


def _get_b_folders_placemarks(root_b):
    """Return dict: folder_name -> list of Placemark elements (with geometry) in B, same order as in KML."""
    out = {}
    doc = root_b.find(".//" + KML_NS + "Document")
    if doc is None:
        doc = root_b.find(".//" + KML_NS_ALT + "Document")
    if doc is None:
        doc = root_b

    def recurse(parent):
        for folder in _kml_find_folders(parent):
            name = _kml_folder_name(folder)
            with_geom = [p for p in _kml_find_placemarks(folder) if _kml_has_geometry(p)]
            if with_geom:
                out[name] = with_geom
            recurse(folder)

    recurse(doc)
    return out


def _get_b_all_folder_names(root_b):
    """Return set of all Folder names in B (including folders with no placemarks)."""
    out = set()
    doc = root_b.find(".//" + KML_NS + "Document")
    if doc is None:
        doc = root_b.find(".//" + KML_NS_ALT + "Document")
    if doc is None:
        doc = root_b

    def recurse(parent):
        for folder in _kml_find_folders(parent):
            name = _kml_folder_name(folder)
            out.add(name)
            recurse(folder)

    recurse(doc)
    return out


def _get_b_folder_name_to_style(root_b):
    """Return dict: folder_name -> { placemark_name -> style_id } for matching A placemarks by name."""
    b_placemarks = _get_b_folders_placemarks(root_b)
    result = {}
    for folder_name, pms in b_placemarks.items():
        result[folder_name] = {}
        for pm in pms:
            name = _kml_placemark_name(pm)
            style_id = _placemark_style_url_static(pm)
            if style_id is not None:
                result[folder_name][name] = style_id
    return result


def _placemark_style_url_static(pm):
    """Get styleUrl #id from placemark (without #)."""
    for c in pm:
        if c.tag is None:
            continue
        local = c.tag.split("}")[-1] if isinstance(c.tag, str) and "}" in c.tag else (c.tag if isinstance(c.tag, str) else "")
        if local == "styleUrl" and (c.text or "").strip().startswith("#"):
            return (c.text or "").strip()[1:].strip()
    return None


def _normalize_kmz_icon_href(href_text):
    """Convert absolute path pointing into KMZ (e.g. file:///.../x.kmz!/files/icon.png) to relative path (files/icon.png)."""
    if not href_text or not isinstance(href_text, str):
        return href_text
    s = href_text.strip()
    if not s:
        return s
    # Already relative (no scheme, no drive letter at start)
    if not s.startswith(("file:", "file://", "file:///")) and (len(s) < 2 or s[1] != ":"):
        return s
    # file:///C:/path/to/x.kmz!/files/icon.png -> take after "!"
    if "!" in s:
        after = s.split("!")[-1].strip().lstrip("/\\")
        if after:
            return after.replace("\\", "/")
    # C:\path\to\x.kmz\files\icon.png or /path/to/x.kmz/files/icon.png
    if ".kmz" in s.lower():
        idx = s.lower().rfind(".kmz")
        after = s[idx + 4 :].lstrip("/\\")
        if after:
            return after.replace("\\", "/")
    return s


def _href_to_local_path(href_text):
    """Convert file:// URL or absolute path to local filesystem path, or None if not external."""
    if not href_text or not isinstance(href_text, str):
        return None
    s = href_text.strip()
    if s.startswith("file:///"):
        path = s[8:].replace("/", os.sep)
    elif s.startswith("file://"):
        path = s[7:].replace("/", os.sep)
    elif s.startswith("file:"):
        path = s[5:].lstrip("/").replace("/", os.sep)
    elif len(s) >= 2 and s[1] == ":":
        path = s.replace("/", os.sep)
    elif s.startswith("/"):
        path = s.replace("/", os.sep)
    else:
        return None
    return path if path else None


def _kml_normalize_style_hrefs(element, external_files=None):
    """In style subtree, set any href to relative path (point/line/poly/list icons).
    Handles: IconStyle/Icon/href, ListStyle/ItemIcon/href, and any other element with href.
    If external_files is a list, embed external icon files (outside KMZ) and set href to files/_ext_*.png|svg|..."""
    if external_files is None:
        external_files = []
    ext_counter = [len(external_files)]
    for el in element.iter():
        if el.tag is None:
            continue
        tag_lower = el.tag.lower() if isinstance(el.tag, str) else ""
        if "href" not in tag_lower or not (el.text or "").strip():
            continue
        raw = (el.text or "").strip()
        normalized = _normalize_kmz_icon_href(raw)
        if normalized != raw or _href_to_local_path(raw) is not None:
            path = _href_to_local_path(normalized) or _href_to_local_path(raw)
            if path and os.path.isfile(path):
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                except Exception:
                    data = None
                if data is not None:
                    _, ext = os.path.splitext(path)
                    if ext and ext.lower() in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg"):
                        pass
                    else:
                        ext = ".png"
                    zip_name = "files/_ext_{}{}".format(ext_counter[0], ext)
                    ext_counter[0] += 1
                    external_files.append((zip_name, data))
                    el.text = zip_name
                    continue
        el.text = normalized


def _kml_rewrite_style_urls(element, old_to_new):
    """Replace styleUrl #old with #new in element subtree (e.g. StyleMap Pair/styleUrl)."""
    for el in list(element.iter()):
        if el.tag is None:
            continue
        if "styleurl" not in (el.tag.lower() if isinstance(el.tag, str) else ""):
            continue
        raw = el.text
        if raw is None:
            raw = ""
        s = raw.strip()
        if not s.startswith("#"):
            continue
        key = s[1:].strip()
        if not key or key not in old_to_new:
            continue
        new_val = "#" + old_to_new[key]
        el.text = new_val


def _kml_style_has_icon(style_el):
    """Return True if this Style element has an IconStyle (point icon). StyleMap not resolved."""
    if style_el is None:
        return False
    for uri in (KML_NS, KML_NS_ALT, ""):
        tag = (uri + "IconStyle") if uri else "IconStyle"
        if style_el.find(tag) is not None:
            return True
    for child in style_el:
        if child.tag and "iconstyle" in (child.tag.lower() if isinstance(child.tag, str) else ""):
            return True
    return False


_KML_FOLDER_META_TAGS = {
    "name", "visibility", "open", "address", "phoneNumber",
    "Snippet", "description", "LookAt", "Camera",
    "TimeStamp", "TimeSpan", "Region",
}


def _kml_find_liststyle(style_el):
    if style_el is None:
        return None
    for uri in (KML_NS, KML_NS_ALT, ""):
        tag = (uri + "ListStyle") if uri else "ListStyle"
        el = style_el.find(tag)
        if el is not None:
            return el
    for child in style_el:
        if _kml_local_tag(child) == "ListStyle":
            return child
    return None


def _kml_folder_had_iconstyle(folder):
    """True if this Folder itself (not its placemarks) already carries IconStyle/StyleMap.

    Some KMZ viewers use a Folder's own IconStyle as the tree icon. Layer folders
    that already look like point symbols in the reference should keep that; grouping
    folders that only had a default folder icon must not gain IconStyle.
    """
    for ch in list(folder):
        local = _kml_local_tag(ch)
        if local == "Style" and _kml_style_has_icon(ch):
            return True
        if local == "StyleMap":
            return True
    return False


def _kml_folder_keep_liststyle(folder):
    """Copy ListStyle from a folder-owned Style that is not a point IconStyle.

    Point styles often carry ListStyle/ItemIcon with the same png; using that
    Style on the Folder makes Google Earth show the point icon as the folder icon.
    """
    for ch in list(folder):
        if _kml_local_tag(ch) != "Style":
            continue
        if _kml_style_has_icon(ch):
            continue
        ls = _kml_find_liststyle(ch)
        if ls is not None:
            return ET.fromstring(ET.tostring(ls))  # nosec B314
    return None


def _kml_insert_after_folder_meta(folder, el):
    idx = 0
    for i, ch in enumerate(list(folder)):
        if _kml_local_tag(ch) in _KML_FOLDER_META_TAGS:
            idx = i + 1
        else:
            break
    folder.insert(idx, el)


def _kml_make_folder_list_style(style_id, liststyle_src=None):
    """Style used only by the Folder itself so the Places list keeps a folder icon."""
    style = ET.Element(KML_NS + "Style")
    style.set("id", style_id)
    if liststyle_src is not None:
        style.append(ET.fromstring(ET.tostring(liststyle_src)))  # nosec B314
    else:
        ls = ET.SubElement(style, KML_NS + "ListStyle")
        lit = ET.SubElement(ls, KML_NS + "listItemType")
        lit.text = "check"
    return style


def _kml_detach_icon_from_grouping_folders(doc, next_id):
    """Move IconStyle off folders that contain child Folders so the tree keeps a folder icon."""
    def walk(parent):
        for folder in _kml_find_folders(parent):
            walk(folder)
            if not _kml_folder_has_nested_container(folder):
                continue
            has_styleurl = any(_kml_local_tag(ch) == "styleUrl" for ch in list(folder))
            if not _kml_folder_had_iconstyle(folder) and not has_styleurl:
                continue
            keep_ls = _kml_folder_keep_liststyle(folder)
            to_move = []
            to_drop_su = []
            for ch in list(folder):
                local = _kml_local_tag(ch)
                if local == "StyleMap" or (local == "Style" and _kml_style_has_icon(ch)):
                    to_move.append(ch)
                elif local == "styleUrl":
                    to_drop_su.append(ch)
            for el in to_move:
                folder.remove(el)
                doc.append(el)
            for el in to_drop_su:
                folder.remove(el)
            list_id = next_id("group_list")
            folder.append(_kml_make_folder_list_style(list_id, keep_ls))
            su = ET.Element(KML_NS + "styleUrl")
            su.text = "#" + list_id
            _kml_insert_after_folder_meta(folder, su)
    walk(doc)


def _placemark_get_inline_style(pm):
    """Get inline <Style> element from a Placemark (style without id, direct child of Placemark).
    Returns the Style element or None."""
    for uri in (KML_NS, KML_NS_ALT, ""):
        tag = (uri + "Style") if uri else "Style"
        style = pm.find(tag)
        if style is not None:
            return style
    for child in pm:
        if child.tag and isinstance(child.tag, str):
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "Style":
                return child
    return None


def _shared_style_from_placemark(pm, all_styles_by_id):
    debug_lines = []
    empty = {
        'normal_style': None, 'highlight_style': None,
        'stylemap': None, 'is_stylemap': False, 'debug': "",
    }
    if pm is None:
        return empty
    inline = _placemark_get_inline_style(pm)
    if inline is not None:
        style_copy = ET.fromstring(ET.tostring(inline))  # nosec B314
        _kml_normalize_ns(style_copy)
        debug_lines.append("使用内联样式")
        return {
            'normal_style': style_copy, 'highlight_style': None,
            'stylemap': None, 'is_stylemap': False, 'debug': "; ".join(debug_lines)
        }
    ref_id = _placemark_style_url_static(pm)
    if not ref_id or ref_id not in all_styles_by_id:
        debug_lines.append("ref_id={}, 在dict={}".format(ref_id, ref_id in all_styles_by_id if ref_id else "N/A"))
        empty['debug'] = "; ".join(debug_lines)
        return empty
    ref_el = all_styles_by_id[ref_id]
    tag_lower = (ref_el.tag or "").lower() if isinstance(ref_el.tag, str) else ""
    if "stylemap" in tag_lower:
        normal_id, highlight_id = _kml_stylemap_get_normal_highlight_ids(ref_el)
        normal_style = all_styles_by_id.get(normal_id) if normal_id else None
        highlight_style = all_styles_by_id.get(highlight_id) if highlight_id else None
        debug_lines.append("StyleMap id={}, normal_id={} (找到={}), highlight_id={} (找到={})".format(
            ref_id, normal_id, normal_style is not None, highlight_id, highlight_style is not None))
        if normal_style is not None:
            ns_copy = ET.fromstring(ET.tostring(normal_style))  # nosec B314
            _kml_normalize_ns(ns_copy)
            hs_copy = None
            if highlight_style is not None:
                hs_copy = ET.fromstring(ET.tostring(highlight_style))  # nosec B314
                _kml_normalize_ns(hs_copy)
            sm_copy = ET.fromstring(ET.tostring(ref_el))  # nosec B314
            _kml_normalize_ns(sm_copy)
            return {
                'normal_style': ns_copy, 'highlight_style': hs_copy,
                'stylemap': sm_copy, 'is_stylemap': True, 'debug': "; ".join(debug_lines)
            }
        debug_lines.append("normal_style为None，回退到直接使用StyleMap")
        sm_copy = ET.fromstring(ET.tostring(ref_el))  # nosec B314
        _kml_normalize_ns(sm_copy)
        return {
            'normal_style': sm_copy, 'highlight_style': None,
            'stylemap': None, 'is_stylemap': False, 'debug': "; ".join(debug_lines)
        }
    style_copy = ET.fromstring(ET.tostring(ref_el))  # nosec B314
    _kml_normalize_ns(style_copy)
    debug_lines.append("普通Style id={}".format(ref_id))
    return {
        'normal_style': style_copy, 'highlight_style': None,
        'stylemap': None, 'is_stylemap': False, 'debug': "; ".join(debug_lines)
    }


def _get_b_folder_shared_style(root_b):
    """For each folder in B, extract ONE shared style (from first Placemark).
    Returns dict: folder_name -> style info. Duplicate names: last folder wins.
    """
    all_styles_by_id = _get_all_styles_by_id(root_b)
    b_placemarks = _get_b_folders_placemarks(root_b)
    result = {}
    for folder_name, pms in b_placemarks.items():
        if pms:
            result[folder_name] = _shared_style_from_placemark(pms[0], all_styles_by_id)
    return result


def _get_b_folder_shared_style_by_path(root_b):
    """Like _get_b_folder_shared_style but keyed by folder path tuple."""
    all_styles_by_id = _get_all_styles_by_id(root_b)
    result = {}
    doc = root_b.find(".//" + KML_NS + "Document") if root_b is not None else None
    if doc is None and root_b is not None:
        doc = root_b.find(".//" + KML_NS_ALT + "Document")
    if doc is None:
        doc = root_b

    def recurse(parent, path):
        for folder in _kml_find_folders(parent):
            name = _kml_folder_name(folder)
            new_path = path + (name,)
            pms = [p for p in _kml_find_placemarks(folder) if _kml_has_geometry(p)]
            if pms:
                result[new_path] = _shared_style_from_placemark(pms[0], all_styles_by_id)
            recurse(folder, new_path)

    if doc is not None:
        recurse(doc, ())
    return result


def _kml_find_linestyle(style_el):
    """Return the LineStyle child element of a Style, or None. Handles namespaces."""
    for uri in (KML_NS, KML_NS_ALT, ""):
        tag = (uri + "LineStyle") if uri else "LineStyle"
        el = style_el.find(tag)
        if el is not None:
            return el
    for child in style_el:
        if child.tag and "linestyle" in (child.tag.lower() if isinstance(child.tag, str) else ""):
            return child
    return None


def _kml_copy_linestyle(from_style_el, to_style_el):
    """Copy LineStyle from from_style_el into to_style_el (replace existing LineStyle so highlight matches normal)."""
    src = _kml_find_linestyle(from_style_el)
    if src is None:
        return
    # Remove existing LineStyle in to_style_el
    for uri in (KML_NS, KML_NS_ALT, ""):
        tag = (uri + "LineStyle") if uri else "LineStyle"
        existing = to_style_el.find(tag)
        if existing is not None:
            to_style_el.remove(existing)
            break
    for child in list(to_style_el):
        if child.tag and "linestyle" in (child.tag.lower() if isinstance(child.tag, str) else ""):
            to_style_el.remove(child)
            break
    to_style_el.append(ET.fromstring(ET.tostring(src)))  # nosec B314


def _kml_stylemap_get_normal_highlight_ids(stylemap_el):
    """From a StyleMap element, return (normal_style_id, highlight_style_id) from Pair key/styleUrl. Ids without #."""
    normal_id = highlight_id = None
    pairs = []
    for c in stylemap_el:
        if c.tag is None:
            continue
        local = c.tag.split("}")[-1] if isinstance(c.tag, str) and "}" in c.tag else (c.tag if isinstance(c.tag, str) else "")
        if local == "Pair":
            pairs.append(c)
    for pair in pairs:
        key_el = url_el = None
        for c in pair:
            if c.tag is None:
                continue
            local = c.tag.split("}")[-1] if isinstance(c.tag, str) and "}" in c.tag else (c.tag if isinstance(c.tag, str) else "")
            if local == "key":
                key_el = c
            elif local == "styleUrl":
                url_el = c
        if key_el is None or url_el is None or not (url_el.text or "").strip().startswith("#"):
            continue
        key = (key_el.text or "").strip().lower()
        sid = (url_el.text or "").strip()[1:].strip()
        if key == "normal":
            normal_id = sid
        elif key == "highlight":
            highlight_id = sid
    return normal_id, highlight_id


def _kml_unify_stylemap_highlight_with_normal(new_children):
    """For each StyleMap in new_children, make highlight Style's LineStyle equal to normal's so hover doesn't change line width/color."""
    id_to_el = {}
    for el in new_children:
        sid = el.get("id") if el is not None else None
        if sid:
            id_to_el[sid] = el
    for el in new_children:
        if el is None:
            continue
        tag_lower = (el.tag or "").lower() if isinstance(el.tag, str) else ""
        if "stylemap" not in tag_lower:
            continue
        normal_id, highlight_id = _kml_stylemap_get_normal_highlight_ids(el)
        if not normal_id or not highlight_id or normal_id == highlight_id:
            continue
        normal_style = id_to_el.get(normal_id)
        highlight_style = id_to_el.get(highlight_id)
        if normal_style is not None and highlight_style is not None:
            _kml_copy_linestyle(normal_style, highlight_style)


def _kml_find_first_folder_by_name(parent, name):
    """Return first Folder (at any depth) whose name equals name."""
    for folder in parent.iter():
        if _kml_local_tag(folder) == "Folder" and _kml_folder_name(folder) == name:
            return folder
    return None


def _kml_strip_feature_data(parent):
    """Remove Placemark / overlay / NetworkLink data. Keep Folder tree, names and styles."""
    data_tags = (
        "Placemark", "NetworkLink",
        "GroundOverlay", "ScreenOverlay", "PhotoOverlay",
    )
    for ch in list(parent):
        local = _kml_local_tag(ch)
        if local in data_tags:
            parent.remove(ch)
        elif local in ("Folder", "Document"):
            _kml_strip_feature_data(ch)


def _kmz_verify_doc_exported(path_c, expected_list):
    """写完后读生成 KMZ，校验 DOC 结构：各预期文件夹是否存在且 Placemark 数量与预期一致。
    expected_list: [(path_prefix, display_name, path_tuple, expected_count), ...]，path_tuple 为 Document 下文件夹路径。
    返回 failed 集合：set of (path_prefix, display_name)。"""
    if not expected_list:
        return set()
    root_c, _ = _kmz_get_kml_root(path_c)
    if root_c is None:
        return set((path_prefix, display_name) for path_prefix, display_name, _, _ in expected_list)
    doc = root_c.find(".//" + KML_NS + "Document")
    if doc is None:
        doc = root_c.find(".//" + KML_NS_ALT + "Document")
    if doc is None:
        doc = root_c
    failed = set()
    for path_prefix, display_name, path_tuple, expected_count in expected_list:
        folder = _kml_folder_at_path(doc, path_tuple)
        if folder is None:
            failed.add((path_prefix, display_name))
            continue
        placemarks = (
            folder.findall(KML_NS + "Placemark") +
            folder.findall(KML_NS_ALT + "Placemark") +
            folder.findall("Placemark")
        )
        with_geom = [p for p in placemarks if _kml_has_geometry(p)]
        if len(with_geom) != expected_count:
            failed.add((path_prefix, display_name))
    return failed


def _kmz_verify_style_replaced(path_c, expected_replaced_folder_names):
    """Re-open path_c and verify each expected folder has all placemarks with valid styleUrl.
    Returns (success_count, failed_folder_names)."""
    if not expected_replaced_folder_names:
        return 0, []
    root_c, _ = _kmz_get_kml_root(path_c)
    if root_c is None:
        return 0, list(expected_replaced_folder_names)
    all_style_ids = set(_get_all_styles_by_id(root_c).keys())
    c_folders = _get_a_folders_with_placemarks(root_c)
    folder_placemarks = {name: pms for name, pms, _ in c_folders}
    ok = []
    failed = []
    for folder_name in expected_replaced_folder_names:
        pms = folder_placemarks.get(folder_name, [])
        if not pms:
            failed.append(folder_name)
            continue
        bad = False
        for pm in pms:
            sid = _placemark_style_url_static(pm)
            if not sid or sid not in all_style_ids:
                bad = True
                break
        if bad:
            failed.append(folder_name)
        else:
            ok.append(folder_name)
    return len(ok), failed


def _qgis_geometry_to_kml_element(geom, layer_crs):
    """Transform geometry to WGS84 and return KML geometry element (Point/LineString/Polygon/MultiGeometry).
    Supports PointZ/LineStringZ/PolygonZ 等带 Z/M 的几何：先丢弃 Z/M 再按大类导出，转换异常时返回 None（计入 skip_failed）。"""
    if geom is None or geom.isEmpty():
        return None
    try:
        dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        if layer_crs != dest_crs:
            xform = QgsCoordinateTransform(layer_crs, dest_crs, QgsProject.instance().transformContext())
            geom = QgsGeometry(geom)
            geom.transform(xform)
        else:
            geom = QgsGeometry(geom)

        # 带 Z/M 的 wkbType 统一按几何大类处理并丢弃 Z/M，避免整层被跳过
        if hasattr(geom, "dropZValue"):
            geom.dropZValue()
        if hasattr(geom, "dropMValue"):
            geom.dropMValue()

        def coord_str(pt):
            return "{},{},0".format(pt.x(), pt.y())

        gtype = QgsWkbTypes.geometryType(geom.wkbType())

        if gtype == QgsWkbTypes.GeometryType.PointGeometry:
            if geom.isMultipart():
                multi = ET.Element(KML_NS + "MultiGeometry")
                for pt in geom.asMultiPoint():
                    el = ET.Element(KML_NS + "Point")
                    coords = ET.SubElement(el, KML_NS + "coordinates")
                    coords.text = coord_str(pt)
                    multi.append(el)
                return multi
            pt = geom.asPoint()
            el = ET.Element(KML_NS + "Point")
            coords = ET.SubElement(el, KML_NS + "coordinates")
            coords.text = coord_str(pt)
            return el

        if gtype == QgsWkbTypes.GeometryType.LineGeometry:
            if geom.isMultipart():
                multi = ET.Element(KML_NS + "MultiGeometry")
                for pl in geom.asMultiPolyline():
                    el = ET.Element(KML_NS + "LineString")
                    ET.SubElement(el, KML_NS + "tessellate").text = "1"
                    coords = ET.SubElement(el, KML_NS + "coordinates")
                    coords.text = " ".join(coord_str(p) for p in pl)
                    multi.append(el)
                return multi
            pts = geom.asPolyline()
            el = ET.Element(KML_NS + "LineString")
            ET.SubElement(el, KML_NS + "tessellate").text = "1"
            coords = ET.SubElement(el, KML_NS + "coordinates")
            coords.text = " ".join(coord_str(p) for p in pts)
            return el

        if gtype == QgsWkbTypes.GeometryType.PolygonGeometry:
            def polygon_el(poly_rings):
                el = ET.Element(KML_NS + "Polygon")
                for i, ring in enumerate(poly_rings):
                    if not ring:
                        continue
                    tag = KML_NS + "outerBoundaryIs" if i == 0 else KML_NS + "innerBoundaryIs"
                    boundary = ET.SubElement(el, tag)
                    linear = ET.SubElement(boundary, KML_NS + "LinearRing")
                    coords = ET.SubElement(linear, KML_NS + "coordinates")
                    coords.text = " ".join(coord_str(p) for p in ring)
                return el

            if geom.isMultipart():
                multi = ET.Element(KML_NS + "MultiGeometry")
                for poly in geom.asMultiPolygon():
                    multi.append(polygon_el(poly))
                return multi
            return polygon_el(geom.asPolygon())
    except Exception:
        return None
    return None


def _qgis_layer_tree_vector_layers():
    """Return list of (QgsVectorLayer, group_names) in layer tree order. group_names is list of parent group names from root."""
    result = []
    try:
        root = QgsProject.instance().layerTreeRoot()
    except Exception:
        root = None
    if root is None:
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                result.append((layer, []))
        return result

    def recurse(node, group_path):
        for child in node.children():
            try:
                layer = getattr(child, "layer", None)
                if callable(layer):
                    layer = layer()
                if layer and isinstance(layer, QgsVectorLayer):
                    result.append((layer, list(group_path)))
            except Exception:  # nosec B110
                pass
            child_name = getattr(child, "name", lambda: "")() if hasattr(child, "name") else ""
            if hasattr(child, "children") and callable(getattr(child, "children", None)):
                recurse(child, group_path + [child_name])

    recurse(root, [])
    return result


def _qgis_layer_tree_nodes():
    """Return list of tree nodes for UI: each is dict with type 'group'|'layer', name, layer (optional), children (optional)."""
    result = []
    try:
        root = QgsProject.instance().layerTreeRoot()
    except Exception:
        root = None
    if root is None:
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                result.append({"type": "layer", "name": layer.name(), "layer": layer})
        return result

    def recurse(node):
        nodes = []
        for child in node.children():
            layer = getattr(child, "layer", None)
            if callable(layer):
                layer = layer()
            child_name = getattr(child, "name", lambda: "")() if hasattr(child, "name") else ""
            if layer and isinstance(layer, QgsVectorLayer):
                nodes.append({"type": "layer", "name": layer.name(), "layer": layer})
            elif hasattr(child, "children") and callable(getattr(child, "children", None)):
                children = recurse(child)
                nodes.append({"type": "group", "name": child_name or "组", "children": children})
        return nodes

    return recurse(root)


_ILLEGAL_XML_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _kml_local_name(tag):
    if tag and "}" in tag:
        return tag.split("}", 1)[1]
    return tag or ""


def _clone_kml_element(el):
    cloned = ET.Element(el.tag, dict(el.attrib))
    cloned.text = el.text
    for child in list(el):
        cloned.append(_clone_kml_element(child))
    return cloned


def _xml_escape_text(text):
    text = _ILLEGAL_XML_RE.sub("", text or "")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_escape_attr(text):
    return _xml_escape_text(text).replace('"', "&quot;")


def _write_kml_element(el, parts, ns_written):
    if el.tag.startswith("{") and not el.tag.startswith(KML_NS):
        return
    local = _kml_local_name(el.tag)
    if not local:
        return
    attrs = []
    for key, val in el.attrib.items():
        if key.startswith("{"):
            continue
        attrs.append(' {}="{}"'.format(key, _xml_escape_attr(val or "")))
    extra = "" if ns_written else ' xmlns="http://www.opengis.net/kml/2.2"'
    attr_text = "".join(attrs)
    children = list(el)
    text = el.text or ""
    if not children and text == "":
        parts.append("<{}{}{}></{}>".format(local, extra, attr_text, local))
        return
    parts.append("<{}{}{}>".format(local, extra, attr_text))
    if text:
        if local == "description" and "<" in text:
            safe = _ILLEGAL_XML_RE.sub("", text).replace("]]>", "]]]]><![CDATA[>")
            parts.append("<![CDATA[" + safe + "]]>")
        else:
            parts.append(_xml_escape_text(text))
    for child in children:
        _write_kml_element(child, parts, True)
    parts.append("</{}>".format(local))


def _serialize_kml(root):
    parts = []
    _write_kml_element(root, parts, False)
    body = "".join(parts)
    return ('<?xml version="1.0" encoding="utf-8" ?>\n' + body).encode("utf-8")


def _placemark_simple_pairs(placemark):
    pairs = []
    for el in placemark.iter():
        if _kml_local_name(el.tag) == "SimpleData":
            pairs.append((el.get("name") or "", el.text or ""))
    if pairs:
        return pairs
    for el in placemark.iter():
        if _kml_local_name(el.tag) != "Data":
            continue
        value = ""
        for child in list(el):
            if _kml_local_name(child.tag) == "value":
                value = child.text or ""
                break
        if not value and el.text and el.text.strip():
            value = el.text.strip()
        pairs.append((el.get("name") or "", value))
    return pairs


def _attr_summary_html(pairs):
    rows = []
    for name, value in pairs:
        cell = html.escape(value or "", quote=False).replace("\n", "<br/>")
        rows.append("<tr><td>{}</td><td>{}</td></tr>".format(
            html.escape(name or "", quote=False), cell))
    if not rows:
        return ""
    return "<table border=\"1\">" + "".join(rows) + "</table>"


def _set_placemark_summary(placemark, summary_html):
    old = ""
    for child in list(placemark):
        if _kml_local_name(child.tag) == "description":
            old = child.text or ""
            placemark.remove(child)
    parts = []
    if old.strip() and not old.strip().startswith("<table"):
        parts.append("<div>{}</div>".format(
            html.escape(old, quote=False).replace("\n", "<br/>")))
    if summary_html:
        parts.append(summary_html)
    summary_html = "".join(parts)
    if not summary_html:
        return
    desc = ET.Element(KML_NS + "description")
    desc.text = summary_html
    insert_at = 0
    for i, child in enumerate(list(placemark)):
        if _kml_local_name(child.tag) == "name":
            insert_at = i + 1
            break
    placemark.insert(insert_at, desc)


def _iter_kml_placemarks(el):
    found = []
    for child in list(el):
        if _kml_local_name(child.tag) == "Placemark":
            found.append(child)
        else:
            found.extend(_iter_kml_placemarks(child))
    return found


def _parse_qgis_kml(path):
    tree = ET.parse(path)  # nosec B314
    root = tree.getroot()
    doc = root
    if _kml_local_name(root.tag) != "Document":
        for child in list(root):
            if _kml_local_name(child.tag) == "Document":
                doc = child
                break
    schemas = [_clone_kml_element(c) for c in list(doc) if _kml_local_name(c.tag) == "Schema"]
    placemarks = [_clone_kml_element(pm) for pm in _iter_kml_placemarks(doc)]
    return schemas, placemarks


def _unique_schema_id(prefer, used):
    base = (prefer or "").strip() or "layer"
    sid = base
    n = 2
    while sid in used:
        sid = "{}_{}".format(base, n)
        n += 1
    used.add(sid)
    return sid


def _retarget_layer_kml(schemas, placemarks, used_ids):
    schema = schemas[0] if schemas else None
    old_id = schema.get("id") if schema is not None else ""
    sid = _unique_schema_id(old_id or "layer", used_ids)
    if schema is not None:
        schema.set("id", sid)
        schema.set("name", sid)
    for index, pm in enumerate(placemarks, 1):
        for el in pm.iter():
            if _kml_local_name(el.tag) == "SchemaData":
                el.set("schemaUrl", "#" + sid)
        pm.set("id", "{}.{}".format(sid, index))
    return schema, placemarks


def _export_vector_tree():
    """图层树里的矢量图层。组名、图层名用图例上看到的名称。"""
    try:
        root = QgsProject.instance().layerTreeRoot()
    except Exception:
        root = None
    if root is None:
        nodes = []
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                nodes.append({"type": "layer", "name": layer.name(), "layer": layer})
        return nodes

    def walk(node):
        items = []
        for child in node.children():
            layer = None
            try:
                getter = getattr(child, "layer", None)
                if callable(getter):
                    layer = getter()
            except Exception:
                layer = None
            try:
                name = child.name() or ""
            except Exception:
                name = ""
            if isinstance(layer, QgsVectorLayer):
                items.append({"type": "layer", "name": name or layer.name() or "图层", "layer": layer})
                continue
            if hasattr(child, "children"):
                kids = walk(child)
                if kids:
                    items.append({"type": "group", "name": name or "组", "children": kids})
        return items

    return walk(root)


def _write_layer_kml(layer, legend_name, kml_path):
    """用 QGIS / GDAL 的 KML 驱动写出单个图层，字段格式与「另存为 KML」一致。"""
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "KML"
    options.fileEncoding = "UTF-8"
    options.layerName = legend_name or layer.name() or "layer"
    options.onlySelectedFeatures = False
    try:
        options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    except Exception:  # nosec B110
        pass
    dest = QgsCoordinateReferenceSystem("EPSG:4326")
    src = layer.crs()
    if src.isValid() and dest.isValid() and src != dest:
        options.ct = QgsCoordinateTransform(src, dest, QgsProject.instance().transformContext())
    ctx = QgsProject.instance().transformContext()
    writer = getattr(QgsVectorFileWriter, "writeAsVectorFormatV3", None)
    if callable(writer):
        result = writer(layer, kml_path, ctx, options)
    else:
        result = QgsVectorFileWriter.writeAsVectorFormat(
            layer, kml_path, "UTF-8", dest if dest.isValid() else layer.crs(), "KML"
        )
    if isinstance(result, tuple):
        err = result[0]
        err_msg = result[1] if len(result) > 1 else ""
        written = result[2] if len(result) > 2 and result[2] else kml_path
    else:
        err, err_msg, written = result, "", kml_path
    no_err = getattr(QgsVectorFileWriter, "NoError", 0)
    if err != no_err:
        raise ValueError(err_msg or "写入 KML 失败")
    if not written or not os.path.isfile(written):
        written = kml_path
    if not os.path.isfile(written):
        raise ValueError("没有生成 KML 文件")
    return written


def _layer_has_no_features(layer):
    try:
        count = layer.featureCount()
    except Exception:
        count = -1
    if count == 0:
        return True
    if count > 0:
        return False
    try:
        return next(layer.getFeatures(), None) is None
    except Exception:
        return False


def _kmz_sub(parent, tag, text=None):
    el = ET.SubElement(parent, KML_NS + tag)
    if text is not None:
        el.text = str(text)
    return el


def _kmz_kml_color(color, opacity=1.0):
    if color is None or not color.isValid():
        color = QColor(255, 255, 255, 255)
    alpha = int(color.alpha() * opacity)
    if alpha < 0:
        alpha = 0
    elif alpha > 255:
        alpha = 255
    return "{:02x}{:02x}{:02x}{:02x}".format(alpha, color.blue(), color.green(), color.red())


def _kmz_value_text(value):
    if value is None:
        return ""
    try:
        if value == NULL:
            return ""
    except Exception:  # nosec B110
        pass
    type_name = type(value).__name__
    if type_name in ("QByteArray", "bytes", "bytearray", "memoryview"):
        return ""
    if isinstance(value, QDateTime):
        return value.toString(Qt.DateFormat.ISODate) if value.isValid() else ""
    if isinstance(value, QDate):
        return value.toString(Qt.DateFormat.ISODate) if value.isValid() else ""
    if isinstance(value, QTime):
        return value.toString("HH:mm:ss") if value.isValid() else ""
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat()
    return str(value)


def _kmz_attr_text(feature, field_name):
    try:
        return _kmz_value_text(feature.attribute(field_name))
    except Exception:
        return ""


def _kmz_layer_classified(layer):
    """图层符号化是分类或分级时，才允许按 QGIS 分类拆子文件夹。"""
    if layer is None:
        return False
    try:
        renderer = layer.renderer()
        kind = renderer.type() if renderer is not None else ""
    except Exception:
        return False
    return kind in ("categorizedSymbol", "graduatedSymbol")


def _kmz_field_for_key(fields, key):
    """同一字段的大小写写法。有多个时优先 Name。"""
    folded = (key or "").casefold()
    if not folded:
        return None
    hits = [name for name in (fields or []) if name.casefold() == folded]
    if not hits:
        return None
    for name in hits:
        if name == "Name":
            return name
    return hits[0]


def _kmz_export_columns(layer, field_specs):
    """要写进 KMZ 的字段。(原字段名, 导出名称)。未指定时全部按原名。"""
    if field_specs is None:
        try:
            names = [field.name() for field in layer.fields()]
        except Exception:
            names = []
        return [(name, name) for name in names if name]
    columns = []
    used = set()
    for spec in field_specs:
        if not spec.get("on", True):
            continue
        src = (spec.get("source") or "").strip()
        export = (spec.get("export") or src).strip() or src
        if not src or not export:
            continue
        key = export.casefold()
        if key in used:
            n = 2
            while "{}_{}".format(export, n).casefold() in used:
                n += 1
            export = "{}_{}".format(export, n)
            key = export.casefold()
        used.add(key)
        columns.append((src, export))
    return columns


def _kmz_add_schema(ctx, columns):
    ctx["schema_n"] = ctx.get("schema_n", 0) + 1
    sid = "schema{}".format(ctx["schema_n"])
    schema = ET.Element(KML_NS + "Schema")
    schema.set("name", sid)
    schema.set("id", sid)
    for _src, export in columns:
        field = _kmz_sub(schema, "SimpleField")
        field.set("name", export)
        field.set("type", "string")
        _kmz_sub(field, "displayName", export)
    ctx.setdefault("schemas", []).append(schema)
    return sid


def _kmz_category_label(category):
    label = ""
    try:
        label = (category.label() or "").strip()
    except Exception:
        label = ""
    if label:
        return label
    try:
        value = category.value()
    except Exception:
        value = None
    if _kmz_is_null_category(value):
        return "NULL"
    text = _kmz_value_text(value).strip()
    return text or "NULL"


def _kmz_qgis_bucket(state, feature):
    kind = state.get("kind")
    renderer = state.get("renderer")
    if kind == "categorized" and renderer is not None:
        idx = -1
        try:
            exp_ctx = state["exp_context"]
            exp_ctx.setFeature(feature)
            value = state["field_exp"].evaluate(exp_ctx)
            idx = renderer.categoryIndexForValue(value)
        except Exception:
            idx = -1
        if idx == -1 and state.get("default_cat", -1) != -1:
            idx = state["default_cat"]
        if idx < 0:
            return "其他"
        try:
            return _kmz_category_label(renderer.categories()[idx])
        except Exception:
            return "其他"
    if kind == "graduated" and renderer is not None:
        idx = -1
        try:
            exp_ctx = state["exp_context"]
            exp_ctx.setFeature(feature)
            value = state["field_exp"].evaluate(exp_ctx)
            rng = renderer.rangeForValue(value)
            if rng is not None:
                try:
                    idx = state["ranges"].index(rng)
                except ValueError:
                    idx = -1
                    for i, one in enumerate(state["ranges"]):
                        if one.lowerValue() == rng.lowerValue() and one.upperValue() == rng.upperValue():
                            idx = i
                            break
        except Exception:
            idx = -1
        if idx < 0:
            return "其他"
        try:
            label = (state["ranges"][idx].label() or "").strip()
        except Exception:
            label = ""
        return label or "NULL"
    return None


def _kmz_feature_bucket(state, feature, split_mode):
    mode = (split_mode or "").strip()
    if not mode:
        return None
    if mode == "qgis":
        return _kmz_qgis_bucket(state, feature)
    return _kmz_attr_text(feature, mode).strip() or "NULL"


def _kmz_bucket_order(state, split_mode):
    if split_mode != "qgis":
        return []
    kind = state.get("kind")
    if kind == "categorized":
        try:
            return [_kmz_category_label(category) for category in state["renderer"].categories()]
        except Exception:
            return []
    if kind == "graduated":
        labels = []
        for rng in state.get("ranges") or []:
            try:
                label = (rng.label() or "").strip()
            except Exception:
                label = ""
            labels.append(label or "NULL")
        return labels
    return []


def _kmz_pack_buckets(legend, rows, preferred):
    if not rows or all(label is None for label, _pm in rows):
        return ("layer", legend, [pm for _label, pm in rows])
    groups = {}
    seen = []
    for label, pm in rows:
        key = label if label is not None else "其他"
        if key not in groups:
            groups[key] = []
            seen.append(key)
        groups[key].append(pm)
    order = []
    for name in preferred or []:
        if name in groups and name not in order:
            order.append(name)
    for name in seen:
        if name not in order and name not in ("其他", "NULL"):
            order.append(name)
    if "NULL" in groups and "NULL" not in order:
        order.append("NULL")
    if "其他" in groups and "其他" not in order:
        order.append("其他")
    return ("group", legend, [("layer", name, groups[name]) for name in order])


def _kmz_match_name_field(layer, token):
    """要素显示名用的字段。不区分大小写；有多个只是大小写不同时，优先和输入完全一致的写法。"""
    token = (token or "Name").strip() or "Name"
    names = []
    try:
        names = [field.name() for field in layer.fields()]
    except Exception:
        names = []
    for name in names:
        if name == token:
            return name
    folded = token.casefold()
    matches = [name for name in names if name.casefold() == folded]
    if not matches:
        return None
    for name in matches:
        if name == "Name":
            return name
    return matches[0]


def _kmz_class_expression(layer, attr):
    text = (attr or "").strip()
    if not text:
        return None
    try:
        if layer.fields().indexFromName(text) >= 0:
            expr = QgsExpression('"{}"'.format(text.replace('"', '""')))
        else:
            expr = QgsExpression(text)
    except Exception:
        return None
    try:
        if expr.hasParserError():
            return None
    except Exception:
        return None
    return expr


def _kmz_is_null_category(value):
    if value is None:
        return True
    try:
        if value == NULL:
            return True
    except Exception:  # nosec B110
        pass
    return False


def _kmz_add_style(ctx):
    ctx["n"] += 1
    style = ET.Element(KML_NS + "Style")
    style.set("id", "s{}".format(ctx["n"]))
    ctx["styles"].append(style)
    return style.get("id"), style


def _kmz_symbol_opacity(symbol, layer_opacity):
    try:
        return float(symbol.opacity()) * float(layer_opacity)
    except Exception:
        return float(layer_opacity)


def _kmz_build_symbol_style(ctx, symbol, geomtype, symcontext, layer_opacity):
    sid, style = _kmz_add_style(ctx)
    opacity = _kmz_symbol_opacity(symbol, layer_opacity)
    icon_meta = None
    if geomtype == QgsWkbTypes.GeometryType.PointGeometry:
        try:
            sym_size = float(symbol.size(symcontext) or 0)
        except Exception:
            sym_size = 3.0
        try:
            bounds = symbol.bounds(QPointF(0, 0), symcontext)
            px = max(bounds.width(), bounds.height())
            px = max(1, int(px * 1.1 + 0.999))
        except Exception:
            px = 32
        icon_name = "icon{}.png".format(ctx["n"])
        icon_path = os.path.join(ctx["tmpdir"], icon_name)
        icon = _kmz_sub(style, "IconStyle")
        href = "http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png"
        hotspot = False
        wrote = False
        try:
            symbol.exportImage(icon_path, "png", QSize(int(px), int(px)))
            wrote = os.path.isfile(icon_path)
        except Exception:
            wrote = False
        if wrote:
            href = "files/" + icon_name
            ctx["icons"].append((href, icon_path))
            hotspot = True
            _kmz_sub(icon, "scale", "{:.4f}".format((sym_size / 15.0) if sym_size else 1.0))
            _kmz_sub(icon, "color", "{:02x}ffffff".format(int(max(0, min(255, 255 * opacity)))))
        icon_el = _kmz_sub(icon, "Icon")
        _kmz_sub(icon_el, "href", href)
        if hotspot:
            spot = _kmz_sub(icon, "hotSpot")
            spot.set("x", "0.5")
            spot.set("y", "0.5")
            spot.set("xunits", "fraction")
            spot.set("yunits", "fraction")
        line_color = None
        try:
            line_color = _kmz_kml_color(symbol.color())
            line = _kmz_sub(style, "LineStyle")
            _kmz_sub(line, "color", line_color)
        except Exception:
            line_color = None
        icon_meta = {
            "href": href,
            "scale": (sym_size / 15.0) if sym_size else 1.0,
            "color": "{:02x}ffffff".format(int(max(0, min(255, 255 * opacity)))) if wrote else None,
            "hotspot": hotspot,
            "line_color": line_color,
        }
        return sid, icon_meta

    if geomtype == QgsWkbTypes.GeometryType.LineGeometry:
        try:
            width = float(symbol.width() or 0)
        except Exception:
            width = 0
        if not width:
            width = 0.5
        try:
            color = _kmz_kml_color(symbol.color(), opacity)
        except Exception:
            color = _kmz_kml_color(None)
        line = _kmz_sub(style, "LineStyle")
        _kmz_sub(line, "color", color)
        _kmz_sub(line, "width", "{:.3f}".format(width * 2.83))
        poly = _kmz_sub(style, "PolyStyle")
        _kmz_sub(poly, "color", color)
        return sid, None

    symbol_layer = None
    try:
        symbol_layer = symbol.symbolLayer(0)
    except Exception:
        symbol_layer = None
    stroke_width = 0.5
    stroke_color = QColor(0, 0, 0, 255)
    fill_color = QColor(190, 190, 190, 180)
    layer_type = None
    stroke_style = None
    if symbol_layer is not None:
        try:
            layer_type = symbol_layer.layerType()
        except Exception:
            layer_type = None
        try:
            stroke_style = symbol_layer.strokeStyle()
        except Exception:
            stroke_style = None
        if stroke_style == 0:
            stroke_width = 0
        else:
            try:
                stroke_width = float(symbol_layer.strokeWidth())
            except Exception:
                stroke_width = 0.5
        if layer_type == "SimpleLine":
            try:
                stroke_color = symbol_layer.color()
            except Exception:  # nosec B110
                pass
            line = _kmz_sub(style, "LineStyle")
            _kmz_sub(line, "color", _kmz_kml_color(stroke_color, opacity))
            _kmz_sub(line, "width", "{:.3f}".format(stroke_width * 2.83))
            poly = _kmz_sub(style, "PolyStyle")
            _kmz_sub(poly, "color", "00ffffff")
            return sid, None
        try:
            stroke_color = symbol_layer.strokeColor()
        except Exception:  # nosec B110
            pass
        try:
            fill_color = symbol_layer.color()
        except Exception:  # nosec B110
            pass
    line = _kmz_sub(style, "LineStyle")
    _kmz_sub(line, "color", _kmz_kml_color(stroke_color, opacity))
    _kmz_sub(line, "width", "{:.3f}".format(stroke_width * 2.83))
    poly = _kmz_sub(style, "PolyStyle")
    _kmz_sub(poly, "color", _kmz_kml_color(fill_color, opacity))
    return sid, None


def _kmz_fallback_style(ctx, geomtype):
    sid, style = _kmz_add_style(ctx)
    if geomtype == QgsWkbTypes.GeometryType.PointGeometry:
        icon = _kmz_sub(style, "IconStyle")
        icon_el = _kmz_sub(icon, "Icon")
        _kmz_sub(icon_el, "href", "http://maps.google.com/mapfiles/kml/pushpin/wht-pushpin.png")
    elif geomtype == QgsWkbTypes.GeometryType.LineGeometry:
        line = _kmz_sub(style, "LineStyle")
        _kmz_sub(line, "color", "ff787878")
        _kmz_sub(line, "width", "1.5")
    else:
        line = _kmz_sub(style, "LineStyle")
        _kmz_sub(line, "color", "ff787878")
        _kmz_sub(line, "width", "1")
        poly = _kmz_sub(style, "PolyStyle")
        _kmz_sub(poly, "color", "80bebebe")
    return sid


def _kmz_render_context(layer):
    try:
        extent = layer.extent()
        if extent.isNull() or extent.isEmpty():
            extent.grow(1.0)
        settings = QgsMapSettings()
        settings.setExtent(extent)
        settings.setOutputSize(QSize(1024, 1024))
        settings.setDestinationCrs(layer.crs())
        settings.setLayers([layer])
        return QgsRenderContext.fromMapSettings(settings)
    except Exception:
        return QgsRenderContext()


def _kmz_prepare_styles(ctx, layer, geomtype):
    """单一、分类、分级做成 KML 样式。其他渲染方式返回说明，几何照常导出。"""
    state = {
        "kind": None,
        "simple_id": None,
        "cat_ids": {},
        "default_cat": -1,
        "field_exp": None,
        "exp_context": None,
        "renderer": None,
        "ranges": [],
        "fallback_id": None,
        "angle_prop": None,
        "angle_ctx": None,
        "angle_cache": {},
        "angle_default": 0.0,
        "icon": None,
        "geomtype": geomtype,
    }
    renderer = None
    try:
        renderer = layer.renderer()
    except Exception:
        renderer = None
    if renderer is None:
        state["fallback_id"] = _kmz_fallback_style(ctx, geomtype)
        return state, tr("没有符号化")
    render_type = ""
    try:
        render_type = renderer.type() or ""
    except Exception:
        render_type = ""
    if render_type not in ("singleSymbol", "categorizedSymbol", "graduatedSymbol"):
        state["fallback_id"] = _kmz_fallback_style(ctx, geomtype)
        return state, tr("样式不是单一、分类或分级")
    try:
        layer_opacity = float(layer.opacity()) if hasattr(layer, "opacity") else 1.0
    except Exception:
        layer_opacity = 1.0
    symcontext = _kmz_render_context(layer)
    state["renderer"] = renderer
    if render_type == "singleSymbol":
        symbol = renderer.symbol()
        draw_symbol = symbol
        if geomtype == QgsWkbTypes.GeometryType.PointGeometry and symbol is not None:
            try:
                dd = symbol.dataDefinedAngle()
                if dd is not None and dd.isActive():
                    state["angle_prop"] = dd
                    angle_ctx = QgsExpressionContext()
                    angle_ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
                    state["angle_ctx"] = angle_ctx
                    try:
                        raw = symbol.angle()
                        state["angle_default"] = float(raw[0] if isinstance(raw, tuple) else raw)
                    except Exception:
                        state["angle_default"] = 0.0
                    try:
                        draw_symbol = symbol.clone()
                        draw_symbol.setAngle(0)
                    except Exception:
                        draw_symbol = symbol
            except Exception:
                state["angle_prop"] = None
        sid, icon_meta = _kmz_build_symbol_style(ctx, draw_symbol, geomtype, symcontext, layer_opacity)
        state["kind"] = "single"
        state["simple_id"] = sid
        state["icon"] = icon_meta
        return state, None
    expr = _kmz_class_expression(layer, renderer.classAttribute())
    if expr is None:
        state["fallback_id"] = _kmz_fallback_style(ctx, geomtype)
        return state, tr("分类字段无法识别")
    exp_context = QgsExpressionContext()
    exp_context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    state["field_exp"] = expr
    state["exp_context"] = exp_context
    if render_type == "categorizedSymbol":
        state["kind"] = "categorized"
        for idx, category in enumerate(renderer.categories()):
            if _kmz_is_null_category(category.value()):
                state["default_cat"] = idx
            symbol = category.symbol()
            if symbol is None:
                continue
            sid, _meta = _kmz_build_symbol_style(ctx, symbol, geomtype, symcontext, layer_opacity)
            state["cat_ids"][idx] = sid
        return state, None
    state["kind"] = "graduated"
    try:
        state["ranges"] = list(renderer.ranges())
    except Exception:
        state["ranges"] = []
    for idx, rng in enumerate(state["ranges"]):
        symbol = rng.symbol()
        if symbol is None:
            continue
        sid, _meta = _kmz_build_symbol_style(ctx, symbol, geomtype, symcontext, layer_opacity)
        state["cat_ids"][idx] = sid
    return state, None


def _kmz_heading_style(ctx, state, feature):
    prop = state.get("angle_prop")
    icon = state.get("icon") or {}
    if prop is None or not icon:
        return state.get("simple_id")
    angle = state.get("angle_default") or 0.0
    try:
        exp_ctx = state.get("angle_ctx")
        exp_ctx.setFeature(feature)
        result = prop.valueAsDouble(exp_ctx, angle)
        if isinstance(result, tuple):
            angle = float(result[0])
        else:
            angle = float(result)
    except Exception:
        angle = state.get("angle_default") or 0.0
    angle = angle % 360.0
    key = round(angle, 1)
    cache = state["angle_cache"]
    if key in cache:
        return cache[key]
    sid, style = _kmz_add_style(ctx)
    icon_el = _kmz_sub(style, "IconStyle")
    if icon.get("color"):
        _kmz_sub(icon_el, "color", icon["color"])
    _kmz_sub(icon_el, "scale", "{:.4f}".format(icon.get("scale") or 1.0))
    _kmz_sub(icon_el, "heading", "{:.1f}".format(key))
    href_el = _kmz_sub(icon_el, "Icon")
    _kmz_sub(href_el, "href", icon.get("href") or "")
    if icon.get("hotspot"):
        spot = _kmz_sub(icon_el, "hotSpot")
        spot.set("x", "0.5")
        spot.set("y", "0.5")
        spot.set("xunits", "fraction")
        spot.set("yunits", "fraction")
    if icon.get("line_color"):
        line = _kmz_sub(style, "LineStyle")
        _kmz_sub(line, "color", icon["line_color"])
    cache[key] = sid
    return sid


def _kmz_style_for_feature(ctx, state, feature):
    kind = state.get("kind")
    if kind == "single":
        if state.get("angle_prop") is not None:
            return _kmz_heading_style(ctx, state, feature)
        return state.get("simple_id") or state.get("fallback_id")
    if kind == "categorized":
        idx = -1
        try:
            exp_ctx = state["exp_context"]
            exp_ctx.setFeature(feature)
            value = state["field_exp"].evaluate(exp_ctx)
            idx = state["renderer"].categoryIndexForValue(value)
        except Exception:
            idx = -1
        if idx == -1 and state.get("default_cat", -1) != -1:
            idx = state["default_cat"]
        return state["cat_ids"].get(idx) or state.get("fallback_id")
    if kind == "graduated":
        idx = -1
        try:
            exp_ctx = state["exp_context"]
            exp_ctx.setFeature(feature)
            value = state["field_exp"].evaluate(exp_ctx)
            rng = state["renderer"].rangeForValue(value)
            if rng is not None:
                try:
                    idx = state["ranges"].index(rng)
                except ValueError:
                    idx = -1
                    for i, one in enumerate(state["ranges"]):
                        if one.lowerValue() == rng.lowerValue() and one.upperValue() == rng.upperValue():
                            idx = i
                            break
        except Exception:
            idx = -1
        return state["cat_ids"].get(idx) or state.get("fallback_id")
    return state.get("fallback_id")


def _kmz_abstract_parts(geom):
    try:
        raw = geom.constGet()
    except Exception:
        raw = None
    if raw is None:
        return []
    try:
        if geom.isMultipart():
            return list(raw)
    except Exception:  # nosec B110
        pass
    return [raw]


def _kmz_ring_points(ring):
    if ring is None:
        return []
    curve = ring
    try:
        lined = ring.curveToLine()
        if lined is not None:
            curve = lined
    except Exception:
        curve = ring
    pts = []
    try:
        count = curve.numPoints()
        for i in range(count):
            point = curve.pointN(i)
            pts.append((point.x(), point.y()))
        if pts:
            return pts
    except Exception:
        pts = []
    try:
        for point in curve:
            pts.append((point.x(), point.y()))
    except Exception:
        return pts
    return pts


def _kmz_coord_text(pts):
    return " ".join("{:.8f},{:.8f},0".format(x, y) for x, y in pts)


def _kmz_add_altitude(geom_el, tessellate):
    _kmz_sub(geom_el, "altitudeMode", "clampToGround")
    if tessellate:
        _kmz_sub(geom_el, "tessellate", "1")


def _kmz_write_part(parent, part, geomtype):
    if geomtype == QgsWkbTypes.GeometryType.PointGeometry:
        el = _kmz_sub(parent, "Point")
        _kmz_add_altitude(el, False)
        try:
            _kmz_sub(el, "coordinates", "{:.8f},{:.8f},0".format(part.x(), part.y()))
        except Exception:
            return False
        return True
    if geomtype == QgsWkbTypes.GeometryType.LineGeometry:
        pts = _kmz_ring_points(part)
        if len(pts) < 2:
            return False
        el = _kmz_sub(parent, "LineString")
        _kmz_add_altitude(el, True)
        _kmz_sub(el, "coordinates", _kmz_coord_text(pts))
        return True
    try:
        outer = part.exteriorRing()
    except Exception:
        return False
    outer_pts = _kmz_ring_points(outer)
    if len(outer_pts) < 3:
        return False
    el = _kmz_sub(parent, "Polygon")
    _kmz_add_altitude(el, True)
    ob = _kmz_sub(el, "outerBoundaryIs")
    ring = _kmz_sub(ob, "LinearRing")
    _kmz_sub(ring, "tessellate", "1")
    _kmz_sub(ring, "coordinates", _kmz_coord_text(outer_pts))
    try:
        holes = part.numInteriorRings()
    except Exception:
        holes = 0
    for i in range(holes):
        try:
            hole = part.interiorRing(i)
        except Exception:  # nosec B112
            continue
        hole_pts = _kmz_ring_points(hole)
        if len(hole_pts) < 3:
            continue
        ib = _kmz_sub(el, "innerBoundaryIs")
        inner = _kmz_sub(ib, "LinearRing")
        _kmz_sub(inner, "tessellate", "1")
        _kmz_sub(inner, "coordinates", _kmz_coord_text(hole_pts))
    return True


def _kmz_placemark(feature, geom, geomtype, style_id, name_text, show_summary, columns=None, schema_id=None):
    pm = ET.Element(KML_NS + "Placemark")
    if name_text:
        _kmz_sub(pm, "name", name_text)
    if style_id:
        _kmz_sub(pm, "styleUrl", "#" + style_id)
    parts = _kmz_abstract_parts(geom)
    written = []
    holder = ET.Element(KML_NS + "holder")
    for part in parts:
        if _kmz_write_part(holder, part, geomtype):
            written.append(holder[-1])
    if not written:
        return None
    if len(written) == 1:
        pm.append(written[0])
    else:
        multi = _kmz_sub(pm, "MultiGeometry")
        for part_el in written:
            multi.append(part_el)
    if columns is None:
        try:
            columns = [(field.name(), field.name()) for field in feature.fields() if field.name()]
        except Exception:
            columns = []
    pairs = []
    for src, export in columns:
        pairs.append((export, _kmz_attr_text(feature, src)))
    if pairs:
        data = _kmz_sub(pm, "ExtendedData")
        if schema_id:
            schema_data = _kmz_sub(data, "SchemaData")
            schema_data.set("schemaUrl", "#" + schema_id)
            for export, text in pairs:
                simple = _kmz_sub(schema_data, "SimpleData", text)
                simple.set("name", export)
        for export, text in pairs:
            item = _kmz_sub(data, "Data")
            item.set("name", export)
            _kmz_sub(item, "displayName", export)
            _kmz_sub(item, "value", text)
    if show_summary and pairs:
        summary = _attr_summary_html(pairs)
        if summary:
            _set_placemark_summary(pm, summary)
    return pm


def _kmz_feature_count(layer):
    if layer is None:
        return 0
    try:
        count = layer.featureCount()
    except Exception:
        count = -1
    try:
        count = int(count)
    except Exception:
        count = -1
    if count >= 0:
        return count
    try:
        return sum(1 for _feat in layer.getFeatures())
    except Exception:
        return 0


def _kmz_path_key(path):
    return "/".join(str(part) for part in (path or ()))


def _kmz_stamp_tree(nodes, prefix=()):
    stamped = []
    for index, item in enumerate(nodes or []):
        path = prefix + (index,)
        one = {
            "type": item.get("type"),
            "name": item.get("name") or "",
            "path": path,
        }
        if item.get("type") == "group":
            one["children"] = _kmz_stamp_tree(item.get("children") or [], path)
        else:
            one["layer"] = item.get("layer")
        stamped.append(one)
    return stamped


def _write_sidecar(folder, name, payload, is_path=False):
    rel = str(name or "").replace("\\", "/").lstrip("/")
    if not rel or rel.lower() == "doc.kml":
        return
    dest = os.path.join(folder, rel.replace("/", os.sep))
    parent = os.path.dirname(dest)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    if is_path:
        if os.path.abspath(payload) != os.path.abspath(dest):
            shutil.copyfile(payload, dest)
        return
    with open(dest, "wb") as handle:
        handle.write(payload)


def _write_kml_package(output_path, kml_bytes, extra_bytes=None, extra_paths=None):
    """Write a KMZ, or a plain KML plus icon files beside it."""
    if isinstance(kml_bytes, str):
        kml_bytes = kml_bytes.encode("utf-8")
    extra_bytes = extra_bytes or {}
    extra_paths = extra_paths or []
    if str(output_path).lower().endswith(".kml"):
        folder = os.path.dirname(os.path.abspath(output_path)) or "."
        with open(output_path, "wb") as handle:
            handle.write(kml_bytes)
        for name, data in extra_bytes.items():
            _write_sidecar(folder, name, data)
        for name, src in extra_paths:
            if src and os.path.isfile(src):
                _write_sidecar(folder, name, src, is_path=True)
        return
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_bytes)
        for name, data in extra_bytes.items():
            zf.writestr(name, data)
        for name, src in extra_paths:
            if src and os.path.isfile(src):
                zf.write(src, name)


def export_project_kmz(output_path, show_summary, include_empty=False, on_progress=None, name_field="Name", selection=None, empty_name="NULL"):
    """按图层树导出 KMZ。样式取地图上的单一符号、分类、分级。
    selection 为 None 时导出全部图层。否则只导出 selection['layers'] 里勾选的图层，
    文件夹名和要素名称字段按里面的填写。"""
    nodes = _kmz_stamp_tree(_export_vector_tree())
    layers = []

    def collect(items):
        for item in items:
            if item.get("type") == "layer":
                layers.append(item)
            else:
                collect(item.get("children") or [])

    collect(nodes)
    if not layers:
        return False, tr("当前工程里没有可导出的矢量图层。")

    token = (name_field or "Name").strip() or "Name"
    blank_name = (empty_name or "NULL").strip() or "NULL"
    chosen = None if selection is None else (selection.get("layers") or {})
    group_names = {} if selection is None else (selection.get("groups") or {})
    tmpdir = tempfile.mkdtemp(prefix="ittp_kmz_")
    ctx = {"n": 0, "styles": [], "icons": [], "tmpdir": tmpdir, "schemas": [], "schema_n": 0}
    skipped = []
    missing_name = []
    plain_style = []
    unsplit_note = []
    bad_split = []
    feature_count = 0
    layer_count = 0
    exported_layers = 0
    dest = QgsCoordinateReferenceSystem("EPSG:4326")
    canceled = {"stop": False}

    def convert(items):
        nonlocal feature_count, layer_count, exported_layers
        if canceled["stop"]:
            return []
        folders = []
        for item in items:
            if item.get("type") == "group":
                children = convert(item.get("children") or [])
                if children:
                    gname = group_names.get(_kmz_path_key(item.get("path"))) or item.get("name") or "组"
                    folders.append(("group", gname, children))
                continue
            layer = item.get("layer")
            legend = item.get("name") or (layer.name() if layer is not None else "") or "图层"
            layer_token = token
            field_specs = None
            split_mode = ""
            if chosen is not None:
                layer_id = ""
                try:
                    layer_id = layer.id() if layer is not None else ""
                except Exception:
                    layer_id = ""
                spec = chosen.get(layer_id)
                if not spec:
                    continue
                custom_name = (spec.get("export_name") or "").strip()
                if custom_name:
                    legend = custom_name
                layer_token = (spec.get("name_field") or "").strip()
                field_specs = spec.get("fields")
                split_mode = (spec.get("split") or "").strip()
            layer_count += 1
            if on_progress:
                keep_going = on_progress(layer_count, len(chosen) if chosen is not None else len(layers), legend)
                if keep_going is False:
                    canceled["stop"] = True
                    return folders
            if layer is None or not layer.isValid():
                skipped.append(tr("{0}（图层无效）").format(legend))
                continue
            try:
                spatial = layer.isSpatial()
            except Exception:
                spatial = True
            if not spatial:
                skipped.append(tr("{0}（没有几何）").format(legend))
                continue
            if (not include_empty) and _layer_has_no_features(layer):
                skipped.append(tr("{0}（元素为空）").format(legend))
                continue
            try:
                geomtype = QgsWkbTypes.geometryType(layer.wkbType())
            except Exception:
                geomtype = QgsWkbTypes.GeometryType.UnknownGeometry
            if geomtype not in (
                QgsWkbTypes.GeometryType.PointGeometry,
                QgsWkbTypes.GeometryType.LineGeometry,
                QgsWkbTypes.GeometryType.PolygonGeometry,
            ):
                skipped.append(tr("{0}（没有可用的点线面）").format(legend))
                continue
            if layer_token:
                name_attr = _kmz_match_name_field(layer, layer_token)
            else:
                name_attr = None
            if name_attr is None:
                missing_name.append(legend)
            transform = None
            try:
                src = layer.crs()
                if src.isValid() and dest.isValid() and src != dest:
                    transform = QgsCoordinateTransform(src, dest, QgsProject.instance().transformContext())
            except Exception:
                transform = None
            try:
                state, style_note = _kmz_prepare_styles(ctx, layer, geomtype)
            except Exception as exc:
                state, style_note = {"kind": None, "fallback_id": None}, str(exc)
            if style_note:
                plain_style.append(tr("{0}（{1}）").format(legend, style_note))
                if not state.get("fallback_id"):
                    state["fallback_id"] = _kmz_fallback_style(ctx, geomtype)
            if split_mode and split_mode != "qgis":
                try:
                    has_split_field = layer.fields().indexFromName(split_mode) >= 0
                except Exception:
                    has_split_field = False
                if not has_split_field:
                    bad_split.append(legend)
                    split_mode = ""
            columns = _kmz_export_columns(layer, field_specs)
            schema_id = _kmz_add_schema(ctx, columns) if columns else None
            rows = []
            if not _layer_has_no_features(layer):
                for feature in layer.getFeatures():
                    try:
                        geom = QgsGeometry(feature.geometry())
                    except Exception:
                        geom = None
                    if geom is None or geom.isNull() or geom.isEmpty():
                        continue
                    if transform is not None:
                        try:
                            geom.transform(transform)
                        except Exception:  # nosec B112
                            continue
                    try:
                        style_id = _kmz_style_for_feature(ctx, state, feature)
                    except Exception:
                        style_id = state.get("fallback_id")
                    if not style_id:
                        if not state.get("fallback_id"):
                            state["fallback_id"] = _kmz_fallback_style(ctx, geomtype)
                        style_id = state.get("fallback_id")
                    name_text = ""
                    if name_attr:
                        try:
                            name_text = _kmz_value_text(feature.attribute(name_attr)).strip()
                        except Exception:
                            name_text = ""
                    if not name_text:
                        name_text = blank_name
                    pm = _kmz_placemark(
                        feature, geom, geomtype, style_id, name_text, show_summary, columns, schema_id
                    )
                    if pm is not None:
                        rows.append((_kmz_feature_bucket(state, feature, split_mode), pm))
            feature_count += len(rows)
            if rows or include_empty:
                exported_layers += 1
                if rows and split_mode:
                    folders.append(_kmz_pack_buckets(legend, rows, _kmz_bucket_order(state, split_mode)))
                    if split_mode == "qgis" and state.get("kind") not in ("categorized", "graduated", "single"):
                        unsplit_note.append(legend)
                else:
                    folders.append(("layer", legend, [pm for _label, pm in rows]))
            elif not rows:
                skipped.append(tr("{0}（没有可写出的要素）").format(legend))
        return folders

    try:
        tree = convert(nodes)
        if canceled["stop"]:
            return False, tr("已取消导出。文件可能不完整。")
        if not tree:
            detail = "\n".join(skipped[:12]) if skipped else tr("没有写出任何图层。")
            return False, detail
        proj = QgsProject.instance()
        doc_name = (proj.baseName() or proj.title() or "QGIS").strip() or "QGIS"
        kml = ET.Element(KML_NS + "kml")
        doc = ET.SubElement(kml, KML_NS + "Document")
        doc.set("id", "root_doc")
        _kmz_sub(doc, "name", doc_name)
        for schema in ctx["schemas"]:
            doc.append(schema)
        for style in ctx["styles"]:
            doc.append(style)

        def append_folders(parent, folders):
            for kind, name, payload in folders:
                folder = ET.SubElement(parent, KML_NS + "Folder")
                _kmz_sub(folder, "name", name or ("组" if kind == "group" else "图层"))
                if kind == "group":
                    append_folders(folder, payload)
                else:
                    for pm in payload:
                        folder.append(pm)

        append_folders(doc, tree)
        data = _serialize_kml(kml)
        _write_kml_package(output_path, data, extra_paths=ctx["icons"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    lines = [
        tr("已导出 {0} 个图层，共 {1} 个要素。").format(exported_layers, feature_count),
        tr("要素名称按每个图层填写的字段，不区分大小写。") if chosen is not None
        else tr("要素名称字段：{0}（不区分大小写）").format(token),
        output_path,
    ]
    if unsplit_note:
        lines.append(tr("这些图层不是分类或分级，没有按 QGIS 分类拆开："))
        lines.extend(unsplit_note[:12])
        if len(unsplit_note) > 12:
            lines.append(tr("等 {0} 个").format(len(unsplit_note)))
    if bad_split:
        lines.append(tr("这些图层没有用来分类的字段，没有拆开："))
        lines.extend(bad_split[:12])
        if len(bad_split) > 12:
            lines.append(tr("等 {0} 个").format(len(bad_split)))
    if missing_name:
        lines.append(tr("这些图层没有可用的显示字段，要素名称写成 {0}：").format(blank_name))
        lines.extend(missing_name[:12])
        if len(missing_name) > 12:
            lines.append(tr("等 {0} 个").format(len(missing_name)))
    if plain_style:
        lines.append(tr("这些图层没有按地图上色："))
        lines.extend(plain_style[:12])
        if len(plain_style) > 12:
            lines.append(tr("等 {0} 个").format(len(plain_style)))
    if skipped:
        lines.append(tr("未写入："))
        lines.extend(skipped[:12])
        if len(skipped) > 12:
            lines.append(tr("等 {0} 个").format(len(skipped)))
    return True, "\n".join(lines)


def _qgis_build_placemark_description(feature, layer, table_border=True):
    """Build KML description from feature attributes. table_border=False 时表格无外边框（与参考一致时用）."""
    parts = []
    for f in layer.fields():
        v = feature.attribute(f.name())
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        if isinstance(v, str) and len(v) > 500:
            v = v[:500] + "..."
        parts.append("<tr><td><b>{}</b></td><td>{}</td></tr>".format(
            str(f.displayName() or f.name()), str(v).replace("<", "&lt;").replace(">", "&gt;")))
    if not parts:
        return ""
    border_attr = " border='1'" if table_border else ""
    return "<table{} cellpadding='4' style='border-collapse:collapse'>".format(border_attr) + "".join(parts) + "</table>"


def _kml_placemark_description_inner_xml(pm):
    """Return inner XML/text of Placemark description (preserve HTML structure from reference KMZ)."""
    if pm is None:
        return ""
    desc_el = None
    for uri in (KML_NS, KML_NS_ALT, ""):
        tag = (uri + "description") if uri else "description"
        desc_el = pm.find(tag)
        if desc_el is not None:
            break
    if desc_el is None:
        return ""
    parts = []
    if desc_el.text:
        parts.append(desc_el.text)
    for c in desc_el:
        try:
            parts.append(ET.tostring(c, encoding="unicode"))
        except Exception:
            parts.append(ET.tostring(c, encoding="utf-8").decode("utf-8", errors="replace"))
        if c.tail:
            parts.append(c.tail)
    return "".join(parts).strip()


def _qgis_fill_kml_description_template(template, feature, layer):
    """Replace $[fieldName] with HTML-escaped values from QGIS feature (field name = 图层字段名).
    较长字段名先替换，避免名称互为前缀时误替。未匹配的占位符保留，供 Google Earth 结合 ExtendedData 解析。"""
    if not template or not isinstance(template, str):
        return ""
    s = template
    fields_sorted = sorted(layer.fields(), key=lambda ff: len(ff.name()), reverse=True)
    for f in fields_sorted:
        v = feature.attribute(f.name())
        text_val = "" if v is None else str(v)
        if isinstance(text_val, str) and len(text_val) > 8000:
            text_val = text_val[:8000] + "..."
        esc = html.escape(text_val, quote=False)
        token = "$[" + f.name() + "]"
        s = s.replace(token, esc)
    return s


def _kml_substitute_balloon_placeholders(text, name_text, feature, layer):
    """Replace KML balloon placeholders: $[name], $[description], $[ExtendedData/xxx]. Returns substituted string."""
    if not text or not isinstance(text, str):
        return text or ""
    out = text.replace("$[name]", (name_text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    desc_html = _qgis_build_placemark_description(feature, layer, table_border=False)
    out = out.replace("$[description]", desc_html or "")
    for f in layer.fields():
        key = "$[ExtendedData/" + f.name() + "]"
        if key in out:
            v = feature.attribute(f.name())
            val = str(v) if v is not None else ""
            val = val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            out = out.replace(key, val)
    return out


def _ref_kmz_load_doc_and_templates(reference_kmz_path):
    """Load reference KMZ: clone Document and build templates per folder (path -> folder_el, placemark_template).
    Returns (doc_clone, templates_by_path, ref_zip_handle_or_None, ref_empty_folder_paths)."""
    root_ref, _ = _kmz_get_kml_root(reference_kmz_path)
    if root_ref is None:
        return None, {}, None, set()
    doc_ref = root_ref.find(".//" + KML_NS + "Document")
    if doc_ref is None:
        doc_ref = root_ref.find(".//" + KML_NS_ALT + "Document")
    if doc_ref is None:
        doc_ref = root_ref
    doc_clone = ET.fromstring(ET.tostring(doc_ref))  # nosec B314
    _kml_normalize_ns(doc_clone)

    templates_by_path = {}
    ref_empty_folder_paths = set()

    def recurse(parent_clone, path_tuple):
        for folder in _kml_find_folders(parent_clone):
            name = _kml_folder_name(folder)
            path_here = path_tuple + (name,)
            placemarks = (
                folder.findall(KML_NS + "Placemark")
                + folder.findall(KML_NS_ALT + "Placemark")
                + folder.findall("Placemark")
            )
            with_geom = [p for p in placemarks if _kml_has_geometry(p)]
            if with_geom:
                template = ET.fromstring(ET.tostring(with_geom[0]))  # nosec B314
                _kml_normalize_ns(template)
                _kml_placemark_remove_geometry(template)
                templates_by_path[path_here] = (folder, template)
            else:
                ref_empty_folder_paths.add(path_here)
            recurse(folder, path_here)

    recurse(doc_clone, ())

    ref_zip = None
    try:
        try:
            ref_zip = zipfile.ZipFile(reference_kmz_path, "r", metadata_encoding="utf-8")
        except TypeError:
            ref_zip = zipfile.ZipFile(reference_kmz_path, "r")
    except Exception:  # nosec B110
        pass
    return doc_clone, templates_by_path, ref_zip, ref_empty_folder_paths


def _kml_extended_data_element_field_name(data_el, d_local):
    """与 _kml_placemark_fill_from_feature 一致：解析 ExtendedData 下 Data / SimpleData 的字段名（含 KML 命名空间 name 与 attrib 扫描）。"""
    if data_el is None:
        return None
    if d_local == "Data":
        data_name = data_el.get("name") or data_el.get("{" + "http://www.opengis.net/kml/2.2" + "}name")
        if data_name is None:
            for k, v in data_el.attrib.items():
                if "name" in k.lower():
                    data_name = v
                    break
        return data_name
    if d_local == "SimpleData":
        return data_el.get("name")
    return None


def _qcombo_data_str(val, default=None):
    """将 QComboBox 的 itemData/currentData 规范为 str，兼容 PyQt5 下偶发 QVariant/非 str。"""
    if val is None:
        return default
    if isinstance(val, str):
        return val
    try:
        from qgis.PyQt.QtCore import QVariant
        if isinstance(val, QVariant):
            if not val.isValid():
                return default
            py = val.value()
            if isinstance(py, str):
                return py
            return str(py) if py is not None else default
    except Exception:  # nosec B110
        pass
    try:
        return str(val)
    except Exception:
        return default


def _kml_placemark_fill_from_feature(template_placemark, feature, layer, name_field, geom_el, balloon_mode="A"):
    """Clone template Placemark, fill name/description/ExtendedData/Snippet from feature, set geometry.
    balloon_mode: A=方案A(参考 description 占位符)；B=方案B(不覆盖 description，由 BalloonStyle 驱动)。"""
    pm = ET.fromstring(ET.tostring(template_placemark))  # nosec B314
    _kml_normalize_ns(pm)

    idx_name = layer.fields().indexFromName(name_field) if name_field else -1
    name_text = ""
    if idx_name >= 0:
        val = feature.attribute(idx_name)
        name_text = str(val) if val is not None else ""
    for child in list(pm):
        local = child.tag.split("}")[-1] if isinstance(child.tag, str) and "}" in child.tag else (child.tag or "")
        if local == "name":
            child.text = name_text
        elif local == "Snippet":
            child.text = name_text or ""
    for child in pm:
        local = child.tag.split("}")[-1] if isinstance(child.tag, str) and "}" in child.tag else (child.tag or "")
        if local == "description":
            if balloon_mode == "B":
                pass
            else:
                template_desc = (child.text or "").strip()
                if template_desc:
                    child.text = _kml_substitute_balloon_placeholders(template_desc, name_text, feature, layer)
                else:
                    child.text = _qgis_build_placemark_description(feature, layer, table_border=False) or ""
            break
    for ext in pm.iter():
        if ext.tag is None:
            continue
        tag_local = ext.tag.split("}")[-1] if "}" in ext.tag else ext.tag
        if tag_local == "ExtendedData":
            for data_el in ext:
                d_local = data_el.tag.split("}")[-1] if isinstance(data_el.tag, str) and "}" in data_el.tag else (data_el.tag or "")
                if d_local == "Data":
                    data_name = _kml_extended_data_element_field_name(data_el, "Data")
                    if data_name is not None:
                        val = feature.attribute(data_name) if layer.fields().indexFromName(data_name) >= 0 else None
                        val_str = str(val) if val is not None else ""
                        val_el = data_el.find(KML_NS + "value")
                        if val_el is None:
                            val_el = data_el.find(KML_NS_ALT + "value")
                        if val_el is None:
                            val_el = data_el.find("value")
                        if val_el is not None:
                            val_el.text = val_str
                        else:
                            v = ET.SubElement(data_el, KML_NS + "value")
                            v.text = val_str
                elif d_local == "SimpleData":
                    data_name = _kml_extended_data_element_field_name(data_el, "SimpleData")
                    if data_name is not None:
                        val = feature.attribute(data_name) if layer.fields().indexFromName(data_name) >= 0 else None
                        data_el.text = str(val) if val is not None else ""
            break
    pm.append(geom_el)
    return pm


def _qgis_export_to_kmz(layers_with_options, output_path, reference_kmz_path=None):
    """Export QGIS layers to KMZ (flat list). See _qgis_export_to_kmz_tree for nested structure."""
    tree = [{"type": "layer", "layer": layer, "display_name": dname, "name_field": nfield}
            for layer, dname, nfield in layers_with_options]
    _qgis_export_to_kmz_tree(tree, output_path, reference_kmz_path)


def _qgis_export_kmz_reference_precheck(export_tree, reference_kmz_path):
    """导出前预检（按参考输出模式）：区分未找到同名、同名但无几何、同名有几何但无可用样式。
    返回 (has_issues, message)。"""
    if not reference_kmz_path or not os.path.isfile(reference_kmz_path):
        return False, ""
    try:
        root_b, _ = _kmz_get_kml_root(reference_kmz_path)
    except Exception:
        return False, ""
    if root_b is None:
        return False, ""
    b_shared = _get_b_folder_shared_style(root_b)
    b_all_folder_names = _get_b_all_folder_names(root_b)

    def flatten_layers(nodes, path_prefix):
        for node in nodes:
            if node.get("type") == "group":
                name = node.get("name") or "组"
                for item in flatten_layers(node.get("children", []), path_prefix + (name,)):
                    yield item
            else:
                layer = node.get("layer")
                if not layer or not layer.isValid():
                    continue
                display_name = (node.get("display_name") or "") or (layer.name() if layer else "")
                yield (path_prefix, display_name)

    no_style = []
    ref_no_geom = []
    ref_no_style = []
    for path_prefix, display_name in flatten_layers(export_tree, ()):
        b_info = b_shared.get(display_name)
        if b_info and b_info.get("normal_style") is not None:
            continue
        if display_name not in b_all_folder_names:
            no_style.append((path_prefix, display_name))
        elif display_name not in b_shared:
            ref_no_geom.append((path_prefix, display_name))
        else:
            ref_no_style.append((path_prefix, display_name))

    if not no_style and not ref_no_geom and not ref_no_style:
        return False, ""

    section_defs = [
        ("参考中未找到同名图层（将使用默认样式）", no_style),
        (
            "参考中找到同名图层，但未识别到有几何要素（该文件夹下无带几何的 Placemark，将使用默认样式）",
            ref_no_geom,
        ),
        (
            "参考中找到同名图层且有要素，但无可用样式（如无 styleUrl／内联 Style，默认导出常属此类，将使用默认样式）",
            ref_no_style,
        ),
    ]
    ordinals = ["一", "二", "三", "四", "五"]
    lines = ["【参考 KMZ 预检】以下图层在参考中未找到可用样式，将使用默认样式导出。", ""]
    sec_i = 0
    for title, items in section_defs:
        if not items:
            continue
        label = ordinals[sec_i] if sec_i < len(ordinals) else str(sec_i + 1)
        sec_i += 1
        lines.append("{}、{}：".format(label, title))
        for path_prefix, display_name in items:
            path_str = " / ".join(path_prefix) if path_prefix else ""
            lines.append("  · {}（路径：{}）".format(display_name, path_str if path_str else "根下"))
        lines.append("")
    lines.append("所有 QGIS 图层的数据仍会完整导出，仅上述图层的样式为默认样式。")
    lines.append("是否继续导出？")
    return True, "\n".join(lines)


def _qgis_export_to_kmz_tree(export_tree, output_path, reference_kmz_path=None, output_mode="ref"):
    """Export to KMZ preserving QGIS tree structure.
    output_mode: 'ref'=按参考输出(QGIS建树+参考套样式)；'default'=默认输出(不看参考)。
    结构/数据始终以 QGIS 为准；参考提供 Style/StyleMap（含 BalloonStyle、ListStyle 等子节点）、
    图标资源、ZIP 内非 doc.kml 文件。仅当参考同名图层首要素存在非空 description 时才写入
    <description>（$[字段名] 替换为 QGIS 值）；参考无 description 时不写该标签，气球仍由
    ExtendedData 与 BalloonStyle 等呈现。Snippet 是否输出及 maxLines 与参考一致。"""
    compare_rows = []
    layer_result_list = []

    def flatten_layers(nodes, path_prefix):
        for node in nodes:
            if node["type"] == "group":
                name = node.get("name") or "组"
                for item in flatten_layers(node.get("children", []), path_prefix + (name,)):
                    yield item
            else:
                layer = node.get("layer")
                if not layer or not layer.isValid():
                    continue
                display_name = (node.get("display_name") or "") or (layer.name() if layer else "")
                yield (path_prefix, display_name, layer, node.get("name_field"))

    use_reference = (output_mode == "ref") and reference_kmz_path and os.path.isfile(reference_kmz_path)

    ref_shared_styles = {}
    ref_snippet_visible = {}
    ref_snippet_maxlines = {}
    ref_desc_template = {}
    ref_zip = None
    external_icon_files = []
    if use_reference:
        try:
            root_b, _ = _kmz_get_kml_root(reference_kmz_path)
        except Exception:
            root_b = None
        if root_b is not None:
            ref_shared_styles = _get_b_folder_shared_style(root_b)
            b_placemarks = _get_b_folders_placemarks(root_b)
            for folder_name, pms in b_placemarks.items():
                if pms:
                    pm0 = pms[0]
                    has_snippet = False
                    max_lines_attr = None
                    for child in pm0:
                        local = child.tag.split("}")[-1] if isinstance(child.tag, str) and "}" in child.tag else (child.tag or "")
                        if local == "Snippet":
                            ml = child.get("maxLines")
                            has_snippet = ml is None or ml != "0"
                            max_lines_attr = ml
                            break
                    ref_snippet_visible[folder_name] = has_snippet
                    ref_snippet_maxlines[folder_name] = max_lines_attr
                    ref_desc_template[folder_name] = _kml_placemark_description_inner_xml(pm0) or ""
        try:
            try:
                ref_zip = zipfile.ZipFile(reference_kmz_path, "r", metadata_encoding="utf-8")
            except TypeError:
                ref_zip = zipfile.ZipFile(reference_kmz_path, "r")
        except Exception:
            ref_zip = None

    style_id_counter = [0]
    def next_style_id(prefix):
        style_id_counter[0] += 1
        return "{}_s{}".format(prefix.replace(" ", "_").replace(".", "_").replace("/", "_") or "layer", style_id_counter[0])

    doc = ET.Element(KML_NS + "Document")
    name_el = ET.SubElement(doc, KML_NS + "name")
    name_el.text = "QGIS Export"

    style_match_info = {}

    def add_placemarks_to_folder(parent_kml_folder, layer, folder_display_name, name_field):
        if not layer or not layer.isValid():
            return
        layer_crs = layer.crs()
        idx_name = layer.fields().indexFromName(name_field) if name_field else -1
        total = 0
        exportable = 0
        exported = 0
        skip_no_geom = 0
        skip_failed = 0

        pm_style_ref = None
        style_used = False
        style_verify = "默认样式"

        if use_reference:
            b_info = ref_shared_styles.get(folder_display_name)
            if b_info and b_info.get("normal_style") is not None:
                safe_prefix = folder_display_name.replace(" ", "_").replace("/", "_") or "layer"
                style_elements = []
                if b_info["is_stylemap"] and b_info["stylemap"] is not None:
                    new_normal_id = next_style_id(safe_prefix)
                    normal_copy = ET.fromstring(ET.tostring(b_info["normal_style"]))  # nosec B314
                    _kml_normalize_ns(normal_copy)
                    normal_copy.set("id", new_normal_id)
                    _kml_normalize_style_hrefs(normal_copy, external_icon_files)
                    style_elements.append(normal_copy)

                    new_hl_id = next_style_id(safe_prefix)
                    if b_info["highlight_style"] is not None:
                        hl_copy = ET.fromstring(ET.tostring(b_info["highlight_style"]))  # nosec B314
                    else:
                        hl_copy = ET.fromstring(ET.tostring(b_info["normal_style"]))  # nosec B314
                    _kml_normalize_ns(hl_copy)
                    hl_copy.set("id", new_hl_id)
                    _kml_normalize_style_hrefs(hl_copy, external_icon_files)
                    _kml_copy_linestyle(normal_copy, hl_copy)
                    style_elements.append(hl_copy)

                    orig_normal_id, orig_highlight_id = _kml_stylemap_get_normal_highlight_ids(b_info["stylemap"])
                    new_sm_id = next_style_id(safe_prefix)
                    sm_copy = ET.fromstring(ET.tostring(b_info["stylemap"]))  # nosec B314
                    _kml_normalize_ns(sm_copy)
                    sm_copy.set("id", new_sm_id)
                    remap = {}
                    if orig_normal_id:
                        remap[orig_normal_id] = new_normal_id
                    if orig_highlight_id:
                        remap[orig_highlight_id] = new_hl_id
                    _kml_rewrite_style_urls(sm_copy, remap)
                    style_elements.append(sm_copy)
                    pm_style_ref = "#" + new_sm_id
                else:
                    new_sid = next_style_id(safe_prefix)
                    s_copy = ET.fromstring(ET.tostring(b_info["normal_style"]))  # nosec B314
                    _kml_normalize_ns(s_copy)
                    s_copy.set("id", new_sid)
                    _kml_normalize_style_hrefs(s_copy, external_icon_files)
                    style_elements.append(s_copy)
                    pm_style_ref = "#" + new_sid

                for se in style_elements:
                    parent_kml_folder.append(se)
                style_used = True
                style_verify = "已套用参考样式"

        add_snippet = use_reference and ref_snippet_visible.get(folder_display_name, False)
        snippet_max_lines = ref_snippet_maxlines.get(folder_display_name) if use_reference else None
        use_no_border_desc = use_reference and style_used
        desc_tpl = (ref_desc_template.get(folder_display_name) or "").strip() if use_reference else ""

        for feat in layer.getFeatures():
            total += 1
            geom_el = None
            if feat.hasGeometry():
                geom_el = _qgis_geometry_to_kml_element(feat.geometry(), layer_crs)
            else:
                skip_no_geom += 1
            if geom_el is None:
                if feat.hasGeometry():
                    skip_failed += 1
                continue
            exportable += 1
            pm = ET.SubElement(parent_kml_folder, KML_NS + "Placemark")
            if pm_style_ref:
                su_el = ET.SubElement(pm, KML_NS + "styleUrl")
                su_el.text = pm_style_ref
            pname = ET.SubElement(pm, KML_NS + "name")
            name_text = ""
            if idx_name >= 0:
                val = feat.attribute(idx_name)
                name_text = str(val) if val is not None else ""
            pname.text = name_text
            if use_reference:
                if add_snippet:
                    sn = ET.SubElement(pm, KML_NS + "Snippet")
                    sn.text = name_text
                    if snippet_max_lines is not None and str(snippet_max_lines).strip() != "":
                        sn.set("maxLines", str(snippet_max_lines).strip())
            else:
                sn = ET.SubElement(pm, KML_NS + "Snippet")
                sn.text = name_text
            # 按参考输出：参考首要素有 description 则写 <description>；参考无则省略（与参考「说明」编辑框一致），
            # 气球内容仍由 ExtendedData + Style 中 BalloonStyle 等提供，避免无气球。
            if desc_tpl:
                desc_html = _qgis_fill_kml_description_template(desc_tpl, feat, layer)
                if desc_html:
                    desc = ET.SubElement(pm, KML_NS + "description")
                    desc.text = desc_html
            elif not use_reference:
                desc_html = _qgis_build_placemark_description(feat, layer, table_border=not use_no_border_desc)
                if desc_html:
                    desc = ET.SubElement(pm, KML_NS + "description")
                    desc.text = desc_html
            ext_data = ET.SubElement(pm, KML_NS + "ExtendedData")
            for f in layer.fields():
                v = feat.attribute(f.name())
                val_str = str(v) if v is not None else ""
                data_el = ET.SubElement(ext_data, KML_NS + "Data")
                data_el.set("name", f.name())
                dn_el = ET.SubElement(data_el, KML_NS + "displayName")
                dn_el.text = f.displayName() or f.name()
                val_el = ET.SubElement(data_el, KML_NS + "value")
                val_el.text = val_str
            pm.append(geom_el)
            exported += 1

        compare_rows.append((folder_display_name or (layer.name() if layer else "图层"), total, exportable, exported, skip_no_geom, skip_failed))
        if not style_used and use_reference:
            style_verify = "未找到参考样式(默认)"
        elif not use_reference:
            style_verify = "默认输出"
        style_match_info[folder_display_name] = {"used": style_used, "verify": style_verify}

    def recurse(parent_kml, nodes):
        for node in nodes:
            if node["type"] == "group":
                folder = ET.SubElement(parent_kml, KML_NS + "Folder")
                fn = ET.SubElement(folder, KML_NS + "name")
                fn.text = node.get("name") or "组"
                recurse(folder, node.get("children", []))
            else:
                layer = node.get("layer")
                if not layer or not layer.isValid():
                    continue
                folder = ET.SubElement(parent_kml, KML_NS + "Folder")
                fn = ET.SubElement(folder, KML_NS + "name")
                display_name = (node.get("display_name") or "") or (layer.name() if layer else "")
                fn.text = display_name
                add_placemarks_to_folder(folder, layer, display_name, node.get("name_field"))

    recurse(doc, export_tree)
    kml = ET.Element(KML_NS + "kml")
    kml.append(doc)
    tree_el = ET.ElementTree(kml)
    buf = BytesIO()
    tree_el.write(buf, encoding="utf-8", xml_declaration=True, method="xml")
    kml_bytes = buf.getvalue()
    try:
        s = kml_bytes.decode("utf-8")
        s = re.sub(r'<ns\d+:', '<', s)
        s = re.sub(r'</ns\d+:', '</', s)
        s = re.sub(r'\s+xmlns:ns\d+="[^"]*"', '', s)
        if 'xmlns="http://www.opengis.net/kml/2.2"' not in s:
            s = s.replace("<kml", '<kml xmlns="http://www.opengis.net/kml/2.2"', 1)
        s = re.sub(r'(\s+xmlns="http://www\.opengis\.net/kml/2\.2")+', ' xmlns="http://www.opengis.net/kml/2.2"', s)
        kml_bytes = s.encode("utf-8")
    except Exception:  # nosec B110
        pass

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml_bytes)
        if ref_zip is not None:
            try:
                for name in ref_zip.namelist():
                    if name.lower() == "doc.kml" or name.lower().endswith("/doc.kml"):
                        continue
                    z.writestr(name, ref_zip.read(name))
            except Exception:  # nosec B110
                pass
        for zip_name, data in external_icon_files:
            try:
                z.writestr(zip_name, data)
            except Exception:  # nosec B110
                pass
    if ref_zip is not None:
        try:
            ref_zip.close()
        except Exception:  # nosec B110
            pass

    layer_order = list(flatten_layers(export_tree, ()))
    for (path_prefix, display_name, _layer, _nf), (title, total, exportable, exported, skip_no_geom, skip_failed) in zip(layer_order, compare_rows):
        info = style_match_info.get(display_name, {"used": False, "verify": "默认输出"})
        layer_result_list.append((path_prefix, display_name, info["used"], info["verify"], info["used"], info["verify"], total, exportable, exported, skip_no_geom, skip_failed))

    def walk_tree_for_report(nodes, level, layer_iter):
        rows = []
        for node in nodes:
            if node.get("type") == "group":
                rows.append({"name": node.get("name") or "组", "type": "文件夹", "level": level, "doc_used": None, "doc_verify": "", "icon_used": None, "icon_verify": "", "total": None, "exported": None})
                rows.extend(walk_tree_for_report(node.get("children", []), level + 1, layer_iter))
            else:
                layer = node.get("layer")
                if not layer or not layer.isValid():
                    continue
                display_name = (node.get("display_name") or "") or (layer.name() if layer else "图层")
                try:
                    path_prefix, _dn, doc_used, doc_verify, icon_used, icon_verify, total, _ex, exported, _s1, _s2 = next(layer_iter)
                except StopIteration:
                    path_prefix, doc_used, doc_verify, icon_used, icon_verify, total, exported = (), False, "", False, "", 0, 0
                rows.append({"name": display_name, "type": "图层", "level": level, "doc_used": doc_used, "doc_verify": doc_verify, "icon_used": icon_used, "icon_verify": icon_verify, "total": total, "exported": exported})
        return rows
    report_rows = walk_tree_for_report(export_tree, 0, iter(layer_result_list))

    try:
        output_folder_names = _kmz_get_all_folder_names(output_path)
    except Exception:
        output_folder_names = set()

    for i, r in enumerate(report_rows):
        if r.get("type") != "文件夹":
            continue
        level = r.get("level", 0)
        total_features = 0
        total_exported = 0
        j = i + 1
        while j < len(report_rows) and report_rows[j].get("level", 0) > level:
            if report_rows[j].get("type") == "图层":
                t = report_rows[j].get("total")
                if t is not None:
                    total_features += t
                ex = report_rows[j].get("exported")
                if ex is not None:
                    total_exported += ex
            j += 1
        r["total"] = total_features
        r["exported"] = total_exported
        folder_name = r.get("name") or ""
        if folder_name in output_folder_names:
            r["doc_used"] = True
            r["doc_verify"] = "已创建文件夹"
        else:
            r["doc_used"] = False
            r["doc_verify"] = "文件夹未创建"

    # 写后校验：按 QGIS 树核对 Folder/Placemark 数量
    expected_doc_list = []
    for (path_prefix, display_name, _layer, _nf), (title, total, exportable, exported, skip_no_geom, skip_failed) in zip(layer_order, compare_rows):
        path_tuple = path_prefix + (display_name,)
        expected_doc_list.append((path_prefix, display_name, path_tuple, exported))
    doc_verify_failed = _kmz_verify_doc_exported(output_path, expected_doc_list)
    if doc_verify_failed:
        for r in report_rows:
            if r.get("type") != "图层":
                continue
            name = r.get("name") or ""
            for path_prefix, display_name in doc_verify_failed:
                if display_name == name:
                    r["doc_verify"] = "写后校验未通过"
                    break

    # 样式校验：核对输出中 styleUrl 是否有效
    style_verify_lines = []
    if use_reference:
        replaced_names = [dn for dn in style_match_info if style_match_info[dn]["used"]]
        if replaced_names:
            try:
                ok_count, verify_failed_list = _kmz_verify_style_replaced(output_path, replaced_names)
                if verify_failed_list:
                    style_verify_lines.append("【样式校验】以下图层样式校验未通过：{}".format("、".join(verify_failed_list)))
                    for r in report_rows:
                        if r.get("type") == "图层" and r.get("name") in verify_failed_list:
                            r["icon_verify"] = "样式校验未通过"
                else:
                    style_verify_lines.append("【样式校验】所有参考样式均已生效。")
            except Exception as e:
                style_verify_lines.append("【样式校验】无法核对输出文件：{}".format(str(e)))

    verify_lines = ["【QGIS 导出 KMZ - 导出对账】", ""]
    mismatch = []
    for title, total, exportable, exported, skip_no_geom, skip_failed in compare_rows:
        if exported != exportable:
            mismatch.append(title)
        verify_lines.append(
            "  [{}] QGIS要素总数={}，可导出(可转KML)={}，已写入KMZ={}，跳过:无几何={}，失败/不支持={}".format(
                title, total, exportable, exported, skip_no_geom, skip_failed
            )
        )
    verify_lines.append("")
    if not compare_rows:
        verify_lines.append("（未导出任何图层）")
    elif mismatch:
        verify_lines.append("【警告】以下图层写入数量与可导出数量不一致：{}".format("、".join(mismatch)))
    else:
        verify_lines.append("全部图层写入数量与可导出数量一致。")
    if style_verify_lines:
        verify_lines.append("")
        verify_lines.extend(style_verify_lines)

    return None, verify_lines, report_rows


def _kmz_primary_field_names_from_placemark_template(pm):
    if pm is None or not hasattr(pm, "iter"):
        return set()
    names = []
    for ext in pm.iter():
        tag_local = ext.tag.split("}")[-1] if ext.tag and "}" in ext.tag else (ext.tag or "")
        if tag_local != "ExtendedData":
            continue
        for data_el in ext:
            d_local = data_el.tag.split("}")[-1] if isinstance(data_el.tag, str) and "}" in data_el.tag else (data_el.tag or "")
            if d_local == "Data":
                dn = _kml_extended_data_element_field_name(data_el, "Data")
                if dn:
                    names.append(dn)
            elif d_local == "SimpleData":
                dn = _kml_extended_data_element_field_name(data_el, "SimpleData")
                if dn:
                    names.append(dn)
        break
    return set(names)


def _kmz_primary_find_template(templates_by_path, path_prefix, display_name):
    """返回 ( (folder_el, placemark_template), ref_path_tuple )，与 legacy find_template_for_layer 一致。"""
    folder_path = path_prefix + (display_name,)
    if folder_path in templates_by_path:
        return templates_by_path[folder_path], folder_path
    for ref_path, tpl in templates_by_path.items():
        if ref_path and ref_path[-1] == display_name:
            return tpl, ref_path
    return None, None


def _kmz_primary_alignment_precheck(export_tree, reference_kmz_path):
    """KMZ 为主模式执行前：文件夹/图层/字段名等与 QGIS 导出树对照（不对比要素条数）。返回 (has_issues, message)。"""
    if not reference_kmz_path or not os.path.isfile(reference_kmz_path):
        return True, "未选择参考 KMZ 或文件不存在。"
    try:
        doc_clone, templates_by_path, ref_zip, ref_empty_folder_paths = _ref_kmz_load_doc_and_templates(reference_kmz_path)
    except Exception:
        return True, "无法读取参考 KMZ。"
    try:
        if ref_zip:
            ref_zip.close()
    except Exception:  # nosec B110
        pass
    if doc_clone is None:
        return True, "参考 KMZ 中未找到有效 KML Document。"

    def flatten_layers(nodes, path_prefix):
        for node in nodes:
            if node.get("type") == "group":
                name = node.get("name") or "组"
                for item in flatten_layers(node.get("children", []), path_prefix + (name,)):
                    yield item
            else:
                layer = node.get("layer")
                if not layer or not layer.isValid():
                    continue
                display_name = (node.get("display_name") or "") or (layer.name() if layer else "")
                yield (path_prefix, display_name, layer, node.get("name_field"))

    ref_folders = set()
    for key in templates_by_path:
        for i in range(1, len(key)):
            ref_folders.add(key[:i])

    unmatched = []
    ref_empty_match = []
    position_mismatch = []
    qgis_folder_missing = []
    field_mismatch = []
    qgis_matched_ref_paths = set()
    qgis_folders = set()

    for path_prefix, display_name, layer, _nf in flatten_layers(export_tree, ()):
        qgis_folders.add(path_prefix)
        folder_path = path_prefix + (display_name,)
        tpl, ref_path = _kmz_primary_find_template(templates_by_path, path_prefix, display_name)
        if tpl is None:
            if folder_path in ref_empty_folder_paths:
                ref_empty_match.append((path_prefix, display_name))
            else:
                by_name = next((p for p in ref_empty_folder_paths if p and p[-1] == display_name), None)
                if by_name is not None:
                    ref_empty_match.append((path_prefix, display_name))
                else:
                    unmatched.append((path_prefix, display_name))
            continue
        qgis_matched_ref_paths.add(ref_path)
        if folder_path != ref_path:
            position_mismatch.append((path_prefix, display_name, ref_path))
        ref_fields = _kmz_primary_field_names_from_placemark_template(tpl[1])
        q_fields = set(f.name() for f in layer.fields())
        if ref_fields != q_fields:
            only_q = sorted(q_fields - ref_fields)
            only_r = sorted(ref_fields - q_fields)
            field_mismatch.append((path_prefix, display_name, only_q, only_r))

    for p in qgis_folders:
        if p and p not in ref_folders:
            qgis_folder_missing.append(p)

    ref_only_layers = [rp for rp in templates_by_path if rp not in qgis_matched_ref_paths]

    if not (unmatched or ref_empty_match or position_mismatch or qgis_folder_missing or field_mismatch or ref_only_layers):
        return False, ""

    lines = [
        "【KMZ 为主 · 导出前校验】参考 KMZ 与当前 QGIS 勾选导出内容存在下列差异。",
        "导出逻辑不变，写入数据仍来自 QGIS；请确认后选择是否继续。",
        "",
    ]
    ordinals = ["一", "二", "三", "四", "五", "六", "七", "八", "九"]
    sec_i = 0

    def add_section(title, rows, fmt):
        nonlocal sec_i
        if not rows:
            return
        lab = ordinals[sec_i] if sec_i < len(ordinals) else str(sec_i + 1)
        sec_i += 1
        lines.append("{}、{}：".format(lab, title))
        for r in rows:
            lines.append(fmt(r))
        lines.append("")

    add_section(
        "参考中未找到可匹配的图层（导出时该图层可能无法按参考 DOC 写入）",
        unmatched,
        lambda t: "  · {}（路径：{}）".format(t[1], " / ".join(t[0]) if t[0] else "根下"),
    )
    add_section(
        "参考中找到同名文件夹但该文件夹下无几何要素（与「仅有文件夹名、无 Placemark」相关）",
        ref_empty_match,
        lambda t: "  · {}（路径：{}）".format(t[1], " / ".join(t[0]) if t[0] else "根下"),
    )
    add_section(
        "QGIS 与参考的文件夹路径不一致（将按名称匹配写入参考中同名位置）",
        position_mismatch,
        lambda t: "  · QGIS：{} → 参考：{}".format(" / ".join(t[0] + (t[1],)), " / ".join(t[2])),
    )
    add_section(
        "参考中未找到对应层级的 QGIS 文件夹",
        qgis_folder_missing,
        lambda pth: "  · {}".format(" / ".join(pth)),
    )
    add_section(
        "字段名集合不一致（参考模板 Placemark 的 ExtendedData vs QGIS 字段名）",
        field_mismatch,
        lambda t: "  · {}（路径：{}）\n      仅QGIS有: {}\n      仅参考有: {}".format(
            t[1],
            " / ".join(t[0]) if t[0] else "根下",
            ",".join(t[2]) if t[2] else "（无）",
            ",".join(t[3]) if t[3] else "（无）",
        ),
    )
    add_section(
        "参考 KMZ 中多出的图层（当前 QGIS 导出列表未匹配到）",
        ref_only_layers,
        lambda pth: "  · {}".format(" / ".join(pth)),
    )
    lines.append("可选择「仍要导出」继续执行 KMZ 为主流程，或「取消」返回检查。")
    return True, "\n".join(lines)


def _legacy_qgis_export_to_kmz_tree(export_tree, output_path, reference_kmz_path=None, balloon_mode="A"):
    """KMZ 为主：与 ITTP.txt 早期逻辑一致——克隆参考 Document 并按模板填充 QGIS 数据。
    balloon_mode: A=方案A(参考 description 占位符)；B=方案B(不覆盖 description，由 BalloonStyle 驱动)。"""
    compare_rows = []
    layer_result_list = []
    style_replace_result_lines = None
    style_replace_icon_by_folder = {}

    def flatten_layers(nodes, path_prefix):
        for node in nodes:
            if node["type"] == "group":
                name = node.get("name") or "组"
                for item in flatten_layers(node.get("children", []), path_prefix + (name,)):
                    yield item
            else:
                layer = node.get("layer")
                if not layer or not layer.isValid():
                    continue
                display_name = (node.get("display_name") or "") or (layer.name() if layer else "")
                yield (path_prefix, display_name, layer, node.get("name_field"))

    use_reference = reference_kmz_path and os.path.isfile(reference_kmz_path)
    doc_clone = None
    templates_by_path = {}
    ref_zip = None

    if use_reference:
        doc_clone, templates_by_path, ref_zip, _ = _ref_kmz_load_doc_and_templates(reference_kmz_path)
        if doc_clone is None:
            use_reference = False

    if use_reference and templates_by_path:
        ref_paths_for_verify = []

        def find_template_for_layer(path_prefix, display_name):
            folder_path = path_prefix + (display_name,)
            tpl = templates_by_path.get(folder_path)
            if tpl is not None:
                return tpl, folder_path
            for ref_path, tpl in templates_by_path.items():
                if ref_path and ref_path[-1] == display_name:
                    return tpl, ref_path
            return None, None

        for path_prefix, display_name, layer, name_field in flatten_layers(export_tree, ()):
            tpl, ref_path = find_template_for_layer(path_prefix, display_name)
            if tpl is None:
                try:
                    total = layer.featureCount()
                except Exception:
                    total = 0
                compare_rows.append((display_name or layer.name(), total, 0, 0, 0, 0))
                layer_result_list.append((path_prefix, display_name or layer.name(), False, "未匹配参考(0条)", False, "—", total, 0, 0, 0, 0))
                ref_paths_for_verify.append(None)
                continue
            folder_el, placemark_template = tpl
            layer_crs = layer.crs()
            idx_name = layer.fields().indexFromName(name_field) if name_field else -1
            total = 0
            exportable = 0
            exported = 0
            skip_no_geom = 0
            skip_failed = 0
            to_remove = []
            for child in folder_el:
                tag_local = child.tag.split("}")[-1] if isinstance(child.tag, str) and "}" in child.tag else (child.tag or "")
                if tag_local == "Placemark":
                    to_remove.append(child)
            for el in to_remove:
                folder_el.remove(el)
            for feat in layer.getFeatures():
                total += 1
                geom_el = None
                if feat.hasGeometry():
                    geom_el = _qgis_geometry_to_kml_element(feat.geometry(), layer_crs)
                else:
                    skip_no_geom += 1
                if geom_el is None:
                    if feat.hasGeometry():
                        skip_failed += 1
                    continue
                exportable += 1
                new_pm = _kml_placemark_fill_from_feature(placemark_template, feat, layer, name_field, geom_el, balloon_mode=balloon_mode)
                folder_el.append(new_pm)
                exported += 1
            compare_rows.append((display_name or (layer.name() if layer else "图层"), total, exportable, exported, skip_no_geom, skip_failed))
            doc_verify = "已按参考写入(已写入{}条)".format(exported) if exported > 0 else "已按参考写入(0条)"
            layer_result_list.append((path_prefix, display_name or (layer.name() if layer else "图层"), True, doc_verify, True, "来自参考DOC", total, exportable, exported, skip_no_geom, skip_failed))
            ref_paths_for_verify.append(ref_path)

        kml = ET.Element(KML_NS + "kml")
        kml.append(doc_clone)
        tree = ET.ElementTree(kml)
        buf = BytesIO()
        tree.write(buf, encoding="utf-8", xml_declaration=True, method="xml")
        kml_bytes = buf.getvalue()
        try:
            s_kml = kml_bytes.decode("utf-8")
            s_kml = re.sub(r'<ns\d+:', '<', s_kml)
            s_kml = re.sub(r'</ns\d+:', '</', s_kml)
            s_kml = re.sub(r'\s+xmlns:ns\d+="[^"]*"', '', s_kml)
            if 'xmlns="http://www.opengis.net/kml/2.2"' not in s_kml:
                s_kml = s_kml.replace("<kml", '<kml xmlns="http://www.opengis.net/kml/2.2"', 1)
            s_kml = re.sub(r'(\s+xmlns="http://www\.opengis\.net/kml/2\.2")+', ' xmlns="http://www.opengis.net/kml/2.2"', s_kml)
            kml_bytes = s_kml.encode("utf-8")
        except Exception:  # nosec B110
            pass

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("doc.kml", kml_bytes)
            if ref_zip is not None:
                try:
                    for name in ref_zip.namelist():
                        if name.lower() == "doc.kml" or name.lower().endswith("/doc.kml"):
                            continue
                        z.writestr(name, ref_zip.read(name))
                except Exception:  # nosec B110
                    pass
                try:
                    ref_zip.close()
                except Exception:  # nosec B110
                    pass
        expected_doc_list = []
        for i, item in enumerate(layer_result_list):
            path_prefix, display_name, doc_used, _doc_verify, _iu, _iv, _t, _ex, exported, _s1, _s2 = item
            if not doc_used:
                continue
            ref_path = ref_paths_for_verify[i] if i < len(ref_paths_for_verify) else None
            path_tuple = ref_path if ref_path is not None else (path_prefix + (display_name,))
            expected_doc_list.append((path_prefix, display_name, path_tuple, exported))
        doc_verify_failed = _kmz_verify_doc_exported(output_path, expected_doc_list)
        if doc_verify_failed:
            new_layer_result_list = []
            for item in layer_result_list:
                path_prefix, display_name, doc_used, doc_verify, icon_used, icon_verify, total, exportable, exported, skip_no_geom, skip_failed = item
                if (path_prefix, display_name) in doc_verify_failed:
                    new_layer_result_list.append((path_prefix, display_name, doc_used, "DOC校验未生效", icon_used, icon_verify, total, exportable, exported, skip_no_geom, skip_failed))
                else:
                    new_layer_result_list.append(item)
            layer_result_list = new_layer_result_list
        style_replace_result_lines = None
    else:
        doc = ET.Element(KML_NS + "Document")
        name_el = ET.SubElement(doc, KML_NS + "name")
        name_el.text = "QGIS Export"

        def add_placemarks_to_folder(parent_kml_folder, layer, folder_display_name, name_field):
            if not layer or not layer.isValid():
                return
            layer_crs = layer.crs()
            idx_name = layer.fields().indexFromName(name_field) if name_field else -1
            total = 0
            exportable = 0
            exported = 0
            skip_no_geom = 0
            skip_failed = 0
            for feat in layer.getFeatures():
                total += 1
                geom_el = None
                if feat.hasGeometry():
                    geom_el = _qgis_geometry_to_kml_element(feat.geometry(), layer_crs)
                else:
                    skip_no_geom += 1
                if geom_el is None:
                    if feat.hasGeometry():
                        skip_failed += 1
                    continue
                exportable += 1
                pm = ET.SubElement(parent_kml_folder, KML_NS + "Placemark")
                pname = ET.SubElement(pm, KML_NS + "name")
                name_text = ""
                if idx_name >= 0:
                    val = feat.attribute(idx_name)
                    name_text = str(val) if val is not None else ""
                pname.text = name_text
                sn = ET.SubElement(pm, KML_NS + "Snippet")
                sn.text = name_text
                desc_html = _qgis_build_placemark_description(feat, layer)
                if desc_html:
                    desc = ET.SubElement(pm, KML_NS + "description")
                    desc.text = desc_html
                pm.append(geom_el)
                exported += 1
            compare_rows.append((folder_display_name or (layer.name() if layer else "图层"), total, exportable, exported, skip_no_geom, skip_failed))

        def recurse(parent_kml, nodes):
            for node in nodes:
                if node["type"] == "group":
                    folder = ET.SubElement(parent_kml, KML_NS + "Folder")
                    fn = ET.SubElement(folder, KML_NS + "name")
                    fn.text = node.get("name") or "组"
                    recurse(folder, node.get("children", []))
                else:
                    layer = node.get("layer")
                    if not layer or not layer.isValid():
                        continue
                    folder = ET.SubElement(parent_kml, KML_NS + "Folder")
                    fn = ET.SubElement(folder, KML_NS + "name")
                    display_name = (node.get("display_name") or "") or (layer.name() if layer else "")
                    fn.text = display_name
                    add_placemarks_to_folder(folder, layer, display_name, node.get("name_field"))

        recurse(doc, export_tree)
        kml = ET.Element(KML_NS + "kml")
        kml.append(doc)
        tree = ET.ElementTree(kml)
        buf = BytesIO()
        tree.write(buf, encoding="utf-8", xml_declaration=True, method="xml")
        kml_bytes = buf.getvalue()
        try:
            s_kml = kml_bytes.decode("utf-8")
            s_kml = re.sub(r'<ns\d+:', '<', s_kml)
            s_kml = re.sub(r'</ns\d+:', '</', s_kml)
            s_kml = re.sub(r'\s+xmlns:ns\d+="[^"]*"', '', s_kml)
            if 'xmlns="http://www.opengis.net/kml/2.2"' not in s_kml:
                s_kml = s_kml.replace("<kml", '<kml xmlns="http://www.opengis.net/kml/2.2"', 1)
            s_kml = re.sub(r'(\s+xmlns="http://www\.opengis\.net/kml/2\.2")+', ' xmlns="http://www.opengis.net/kml/2.2"', s_kml)
            kml_bytes = s_kml.encode("utf-8")
        except Exception:  # nosec B110
            pass

        style_replace_result_lines = None
        if reference_kmz_path and os.path.isfile(reference_kmz_path):
            import tempfile
            fd, temp_kmz = tempfile.mkstemp(suffix=".kmz")
            os.close(fd)
            try:
                with zipfile.ZipFile(temp_kmz, "w", zipfile.ZIP_DEFLATED) as z:
                    z.writestr("doc.kml", kml_bytes)
                style_replace_result_lines, style_replace_icon_by_folder, _ = _kmz_style_replace(temp_kmz, reference_kmz_path, output_path)
            finally:
                try:
                    os.remove(temp_kmz)
                except Exception:  # nosec B110
                    pass
        else:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("doc.kml", kml_bytes)

    if not layer_result_list:
        layer_order = list(flatten_layers(export_tree, ()))
        for (path_prefix, display_name, _layer, _nf), (title, total, exportable, exported, skip_no_geom, skip_failed) in zip(layer_order, compare_rows):
            icon_info = style_replace_icon_by_folder.get(display_name, {"used": False, "verify": "未使用参考" if not reference_kmz_path else "未找到参考样式"})
            layer_result_list.append((path_prefix, display_name, False, "默认DOC结构", icon_info["used"], icon_info["verify"], total, exportable, exported, skip_no_geom, skip_failed))

    def walk_tree_for_report(nodes, level, layer_iter):
        rows = []
        for node in nodes:
            if node.get("type") == "group":
                rows.append({"name": node.get("name") or "组", "type": "文件夹", "level": level, "doc_used": None, "doc_verify": "", "icon_used": None, "icon_verify": "", "total": None, "exported": None})
                rows.extend(walk_tree_for_report(node.get("children", []), level + 1, layer_iter))
            else:
                layer = node.get("layer")
                if not layer or not layer.isValid():
                    continue
                display_name = (node.get("display_name") or "") or (layer.name() if layer else "图层")
                try:
                    path_prefix, _dn, doc_used, doc_verify, icon_used, icon_verify, total, _ex, exported, _s1, _s2 = next(layer_iter)
                except StopIteration:
                    path_prefix, doc_used, doc_verify, icon_used, icon_verify, total, exported = (), False, "", False, "", 0, 0
                rows.append({"name": display_name, "type": "图层", "level": level, "doc_used": doc_used, "doc_verify": doc_verify, "icon_used": icon_used, "icon_verify": icon_verify, "total": total, "exported": exported})
        return rows
    report_rows = walk_tree_for_report(export_tree, 0, iter(layer_result_list))

    try:
        output_folder_names = _kmz_get_all_folder_names(output_path)
    except Exception:
        output_folder_names = set()

    for i, r in enumerate(report_rows):
        if r.get("type") != "文件夹":
            continue
        level = r.get("level", 0)
        total_features = 0
        total_exported = 0
        j = i + 1
        while j < len(report_rows) and report_rows[j].get("level", 0) > level:
            if report_rows[j].get("type") == "图层":
                t = report_rows[j].get("total")
                if t is not None:
                    total_features += t
                ex = report_rows[j].get("exported")
                if ex is not None:
                    total_exported += ex
            j += 1
        r["total"] = total_features
        r["exported"] = total_exported
        folder_name = r.get("name") or ""
        if folder_name in output_folder_names:
            r["doc_used"] = True
            r["doc_verify"] = "已创建文件夹"
        else:
            r["doc_used"] = False
            r["doc_verify"] = "文件夹未创建"

    verify_lines = ["【QGIS 导出 KMZ - 导出对账】", ""]
    mismatch = []
    for title, total, exportable, exported, skip_no_geom, skip_failed in compare_rows:
        if exported != exportable:
            mismatch.append(title)
        verify_lines.append(
            "  [{}] QGIS要素总数={}，可导出(可转KML)={}，已写入KMZ={}，跳过:无几何={}，失败/不支持={}".format(
                title, total, exportable, exported, skip_no_geom, skip_failed
            )
        )
    verify_lines.append("")
    if not compare_rows:
        verify_lines.append("（未导出任何图层）")
    elif mismatch:
        verify_lines.append("【警告】以下图层写入数量与可导出数量不一致：{}".format("、".join(mismatch)))
    else:
        verify_lines.append("全部图层写入数量与可导出数量一致。")

    return style_replace_result_lines, verify_lines, report_rows


_STYLE_MAP_SEP_RE = re.compile(r"[\s_\-./\\()\[\]{}（）【】]+")
_STYLE_MAP_NOISE_RE = re.compile(
    r"(图层|参考|副本|拷贝|copy|layer|kmz|kml)$",
    re.IGNORECASE,
)
_STYLE_MAP_TRAIL_NUM_RE = re.compile(r"[_-]?\d{4,8}$")


def _style_map_path_text(path):
    return " / ".join([p for p in (path or ()) if p])


def _style_map_collect_rows(root):
    """Unique layer rows from KMZ: [{name, geom, count}, ...] in first-seen order."""
    folders = _get_a_folders_with_placemarks(root)
    rows = []
    index = {}
    for name, pms, _folder in folders:
        geom = _kml_placemarks_geom_kind(pms)
        cnt = len(pms)
        if name in index:
            rec = index[name]
            rec["count"] += cnt
            rec["name_hits"] = rec.get("name_hits", 1) + 1
            rec["duplicate"] = True
            if rec["geom"] != geom:
                rec["geom"] = "混合"
        else:
            rec = {
                "name": name, "geom": geom or "—", "count": cnt, "is_layer": True,
                "path": (name,), "level": 0, "display": name,
                "name_hits": 1, "duplicate": False,
            }
            index[name] = rec
            rows.append(rec)
    return rows


def _style_map_collect_tree_rows(root):
    """All Folder nodes in tree order, including grouping folders.
    Layer folders (direct geometry placemarks) have is_layer=True."""
    doc = _kml_find_document(root) if root is not None else None
    rows = []

    def recurse(parent, path):
        for folder in _kml_find_folders(parent):
            name = _kml_folder_name(folder) or "(未命名)"
            new_path = path + (name,)
            with_geom = [p for p in _kml_find_placemarks(folder) if _kml_has_geometry(p)]
            is_layer = bool(with_geom) and not _kml_folder_has_nested_container(folder)
            level = len(new_path) - 1
            rows.append({
                "name": name,
                "path": new_path,
                "level": level,
                "display": ("　" * level) + name,
                "geom": _kml_placemarks_geom_kind(with_geom) if is_layer else "—",
                "count": len(with_geom) if is_layer else 0,
                "is_layer": is_layer,
            })
            recurse(folder, new_path)

    if doc is not None:
        recurse(doc, ())
    return rows

    def recurse(parent, path):
        for folder in _kml_find_folders(parent):
            name = _kml_folder_name(folder) or "(未命名)"
            new_path = path + (name,)
            with_geom = [p for p in _kml_find_placemarks(folder) if _kml_has_geometry(p)]
            is_layer = bool(with_geom) and not _kml_folder_has_nested_container(folder)
            level = len(new_path) - 1
            rows.append({
                "name": name,
                "path": new_path,
                "level": level,
                "display": ("　" * level) + name,
                "geom": _kml_placemarks_geom_kind(with_geom) if is_layer else "—",
                "count": len(with_geom) if is_layer else 0,
                "is_layer": is_layer,
            })
            recurse(folder, new_path)

    if doc is not None:
        recurse(doc, ())
    return rows


def _style_map_norm_name(name):
    s = (name or "").strip()
    s = _STYLE_MAP_SEP_RE.sub("", s)
    s = _STYLE_MAP_NOISE_RE.sub("", s)
    s = _STYLE_MAP_TRAIL_NUM_RE.sub("", s)
    return s


def _style_map_tokens(name):
    parts = [p for p in _STYLE_MAP_SEP_RE.split(name or "") if p]
    tokens = []
    seen = set()
    for p in parts:
        cleaned = _STYLE_MAP_NOISE_RE.sub("", p)
        cleaned = _STYLE_MAP_TRAIL_NUM_RE.sub("", cleaned)
        for t in (cleaned, p):
            if t and t not in seen:
                seen.add(t)
                tokens.append(t)
    return tokens


def _style_map_token_strong(token):
    if not token or token.isdigit():
        return False
    cjk = sum(1 for c in token if "\u4e00" <= c <= "\u9fff")
    if cjk:
        return cjk >= 2
    return len(token) >= 3


def _style_map_geom_filter_ok(b_geom, a_geom):
    """When filtering: left 线 only allows source 线. 参考为混合/空则不限制。"""
    bg = b_geom or ""
    ag = a_geom or ""
    if bg in ("", "—", "混合"):
        return True
    return ag == bg


def _style_map_geom_ok(a_row, b_row, strict=True):
    if not strict:
        return True
    ga = a_row.get("geom") or ""
    gb = b_row.get("geom") or ""
    if ga in ("", "—", "混合") or gb in ("", "—", "混合"):
        return True
    return ga == gb


def _style_map_unique_assign(a_names, b_names, pred):
    """Assign A→B only when each side has exactly one remaining candidate."""
    a_cands = {}
    for an in a_names:
        a_cands[an] = [bn for bn in b_names if pred(an, bn)]
    assigned = {}
    for an, cands in a_cands.items():
        if len(cands) != 1:
            continue
        bn = cands[0]
        owners = [x for x, cs in a_cands.items() if bn in cs]
        if len(owners) == 1:
            assigned[an] = bn
    return assigned


def _style_map_auto_match(a_rows, b_rows, fuzzy=True):
    """Return dict a_name -> (b_name, reason). Auto-match is one-to-one."""
    a_info = {r["name"]: r for r in a_rows}
    b_info = {r["name"]: r for r in b_rows}
    a_names = [r["name"] for r in a_rows]
    b_names = [r["name"] for r in b_rows]
    used_a = set()
    used_b = set()
    result = {}

    def remaining_a():
        return [n for n in a_names if n not in used_a]

    def remaining_b():
        return [n for n in b_names if n not in used_b]

    def take(mapping, reason):
        for an, bn in mapping.items():
            if an in used_a or bn in used_b:
                continue
            used_a.add(an)
            used_b.add(bn)
            result[an] = (bn, reason)

    exact = {}
    for an in remaining_a():
        for bn in remaining_b():
            if an == bn and bn not in exact.values():
                exact[an] = bn
                break
    take(exact, "精确")

    def pred_norm(an, bn):
        na = _style_map_norm_name(an)
        nb = _style_map_norm_name(bn)
        if not na or na != nb:
            return False
        return _style_map_geom_ok(a_info[an], b_info[bn])

    take(_style_map_unique_assign(remaining_a(), remaining_b(), pred_norm), "去尾")

    if fuzzy:
        def pred_token(an, bn):
            if not _style_map_geom_ok(a_info[an], b_info[bn]):
                return False
            ta = set(t for t in _style_map_tokens(an) if _style_map_token_strong(t))
            tb = set(t for t in _style_map_tokens(bn) if _style_map_token_strong(t))
            return bool(ta & tb)

        take(_style_map_unique_assign(remaining_a(), remaining_b(), pred_token), "模糊")

        def pred_contains(an, bn):
            if not _style_map_geom_ok(a_info[an], b_info[bn]):
                return False
            a, b = (an or "").strip(), (bn or "").strip()
            if not a or not b or a == b:
                return False
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if not _style_map_token_strong(shorter):
                return False
            return shorter in longer

        take(_style_map_unique_assign(remaining_a(), remaining_b(), pred_contains), "模糊")

    return result


def _kmz_style_replace(path_a, path_b, path_c, name_map=None):
    """Content from A, styles from B, by folder name matching.

    Per-folder shared style: for each folder in B, extract one shared style
    (from first Placemark), then all A Placemarks in the same-named folder
    reference that single shared style.

    For StyleMap cases, highlight LineStyle is unified with normal so hover
    doesn't change line width/color.

    name_map: optional dict A_folder_name -> B_folder_name. None keeps
    original exact-name matching. Empty mapped value means skip (keep A style)."""
    root_a, _ = _kmz_get_kml_root(path_a)
    root_b, _ = _kmz_get_kml_root(path_b)
    if root_a is None:
        raise ValueError("无法读取 A 的 KML 内容")
    if root_b is None:
        raise ValueError("无法读取 B 的 KML 内容")

    a_folders = _get_a_folders_with_placemarks(root_a)
    b_shared = _get_b_folder_shared_style(root_b)
    b_all_folder_names = _get_b_all_folder_names(root_b)

    result_lines = [tr("【KMZ 样式替换结果】"), ""]
    result_lines.append(tr("A 中有元素的图层：{0}").format(
        ", ".join(n for n, _, _ in a_folders) if a_folders else tr("（无）")))
    result_lines.append(tr("B 中有要素的图层：{0}").format(
        ", ".join(sorted(b_shared.keys())) if b_shared else tr("（无）")))
    if name_map is not None:
        result_lines.append(tr("名称映射（源 → 参考）："))
        seen_map = set()
        for n, _, _ in a_folders:
            if n in seen_map:
                continue
            seen_map.add(n)
            mapped = (name_map.get(n) or "").strip()
            result_lines.append(tr("  {0} → {1}").format(n, mapped if mapped else tr("（未匹配）")))
    result_lines.append("")

    doc_a = root_a.find(".//" + KML_NS + "Document")
    if doc_a is None:
        doc_a = root_a.find(".//" + KML_NS_ALT + "Document")
    if doc_a is None:
        doc_a = root_a
    doc_c = ET.fromstring(ET.tostring(doc_a))  # nosec B314
    _kml_normalize_ns(doc_c)
    for ch in list(doc_c):
        if ch.tag is not None and isinstance(ch.tag, str):
            local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
            if local in ("Style", "StyleMap"):
                doc_c.remove(ch)

    style_id_counter = [0]
    external_icon_files = []
    replaced_folder_names = []  # 记录预期已替换样式的图层，用于导出后校验
    failed_folder_names = []    # 记录未找到样式而跳过的图层（B中无对应样式或未找到节点）

    def next_id(prefix):
        style_id_counter[0] += 1
        return "{}_s{}".format(prefix.replace(" ", "_").replace(".", "_"), style_id_counter[0])

    for folder_name, a_placemarks, orig_folder in a_folders:
        folder_in_c = _kml_find_first_folder_by_name(doc_c, folder_name)
        if folder_in_c is None:
            result_lines.append(tr("  [{0}] 在副本中未找到同名节点，跳过").format(folder_name))
            failed_folder_names.append(folder_name)
            continue

        if name_map is not None:
            b_lookup = (name_map.get(folder_name) or "").strip()
            if not b_lookup:
                result_lines.append(tr("  [{0}] 未匹配参考图层，保留原样式").format(folder_name))
                failed_folder_names.append(folder_name)
                continue
        else:
            b_lookup = folder_name

        b_info = b_shared.get(b_lookup)
        if not b_info or b_info['normal_style'] is None:
            if b_lookup not in b_all_folder_names:
                reason = tr("未找到映射图层 [{0}]").format(b_lookup) if name_map is not None else tr("未找到同名图层")
            elif b_lookup not in b_shared:
                reason = tr("找到图层 [{0}]，但未识别到有几何要素").format(b_lookup) if name_map is not None else tr("找到同名图层，但未识别到有几何要素")
            else:
                reason = tr("找到图层 [{0}] 且有要素，但参考中无可用样式").format(b_lookup) if name_map is not None else tr("找到同名且有要素，但参考中无可用样式")
            result_lines.append(tr("  [{0}] B中无对应样式 ({1})").format(folder_name, reason))
            failed_folder_names.append(folder_name)
            continue

        safe_prefix = folder_name.replace(" ", "_").replace("/", "_") or "layer"
        style_elements = []

        if b_info['is_stylemap'] and b_info['stylemap'] is not None:
            new_normal_id = next_id(safe_prefix)
            normal_copy = ET.fromstring(ET.tostring(b_info['normal_style']))  # nosec B314
            _kml_normalize_ns(normal_copy)
            normal_copy.set("id", new_normal_id)
            _kml_normalize_style_hrefs(normal_copy, external_icon_files)
            style_elements.append(normal_copy)

            new_hl_id = next_id(safe_prefix)
            if b_info['highlight_style'] is not None:
                hl_copy = ET.fromstring(ET.tostring(b_info['highlight_style']))  # nosec B314
            else:
                hl_copy = ET.fromstring(ET.tostring(b_info['normal_style']))  # nosec B314
            _kml_normalize_ns(hl_copy)
            hl_copy.set("id", new_hl_id)
            _kml_normalize_style_hrefs(hl_copy, external_icon_files)
            _kml_copy_linestyle(normal_copy, hl_copy)
            style_elements.append(hl_copy)

            orig_normal_id, orig_highlight_id = _kml_stylemap_get_normal_highlight_ids(b_info['stylemap'])
            new_sm_id = next_id(safe_prefix)
            sm_copy = ET.fromstring(ET.tostring(b_info['stylemap']))  # nosec B314
            _kml_normalize_ns(sm_copy)
            sm_copy.set("id", new_sm_id)
            remap = {}
            if orig_normal_id:
                remap[orig_normal_id] = new_normal_id
            if orig_highlight_id:
                remap[orig_highlight_id] = new_hl_id
            _kml_rewrite_style_urls(sm_copy, remap)
            style_elements.append(sm_copy)

            pm_style_ref = "#" + new_sm_id
            result_lines.append(tr("  [{0}] StyleMap: {1} -> normal={2}, highlight={3}, A有{4}个要素").format(
                folder_name, new_sm_id, new_normal_id, new_hl_id, len(a_placemarks)))
            replaced_folder_names.append(folder_name)
        else:
            new_sid = next_id(safe_prefix)
            s_copy = ET.fromstring(ET.tostring(b_info['normal_style']))  # nosec B314
            _kml_normalize_ns(s_copy)
            s_copy.set("id", new_sid)
            _kml_normalize_style_hrefs(s_copy, external_icon_files)
            style_elements.append(s_copy)

            pm_style_ref = "#" + new_sid
            result_lines.append(tr("  [{0}] Style: {1}, A有{2}个要素").format(
                folder_name, new_sid, len(a_placemarks)))
            replaced_folder_names.append(folder_name)

        to_remove = []
        for ch in list(folder_in_c):
            if ch.tag is None:
                continue
            if isinstance(ch.tag, str):
                local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
                if local in ("Style", "StyleMap", "Placemark"):
                    to_remove.append(ch)
        for ch in to_remove:
            folder_in_c.remove(ch)

        for se in style_elements:
            folder_in_c.append(se)

        for a_pm in a_placemarks:
            pm_copy = ET.fromstring(ET.tostring(a_pm))  # nosec B314
            _kml_normalize_ns(pm_copy)
            for ch in list(pm_copy):
                if ch.tag and isinstance(ch.tag, str):
                    local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
                    if local in ("Style", "StyleMap"):
                        pm_copy.remove(ch)
            su_el = None
            for ch in pm_copy:
                if ch.tag and isinstance(ch.tag, str):
                    local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
                    if local == "styleUrl":
                        su_el = ch
                        break
            if su_el is not None:
                su_el.text = pm_style_ref
            else:
                su_el = ET.SubElement(pm_copy, KML_NS + "styleUrl")
                su_el.text = pm_style_ref
            folder_in_c.append(pm_copy)

    kml_c = ET.Element(KML_NS + "kml")
    kml_c.append(doc_c)
    tree = ET.ElementTree(kml_c)
    buf = BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True, method="xml")
    kml_bytes = buf.getvalue()
    try:
        s = kml_bytes.decode("utf-8")
        s = re.sub(r'<ns\d+:', '<', s)
        s = re.sub(r'</ns\d+:', '</', s)
        s = re.sub(r'\s+xmlns:ns\d+="[^"]*"', '', s)
        kml_ns_uri = "http://www.opengis.net/kml/2.2"
        if 'xmlns="{}"'.format(kml_ns_uri) not in s:
            s = s.replace("<kml", '<kml xmlns="{}"'.format(kml_ns_uri), 1)
        s = re.sub(r'(\s+xmlns="http://www\.opengis\.net/kml/2\.2")+',
                    ' xmlns="http://www.opengis.net/kml/2.2"', s)
        kml_bytes = s.encode("utf-8")
    except Exception:  # nosec B110
        pass

    main_kml_names = ("doc.kml", "Doc.kml", "document.kml")
    extra_files = {}

    def _read_kmz_resources(kmz_path):
        """Read non-KML resources, fixing garbled filenames from CP437-decoded UTF-8."""
        result = {}
        with zipfile.ZipFile(kmz_path, "r") as zf:
            for info in zf.infolist():
                n = info.filename
                if n.endswith("/") or n in main_kml_names or (n.count("/") == 0 and n.lower().endswith(".kml")):
                    continue
                try:
                    data = zf.read(n)
                except Exception:  # nosec B112
                    continue
                fixed_name = n
                if not info.flag_bits & 0x800:
                    try:
                        fixed_name = n.encode("cp437").decode("utf-8")
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        pass
                result[fixed_name] = data
        return result

    extra_files.update(_read_kmz_resources(path_a))
    extra_files.update(_read_kmz_resources(path_b))

    packed = dict(extra_files)
    for name, data in external_icon_files:
        packed[name] = data
    _write_kml_package(path_c, kml_bytes, packed)

    # 汇总：共 X 个图层，Y 成功，Z 失败
    total_folders = len(a_folders)
    success_count = len(replaced_folder_names)
    failed_count = len(failed_folder_names)
    result_lines.append("")
    if name_map is not None:
        unmatched_names = [n for n in failed_folder_names if not (name_map.get(n) or "").strip()]
        real_failed = [n for n in failed_folder_names if n not in unmatched_names]
        result_lines.append(tr("【汇总】共 {0} 个图层，{1} 成功，{2} 未匹配（保留原样式），{3} 失败。").format(
            total_folders, success_count, len(unmatched_names), len(real_failed)))
        if unmatched_names:
            result_lines.append(tr("未匹配图层：{0}").format("、".join(unmatched_names)))
        if real_failed:
            result_lines.append(tr("未成功图层：{0}").format("、".join(real_failed)))
        elif failed_count == 0:
            result_lines.append(tr("全部成功。"))
    else:
        result_lines.append(tr("【汇总】共 {0} 个图层，{1} 成功，{2} 失败。").format(total_folders, success_count, failed_count))
        if failed_count == 0:
            result_lines.append(tr("全部成功。"))
        else:
            result_lines.append(tr("未成功图层：{0}").format("、".join(failed_folder_names)))
    verify_failed_list = []
    if success_count > 0:
        try:
            ok_count, verify_failed_list = _kmz_verify_style_replaced(path_c, replaced_folder_names)
            if ok_count < success_count and verify_failed_list:
                result_lines.append(tr("【校验】未生效图层：{0}").format("、".join(verify_failed_list)))
        except Exception as e:
            result_lines.append(tr("【校验】无法核对输出文件：{0}").format(str(e)))
    result_lines.append("")
    result_lines.append(tr("输出图层已导出：{0}").format(path_c))

    # 供调用方做表格展示：每图层（文件夹名）的图标样式采用与确认结果；folder_names 为 A 中有要素的图层名列表（顺序与 a_folders 一致）
    icon_by_folder = {}
    for folder_name in replaced_folder_names:
        icon_by_folder[folder_name] = {"used": True, "verify": "校验未生效" if folder_name in verify_failed_list else "已替换"}
    for folder_name in failed_folder_names:
        if name_map is not None and not (name_map.get(folder_name) or "").strip():
            icon_by_folder[folder_name] = {"used": False, "verify": "未匹配（保留原样式）"}
        else:
            icon_by_folder[folder_name] = {"used": False, "verify": "未找到参考样式"}
    folder_names = [name for name, _, _ in a_folders]
    return result_lines, icon_by_folder, folder_names


def _kmz_apply_shared_style_to_folder(folder_in_c, folder_name, a_placemarks, b_info, next_id, external_icon_files, doc_c=None):
    """Replace a folder's Style/StyleMap/Placemark with B shared style and given placemarks.
    a_placemarks may be empty (styled empty folder). Caller must pass valid b_info with normal_style.
    Point IconStyle is attached to the Folder only if the reference Folder already had one;
    otherwise styles live on Document so KMZ viewers keep a normal folder icon.
    Returns (pm_style_ref, result_line)."""
    a_placemarks = list(a_placemarks or [])
    safe_prefix = folder_name.replace(" ", "_").replace("/", "_") or "layer"
    keep_liststyle = _kml_folder_keep_liststyle(folder_in_c)
    attach_icon_on_folder = _kml_folder_had_iconstyle(folder_in_c) and not _kml_folder_has_nested_container(folder_in_c)
    style_parent = folder_in_c if attach_icon_on_folder or doc_c is None else doc_c
    style_elements = []

    if b_info['is_stylemap'] and b_info['stylemap'] is not None:
        new_normal_id = next_id(safe_prefix)
        normal_copy = ET.fromstring(ET.tostring(b_info['normal_style']))  # nosec B314
        _kml_normalize_ns(normal_copy)
        normal_copy.set("id", new_normal_id)
        _kml_normalize_style_hrefs(normal_copy, external_icon_files)
        style_elements.append(normal_copy)

        new_hl_id = next_id(safe_prefix)
        if b_info['highlight_style'] is not None:
            hl_copy = ET.fromstring(ET.tostring(b_info['highlight_style']))  # nosec B314
        else:
            hl_copy = ET.fromstring(ET.tostring(b_info['normal_style']))  # nosec B314
        _kml_normalize_ns(hl_copy)
        hl_copy.set("id", new_hl_id)
        _kml_normalize_style_hrefs(hl_copy, external_icon_files)
        _kml_copy_linestyle(normal_copy, hl_copy)
        style_elements.append(hl_copy)

        orig_normal_id, orig_highlight_id = _kml_stylemap_get_normal_highlight_ids(b_info['stylemap'])
        new_sm_id = next_id(safe_prefix)
        sm_copy = ET.fromstring(ET.tostring(b_info['stylemap']))  # nosec B314
        _kml_normalize_ns(sm_copy)
        sm_copy.set("id", new_sm_id)
        remap = {}
        if orig_normal_id:
            remap[orig_normal_id] = new_normal_id
        if orig_highlight_id:
            remap[orig_highlight_id] = new_hl_id
        _kml_rewrite_style_urls(sm_copy, remap)
        style_elements.append(sm_copy)
        pm_style_ref = "#" + new_sm_id
        kind = "StyleMap"
        extra = " -> normal={}, highlight={}".format(new_normal_id, new_hl_id)
    else:
        new_sid = next_id(safe_prefix)
        s_copy = ET.fromstring(ET.tostring(b_info['normal_style']))  # nosec B314
        _kml_normalize_ns(s_copy)
        s_copy.set("id", new_sid)
        _kml_normalize_style_hrefs(s_copy, external_icon_files)
        style_elements.append(s_copy)
        pm_style_ref = "#" + new_sid
        kind = "Style"
        extra = ""

    to_remove = []
    for ch in list(folder_in_c):
        if ch.tag is None:
            continue
        if isinstance(ch.tag, str):
            local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
            if local in ("Style", "StyleMap", "Placemark", "styleUrl"):
                to_remove.append(ch)
    for ch in to_remove:
        folder_in_c.remove(ch)

    for se in style_elements:
        style_parent.append(se)

    if attach_icon_on_folder:
        folder_su = ET.Element(KML_NS + "styleUrl")
        folder_su.text = pm_style_ref
        _kml_insert_after_folder_meta(folder_in_c, folder_su)
    else:
        folder_list_id = next_id(safe_prefix + "_list")
        folder_list_style = _kml_make_folder_list_style(folder_list_id, keep_liststyle)
        folder_in_c.append(folder_list_style)
        folder_su = ET.Element(KML_NS + "styleUrl")
        folder_su.text = "#" + folder_list_id
        _kml_insert_after_folder_meta(folder_in_c, folder_su)

    for a_pm in a_placemarks:
        pm_copy = ET.fromstring(ET.tostring(a_pm))  # nosec B314
        _kml_normalize_ns(pm_copy)
        for ch in list(pm_copy):
            if ch.tag and isinstance(ch.tag, str):
                local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
                if local in ("Style", "StyleMap"):
                    pm_copy.remove(ch)
        su_el = None
        for ch in pm_copy:
            if ch.tag and isinstance(ch.tag, str):
                local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
                if local == "styleUrl":
                    su_el = ch
                    break
        if su_el is not None:
            su_el.text = pm_style_ref
        else:
            su_el = ET.SubElement(pm_copy, KML_NS + "styleUrl")
            su_el.text = pm_style_ref
        folder_in_c.append(pm_copy)

    if a_placemarks:
        result_line = tr("  [{0}] {1}: {2}{3}, 源数据{4}个要素").format(
            folder_name, kind, pm_style_ref.lstrip("#"), extra, len(a_placemarks))
    else:
        result_line = tr("  [{0}] 空图层（保留参考样式与名称，无源数据）").format(folder_name)
    return pm_style_ref, result_line


def _kmz_write_doc_to_kmz(path_a, path_b, path_c, doc_c, external_icon_files):
    """Serialize Document to KMZ, merging non-KML resources from A then B."""
    if _kml_local_tag(doc_c) == "kml":
        kml_c = doc_c
    else:
        kml_c = ET.Element(KML_NS + "kml")
        kml_c.append(doc_c)
    tree = ET.ElementTree(kml_c)
    buf = BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True, method="xml")
    kml_bytes = buf.getvalue()
    try:
        s = kml_bytes.decode("utf-8")
        s = re.sub(r'<ns\d+:', '<', s)
        s = re.sub(r'</ns\d+:', '</', s)
        s = re.sub(r'\s+xmlns:ns\d+="[^"]*"', '', s)
        kml_ns_uri = "http://www.opengis.net/kml/2.2"
        if 'xmlns="{}"'.format(kml_ns_uri) not in s:
            s = s.replace("<kml", '<kml xmlns="{}"'.format(kml_ns_uri), 1)
        s = re.sub(r'(\s+xmlns="http://www\.opengis\.net/kml/2\.2")+',
                    ' xmlns="http://www.opengis.net/kml/2.2"', s)
        kml_bytes = s.encode("utf-8")
    except Exception:  # nosec B110
        pass

    main_kml_names = ("doc.kml", "Doc.kml", "document.kml")
    extra_files = {}

    def _read_kmz_resources(kmz_path):
        result = {}
        with zipfile.ZipFile(kmz_path, "r") as zf:
            for info in zf.infolist():
                n = info.filename
                if n.endswith("/") or n in main_kml_names or (n.count("/") == 0 and n.lower().endswith(".kml")):
                    continue
                try:
                    data = zf.read(n)
                except Exception:  # nosec B112
                    continue
                fixed_name = n
                if not info.flag_bits & 0x800:
                    try:
                        fixed_name = n.encode("cp437").decode("utf-8")
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        pass
                result[fixed_name] = data
        return result

    extra_files.update(_read_kmz_resources(path_a))
    extra_files.update(_read_kmz_resources(path_b))

    packed = dict(extra_files)
    for name, data in external_icon_files:
        packed[name] = data
    _write_kml_package(path_c, kml_bytes, packed)


def _kmz_style_replace_ref_structure(path_a, path_b, path_c, name_map, assignments=None,
                                     use_source_root_name=True):
    """Manual replace: output B's folder tree and layer names; data only from A.
    Unmatched A layers are dropped. Unmatched B layers stay as empty styled folders.
    Reference placemarks / overlays are never kept.
    If use_source_root_name, Document <name> comes from source KMZ (else source filename)."""
    name_map = name_map or {}
    root_a, _ = _kmz_get_kml_root(path_a)
    root_b, _ = _kmz_get_kml_root(path_b)
    if root_a is None:
        raise ValueError("无法读取 A 的 KML 内容")
    if root_b is None:
        raise ValueError("无法读取 B 的 KML 内容")

    a_folders = _get_a_folders_with_placemarks(root_a)
    a_by_name = {}
    a_order = []
    for n, pms, _folder in a_folders:
        if n not in a_by_name:
            a_order.append(n)
            a_by_name[n] = []
        a_by_name[n].extend(pms)

    b_tree_rows = _style_map_collect_tree_rows(root_b)
    b_layer_rows = [r for r in b_tree_rows if r.get("is_layer")]
    b_shared = _get_b_folder_shared_style(root_b)
    b_shared_path = _get_b_folder_shared_style_by_path(root_b)
    b_all_folder_names = _get_b_all_folder_names(root_b)

    path_to_a = {}
    used_a = set()
    if assignments:
        for item in assignments:
            path = tuple(item.get("path") or ())
            src = (item.get("source") or "").strip()
            if path:
                path_to_a[path] = src
                if src:
                    used_a.add(src)
    else:
        b_to_a = {}
        for a_name in a_order:
            b_name = (name_map.get(a_name) or "").strip()
            if b_name:
                b_to_a.setdefault(b_name, []).append(a_name)
                used_a.add(a_name)
        for brow in b_layer_rows:
            srcs = b_to_a.get(brow["name"]) or []
            path_to_a[brow["path"]] = srcs[0] if srcs else ""
            if srcs:
                b_to_a[brow["name"]] = srcs[1:]

    dropped_a = [n for n in a_order if n not in used_a]

    result_lines = [tr("【手动样式替换结果】（按参考的结构与名称输出）"), ""]
    result_lines.append(tr("数据仅来自源图层，参考中的原要素已全部清除。点/线名称仍用源数据。"))
    if use_source_root_name:
        preview_root = _kml_source_root_display_name(root_a, path_a)
        result_lines.append(tr("最外层名称：{0}（源 KMZ 文件名）").format(preview_root or tr("（未能读取）")))
    else:
        result_lines.append(tr("最外层名称：沿用参考 KMZ"))
    result_lines.append(tr("A 中有元素的图层：{0}").format("、".join(a_order) if a_order else tr("（无）")))
    result_lines.append(tr("B 中图层：{0}").format(
        "、".join(_style_map_path_text(r["path"]) for r in b_layer_rows) if b_layer_rows else tr("（无）")))
    result_lines.append(tr("名称映射（源 → 参考）："))
    for a_name in a_order:
        mapped = (name_map.get(a_name) or "").strip()
        result_lines.append(tr("  {0} → {1}").format(a_name, mapped if mapped else tr("（未匹配，不导出）")))
    result_lines.append("")

    doc_b = _kml_find_document(root_b)
    if doc_b is None:
        doc_b = root_b
    doc_c = ET.fromstring(ET.tostring(doc_b))  # nosec B314
    _kml_normalize_ns(doc_c)
    _kml_strip_feature_data(doc_c)
    if use_source_root_name:
        src_root = _kml_source_root_display_name(root_a, path_a)
        if src_root:
            _kml_set_document_name(doc_c, src_root)

    style_id_counter = [0]
    external_icon_files = []
    replaced_folder_names = []
    empty_folder_names = []
    failed_folder_names = []

    def next_id(prefix):
        style_id_counter[0] += 1
        return "{}_s{}".format(prefix.replace(" ", "_").replace(".", "_"), style_id_counter[0])

    icon_by_folder = {}
    folder_names = []

    for brow in b_layer_rows:
        b_name = brow["name"]
        b_path = brow.get("path") or (b_name,)
        label = _style_map_path_text(b_path) or b_name
        folder_names.append(label)
        folder_in_c = _kml_folder_at_path(doc_c, b_path)
        if folder_in_c is None:
            cand = _kml_find_first_folder_by_name(doc_c, b_name)
            if cand is not None and not _kml_folder_has_nested_container(cand):
                folder_in_c = cand
        src_name = (path_to_a.get(b_path) or "").strip()
        src_names = [src_name] if src_name else []
        a_pms = []
        for sn in src_names:
            a_pms.extend(a_by_name.get(sn, []))

        if folder_in_c is None:
            result_lines.append(tr("  [{0}] 参考结构中未找到该图层节点").format(label))
            failed_folder_names.append(label)
            icon_by_folder[label] = {
                "used": False, "verify": "参考结构中未找到节点",
                "total": len(a_pms), "exported": 0,
                "doc_verify": "参考结构缺失",
            }
            continue

        if _kml_folder_has_nested_container(folder_in_c):
            result_lines.append(tr("  [{0}] 分组文件夹，不套用点图层图标").format(label))
            icon_by_folder[label] = {
                "used": False, "verify": "分组文件夹",
                "total": len(a_pms), "exported": 0,
                "doc_verify": "参考结构与名称",
            }
            continue

        b_info = b_shared_path.get(tuple(b_path)) or b_shared.get(b_name)
        if not b_info or b_info.get("normal_style") is None:
            if b_name not in b_all_folder_names:
                reason = tr("未找到参考图层")
            elif b_name not in b_shared:
                reason = tr("参考中未识别到有几何要素")
            else:
                reason = tr("参考中无可用样式")
            result_lines.append(tr("  [{0}] 无法写入样式 ({1})").format(label, reason))
            failed_folder_names.append(label)
            icon_by_folder[label] = {
                "used": False, "verify": "未找到参考样式",
                "total": len(a_pms), "exported": 0,
                "doc_verify": "参考结构与名称",
            }
            continue

        _ref, line = _kmz_apply_shared_style_to_folder(
            folder_in_c, b_name, a_pms, b_info, next_id, external_icon_files, doc_c=doc_c)
        result_lines.append(line.replace("[{}]".format(b_name), "[{}]".format(label), 1))
        if src_names:
            result_lines.append(tr("      源图层：{0}").format("、".join(src_names)))
        if a_pms:
            replaced_folder_names.append(b_name)
            verify = "已替换"
            exported = len(a_pms)
        else:
            empty_folder_names.append(label)
            verify = "空图层（无源数据）"
            exported = 0
        icon_by_folder[label] = {
            "used": True, "verify": verify,
            "total": exported, "exported": exported,
            "doc_verify": "参考结构与名称",
        }

    _kml_detach_icon_from_grouping_folders(doc_c, next_id)
    _kmz_write_doc_to_kmz(path_a, path_b, path_c, doc_c, external_icon_files)

    result_lines.append("")
    result_lines.append(tr("【汇总】参考图层 {0} 个，写入源数据 {1} 个，空图层 {2} 个，失败 {3} 个；源图层未导出 {4} 个。").format(
        len(b_layer_rows), len(replaced_folder_names), len(empty_folder_names),
        len(failed_folder_names), len(dropped_a)))
    if dropped_a:
        result_lines.append(tr("未导出的源图层：{0}").format("、".join(dropped_a)))
    if empty_folder_names:
        result_lines.append(tr("空图层（无源数据）：{0}").format("、".join(empty_folder_names)))
    if failed_folder_names:
        result_lines.append(tr("未成功图层：{0}").format("、".join(failed_folder_names)))

    verify_failed_list = []
    if replaced_folder_names:
        try:
            ok_count, verify_failed_list = _kmz_verify_style_replaced(path_c, replaced_folder_names)
            if ok_count < len(replaced_folder_names) and verify_failed_list:
                result_lines.append(tr("【校验】未生效图层：{0}").format("、".join(verify_failed_list)))
                for fn in verify_failed_list:
                    info = icon_by_folder.get(fn) or {}
                    info["verify"] = "校验未生效"
                    icon_by_folder[fn] = info
        except Exception as e:
            result_lines.append(tr("【校验】无法核对输出文件：{0}").format(str(e)))

    try:
        out_names = _kmz_get_all_folder_names(path_c)
        missing = sorted(b_all_folder_names - out_names)
        extra = sorted(out_names - b_all_folder_names)
        if missing:
            result_lines.append(tr("【结构校验】输出缺少参考中的文件夹：{0}").format("、".join(missing)))
        if extra:
            result_lines.append(tr("【结构校验】输出多出参考中没有的文件夹：{0}").format("、".join(extra)))
        if not missing and not extra:
            result_lines.append(tr("【结构校验】输出文件夹名称与参考一致。"))
    except Exception as e:
        result_lines.append(tr("【结构校验】无法核对：{0}").format(str(e)))

    result_lines.append("")
    result_lines.append(tr("输出图层已导出：{0}").format(path_c))

    for a_name in dropped_a:
        folder_names.append(a_name)
        icon_by_folder[a_name] = {
            "used": False, "verify": "未导出（未匹配）",
            "total": len(a_by_name.get(a_name) or []), "exported": 0,
            "doc_verify": "未导出",
        }
    return result_lines, icon_by_folder, folder_names



