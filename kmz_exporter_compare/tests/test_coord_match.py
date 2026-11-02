# -*- coding: utf-8 -*-
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from coord_match import keyword_score


class KeywordScoreTests(unittest.TestCase):
    def test_exact_one_char(self):
        self.assertGreater(keyword_score("1", "1"), 0)
        self.assertEqual(keyword_score("1", "1200"), 0)

    def test_exact_longer(self):
        self.assertEqual(keyword_score("Roads", "roads"), 1005)

    def test_substring(self):
        self.assertGreater(keyword_score("Main Roads", "roads extra"), 0)


if __name__ == "__main__":
    unittest.main()
