# -*- coding: utf-8 -*-
"""Pair features by distance and by name. No QGIS imports, so tests can run it."""

STATUS_ONLY_QGIS = "only_qgis"
STATUS_ONLY_KMZ = "only_kmz"
STATUS_MOVED = "moved"


def layer_field_issues(qgis_by_name, kmz_by_name):
    """Compare layer names and ordered field lists.

    qgis_by_name / kmz_by_name: {name: [field, ...]}.
    Returns a list of issue dicts with keys: kind, layer, detail.
    kind is only_qgis, only_kmz, fields_only_qgis, fields_only_kmz, or field_order.
    """
    issues = []
    qgis_names = {(name or "").strip(): fields for name, fields in (qgis_by_name or {}).items() if (name or "").strip()}
    kmz_names = {(name or "").strip(): fields for name, fields in (kmz_by_name or {}).items() if (name or "").strip()}
    qgis_fold = {name.casefold(): name for name in qgis_names}
    kmz_fold = {name.casefold(): name for name in kmz_names}
    for folded, name in sorted(qgis_fold.items(), key=lambda item: item[1].casefold()):
        if folded not in kmz_fold:
            issues.append({
                "kind": "only_qgis",
                "layer": name,
                "qgis": name,
                "kmz": "",
                "detail": "",
            })
    for folded, name in sorted(kmz_fold.items(), key=lambda item: item[1].casefold()):
        if folded not in qgis_fold:
            issues.append({
                "kind": "only_kmz",
                "layer": name,
                "qgis": "",
                "kmz": name,
                "detail": "",
            })
    for folded in sorted(set(qgis_fold) & set(kmz_fold), key=lambda key: qgis_fold[key].casefold()):
        q_name = qgis_fold[folded]
        k_name = kmz_fold[folded]
        q_fields = list(qgis_names.get(q_name) or [])
        k_fields = list(kmz_names.get(k_name) or [])
        q_set = {item.casefold(): item for item in q_fields if item}
        k_set = {item.casefold(): item for item in k_fields if item}
        only_q = [q_set[key] for key in q_set if key not in k_set]
        only_k = [k_set[key] for key in k_set if key not in q_set]
        if only_q:
            issues.append({
                "kind": "fields_only_qgis",
                "layer": q_name,
                "qgis": q_name,
                "kmz": k_name,
                "detail": ", ".join(only_q),
            })
        if only_k:
            issues.append({
                "kind": "fields_only_kmz",
                "layer": q_name,
                "qgis": q_name,
                "kmz": k_name,
                "detail": ", ".join(only_k),
            })
        shared_q = [name for name in q_fields if name and name.casefold() in k_set]
        shared_k = [name for name in k_fields if name and name.casefold() in q_set]
        shared_q_fold = [name.casefold() for name in shared_q]
        shared_k_fold = [name.casefold() for name in shared_k]
        if shared_q_fold != shared_k_fold and (shared_q or shared_k):
            issues.append({
                "kind": "field_order",
                "layer": q_name,
                "qgis": q_name,
                "kmz": k_name,
                "detail": "QGIS: {0} | KMZ: {1}".format(
                    " → ".join(shared_q) if shared_q else "—",
                    " → ".join(shared_k) if shared_k else "—",
                ),
            })
    return issues


def _separated(a, b, tolerance):
    ab = a.get("bbox")
    bb = b.get("bbox")
    if not ab or not bb:
        return False
    return (
        ab[2] + tolerance < bb[0]
        or bb[2] + tolerance < ab[0]
        or ab[3] + tolerance < bb[1]
        or bb[3] + tolerance < ab[1]
    )


def classify(src, dst, tolerance, distance):
    """Split features into only-QGIS, only-KMZ, and same-name-but-moved.

    src and dst items are dicts with id, name, payload, and an optional bbox
    (xmin, ymin, xmax, ymax). distance(payload, payload) returns a number in
    the same unit as tolerance. Empty names are never treated as the same object.
    """
    near_src = set()
    near_dst = set()
    for i, left in enumerate(src):
        for j, right in enumerate(dst):
            if _separated(left, right, tolerance):
                continue
            try:
                gap = distance(left["payload"], right["payload"])
            except Exception:  # nosec B112
                continue
            if gap <= tolerance:
                near_src.add(i)
                near_dst.add(j)

    leftover = {}
    for j, right in enumerate(dst):
        if j in near_dst:
            continue
        name = (right.get("name") or "").strip()
        if not name:
            continue
        leftover.setdefault(name, []).append(j)

    only_src = []
    moved = []
    used_dst = set()
    for i, left in enumerate(src):
        if i in near_src:
            continue
        name = (left.get("name") or "").strip()
        pick = None
        best = None
        for j in leftover.get(name, []):
            if j in used_dst:
                continue
            try:
                gap = distance(left["payload"], dst[j]["payload"])
            except Exception:  # nosec B112
                continue
            if best is None or gap < best:
                best = gap
                pick = j
        if pick is None:
            only_src.append(left)
            continue
        used_dst.add(pick)
        moved.append({
            "src": left,
            "dst": dst[pick],
            "distance": best,
        })

    only_dst = [
        right for j, right in enumerate(dst)
        if j not in near_dst and j not in used_dst
    ]
    return only_src, only_dst, moved
