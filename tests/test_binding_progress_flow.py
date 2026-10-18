"""Same native source binder/writer with and without its optional work observer."""

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.application.binding_progress import BindingProgress
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.stages import read_progress


class BindingProgressFlowTests(unittest.TestCase):
    def test_native_source_and_csv_bytes_do_not_change_when_work_is_observed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf, metadata = root / "control.pdf", root / "metadata.json"
            structures = []
            with fitz.open() as document:
                page = document.new_page()
                for x in (50, 100, 280):
                    page.draw_line((x, 90), (x, 315))
                for y in (90, 115, 215, 315):
                    page.draw_line((50, y), (280, y))
                page.insert_text((53, 105), "Cmpd No.", fontsize=7)
                page.insert_text((140, 105), "Structure", fontsize=9)
                page.insert_text(
                    (40, 760),
                    "Native synthetic source-work observation control; not chemical evidence.",
                    fontsize=8,
                )
                for number, y in ((1, 125), (2, 225)):
                    page.insert_text((65, y + 30), f"{number}.", fontsize=10)
                    bounds = [110.0, float(y), 265.0, float(y + 80)]
                    image = root / f"diagram-{number}.png"
                    page.get_pixmap(clip=fitz.Rect(bounds)).save(image)
                    structures.append(
                        {
                            "structure_id": f"S{number:04}",
                            "structure_index": number - 1,
                            "page_no": 1,
                            "bbox_pdf": bounds,
                            "image_path": str(image),
                        }
                    )
                document.save(pdf)
            metadata.write_text(
                json.dumps({"patent_number": "CONTROL", "structures": structures})
            )
            events = []
            observed_root = root / "observed"
            progress = BindingProgress(str(observed_root / "structure_bindings"))

            def observer(*event):
                events.append(event)
                progress(*event)

            profile = {"active_cpds": [], "structure_candidate_pages": [0]}
            with (
                patch("patent_sar_extractor.core.binding_artifacts.datetime") as clock,
                patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    side_effect=AssertionError("Native control must not load a model"),
                ),
                patch(
                    "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                    side_effect=AssertionError("Native heading must not load a model"),
                ),
            ):
                clock.now.return_value = datetime(2026, 1, 1, tzinfo=UTC)
                plain = bind(str(pdf), profile, str(root / "plain"), str(metadata))
                observed = bind(
                    str(pdf),
                    profile,
                    str(observed_root / "structure_bindings"),
                    str(metadata),
                    progress=observer,
                )
            self.assertEqual(plain["bound"], 2)
            self.assertEqual(observed["bound"], 2)
            for kind in ("json", "csv"):
                self.assertEqual(
                    Path(plain["output_files"][kind]).read_bytes(),
                    Path(observed["output_files"][kind]).read_bytes(),
                )
            phases = list(dict.fromkeys(event[0] for event in events))
            self.assertEqual(
                phases,
                [
                    "caption_sources",
                    "numbered_sources",
                    "numbered_cells",
                    "declaration_sources",
                    "visible_captions",
                    "reference_sources",
                    "heading_sources",
                ],
            )
            for phase in phases:
                records = [event for event in events if event[0] == phase]
                self.assertEqual(records[0][1], 0)
                self.assertEqual(records[-1][1], records[-1][2])
            view = read_progress(SafeFiles(observed_root), "bind")
            self.assertEqual(view.source_phase, "heading_sources")
            self.assertEqual((view.completed, view.total), (1, 1))


if __name__ == "__main__":
    unittest.main()
