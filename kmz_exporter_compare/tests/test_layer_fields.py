# -*- coding: utf-8 -*-
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from compare_core import layer_field_issues


class LayerFieldIssuesTests(unittest.TestCase):
    def test_only_sides_and_order(self):
        qgis = {
            "Roads": ["id", "name", "type"],
            "OnlyQ": ["a"],
        }
        kmz = {
            "Roads": ["id", "type", "name"],
            "OnlyK": ["b"],
        }
        issues = layer_field_issues(qgis, kmz)
        kinds = sorted(item["kind"] for item in issues)
        self.assertIn("only_qgis", kinds)
        self.assertIn("only_kmz", kinds)
        self.assertIn("field_order", kinds)
        order = [item for item in issues if item["kind"] == "field_order"][0]
        self.assertEqual(order["layer"], "Roads")
        self.assertIn("QGIS:", order["detail"])
        self.assertIn("KMZ:", order["detail"])

    def test_field_presence(self):
        qgis = {"A": ["x", "y"]}
        kmz = {"A": ["x", "z"]}
        issues = layer_field_issues(qgis, kmz)
        kinds = {item["kind"]: item["detail"] for item in issues}
        self.assertEqual(kinds["fields_only_qgis"], "y")
        self.assertEqual(kinds["fields_only_kmz"], "z")

    def test_all_match(self):
        qgis = {"A": ["id", "name"]}
        kmz = {"a": ["id", "name"]}
        self.assertEqual(layer_field_issues(qgis, kmz), [])


if __name__ == "__main__":
    unittest.main()
