"""Bounded literal-caption matching on generated text, without PDF or OCR."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

from patent_sar_extractor.core.source_table_markers import (
    TABLE_BOUNDARY_LINE,
    caption_table_marker,
    unproved_caption_prefix,
)

NEGATIVE_PROBE = """
from patent_sar_extractor.core.source_table_markers import (
    TABLE_BOUNDARY_LINE, table_body_boundary,
)
for prefix in ('[42]', '[42', '［４２］', '[123456789]'):
    raw = prefix + ' ' * 20000 + 'not a table'
    assert TABLE_BOUNDARY_LINE.search(raw) is None
    assert not table_body_boundary(raw)
"""


class TableBoundaryBudgetTests(unittest.TestCase):
    def test_negative_numeric_prefixes_complete_within_a_bounded_worker(self):
        env = {
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        try:
            result = subprocess.run(
                [sys.executable, "-B", "-c", NEGATIVE_PROBE],
                env=env,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("Generated negative caption exceeded its 3-second work bound")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_large_spacing_keeps_the_complete_literal_caption_span_and_role(self):
        for prefix in ("[42]", "[42", "［４２］", "[123456789]"):
            raw = prefix + " " * 20000 + "Table 9. Activity"
            with self.subTest(prefix=prefix):
                boundary = TABLE_BOUNDARY_LINE.match(raw)
                self.assertIsNotNone(boundary)
                self.assertEqual(boundary.start(), 0)
                self.assertEqual(boundary.end(), len(prefix) + 20000 + len("Table 9"))
                proved = prefix in {"[42]", "［４２］"}
                self.assertEqual(caption_table_marker(raw) is not None, proved)
                self.assertEqual(unproved_caption_prefix(raw), not proved)


if __name__ == "__main__":
    unittest.main()
