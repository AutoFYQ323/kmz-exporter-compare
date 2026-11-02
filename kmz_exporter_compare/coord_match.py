# -*- coding: utf-8 -*-
"""Layer name pairing for coordinate compare (no QGIS dependency)."""

import re


def keyword_score(left_name, right_name):
    left = (left_name or "").strip().lower()
    right = (right_name or "").strip().lower()
    if not left or not right:
        return 0
    if left == right:
        return 1000 + len(left)
    if len(left) < 2 or len(right) < 2:
        return 0
    if left in right or right in left:
        return 500 + min(len(left), len(right))
    best = 0
    for token in re.split(r"[^\w]+", left, flags=re.UNICODE):
        if len(token) >= 2 and token in right:
            best = max(best, 100 + len(token))
    for token in re.split(r"[^\w]+", right, flags=re.UNICODE):
        if len(token) >= 2 and token in left:
            best = max(best, 100 + len(token))
    return best
