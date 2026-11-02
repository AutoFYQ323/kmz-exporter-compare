# -*- coding: utf-8 -*-
"""Pair features by distance and by name. No QGIS imports, so tests can run it."""

STATUS_ONLY_QGIS = "only_qgis"
STATUS_ONLY_KMZ = "only_kmz"
STATUS_MOVED = "moved"


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
