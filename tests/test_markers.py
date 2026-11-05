import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/workflow"))
from tools.workflow import markers


class Markers(unittest.TestCase):
    def test_review_marker(self):
        self.assertEqual(
            markers.review_marker(12, 2), "<!-- nightly:review issue=12 round=2 -->"
        )
        self.assertEqual(
            markers.review_marker(1, 1), "<!-- nightly:review issue=1 round=1 -->"
        )
        for bad in (0, -1, True, "2"):
            for args in ((bad, 2), (12, bad)):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    markers.review_marker(*args)

    def test_parse_review_marker(self):
        valid = "<!-- nightly:review issue=12 round=2 -->"
        self.assertEqual(markers.parse_review_marker(valid), (12, 2))
        for invalid_value in (None, 3):
            with self.subTest(invalid_value=invalid_value):
                self.assertIsNone(markers.parse_review_marker(invalid_value))
        for invalid in (
            " " + valid,
            valid + " ",
            valid.replace("round=2", "round=02"),
            valid.replace("round=2", "round=0"),
            valid.replace("issue=12", "issue=x"),
            valid.replace(" -->", " extra=1 -->"),
            "<!-- nightly:shared begin -->",
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(markers.parse_review_marker(invalid))

    def test_shared_markers(self):
        self.assertEqual(markers.SHARED_BEGIN, "<!-- nightly:shared begin -->")
        self.assertEqual(markers.SHARED_END, "<!-- nightly:shared end -->")
