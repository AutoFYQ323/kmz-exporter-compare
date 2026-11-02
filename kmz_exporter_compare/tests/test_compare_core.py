# -*- coding: utf-8 -*-
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from compare_core import classify


def _euclid(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _pt(fid, name, x, y):
    return {
        "id": fid,
        "name": name,
        "payload": (x, y),
        "bbox": (x, y, x, y),
    }


class ClassifyTests(unittest.TestCase):
    def test_overlap_is_dropped(self):
        src = [_pt(1, "A", 0, 0)]
        dst = [_pt(2, "A", 0.000001, 0)]
        only_src, only_dst, moved = classify(src, dst, 0.00001, _euclid)
        self.assertEqual(only_src, [])
        self.assertEqual(only_dst, [])
        self.assertEqual(moved, [])

    def test_same_name_far_apart_is_moved(self):
        src = [_pt(1, "A", 0, 0)]
        dst = [_pt(2, "A", 1, 0)]
        only_src, only_dst, moved = classify(src, dst, 0.00001, _euclid)
        self.assertEqual(only_src, [])
        self.assertEqual(only_dst, [])
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["src"]["id"], 1)
        self.assertAlmostEqual(moved[0]["distance"], 1)

    def test_missing_sides_and_blank_names_are_not_moved(self):
        src = [_pt(1, "A", 0, 0), _pt(2, "", 5, 5)]
        dst = [_pt(3, "B", 9, 9), _pt(4, "", 6, 6)]
        only_src, only_dst, moved = classify(src, dst, 0.1, _euclid)
        self.assertEqual(moved, [])
        self.assertEqual(sorted(item["id"] for item in only_src), [1, 2])
        self.assertEqual(sorted(item["id"] for item in only_dst), [3, 4])


if __name__ == "__main__":
    unittest.main()
