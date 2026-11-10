# -*- coding: utf-8 -*-
"""Which layer-tree groups are written when they contain no features."""


def node_has_layer(item):
    for child in item.get("children") or []:
        if child.get("type") == "layer":
            return True
        if child.get("type") == "group" and node_has_layer(child):
            return True
    return False


def tree_has_group(nodes):
    for item in nodes or []:
        if item.get("type") == "group":
            return True
        if tree_has_group(item.get("children") or []):
            return True
    return False


def should_write_empty_group(item, path, checked_paths):
    """A group with no vector layer under it is written only when it is checked.

    checked_paths is None when the whole tree is exported. A group that still
    has vector layers under it is not an empty folder, even if those layers
    were skipped.
    """
    if node_has_layer(item):
        return False
    if checked_paths is None:
        return True
    return path in checked_paths


def count_bare_folders(folders):
    """Folders in the written tree that contain no placemarks, including parents of only such folders."""
    total = 0
    for kind, _name, payload in folders or []:
        if kind != "group":
            continue
        nested = count_bare_folders(payload)
        has_features = any(child_kind != "group" for child_kind, _child_name, _child_payload in payload or [])
        if has_features:
            total += nested
        else:
            total += 1 + nested
    return total
