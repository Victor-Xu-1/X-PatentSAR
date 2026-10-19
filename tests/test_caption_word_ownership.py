"""Original word boundaries must precede a caption's bare/prefixed form."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz
import numpy as np

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_original_replay import (
    original_caption_source_errors,
)
from patent_sar_extractor.core.caption_word_geometry import caption_word_partitions
from patent_sar_extractor.core.caption_word_proof import _selected_partition
from patent_sar_extractor.core.compound_caption import prefixed_label
from patent_sar_extractor.core.ocsr.label_mask import _caption_box
from patent_sar_extractor.core.table_geometry import (
    detect_ruled_table_regions,
    page_tokens,
)
from tests.test_caption_nomination_forms import formal_binding
from tests.test_caption_role_raster import raster_catalog


def merged_role_hints(tokens, grid):
    """Simulate a page detector merging role+ID; don't change original pixels."""
    tokens = copy.deepcopy(tokens)
    remove = set()
    for x0, x1 in zip(grid["xs"][:-1], grid["xs"][1:], strict=True):
        indices = [
            i
            for i, t in enumerate(tokens)
            if x0 <= t["x"] < x1 and grid["ys"][0] <= t["y"] < grid["ys"][1]
        ]
        assert indices
        parts = [tokens[i] for i in indices]
        label = prefixed_label(
            " ".join(t["text"] for t in sorted(parts, key=lambda t: t["x"]))
        )
        assert label
        box = [
            min(t["bbox"][0] for t in parts),
            min(t["bbox"][1] for t in parts),
            max(t["bbox"][2] for t in parts),
            max(t["bbox"][3] for t in parts),
        ]
        tokens[indices[0]].update(
            text="Nominated" + label,
            bbox=box,
            x=(box[0] + box[2]) / 2,
            y=(box[1] + box[3]) / 2,
            confidence=0.99,
            confidence_available=True,
            confidence_valid=True,
        )
        remove.update(indices[1:])
    tokens[:] = [t for i, t in enumerate(tokens) if i not in remove]
    return tokens


class CaptionWordOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document, structures, boxes = raster_catalog(prefixed=True)
        page = cls.document[0]
        grids = detect_ruled_table_regions(page, dpi=240)
        cls.tokens = merged_role_hints(
            page_tokens(page, dpi=200, allow_tesseract=False), grids[0]
        )
        cls.result = bind_caption_grids(
            cls.document,
            structures,
            boxes,
            [1],
            grids_for_page=lambda _p: grids,
            tokens_for_page=lambda _p: cls.tokens,
        )
        cls.bindings = [formal_binding(pair) for pair in cls.result.bindings]

    @classmethod
    def tearDownClass(cls):
        cls.document.close()

    def test_complete_original_word_form_prevents_a_merged_role_becoming_bare_id(self):
        self.assertEqual(
            [p["label"] for p in self.result.bindings],
            ["I-004A", "I-009B"],
            [i["reason"] for i in self.result.issues],
        )
        self.assertFalse(self.result.issues)
        self.assertTrue(
            all("identifier_form" not in p["ownership"] for p in self.result.bindings)
        )

    def test_saved_form_keeps_page_hint_and_both_full_and_word_source_readings(self):
        self.assertEqual(len(self.bindings), 2)
        for original in self.bindings:
            binding = json.loads(json.dumps(original))
            self.assertTrue(valid_caption_binding_evidence(binding))
            observations = binding["exact_caption_evidence"]["observations"]
            self.assertEqual(len(observations), 4)
            self.assertTrue(observations[0]["text"].startswith("Nominated"))
            self.assertEqual(
                [r["method"] for r in observations[1:3]],
                ["cell_ocr_400dpi", "cell_ocr_600dpi"],
            )
            self.assertEqual(observations[3]["method"], "caption_word_form")
            self.assertEqual(
                original_caption_source_errors(self.document, [binding]), []
            )

    def test_form_proof_cannot_be_removed_or_turned_into_bare_ownership(self):
        self.assertTrue(self.bindings)
        for mode in ("strip", "bare", "unknown_role", "changed_id", "wrong_scope"):
            with self.subTest(mode=mode):
                binding = copy.deepcopy(self.bindings[0])
                packet = binding["exact_caption_evidence"]
                if mode == "strip":
                    packet["observations"].pop()
                elif mode == "bare":
                    packet["ownership"]["identifier_form"] = "bare"
                elif mode == "unknown_role":
                    packet["ownership"]["caption_role"]["role"] = "unknown"
                elif mode == "changed_id":
                    binding["cpd"] = "Compound I-099Z"
                else:
                    packet["observations"][-1]["caption_word_form"]["bbox"][2] += 1
                self.assertFalse(valid_caption_binding_evidence(binding))

    def test_word_proof_never_overrules_native_or_complete_prefixed_conflicts(self):
        self.assertTrue(self.bindings)
        for method, text in (
            ("page_ocr_cell", "Compound I-099Z"),
            ("page_ocr_cell", "NominatedI-004Z"),
            ("page_ocr_cell", "Intermediate I-004A"),
            ("native_cell", "NominatedI-004A"),
        ):
            with self.subTest(method=method, text=text):
                binding = copy.deepcopy(self.bindings[0])
                observation = binding["exact_caption_evidence"]["observations"][0]
                observation["method"] = method
                observation["text"] = text
                source = observation["source_observation"]
                source["text"] = text
                source["tokens"][0]["text"] = text
                if method == "native_cell":
                    source["origin"] = source["tokens"][0]["source"] = "native"
                    source["tokens"][0]["confidence"] = 1
                self.assertFalse(valid_caption_binding_evidence(binding))

    def test_original_readback_rejects_changed_pixels_even_after_proof_rehash(self):
        self.assertTrue(self.bindings)
        changed = copy.deepcopy(self.bindings[0])
        proof = changed["exact_caption_evidence"]["observations"][-1][
            "caption_word_form"
        ]
        proof["readings"][0]["partitions"][0]["words"][0]["pixel_sha256"] = "f" * 64
        self.assertTrue(valid_caption_binding_evidence(changed))
        self.assertTrue(original_caption_source_errors(self.document, [changed]))

    def test_every_raster_caption_requires_actual_original_cell_frames(self):
        self.assertTrue(self.bindings)
        changed = copy.deepcopy(self.bindings[0])
        for reading in changed["exact_caption_evidence"]["observations"][1:3]:
            del reading["source_frame"]
        self.assertFalse(valid_caption_binding_evidence(changed))
        self.assertTrue(original_caption_source_errors(self.document, [changed]))

    def test_a_single_word_page_box_does_not_get_role_word_scope(self):
        self.assertTrue(self.bindings)
        changed = copy.deepcopy(self.bindings[0])
        reading = changed["exact_caption_evidence"]["observations"][0]
        token = reading["source_observation"]["tokens"][0]
        token["bbox"][0] = token["x"]
        token["x"] = (token["bbox"][0] + token["bbox"][2]) / 2
        self.assertFalse(valid_caption_binding_evidence(changed))

    def test_all_source_partitions_are_retained_not_truncated_to_a_matching_cut(self):
        self.assertTrue(self.bindings)
        changed = copy.deepcopy(self.bindings[0])
        proof = changed["exact_caption_evidence"]["observations"][-1][
            "caption_word_form"
        ]
        proof["readings"][0]["partitions"].append(
            copy.deepcopy(proof["readings"][0]["partitions"][0])
        )
        self.assertFalse(valid_caption_binding_evidence(changed))

    def test_invalid_word_confidences_masks_frames_and_versions_are_not_proofs(self):
        self.assertTrue(self.bindings)
        for fault in (
            "confidence",
            "mask",
            "source_frame",
            "version",
            "word_id",
            "status",
        ):
            with self.subTest(fault=fault):
                changed = copy.deepcopy(self.bindings[0])
                observations = changed["exact_caption_evidence"]["observations"]
                packet = observations[-1]["caption_word_form"]
                if fault == "confidence":
                    packet["readings"][0]["partitions"][0]["words"][0]["confidence"] = (
                        True
                    )
                elif fault == "mask":
                    packet["readings"][0]["pixels"]["mask_hex"] += "00"
                elif fault == "source_frame":
                    observations[1]["source_frame"]["pixel_sha256"] = "f" * 64
                elif fault == "version":
                    packet["version"] = True
                elif fault == "word_id":
                    packet["readings"][0]["partitions"][0]["words"][1]["text"] = (
                        "I-099Z"
                    )
                else:
                    packet["status"] = "unresolved"
                self.assertFalse(valid_caption_binding_evidence(changed))

    def test_excess_pixel_or_partition_sources_refuse_without_clipping(self):
        self.assertIsNone(
            caption_word_partitions(np.zeros((1001, 1000), dtype=bool), 400)
        )
        mask = np.zeros((40, 500), dtype=bool)
        for left in range(0, 350, 50):
            mask[10:30, left : left + 10] = True
        self.assertIsNone(caption_word_partitions(mask, 400))

    def test_dense_font_and_numeric_suffix_catalogues_keep_literal_ids(self):
        for height, font in ((14, "hebo"), (15, "helv"), (22, "tiro")):
            with self.subTest(height=height, font=font):
                document, structures, boxes = raster_catalog(
                    prefixed=True,
                    labels=("53Q", "0061", "I-009B"),
                    label_height=height,
                    label_fontname=font,
                )
                with document:
                    grids = detect_ruled_table_regions(document[0], dpi=240)
                    tokens = merged_role_hints(
                        page_tokens(document[0], dpi=200, allow_tesseract=False),
                        grids[0],
                    )
                    result = bind_caption_grids(
                        document,
                        structures,
                        boxes,
                        [1],
                        grids_for_page=lambda p, grids=grids: grids,
                        tokens_for_page=lambda p, tokens=tokens: tokens,
                    )
                    self.assertEqual(
                        [p["label"] for p in result.bindings],
                        ["53Q", "0061", "I-009B"],
                        [i["reason"] for i in result.issues],
                    )
                    self.assertFalse(result.issues)
                    self.assertEqual(
                        original_caption_source_errors(
                            document, [formal_binding(p) for p in result.bindings]
                        ),
                        [],
                    )

    def test_two_literal_matching_partitions_are_not_ranked_by_confidence(self):
        expected = [
            [[0, 0, 40, 20], [50, 0, 100, 20]],
            [[0, 0, 50, 20], [60, 0, 100, 20]],
        ]
        observed = [
            {
                "words": [
                    {
                        "bbox": box,
                        "text": text,
                        "confidence": score,
                        "pixel_sha256": "a" * 64,
                    }
                    for box, text in zip(boxes, ("Compound", "I-004A"), strict=True)
                ]
            }
            for boxes, score in zip(expected, (0.9, 0.99), strict=True)
        ]
        self.assertIsNone(_selected_partition(observed, expected, "Compound", "I-004A"))

    def test_actual_original_change_is_rejected_without_ocr_or_saved_flag_updates(self):
        self.assertTrue(self.bindings)
        with fitz.open(stream=self.document.tobytes(), filetype="pdf") as changed:
            bounds = self.bindings[0]["exact_caption_evidence"]["bbox"]
            changed[0].draw_rect(
                fitz.Rect(bounds[0] + 20, bounds[1] + 4, bounds[2] - 20, bounds[3] - 4),
                fill=(0, 0, 0),
            )
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Readback must not infer text"),
            ):
                self.assertTrue(
                    original_caption_source_errors(changed, [self.bindings[0]])
                )

    def test_ordinary_raster_caption_also_requires_its_current_original_frame(self):
        document, structures, boxes = raster_catalog(prefixed=True)
        with document:
            result = bind_caption_grids(document, structures, boxes, [1])
            self.assertFalse(result.issues)
            binding = formal_binding(result.bindings[0])
            self.assertEqual(original_caption_source_errors(document, [binding]), [])
            for observation in binding["exact_caption_evidence"]["observations"]:
                observation.pop("source_frame", None)
            self.assertTrue(valid_caption_binding_evidence(binding))
            self.assertTrue(original_caption_source_errors(document, [binding]))

    def test_malformed_saved_observation_is_refused_without_crashing_the_reader(self):
        self.assertTrue(self.bindings)
        for value in (None, True, 4, "unknown"):
            with self.subTest(value=value):
                binding = copy.deepcopy(self.bindings[0])
                binding["exact_caption_evidence"]["observations"][0] = value
                self.assertFalse(valid_caption_binding_evidence(binding))

    def test_input_preparation_uses_the_same_caption_budget_not_a_second_limit(self):
        self.assertTrue(self.bindings)
        binding = copy.deepcopy(self.bindings[0])
        frame = {
            "bbox": [0, 0, 400, 400],
            "image_size": [800, 800],
            "image_sha256": "a" * 64,
            "coordinate_space": "original_pdf_points",
            "page_no": 1,
            "structure_id": binding["structure_id"],
        }
        self.assertIsNotNone(
            _caption_box(binding, "I-004A", frame, (800, 800), "a" * 64)
        )
        binding["exact_caption_evidence"]["observations"].pop()
        self.assertIsNone(_caption_box(binding, "I-004A", frame, (800, 800), "a" * 64))


if __name__ == "__main__":
    unittest.main()
