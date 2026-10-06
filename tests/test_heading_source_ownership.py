"""Controlled heading ownership through the retained cache path, without models."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
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
from patent_sar_extractor.core import binding_ocr, page_ocr_cache
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

        def empty_ocr(images, **_kwargs):
            # Controlled observations only; no OCR backend is invoked.
            return [[] for _ in images]

        with (
            self._document() as document,
            patch.object(
                observations, "_paddlex_ocr_texts_batch", side_effect=empty_ocr
            ) as ocr,
            patch.object(observations, "paddlex_available", return_value=False),
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
        structure.pop("source_pdf_sha256")
        with ExitStack() as stack:
            crop_work = self._forbid_crop_work(stack)
            availability = stack.enter_context(
                patch.object(
                    observations,
                    "paddlex_available",
                    side_effect=AssertionError("unsigned source"),
                )
            )
            result = observations._precompute_visible_label_cache(
                [structure], str(self.root / "bound"), {}, {}, workers=1
            )
        self.assertEqual(result, {})
        self.assertFalse((self.root / "bound").exists())
        availability.assert_not_called()
        for work in crop_work:
            work.assert_not_called()

    def test_cache_replace_failure_preserves_existing_bytes(self):
        structure = self._structure()
        path = self.root / "visible_labels.json"
        original = b'{"retained": "original cache bytes"}'
        path.write_bytes(original)
        with (
            patch.object(observations, "paddlex_available", return_value=True),
            patch.object(
                observations,
                "_paddlex_ocr_url",
                return_value="http://127.0.0.1:8090/ocr",
            ),
            patch.object(
                observations,
                "_visible_label_crop_tasks_from_page_image",
                return_value=[("page_strict", object())],
            ),
            patch.object(
                observations,
                "_visible_label_crop_tasks_from_structure_image",
                side_effect=AssertionError("strict result already observed"),
            ),
            patch.object(
                observations, "_paddlex_ocr_texts_batch", return_value=[["42A"]]
            ),
            patch(
                "patent_sar_extractor.artifact_io.os.replace",
                side_effect=OSError("controlled replace failure"),
            ),
        ):
            result = observations._precompute_visible_label_cache(
                [structure],
                str(self.root / "bound"),
                {"visible_labels_path": str(path)},
                {},
                workers=1,
            )
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(result["S1"]["visible_labels"], ["42A"])
        self.assertFalse(list(self.root.glob(f".{path.name}.*.tmp")))

    def _precompute_inputs(self):
        structures = [self._structure(), self._structure("S2"), self._structure("S3")]
        valid = self._cache_entry(structures[0], ["42A"])
        stale = self._cache_entry(structures[1], ["42B"])
        stale["structure_signature"]["page_no"] = 99
        return structures, {"S1": valid, "S2": stale}

    @staticmethod
    def _forbid_crop_work(stack):
        return [
            stack.enter_context(
                patch.object(
                    observations,
                    name,
                    side_effect=AssertionError("Disabled OCR must not render or batch"),
                )
            )
            for name in (
                "_visible_label_crop_tasks_from_page_image",
                "_visible_label_crop_tasks_from_structure_image",
                "_paddlex_ocr_texts_batch",
            )
        ]

    def test_explicitly_off_paddlex_returns_validated_cache_before_crop_work(self):
        structures, cache = self._precompute_inputs()
        path = self.root / "existing_labels.json"
        original = json.dumps(cache).encode("utf-8")
        path.write_bytes(original)
        for disabled in ("off", " OFF ", "none", "0"):
            for availability in (None, True, False):
                with self.subTest(url=disabled, availability=availability):
                    with ExitStack() as stack:
                        stack.enter_context(
                            patch.dict(
                                os.environ, {"PATENTSAR_PADDLEX_OCR_URL": disabled}
                            )
                        )
                        stack.enter_context(
                            patch.object(
                                binding_ocr, "_PADDLEX_OCR_AVAILABLE", availability
                            )
                        )
                        probe = stack.enter_context(
                            patch.object(
                                page_ocr_cache,
                                "_paddlex_endpoint_accepts_payload",
                                side_effect=AssertionError(
                                    "Explicit off must not probe"
                                ),
                            )
                        )
                        crop_work = self._forbid_crop_work(stack)
                        result = observations._precompute_visible_label_cache(
                            structures,
                            str(self.root / "bindings"),
                            {"visible_labels_path": str(path)},
                            cache,
                            workers=1,
                        )
                    self.assertEqual(result, {"S1": cache["S1"]})
                    self.assertEqual(path.read_bytes(), original)
                    self.assertFalse((self.root / "bindings").exists())
                    probe.assert_not_called()
                    for work in crop_work:
                        work.assert_not_called()

    def test_known_unavailable_paddlex_skips_url_resolution_and_crop_work(self):
        structures, cache = self._precompute_inputs()
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(binding_ocr, "_PADDLEX_OCR_AVAILABLE", False)
            )
            resolve = stack.enter_context(
                patch.object(
                    binding_ocr,
                    "_shared_paddlex_ocr_url",
                    side_effect=AssertionError("Known unavailable must not resolve"),
                )
            )
            crop_work = self._forbid_crop_work(stack)
            result = observations._precompute_visible_label_cache(
                structures, str(self.root / "bindings"), {}, cache, workers=1
            )
        self.assertEqual(result, {"S1": cache["S1"]})
        self.assertFalse((self.root / "visible_labels").exists())
        resolve.assert_not_called()
        for work in crop_work:
            work.assert_not_called()

    def test_empty_paddlex_setting_keeps_existing_endpoint_discovery(self):
        structure = self._structure()
        path = self.root / "new_labels.json"
        with (
            patch.dict(os.environ, {"PATENTSAR_PADDLEX_OCR_URL": ""}),
            patch.object(page_ocr_cache, "_PADDLEX_OCR_PROBED", False),
            patch.object(page_ocr_cache, "_PADDLEX_OCR_URL_RESOLVED", None),
            patch.object(
                page_ocr_cache, "_paddlex_endpoint_accepts_payload", return_value=True
            ) as probe,
            patch.object(observations, "paddlex_available", side_effect=[None, True]),
            patch.object(
                observations,
                "_visible_label_crop_tasks_from_page_image",
                return_value=[("page_strict", object())],
            ) as page_crops,
            patch.object(
                observations,
                "_visible_label_crop_tasks_from_structure_image",
                side_effect=AssertionError(
                    "Strict evidence needs no wide/direct crops"
                ),
            ) as structure_crops,
            patch.object(
                observations, "_paddlex_ocr_texts_batch", return_value=[["42A"]]
            ) as batch,
        ):
            result = observations._precompute_visible_label_cache(
                [structure],
                str(self.root / "bindings"),
                {"visible_labels_path": str(path)},
                {},
                workers=1,
            )
        probe.assert_called_once_with("http://127.0.0.1:8090/ocr")
        page_crops.assert_called_once_with(structure, include_wide=False)
        structure_crops.assert_not_called()
        batch.assert_called_once()
        self.assertEqual(batch.call_args.kwargs, {"workers": 1, "timeout": 12.0})
        self.assertEqual(result["S1"]["visible_labels"], ["42A"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), result)

    def test_unavailable_endpoint_discovery_does_not_render_or_write(self):
        structures, cache = self._precompute_inputs()
        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(os.environ, {"PATENTSAR_PADDLEX_OCR_URL": ""})
            )
            stack.enter_context(
                patch.object(binding_ocr, "_PADDLEX_OCR_AVAILABLE", None)
            )
            stack.enter_context(
                patch.object(page_ocr_cache, "_PADDLEX_OCR_PROBED", False)
            )
            stack.enter_context(
                patch.object(page_ocr_cache, "_PADDLEX_OCR_URL_RESOLVED", None)
            )
            probe = stack.enter_context(
                patch.object(
                    page_ocr_cache,
                    "_paddlex_endpoint_accepts_payload",
                    return_value=False,
                )
            )
            crop_work = self._forbid_crop_work(stack)
            result = observations._precompute_visible_label_cache(
                structures, str(self.root / "bindings"), {}, cache, workers=1
            )
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(result, {"S1": cache["S1"]})
        self.assertFalse((self.root / "visible_labels").exists())
        for work in crop_work:
            work.assert_not_called()

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
