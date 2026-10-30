"""Controlled heading ownership through the retained cache path, without models."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image

from patent_sar_extractor.contracts import (
    VISIBLE_LABEL_CACHE_SCHEMA,
    VISIBLE_LABEL_CACHE_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.core import binding_observations as observations
from patent_sar_extractor.core import page_ocr_cache
from patent_sar_extractor.core.binding_source_headings import (
    _document_sha256,
    observed_heading_blocks,
    select_heading_bindings,
)
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.heading_evidence import original_heading_lines
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.table_geometry import page_tokens


class HeadingSourceOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-heading-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with self._document() as document:
            self.document_sha256 = _document_sha256(document)

    @staticmethod
    def _document():
        document = fitz.open()
        page = document.new_page(width=500, height=500)
        page.insert_text((72, 72), "Compound 42A: Synthesis")
        return document

    def _structure(self, sid="S1", x0=100.0):
        image = self.root / f"{sid}.png"
        Image.new("RGB", (150, 110), "white").save(image)
        return {
            "id": sid,
            "idx": int(sid[1:]),
            "page_no": 1,
            "x0": x0,
            "y0": 100.0,
            "x1": x0 + 150.0,
            "y1": 210.0,
            "image_path": str(image),
            "source_pdf_sha256": self.document_sha256,
        }

    @staticmethod
    def _cache_entry(structure, labels, source="page_strict"):
        return {
            **artifact_identity(
                VISIBLE_LABEL_CACHE_SCHEMA, VISIBLE_LABEL_CACHE_SCHEMA_VERSION
            ),
            "structure_signature": observations._structure_cache_signature(structure),
            "cache_version": observations._VISIBLE_LABEL_CACHE_VERSION,
            "cache_complete": True,
            "visible_labels": labels,
            "visible_label_candidates": [
                {"label": label, "source": source} for label in labels
            ],
        }

    def _select(self, structures, cache, line_map=None, extra_source_text=None):
        cache_path = self.root / "visible_labels.json"
        cache_path.write_text(json.dumps(cache), encoding="utf-8")

        with (
            self._document() as document,
            patch.object(
                page_ocr_cache,
                "get_ocr_engine",
                side_effect=AssertionError(
                    "Native headings and retained cache are lazy"
                ),
            ) as ocr,
            patch("patent_sar_extractor.core.heading_observation.get_ocr_engine", ocr),
        ):
            if extra_source_text:
                document[0].insert_text((72, 300), extra_source_text)
            blocks = observed_heading_blocks(document, [0], {})
            bindings, issues = select_heading_bindings(
                document,
                structures,
                blocks,
                line_map or {},
                str(self.root / "bindings"),
                {
                    "visible_labels_path": str(cache_path),
                    "bind_workers": 1,
                    "active_cpds": ["Compound 999"],
                },
            )
        return bindings, issues, ocr, cache_path

    def test_same_crop_and_heading_in_another_pdf_cannot_reuse_labels(self):
        structure = self._structure()
        cache = {"S1": self._cache_entry(structure, ["42A"])}
        bindings, issues, batch, path = self._select(
            [structure],
            cache,
            extra_source_text="Different original evidence outside this crop",
        )
        self.assertEqual(bindings, [])
        self.assertTrue(issues)
        batch.assert_not_called()
        self.assertEqual(json.loads(path.read_text()), cache)

    def test_cache_versions_and_completion_flags_are_exact_typed_contracts(self):
        structure = self._structure()
        valid = self._cache_entry(structure, ["42A"])
        self.assertTrue(
            observations._visible_cache_item_matches_structure(valid, structure)
        )
        for version in (
            True,
            False,
            str(observations._VISIBLE_LABEL_CACHE_VERSION),
            float(observations._VISIBLE_LABEL_CACHE_VERSION),
            observations._VISIBLE_LABEL_CACHE_VERSION + 1,
        ):
            with self.subTest(version=version):
                self.assertFalse(
                    observations._visible_cache_item_matches_structure(
                        {**valid, "cache_version": version}, structure
                    )
                )
        for complete in (1, "true", [], None):
            with self.subTest(complete=complete):
                self.assertFalse(
                    observations._visible_cache_item_matches_structure(
                        {**valid, "cache_complete": complete}, structure
                    )
                )

    def test_missing_original_or_crop_identity_is_not_a_reusable_cache(self):
        structure = self._structure()
        valid = self._cache_entry(structure, ["42A"])
        unsigned = {
            key: value for key, value in structure.items() if key != "source_pdf_sha256"
        }
        self.assertFalse(
            observations._visible_cache_item_matches_structure(valid, unsigned)
        )
        missing = {**structure, "image_path": str(self.root / "missing.png")}
        self.assertFalse(
            observations._visible_cache_item_matches_structure(
                self._cache_entry(missing, ["42A"]), missing
            )
        )

    def test_unsigned_sources_do_not_start_crop_ocr_or_write_cache(self):
        structure = self._structure()
        cache = {"S1": self._cache_entry(structure, ["42A"])}
        structure.pop("source_pdf_sha256")
        path = self.root / "visible_labels.json"
        original = json.dumps(cache).encode("utf-8")
        path.write_bytes(original)
        with patch.object(
            page_ocr_cache,
            "get_ocr_engine",
            side_effect=AssertionError("Unsigned sources cannot initialize OCR"),
        ) as engine:
            result = observations._refine_visible_label_cache_with_page_ocr(
                [structure],
                cache,
                {0: [(210.0, "Compound 42A")]},
                str(self.root / "bound"),
                {"visible_labels_path": str(path)},
            )
        self.assertEqual(result, {})
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / "bound").exists())
        engine.assert_not_called()

    def test_cache_replace_failure_preserves_existing_bytes(self):
        structure = self._structure()
        cache = {"S1": self._cache_entry(structure, ["42"])}
        path = self.root / "visible_labels.json"
        original = json.dumps(cache).encode("utf-8")
        path.write_bytes(original)
        with (
            patch.object(
                page_ocr_cache,
                "get_ocr_engine",
                side_effect=AssertionError("Refinement reuses observations"),
            ) as engine,
            patch(
                "patent_sar_extractor.artifact_io.os.replace",
                side_effect=OSError("controlled replace failure"),
            ),
        ):
            result = observations._refine_visible_label_cache_with_page_ocr(
                [structure],
                cache,
                {0: [(210.0, "Compound 42A")]},
                str(self.root / "bound"),
                {"visible_labels_path": str(path)},
            )
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(result["S1"]["visible_labels"], ["42A"])
        self.assertEqual(cache["S1"]["visible_labels"], ["42"])
        self.assertFalse(list(self.root.glob(f".{path.name}.*.tmp")))
        engine.assert_not_called()

    def test_changed_crop_bytes_cannot_reuse_cache_or_change_source_bytes(self):
        structure = self._structure()
        cache = {"S1": self._cache_entry(structure, ["42A"])}
        # Change bytes without creating a new independently provable diagram.
        changed = Image.new("RGB", (150, 110), "white")
        changed.putpixel((0, 0), (0, 0, 0))
        changed.save(structure["image_path"])
        self.assertFalse(
            observations._visible_cache_item_matches_structure(cache["S1"], structure)
        )
        bindings, issues, engine, path = self._select([structure], cache)
        self.assertEqual(bindings, [])
        self.assertTrue(issues)
        self.assertEqual(json.loads(path.read_text()), cache)
        engine.assert_not_called()

    def test_filtering_retained_cache_is_read_only_and_requires_exact_identity(self):
        structures = [self._structure(), self._structure("S2"), self._structure("S3")]
        cache = {s["id"]: self._cache_entry(s, ["42A"]) for s in structures[:2]}
        cache["S2"]["structure_signature"]["page_no"] = 99
        path = self.root / "source_labels.json"
        original = json.dumps(cache).encode("utf-8")
        path.write_bytes(original)
        loaded = observations._load_visible_label_cache(
            str(self.root / "bound"), {"visible_labels_path": str(path)}
        )
        filtered = observations._filter_visible_label_cache_for_structures(
            loaded, structures
        )
        self.assertEqual(filtered, {"S1": cache["S1"]})
        self.assertEqual(loaded, cache)
        self.assertEqual(path.read_bytes(), original)

    def test_cached_exact_suffix_cannot_supply_a_missing_original_diagram(self):
        structure = self._structure()
        bindings, issues, ocr, _ = self._select(
            [structure], {"S1": self._cache_entry(structure, ["42A"])}
        )
        self.assertEqual(bindings, [], "The retained fixture crop is blank")
        self.assertEqual([row["cpd"] for row in issues], ["Compound 42A"])
        ocr.assert_not_called()

    def test_duplicate_exact_crops_are_withheld_instead_of_ranked(self):
        structures = [self._structure(), self._structure("S2", x0=280.0)]
        cache = {row["id"]: self._cache_entry(row, ["42A"]) for row in structures}
        bindings, issues, ocr, _ = self._select(structures, cache)
        self.assertEqual(bindings, [])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["reason"], "ambiguous_or_unproved_original_heading")
        ocr.assert_not_called()

    def test_missing_parent_competing_and_weak_labels_cannot_prove_ownership(self):
        structure = self._structure()
        cases = [
            ([], "page_strict"),
            (["42"], "page_strict"),
            (["42B"], "page_strict"),
            (["42A", "42B"], "page_strict"),
            (["42A"], "page_wide"),
        ]
        for labels, source in cases:
            with self.subTest(labels=labels, source=source):
                bindings, issues, ocr, _ = self._select(
                    [structure],
                    {"S1": self._cache_entry(structure, labels, source)},
                )
                self.assertEqual(bindings, [])
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]["cpd"], "Compound 42A")
                ocr.assert_not_called()

    def test_stale_signature_cannot_supply_heading_owner_or_replace_cache(self):
        structure = self._structure()
        stale = self._cache_entry(structure, ["42A"])
        stale["structure_signature"]["page_no"] = 99
        cache = {"S1": stale}
        bindings, issues, ocr, path = self._select([structure], cache)
        self.assertEqual(bindings, [])
        self.assertEqual(len(issues), 1)
        ocr.assert_not_called()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), cache)

    def test_page_observation_refines_suffix_without_model_calls(self):
        structure = self._structure()
        bindings, issues, ocr, path = self._select(
            [structure],
            {"S1": self._cache_entry(structure, ["42"])},
            {0: [(210.0, "Compound 42A")]},
        )
        self.assertEqual(
            bindings, [], "Refining a cached label cannot create a diagram"
        )
        self.assertEqual([row["cpd"] for row in issues], ["Compound 42A"])
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))["S1"]["visible_labels"],
            ["42A"],
        )
        ocr.assert_not_called()


class PlotLegendHeadingTests(unittest.TestCase):
    @staticmethod
    def document(
        *, caption=True, ticks=True, axes=True, marker=True, label="Compound 77A"
    ):
        document = fitz.open()
        page = document.new_page(width=520, height=420)
        if axes:
            page.draw_line((100, 90), (100, 250), width=0.8)
            page.draw_line((100, 250), (290, 250), width=0.8)
        if ticks:
            for x, value in zip((100, 160, 220, 280), ("0.01", "0.1", "1", "10")):
                page.insert_text((x - 6, 267), value, fontsize=9)
            for y, value in zip((110, 170, 230), ("100", "50", "0")):
                page.insert_text((75, y + 3), value, fontsize=9)
        if marker:
            page.draw_line((310, 119), (326, 119), width=1)
            page.draw_circle((318, 119), 2, fill=(0, 0, 0))
        page.insert_text((332, 122), label, fontsize=10)
        if caption:
            page.insert_text((180, 300), "FIG. 3B", fontsize=10)
        return document

    def test_quantitative_plot_legend_is_a_source_reference_not_a_missing_structure(
        self,
    ):
        with self.document() as document:
            sections = []
            blocks = observed_heading_blocks(
                document, [0], {}, source_sections=sections, source_regions={0: []}
            )
        self.assertEqual(blocks, [], "A plot legend does not declare a new structure")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["role"], "figure_label_reference")
        self.assertEqual(sections[0]["line_text"], "Compound 77A")

    def test_numbers_and_a_figure_caption_without_observed_axes_do_not_exempt(self):
        with self.document(axes=False) as document:
            sections = []
            blocks = observed_heading_blocks(
                document, [0], {}, source_sections=sections, source_regions={0: []}
            )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(sections[0]["role"], "unproved_heading")
        self.assertEqual(sections[0]["status"], "unresolved")
        self.assertEqual(blocks[0]["cpd"], "Compound 77A")

    def test_no_axes_and_no_unexplained_marker_keeps_a_complete_native_heading(self):
        with self.document(axes=False, marker=False) as document:
            sections = []
            blocks = observed_heading_blocks(
                document, [0], {}, source_sections=sections, source_regions={0: []}
            )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(sections[0]["role"], "compound_heading")
        self.assertEqual(sections[0]["status"], "confirmed")

    def observed(self):
        with self.document() as document:
            sections = []
            observed_heading_blocks(
                document, [0], {}, source_sections=sections, source_regions={0: []}
            )
        return json.loads(json.dumps(sections))

    def test_ordinary_titles_and_unproved_graphs_keep_original_structure_obligations(
        self,
    ):
        for options in (
            {"caption": False},
            {"ticks": False},
            {"marker": False},
            {"label": "Compound 77A: Synthesis"},
        ):
            with self.subTest(options=options), self.document(**options) as document:
                blocks = observed_heading_blocks(
                    document, [0], {}, source_regions={0: []}
                )
                self.assertEqual([b["cpd"] for b in blocks], ["Compound 77A"])

    def test_nearby_true_synthesis_heading_is_not_closed_by_the_figure_reference(self):
        with self.document() as document:
            document[0].insert_text(
                (50, 360), "Compound 008B: Preparation", fontsize=11
            )
            sections = []
            blocks = observed_heading_blocks(
                document, [0], {}, source_sections=sections, source_regions={0: []}
            )
        self.assertEqual([b["cpd"] for b in blocks], ["Compound 008B"])
        payload = {
            "source_sections": sections,
            "source_reference_scope": reference_scope(sections),
        }
        self.assertEqual(
            [p["cpd"] for p in reference_issues(payload, [])], ["Compound 008B"]
        )

    def test_saved_figure_reference_uses_the_existing_inventory_and_round_trip(self):
        sections = self.observed()
        payload = {
            "source_sections": sections,
            "source_reference_scope": reference_scope(sections),
        }
        self.assertEqual(reference_issues(payload, []), [])
        payload["source_reference_scope"]["heading_ids"] = []
        with self.assertRaises(ValueError):
            reference_issues(payload, [])

    def test_serialized_conflicts_omissions_and_pixel_corruption_cannot_grant_a_role(
        self,
    ):
        baseline = self.observed()[0]["heading_observation"]
        self.assertIsNotNone(proved_heading_declaration(baseline))
        mutations = []
        missing = copy.deepcopy(baseline)
        missing["figure_source"]["literal_cells"].pop()
        mutations.append(missing)
        changed = copy.deepcopy(baseline)
        changed["figure_source"]["axes"]["x"].reverse()
        mutations.append(changed)
        changed = copy.deepcopy(baseline)
        changed["nomination"]["text"] = "Compound 77B"
        mutations.append(changed)
        changed = copy.deepcopy(baseline)
        changed["figure_source"]["chunks"] = []
        mutations.append(changed)
        changed = copy.deepcopy(baseline)
        changed["figure_source"]["axis_strokes"]["x"]["readings"][0]["mask_hex"] = "00"
        mutations.append(changed)
        changed = copy.deepcopy(baseline)
        changed["figure_source"]["marker"]["readings"][1]["dpi"] = True
        mutations.append(changed)
        changed = copy.deepcopy(baseline)
        changed["figure_source"]["literal_cells"][0]["reading"]["observations"][0][
            "matrix"
        ][0][0] = "FIG. 4"
        mutations.append(changed)
        changed = copy.deepcopy(baseline)
        changed["figure_source"]["axes"]["x"][0]["role_scope"] = "compound"
        mutations.append(changed)
        for index, proof in enumerate(mutations):
            with self.subTest(mutation=index):
                proof["status"] = "confirmed"
                self.assertIsNone(proved_heading_declaration(proof))

    def test_real_scanned_plot_uses_existing_cell_ocr_and_preserves_saved_source(self):
        with self.document() as original, fitz.open() as scanned:
            lines = [
                {**line, "source": "page_ocr"}
                for line in original_heading_lines(original[0])
            ]
            page = scanned.new_page(width=520, height=420)
            page.insert_image(
                page.rect,
                stream=original[0].get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png"),
            )
            sections = []
            blocks = observed_heading_blocks(
                scanned,
                [0],
                {},
                source_sections=sections,
                source_regions={0: []},
                source_line_map={0: lines},
                tokens_for_page=lambda page: page_tokens(
                    page, dpi=300, allow_tesseract=False
                ),
            )
        details = [
            {
                "role": section["role"],
                "status": section["status"],
                "cells": [
                    {
                        "sources": [p["text"] for p in cell["sources"]],
                        "reads": [
                            r["matrix"]
                            for r in (cell["reading"] or {}).get("observations", [])
                        ],
                    }
                    for cell in section["heading_observation"]
                    .get("figure_source", {})
                    .get("literal_cells", [])
                ],
            }
            for section in sections
        ]
        self.assertFalse(bool(blocks), details)
        self.assertEqual(sections[0]["role"], "figure_label_reference")
        proof = json.loads(json.dumps(sections[0]["heading_observation"]))
        self.assertIsNotNone(proved_heading_declaration(proof))
        self.assertEqual(
            len(proof["figure_source"]["literal_cells"][0]["reading"]["observations"]),
            2,
        )

    def test_hidden_native_conflict_in_a_raster_legend_is_not_an_exemption(self):
        with self.document() as original, fitz.open() as scanned:
            lines = [
                {**line, "source": "page_ocr"}
                for line in original_heading_lines(original[0])
            ]
            page = scanned.new_page(width=520, height=420)
            page.insert_image(
                page.rect,
                stream=original[0].get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png"),
            )
            page.insert_text((332, 122), "Compound 77B", fontsize=10, render_mode=3)
            sections = []
            blocks = observed_heading_blocks(
                scanned,
                [0],
                {},
                source_sections=sections,
                source_regions={0: []},
                source_line_map={0: lines},
                tokens_for_page=lambda page: page_tokens(
                    page, dpi=300, allow_tesseract=False
                ),
            )
        self.assertEqual(len(blocks), 1)
        self.assertTrue(all(s["role"] == "unproved_heading" for s in sections))


if __name__ == "__main__":
    unittest.main()
