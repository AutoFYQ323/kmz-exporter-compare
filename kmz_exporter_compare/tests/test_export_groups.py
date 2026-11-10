# -*- coding: utf-8 -*-

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from export_groups import (
    count_bare_folders,
    node_has_layer,
    should_write_empty_group,
    tree_has_group,
)


class ExportGroupTests(unittest.TestCase):
    def test_empty_group_is_selectable_for_export(self):
        folder = {"type": "group", "name": "123", "children": []}
        self.assertFalse(node_has_layer(folder))
        self.assertTrue(tree_has_group([folder]))
        self.assertTrue(should_write_empty_group(folder, "0", {"0"}))
        self.assertFalse(should_write_empty_group(folder, "0", set()))
        self.assertTrue(should_write_empty_group(folder, "0", None))

    def test_group_with_a_layer_is_not_an_empty_folder(self):
        folder = {
            "type": "group",
            "name": "123",
            "children": [{"type": "layer", "name": "roads"}],
        }
        self.assertTrue(node_has_layer(folder))
        self.assertFalse(should_write_empty_group(folder, "0", {"0"}))

    def test_nested_empty_group_has_no_layer(self):
        folder = {
            "type": "group",
            "name": "123",
            "children": [{"type": "group", "name": "inside", "children": []}],
        }
        self.assertFalse(node_has_layer(folder))
        self.assertTrue(should_write_empty_group(folder, "0", {"0"}))

    def test_bare_folder_count_includes_parent_and_child(self):
        written = [
            ("group", "123", [("group", "inside", [])]),
            ("group", "roads", [("layer", "roads", ["pm"])]),
        ]
        self.assertEqual(count_bare_folders(written), 2)


if __name__ == "__main__":
    unittest.main()
