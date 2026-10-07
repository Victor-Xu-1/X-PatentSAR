"""Controlled heading ownership through the retained cache path, without models."""

from __future__ import annotations

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
            patch("patent_sar_extractor.core.heading_evidence.get_ocr_engine", ocr),
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

    def test_unique_exact_suffix_owner_is_confirmed_without_activity_filter(self):
        structure = self._structure()
        bindings, issues, ocr, _ = self._select(
            [structure], {"S1": self._cache_entry(structure, ["42A"])}
        )
        self.assertEqual(issues, [])
        self.assertEqual([row["cpd"] for row in bindings], ["Compound 42A"])
        self.assertEqual(bindings[0]["structure_id"], "S1")
        self.assertEqual(bindings[0]["accuracy_status"], "confirmed")
        self.assertFalse(bindings[0]["fail_closed"])
        self.assertEqual(
            bindings[0]["original_heading_evidence"]["cpd"], "Compound 42A"
        )
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
        self.assertEqual(issues, [])
        self.assertEqual([row["cpd"] for row in bindings], ["Compound 42A"])
        self.assertEqual(bindings[0]["visible_labels"], ["42A"])
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))["S1"]["visible_labels"],
            ["42A"],
        )
        ocr.assert_not_called()


if __name__ == "__main__":
    unittest.main()
