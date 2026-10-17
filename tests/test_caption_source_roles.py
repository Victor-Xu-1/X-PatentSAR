"""Original table roles must qualify bare IDs, never numeric proximity alone."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_role_observation import (
    observe_caption_role,
    owns_caption_frame,
)
from patent_sar_extractor.core.caption_role_proof import (
    caption_role_status,
    validate_caption_exclusions,
)
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.table_geometry import (
    detect_ruled_table_regions,
    page_tokens,
)
from patent_sar_extractor.core.visible_structure_binding import bind_visible_captions


def catalog(
    title="Table 47. Compounds", *, prefixed=False, below=False, fontname="helv"
):
    doc = fitz.open()
    page = doc.new_page()
    xs = [50, 180, 310]
    ys = [100, 180, 205] if below else [100, 125, 205]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    if title:
        page.insert_text((50, 85), title, fontsize=10, fontname=fontname)
    label_y, diagram_y = (197, 120) if below else (117, 140)
    labels = ("I-004A", "I-009B")
    boxes, structures = [], []
    for index, label in enumerate(labels):
        left = 70 + index * 130
        page.insert_text(
            (left, label_y), f"Compound {label}" if prefixed else label, fontsize=9
        )
        box = (left + 10, diagram_y, left + 70, diagram_y + 35)
        page.draw_line((box[0], box[1] + 12), (box[0] + 30, box[1]))
        page.draw_line((box[0] + 30, box[1]), (box[2], box[1] + 12))
        boxes.append(box)
        structures.append(
            {
                "id": f"original-{index}",
                "page_no": 1,
                **dict(zip(("x0", "y0", "x1", "y1"), box)),
            }
        )
    return doc, {1: structures}, {1: boxes}


class CaptionSourceRoleTests(unittest.TestCase):
    def binding(self, pair):
        return {
            "cpd": f"Compound {pair['label']}",
            "structure_id": pair["structure"]["id"],
            "page_no": pair["structure"]["page_no"],
            **{
                f"struct_{axis}": pair["structure"][axis]
                for axis in ("x0", "y0", "x1", "y1")
            },
            "binding_rule": "original_caption_cell",
            "exact_caption_evidence": {
                "page_no": pair["label_page_no"],
                "bbox": list(pair["label_bbox"]),
                "observations": pair["observations"],
                "ownership": pair["ownership"],
            },
        }

    def test_original_compound_catalog_supports_bare_identifiers_above_or_below(self):
        for below in (False, True):
            with self.subTest(below=below):
                doc, structures, boxes = catalog(below=below)
                with doc:
                    result = bind_caption_grids(doc, structures, boxes, [1])
                self.assertEqual(
                    [pair["label"] for pair in result.bindings], ["I-004A", "I-009B"]
                )
                self.assertEqual(result.issues, [])
                self.assertTrue(
                    all(
                        pair["ownership"].get("caption_role")
                        for pair in result.bindings
                    )
                )

    def test_bare_caption_reaches_the_shared_formal_gate_with_original_role(self):
        doc, structures, boxes = catalog()
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertTrue(result.bindings)
        for pair in result.bindings:
            item = self.binding(pair)
            self.assertTrue(valid_caption_binding_evidence(item))
            for key in ("caption_role", "identifier_form"):
                bad = copy.deepcopy(item)
                del bad["exact_caption_evidence"]["ownership"][key]
                self.assertFalse(valid_caption_binding_evidence(bad))

    def test_unknown_role_retains_the_original_grid_as_unresolved(self):
        for title in (None, "Table 47. Structures"):
            with self.subTest(title=title):
                doc, structures, boxes = catalog(title)
                with doc:
                    result = bind_caption_grids(doc, structures, boxes, [1])
                self.assertEqual(result.bindings, [])
                self.assertEqual(result.pages, {1})
                self.assertTrue(result.issues)

    def test_explicit_intermediate_catalog_cannot_publish_final_compound_claims(self):
        doc, structures, boxes = catalog("Table 47. Intermediates", prefixed=True)
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertEqual(result.bindings, [])
        self.assertEqual(result.pages, {1})
        self.assertEqual(len(result.exclusions), 1)
        validate_caption_exclusions(result.exclusions, [])
        with self.assertRaises(ValueError):
            validate_caption_exclusions(
                result.exclusions, [{"structure_id": "original-0"}]
            )

    def test_mixed_catalogue_roles_are_reviewed_not_silently_excluded(self):
        for title in (
            "Table 47. Compounds and intermediates",
            "Table 47. Intermediates and compounds",
        ):
            for prefixed in (False, True):
                with self.subTest(title=title, prefixed=prefixed):
                    doc, structures, boxes = catalog(title, prefixed=prefixed)
                    with doc:
                        result = bind_caption_grids(doc, structures, boxes, [1])
                    self.assertEqual(result.exclusions, [])
                    self.assertEqual(result.bindings, [])
                    self.assertEqual(result.pages, {1})
                    self.assertTrue(result.issues)

    def test_wrapped_mixed_title_cannot_drop_its_second_role(self):
        doc, structures, boxes = catalog(None, prefixed=True)
        page = doc[0]
        page.insert_text((50, 70), "Table 47. Compounds", fontsize=10)
        page.insert_text((50, 85), "and intermediates", fontsize=10)
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertEqual(result.exclusions, [])
        self.assertEqual(result.bindings, [])
        self.assertTrue(result.issues)

    def test_nonfinal_grid_does_not_hide_a_final_caption_outside_it_on_the_same_page(
        self,
    ):
        doc, structures, _boxes = catalog("Table 47. Intermediates", prefixed=True)
        page = doc[0]
        page.insert_text((80, 295), "Compound 73", fontsize=9)
        page.draw_line((80, 262), (110, 250))
        page.draw_line((110, 250), (140, 262))
        structures[1].append(
            {
                "id": "outside-final",
                "page_no": 1,
                "x0": 80,
                "y0": 250,
                "x1": 140,
                "y1": 280,
            }
        )
        protected, exclusions = set(), []
        with doc:
            bindings = bind_visible_captions(
                doc,
                structures[1],
                None,
                protected_structure_ids=protected,
                source_exclusions=exclusions,
            )
        self.assertEqual([binding.label for binding in bindings], ["73"])
        self.assertEqual(protected, {"original-0", "original-1"})
        validate_caption_exclusions(exclusions, [{"structure_id": "outside-final"}])

    def test_unsupported_literal_id_is_unresolved_not_a_silently_missing_table(self):
        doc, structures, boxes = catalog()
        page = doc[0]
        page.add_redact_annot(fitz.Rect(68, 106, 150, 122), fill=(1, 1, 1))
        page.add_redact_annot(fitz.Rect(198, 106, 285, 122), fill=(1, 1, 1))
        page.apply_redactions()
        page.insert_text((70, 117), "1.2", fontsize=9)
        page.insert_text((200, 117), "1.3", fontsize=9)
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertEqual(result.bindings, [])
        self.assertEqual(result.pages, {1})
        self.assertTrue(result.issues)


class CaptionRoleProofTests(unittest.TestCase):
    def original_scope(self, title="Table 47. Compounds"):
        doc, _structures, _boxes = catalog(title)
        self.addCleanup(doc.close)
        page = doc[0]
        grids = detect_ruled_table_regions(page, dpi=240)
        tokens = page_tokens(page, dpi=200, allow_tesseract=False)
        scope = observe_caption_role(page, grids[0], grids, tokens)
        xs, ys = grids[0]["xs"], grids[0]["ys"]
        return scope, [xs[0], ys[0], xs[1], ys[1]]

    def test_real_native_title_has_replayable_original_role(self):
        for title, expected in (
            ("Table 47. Compounds", "compound"),
            ("Table 47. Intermediates", "nonfinal"),
            ("Table 47. Intermediate compounds", "nonfinal"),
            ("Table 47. Compounds and intermediates", "mixed"),
            ("Table 47. Structures", "unknown"),
        ):
            with self.subTest(title=title):
                scope, cell = self.original_scope(title)
                self.assertEqual(caption_role_status(scope, 1, cell), expected, scope)

    def test_saved_role_and_source_frame_cannot_be_changed_by_flags(self):
        original, cell = self.original_scope()
        for field, value in (
            ("role", "nonfinal"),
            ("table_key", "TABLE48"),
            ("page_no", True),
            ("version", False),
            ("observations", []),
            ("table_bbox", [0, 0, 10, 10]),
        ):
            with self.subTest(field=field):
                scope = copy.deepcopy(original)
                scope[field] = value
                self.assertIsNone(caption_role_status(scope, 1, cell))

    def raster_frame(self, raw_title="Table 47. Finalproducts", *, physical_title=None):
        drawing, _structures, _boxes = catalog(
            physical_title or "Table 47. Final    products"
        )
        self.caption_boxes = _boxes[1]
        with drawing:
            pixels = drawing[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            png = pixels.tobytes("png")
        doc = fitz.open()
        self.addCleanup(doc.close)
        page = doc.new_page()
        page.insert_image(page.rect, stream=png)
        grids = detect_ruled_table_regions(page, dpi=240)
        tokens = page_tokens(page, dpi=200, allow_tesseract=False)
        # Controlled first-pass error; physical source pixels remain untouched.
        hint = {
            "text": raw_title,
            "x": 150,
            "y": 79,
            "bbox": [50, 70, 250, 88],
            "confidence": 0.99,
            "source": "raster",
            "geometry_space": "rendered",
        }
        observed = SourceTokens(
            [hint, *[t for t in tokens if t["y"] >= 100]],
            source_layout(page),
            tokens.scan_bounds,
        )
        return page, grids, observed

    def test_bounded_original_title_read_resolves_unknown_first_pass_without_editing_it(
        self,
    ):
        page, grids, tokens = self.raster_frame()
        before = copy.deepcopy(list(tokens))
        scope = observe_caption_role(page, grids[0], grids, tokens)
        self.assertEqual(scope["role"], "compound", scope)
        self.assertEqual(scope["table_key"], "TABLE47")
        self.assertEqual(list(tokens), before)
        self.assertIn("Finalproducts", scope["observations"][0]["text"])
        self.assertEqual(caption_role_status(scope, 1, scope["table_bbox"]), "compound")
        self.assertIn("refinement", scope)

    def test_known_nonfinal_role_or_table_identity_cannot_be_overwritten(self):
        for title, role in (
            ("Table 47. Intermediates", "nonfinal"),
            ("Table 93. Finalproducts", "unknown"),
        ):
            with self.subTest(title=title):
                page, grids, tokens = self.raster_frame(title)
                scope = observe_caption_role(page, grids[0], grids, tokens)
                self.assertEqual(scope["role"], role)

    def test_serialized_title_refinement_cannot_change_its_original_window(self):
        page, grids, tokens = self.raster_frame()
        scope = observe_caption_role(page, grids[0], grids, tokens)
        self.assertEqual(scope["role"], "compound", scope)
        altered = copy.deepcopy(scope)
        altered["refinement"]["bbox"][0] += 1
        self.assertIsNone(caption_role_status(altered, 1, altered["table_bbox"]))

    def test_refined_unknown_and_mixed_titles_keep_their_declared_roles(self):
        for title, expected in (
            ("Table 47. Continued", "unknown"),
            ("Table 47. Compounds and intermediates", "mixed"),
        ):
            with self.subTest(title=title):
                page, grids, tokens = self.raster_frame(
                    "Table 47. Productlisting", physical_title=title
                )
                scope = observe_caption_role(page, grids[0], grids, tokens)
                self.assertEqual(scope["role"], expected, scope)
                self.assertEqual(
                    caption_role_status(scope, 1, scope["table_bbox"]), expected, scope
                )

    def test_proved_title_reuse_rechecks_original_facts_without_a_second_cell_pass(
        self,
    ):
        page, grids, tokens = self.raster_frame()
        scope = observe_caption_role(page, grids[0], grids, tokens)
        self.assertEqual(scope["role"], "compound")
        with patch(
            "patent_sar_extractor.core.activity_grid_role_observation.observe_role_cells",
            side_effect=AssertionError("A reused frame must not launch title OCR"),
        ):
            self.assertTrue(
                owns_caption_frame(
                    page,
                    grids[0],
                    grids,
                    tokens,
                    self.caption_boxes,
                    original_role=scope,
                )
            )
            changed = copy.deepcopy(tokens)
            changed[0]["text"] = "Table 93. Finalproducts"
            self.assertFalse(
                owns_caption_frame(
                    page,
                    grids[0],
                    grids,
                    changed,
                    self.caption_boxes,
                    original_role=scope,
                )
            )

    def test_refined_title_requires_both_complete_confident_original_readings(self):
        page, grids, tokens = self.raster_frame()
        scope = observe_caption_role(page, grids[0], grids, tokens)
        self.assertEqual(scope["role"], "compound")
        for change in ("missing_read", "weak_part", "changed_matrix", "missing_frame"):
            with self.subTest(change=change):
                altered = copy.deepcopy(scope)
                reading = altered["refinement"]["role_cells"]
                if change == "missing_read":
                    reading["observations"].pop()
                elif change == "weak_part":
                    reading["observations"][0]["cells"][0]["parts"][0]["confidence"] = (
                        0.2
                    )
                elif change == "changed_matrix":
                    reading["observations"][1]["matrix"][0][0] = (
                        "Table 47. Intermediates"
                    )
                else:
                    reading["rendered_frames"].pop()
                self.assertIsNone(
                    caption_role_status(altered, 1, altered["table_bbox"])
                )

    def test_weak_title_cannot_keep_a_previously_declared_compound_role(self):
        scope, cell = self.original_scope()
        part = scope["observations"][0]["tokens"][0]
        part["confidence"] = 0.2
        self.assertIsNone(caption_role_status(scope, 1, cell))

    def test_saved_title_cannot_be_borrowed_from_a_neighbouring_original_grid(self):
        doc, _structures, _boxes = catalog()
        self.addCleanup(doc.close)
        page = doc[0]
        for x in (350, 460, 570):
            page.draw_line((x, 100), (x, 205))
        for y in (100, 125, 205):
            page.draw_line((350, y), (570, y))
        page.insert_text((350, 85), "Table 48. Compounds", fontsize=10)
        grids = sorted(
            detect_ruled_table_regions(page, dpi=240), key=lambda g: g["xs"][0]
        )
        tokens = page_tokens(page, dpi=200, allow_tesseract=False)
        left = observe_caption_role(page, grids[0], grids, tokens)
        right = observe_caption_role(page, grids[1], grids, tokens)
        xs, ys = grids[0]["xs"], grids[0]["ys"]
        cell = [xs[0], ys[0], xs[1], ys[1]]
        self.assertEqual(caption_role_status(left, 1, cell), "compound")
        borrowed = copy.deepcopy(left)
        borrowed["observations"] = copy.deepcopy(right["observations"])
        borrowed["table_key"] = right["table_key"]
        self.assertIsNone(caption_role_status(borrowed, 1, cell))

    def test_centered_and_wrapped_original_titles_replay_the_whole_role(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                doc, _structures, _boxes = catalog(None)
                self.addCleanup(doc.close)
                page = doc[0]
                page.insert_text(
                    (115, 70 if wrapped else 85),
                    "Table 47." if wrapped else "Table 47. Compounds",
                    fontsize=10,
                )
                if wrapped:
                    page.insert_text((115, 85), "Compounds", fontsize=10)
                grids = detect_ruled_table_regions(page, dpi=240)
                scope = observe_caption_role(
                    page,
                    grids[0],
                    grids,
                    page_tokens(page, dpi=200, allow_tesseract=False),
                )
                xs, ys = grids[0]["xs"], grids[0]["ys"]
                cell = [xs[0], ys[0], xs[1], ys[1]]
                self.assertEqual(caption_role_status(scope, 1, cell), "compound", scope)

    def test_missing_malformed_or_excess_original_scope_is_not_accepted(self):
        original, cell = self.original_scope()
        for field, value in (
            ("sources", None),
            ("sources", [None]),
            ("sources", original["sources"] * 3),
            ("grid_axes", {"xs": [50, True, 310], "ys": [100, 125, 205]}),
            ("window", [0, 0, float("nan"), 100]),
            ("observations", [None]),
        ):
            with self.subTest(field=field, value=value):
                scope = copy.deepcopy(original)
                scope[field] = value
                self.assertIsNone(caption_role_status(scope, 1, cell))
