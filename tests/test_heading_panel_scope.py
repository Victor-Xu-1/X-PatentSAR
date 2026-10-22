"""Complete original panels bind their own headings, never a page-wide order."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz
from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_evidence import valid_heading_binding_evidence
from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.reaction_frame import original_frame_path
from patent_sar_extractor.web.compound_catalog import read_compound_catalog


class HeadingPanelScopeTests(LateralStructureControls, unittest.TestCase):
    def test_noisy_pixel_proof_budget_refuses_only_its_panel_and_keeps_the_page(self):
        from io import BytesIO

        import numpy as np
        from PIL import Image

        from patent_sar_extractor.core.binding_source_headings import _document_sha256
        from patent_sar_extractor.core.heading_declaration_index import (
            HeadingDeclarationIndex,
        )
        from patent_sar_extractor.core.heading_declaration_scope import (
            declaration_candidates,
        )
        from patent_sar_extractor.core.heading_evidence import original_heading_lines
        from patent_sar_extractor.core.heading_observation import observe_heading

        with fitz.open() as original:
            page = original.new_page(width=660, height=720)
            for left, label in ((40, "48A"), (360, "72B")):
                page.draw_rect(fitz.Rect(left - 10, 30, left + 260, 330), width=0.6)
                page.insert_text(
                    (left, 65), f"Compound {label}: Preparation", fontsize=10
                )
            noise = (
                np.random.default_rng(4).integers(0, 2, (1500, 1500), dtype=np.uint8)
                * 255
            )
            stream = BytesIO()
            Image.fromarray(noise).save(stream, format="PNG")
            page.insert_image(fitz.Rect(40, 80, 290, 300), stream=stream.getvalue())
            lines = original_heading_lines(page)
            digest = _document_sha256(original)
            inventory = [
                {
                    "id": key,
                    "page_no": 1,
                    "x0": left + 95,
                    "y0": 100,
                    "x1": left + 230,
                    "y1": 210,
                }
                for key, left in (("NOISY", 40), ("CLEAR", 360))
            ]
            index = HeadingDeclarationIndex(
                original, inventory, lambda _: lines, digest
            )
            left = observe_heading(page, lines[0], digest)
            right = observe_heading(page, lines[1], digest)
            refused = index.observe(left)
            self.assertEqual(declaration_candidates(refused, left), ([], False))
            self.assertEqual(refused["panel"]["refusal"], "region_budget")
            self.assertEqual(len(refused["pages"][0]["structures"]), 2)
            with patch(
                "patent_sar_extractor.core.heading_panel_scope.observe_pixels",
                side_effect=AssertionError("Do not retry an oversized original proof"),
            ):
                self.assertEqual(
                    index.observe(left)["panel"]["refusal"], "region_budget"
                )
            current = index.observe(right)
            candidates, complete = declaration_candidates(current, right)
            self.assertTrue(complete)
            self.assertEqual([item["structure_id"] for item in candidates], ["CLEAR"])

    def test_only_the_exact_opaque_panel_rectangle_is_a_native_frame(self):
        with fitz.open() as original:
            page = original.new_page(width=660, height=720)
            frame = [30.0, 30.0, 300.0, 330.0]
            page.draw_rect(fitz.Rect(frame), width=0.6)
            path = page.get_drawings(extended=True)[0]
            self.assertTrue(original_frame_path(path, page, frame))
            for changed in (
                {**path, "type": "fs", "fill": (0.0, 0.0, 0.0)},
                {**path, "stroke_opacity": 0.5},
                {**path, "dashes": "[1 1] 0"},
                {
                    **path,
                    "items": [
                        *path["items"],
                        ("l", fitz.Point(50, 100), fitz.Point(270, 300)),
                    ],
                },
            ):
                self.assertFalse(original_frame_path(changed, page, frame))
            self.assertFalse(
                original_frame_path(path, page, [25.0, 30.0, 300.0, 330.0])
            )
            self.assertFalse(original_frame_path(path, page, None))

    def panel_source(self, labels=("I-017B", "205"), *, raster=False, variant=None):
        def original_panels(document, records):
            page = document.new_page(width=660, height=720)
            for left, label in zip((40, 360), labels, strict=True):
                # Closed physical original panels, not inferred half-page lanes.
                bounds = fitz.Rect(
                    left - 10, 30, left + 260, 690 if variant == "large" else 330
                )
                if variant != "open":
                    page.draw_rect(bounds, width=0.6)
                else:
                    for start, end in (
                        (bounds.tl, bounds.tr),
                        (bounds.tr, bounds.br),
                        (bounds.br, bounds.bl),
                    ):
                        page.draw_line(start, end, width=0.6)
                page.insert_text(
                    (left, 65), f"Compound {label}: Preparation", fontsize=10
                )
                self.add_drawing(
                    page,
                    records,
                    left,
                    130 if variant == "reaction" else 190,
                    f"PANEL-{label}",
                )
                if variant == "reaction":
                    self.add_drawing(page, records, left, 235, f"TERMINAL-{label}")
                    page.draw_line((left + 130, 170), (left + 130, 195), width=1)
                    page.draw_polyline(
                        [(left + 125, 187), (left + 130, 195), (left + 135, 187)],
                        width=1,
                    )
                page.insert_text(
                    (left, 315 if variant == "reaction" else 275),
                    "Step 1: Reaction",
                    fontsize=10,
                )
            if variant == "rival":
                self.add_drawing(page, records, 40, 110, "UNOWNED-PANEL-RIVAL")
            elif variant == "outside":
                self.add_drawing(page, records, 40, 400, "OUTSIDE-ALL-PANELS")
            elif variant == "crossing":
                records[-2]["bbox_pdf"][2] = 310
            elif variant == "crossing_text":
                page.insert_text((285, 240), "Unresolved extra text", fontsize=10)

        return self.run_case(mutate_document=original_panels, raster=raster)

    def test_parallel_closed_original_panels_do_not_borrow_the_other_heading(self):
        for labels in (("I-017B", "205"), ("009", "72C")):
            with self.subTest(labels=labels):
                _, payload = self.panel_source(labels)
                owners = {
                    row["cpd"]: row["structure_id"]
                    for row in payload["compound_catalog"]["entries"]
                }
                self.assertEqual(
                    {
                        "Compound " + label: owners.get("Compound " + label)
                        for label in labels
                    },
                    {"Compound " + label: "PANEL-" + label for label in labels},
                    payload["source_issues"],
                )
                self.assertEqual(payload["total_structures"], 6)
                self.assertEqual(coverage_errors(payload), [])

    def targets(self, payload):
        return [
            row
            for row in payload["compound_catalog"]["entries"]
            if row["structure_id"].startswith("PANEL-")
        ]

    def test_scanned_closed_panels_keep_the_same_literal_owners(self):
        _, payload = self.panel_source(raster=True)
        self.assertEqual(
            {row["cpd"]: row["structure_id"] for row in self.targets(payload)},
            {"Compound I-017B": "PANEL-I-017B", "Compound 205": "PANEL-205"},
            payload["source_issues"],
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_independent_outside_candidates_are_retained_without_expanding_a_panel(
        self,
    ):
        _, payload = self.panel_source(variant="outside")
        self.assertEqual(len(self.targets(payload)), 2)
        self.assertEqual(payload["total_structures"], 7)
        for target in self.targets(payload):
            scope = target["original_heading_structure_evidence"]["declaration_scope"]
            self.assertIn(
                "OUTSIDE-ALL-PANELS",
                {r["structure_id"] for r in scope["pages"][0]["structures"]},
            )

    def test_open_panels_cannot_be_replaced_by_an_arbitrary_page_split(self):
        _, payload = self.panel_source(variant="open")
        self.assertEqual(self.targets(payload), [])
        self.assertTrue(coverage_errors(payload))

    def test_over_budget_panels_cannot_fall_back_to_a_global_unique_candidate(self):
        _, payload = self.panel_source(variant="large")
        self.assertEqual(self.targets(payload), [])
        self.assertTrue(coverage_errors(payload))

    def test_reaction_roles_use_only_the_same_actual_panel_window(self):
        _, payload = self.panel_source(variant="reaction")
        self.assertEqual(
            {
                row["cpd"]: row["structure_id"]
                for row in payload["compound_catalog"]["entries"]
                if row["cpd"] in {"Compound I-017B", "Compound 205"}
            },
            {"Compound I-017B": "TERMINAL-I-017B", "Compound 205": "TERMINAL-205"},
            payload["source_issues"],
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_rival_crossing_diagram_or_crossing_text_remains_unresolved(self):
        for variant in ("rival", "crossing", "crossing_text"):
            with self.subTest(variant=variant):
                _, payload = self.panel_source(variant=variant)
                self.assertNotIn(
                    "PANEL-I-017B",
                    {row["structure_id"] for row in self.targets(payload)},
                )
                self.assertTrue(coverage_errors(payload))

    def test_serialized_consumers_and_original_readback_share_the_panel_source(self):
        from pathlib import Path

        from patent_sar_extractor.application.binding_policy import (
            _load_bindings_from_json,
        )
        from patent_sar_extractor.core.ocsr.run_smiles import (
            validate_strict_binding_input,
        )
        from patent_sar_extractor.web.files import SafeFiles

        result, payload = self.panel_source()
        path = Path(result["output_files"]["json"])
        stored, worker_rows = _load_bindings_from_json(str(path))
        self.assertEqual(stored, payload)
        self.assertEqual(validate_strict_binding_input(str(path), worker_rows), [])
        self.assertEqual(
            SafeFiles(path.parent).json(path.name, optional=False), payload
        )
        saved = json.loads(json.dumps(payload))
        entries = saved["compound_catalog"]["entries"]
        self.assertEqual(len(read_compound_catalog(saved, entries)[0]), 6)
        self.assertEqual(len(recognition_inputs(saved).formal), 6)
        with fitz.open(self.root / "original.pdf") as original:
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("No new OCR on source readback"),
            ):
                self.assertEqual(
                    original_heading_source_errors(original, self.targets(saved)), []
                )
            # Change the original panel border, not the title or final crop.
            original[1].draw_rect(
                fitz.Rect(29, 100, 32, 120), color=None, fill=(1, 1, 1)
            )
            self.assertTrue(
                original_heading_source_errors(original, self.targets(saved))
            )

    def test_missing_shifted_or_unproved_panel_cannot_supply_saved_acceptance(self):
        _, payload = self.panel_source()
        target = self.targets(payload)[0]
        for mutation in (
            "remove",
            "shift",
            "pixels",
            "version",
            "extra",
            "remove_refusal",
            "false_refusal",
        ):
            changed = copy.deepcopy(target)
            scope = changed["original_heading_structure_evidence"]["declaration_scope"]
            if mutation == "remove":
                del scope["panel"]
            elif mutation == "shift":
                scope["panel"]["cell"][2] += 1
            elif mutation == "pixels":
                scope["panel"]["pixels"] = None
            elif mutation == "version":
                scope["panel"]["version"] = True
            elif mutation == "remove_refusal":
                del scope["panel"]["refusal"]
            elif mutation == "false_refusal":
                scope["panel"]["refusal"] = "region_budget"
            else:
                scope["panel"]["foreign"] = True
            changed["original_heading_evidence"]["declaration_scope"] = scope
            with self.subTest(mutation=mutation):
                self.assertFalse(valid_heading_binding_evidence(changed))


if __name__ == "__main__":
    unittest.main()
