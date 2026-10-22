"""Complete source, primitive and budget contracts for pixel reaction readers."""

import copy
import unittest
from unittest.mock import patch

import fitz
from raster_reaction_support import RasterReactionFixture

from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.raster_reaction_detail import (
    observe_pixel_page,
    page_vectors,
)
from patent_sar_extractor.core.reaction_graph import reaction_route
from patent_sar_extractor.core.reaction_page_source import source_page_vectors
from patent_sar_extractor.core.reaction_raster_layout import (
    observe_raster_layout,
    render_pixel_support,
    source_pixel_step,
)
from patent_sar_extractor.core.source_evidence_identity import proof_id


class RasterReactionContractTests(RasterReactionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.rasterize_route()
        self.binding = self.assert_product("S2")
        self.evidence = self.binding["original_heading_structure_evidence"]
        self.regions = [
            row["bbox"]
            for row in self.evidence["declaration_scope"]["pages"][0]["structures"]
        ]

    def test_unknown_missing_or_cropped_source_cannot_become_an_observation(self):
        def mutate(packet, key):
            page = packet["pages"][0]
            source, detail = page["source"], page["details"][0]
            reading = source["reading"]
            if key == "kind":
                page["kind"] = "native"
            elif key == "extra":
                page["accepted"] = True
            elif key == "version":
                source["version"] = True
            elif key == "page":
                source["page_no"] = True
            elif key == "size":
                source["page_size"][0] += 1
            elif key == "layouts":
                source["raster_sources"] = []
            elif key == "axes":
                source["raster_sources"][0]["pixel_axes"][0][0] = 100001
            elif key == "ink":
                reading.pop("ink_mode")
            elif key == "mask":
                reading["mask_hex"] = "00"
            elif key == "encoding":
                reading["mask_encoding"] = "other"
            elif key == "frame":
                reading["source_window"]["source_pixel_sha256"] = "0" * 64
            elif key == "crop":
                reading["source_window"]["read_bounds"][0] += 1
            elif key == "text":
                reading["source_window"]["purpose"] = "text"
            elif key == "lost-detail":
                page["details"].pop()
            elif key == "double-detail":
                page["details"].append(copy.deepcopy(detail))
            elif key == "dpi":
                detail["readings"][0]["dpi"] = True
            elif key == "order":
                detail["readings"].reverse()
            elif key == "shape":
                detail["readings"][0]["shape"][0] = 0
            elif key == "uncertainty":
                source["uncertainty"] = 0
            elif key == "status":
                packet["status"] = "observed_native_reaction"
            elif key == "invent-frame":
                source["frame"] = [0, 0, 660, 660]
            elif key == "missing-frame":
                source.pop("frame")

        for key in (
            "kind",
            "extra",
            "version",
            "page",
            "size",
            "layouts",
            "axes",
            "ink",
            "mask",
            "encoding",
            "frame",
            "crop",
            "text",
            "lost-detail",
            "double-detail",
            "dpi",
            "order",
            "shape",
            "uncertainty",
            "status",
            "invent-frame",
            "missing-frame",
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.binding)
                packet = changed["original_heading_structure_evidence"][
                    "reaction_source"
                ]
                mutate(packet, key)
                packet["identity"] = proof_id(
                    {k: v for k, v in packet.items() if k != "identity"}
                )
                self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])

    def test_binary_geometry_requires_source_and_derived_positive_error(self):
        page = self.evidence["reaction_source"]["pages"][0]
        vectors, errors = page_vectors(page, self.regions)
        candidates = [
            {
                "structure_id": row["structure_id"],
                "page_no": 1,
                "bbox": row["bbox"],
                "inside": True,
            }
            for row in self.evidence["declaration_scope"]["pages"][0]["structures"]
        ]
        with self.assertRaises(ValueError):
            source_page_vectors(vectors, self.regions)
        with self.assertRaises(ValueError):
            reaction_route(candidates, [vectors])
        for malformed in ({}, {True: 1.0}, {0: float("nan")}, {i: 0 for i in errors}):
            with self.subTest(error=malformed), self.assertRaises(ValueError):
                reaction_route(
                    candidates, [vectors], endpoint_uncertainty={1: malformed}
                )
        self.assertEqual(
            reaction_route(candidates, [vectors], endpoint_uncertainty={1: errors})[
                "terminal_structure_id"
            ],
            "S2",
        )

    def test_interpolation_does_not_invent_original_image_resolution(self):
        bounds = self.evidence["reaction_source"]["pages"][0]["source"]["bounds"]
        sources = observe_raster_layout(self.page, bounds)
        self.assertAlmostEqual(source_pixel_step(sources, bounds, 200), 72 / 200)
        self.assertAlmostEqual(source_pixel_step(sources, bounds, 600), 1 / 3)
        self.assertAlmostEqual(
            render_pixel_support(sources, bounds, 600), 1 / 3 + 72 / 600
        )
        self.rasterize_route(pixels_per_point=1)
        sources = observe_raster_layout(self.page, bounds)
        self.assertAlmostEqual(source_pixel_step(sources, bounds, 600), 1.0)

    def test_rotated_original_pixel_axes_preserve_the_same_terminal(self):
        boxes = [list(box) for box in self.regions]
        for angle in (90, 270):
            with self.subTest(angle=angle):
                self.page.set_rotation(angle)
                matrix = self.page.rotation_matrix
                regions = [list(fitz.Rect(box) * matrix) for box in boxes]
                bounds = list(fitz.Rect(10, 60, 650, 590) * matrix)
                packet = observe_pixel_page(self.page, bounds, regions)
                vectors, errors = page_vectors(packet, regions)
                candidates = [
                    {
                        "structure_id": structure["id"],
                        "page_no": 1,
                        "bbox": box,
                        "inside": True,
                    }
                    for structure, box in zip(self.structures, regions, strict=True)
                ]
                self.assertEqual(
                    reaction_route(
                        candidates, [vectors], endpoint_uncertainty={1: errors}
                    )["terminal_structure_id"],
                    "S2",
                )

    def test_pixel_budget_does_not_remove_a_candidate_or_force_a_terminal(self):
        with patch(
            "patent_sar_extractor.core.raster_reaction_pixels.MAX_SOURCE_PIXELS", 1000
        ):
            self.assertEqual(self.select()[0], [])
        self.assertEqual(len(self.structures), 2)
        self.assertEqual(self.assert_product("S2")["structure_id"], "S2")

    def test_crop_that_partly_contains_arrow_ink_cannot_hide_that_crossing(self):
        second = self.structures[1]
        second["x0"] = 240
        self.page.get_pixmap(
            matrix=fitz.Matrix(2, 2),
            clip=fitz.Rect(*(second[key] for key in ("x0", "y0", "x1", "y1"))),
        ).save(second["image_path"])
        self.assertEqual(self.select()[0], [])

    def test_rehashed_foreign_pixel_axes_still_require_the_actual_original(self):
        changed = copy.deepcopy(self.binding)
        packet = changed["original_heading_structure_evidence"]["reaction_source"]
        packet["pages"][0]["source"]["raster_sources"][0]["pixel_axes"][0][0] *= 1.001
        packet["identity"] = proof_id(
            {k: v for k, v in packet.items() if k != "identity"}
        )
        self.assertTrue(original_heading_source_errors(self.document, [changed]))


if __name__ == "__main__":
    unittest.main()
