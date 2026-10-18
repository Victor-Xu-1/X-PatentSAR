"""Physical header bounds, failed reads and serialized evidence consumers."""

import copy
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from patent_sar_extractor.core.activity_header_columns import observe_header_columns
from patent_sar_extractor.core.activity_header_evidence import (
    proof_id,
    validate_header_evidence,
)
from patent_sar_extractor.core.activity_header_identity import detector_header_conflict
from patent_sar_extractor.core.cell_header_lines import header_line_frame
from patent_sar_extractor.core.cell_header_proof import physical_header_valid
from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.cell_ocr_scores import confidence_value
from patent_sar_extractor.core.cell_text_proof import valid_text_components
from patent_sar_extractor.core.cell_text_row_readings import row_recognition_border


def controlled_image(lines=3):
    image = np.full((lines * 55 + 10, 240, 3), 255, dtype=np.uint8)
    for index in range(lines):
        cv2.putText(
            image,
            "Header",
            (10, 30 + index * 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 0),
            1,
        )
    return image


def reading(scores=(0.99, 0.99, 0.99), returned=("Target", "IC50", "nM")):
    responses = [([], 0)]
    for text, score in zip(returned, scores, strict=True):
        responses.append(([[text, score]], 0))
        if confidence_value(score) is None or score < 0.85 or not text.strip():
            responses.append(([[text, score]], 0))
    engine = Mock(side_effect=responses)
    result = observe_cell(
        controlled_image(), "header", 400, engine, lambda text, kind: text.strip()
    )
    return result.evidence(400, [30, 40, 90, 85]), engine


def column_proof(column):
    column = {**column, "crosses_boundary": False, "detector_conflict": False}
    return {
        "status": "observed_header_consensus",
        "observations": [{"columns": [column]}],
    }


class HeaderPhysicalProofTests(unittest.TestCase):
    def test_single_short_header_keeps_both_original_views_not_a_guessed_value(self):
        engine = Mock(side_effect=[([["No.", 0.7]], 0), ([["No.", 0.99]], 0)])
        result = observe_cell(
            controlled_image(1), "header", 400, engine, lambda text, _: text.strip()
        )
        self.assertEqual(result.value, "No.")
        evidence = result.evidence(400, [30, 40, 90, 85])
        self.assertEqual(
            [row["confidence"] for row in evidence["single_row_readings"]], [0.7, 0.99]
        )
        self.assertEqual(engine.call_count, 2)
        self.assertTrue(valid_text_components(evidence, 400))
        for mutate in (
            lambda item: item["single_row_readings"].reverse(),
            lambda item: item["single_row_readings"].pop(0),
            lambda item: item["single_row_readings"][0].update(confidence=0.99),
            lambda item: item["single_row_readings"][1].update(border_pixels=31),
            lambda item: item.update(
                detection_parts=[{"text": "Foreign", "confidence": 0.99}]
            ),
        ):
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(evidence)
                mutate(changed)
                self.assertFalse(valid_text_components(changed, 400))

    def test_invalid_compact_view_policy_is_rejected_without_model_calls(self):
        for height, border in (
            (True, 8),
            (0, 8),
            (-1, 8),
            (1068, 8),
            (20, True),
            (20, 0),
            (20, 33),
        ):
            with (
                self.subTest(height=height, border=border),
                self.assertRaises(ValueError),
            ):
                row_recognition_border(height, border)

    def test_only_weak_original_row_gets_one_compact_view_and_keeps_both_reads(self):
        engine = Mock(
            side_effect=[
                ([], 0),
                ([["Target", 0.99]], 0),
                ([["IC5O", 0.65]], 0),
                ([["IC50", 0.99]], 0),
                ([["nM", 0.99]], 0),
            ]
        )
        observed = observe_cell(
            controlled_image(), "header", 400, engine, lambda text, _: text.strip()
        )
        evidence = observed.evidence(400, [30, 40, 90, 85])
        self.assertTrue(physical_header_valid(evidence))
        self.assertEqual(evidence["raw_text"], "Target\nIC50\nnM")
        readings = evidence["physical_header_lines"]["row_readings"]
        self.assertEqual(list(map(len, readings)), [1, 2, 1])
        self.assertEqual([reading["text"] for reading in readings[1]], ["IC5O", "IC50"])
        self.assertEqual(engine.call_count, 5)
        row = evidence["physical_header_lines"]["row_bounds"][1]
        tight = row_recognition_border(row[3] - row[1], evidence["border_pixels"])
        self.assertEqual(readings[1][1]["border_pixels"], tight)
        self.assertEqual(
            engine.call_args_list[3].args[0].shape[:2],
            (row[3] - row[1] + 2 * tight, row[2] - row[0] + 2 * tight),
        )
        for mutate in (
            lambda packet: packet["row_readings"][1].pop(0),
            lambda packet: packet["row_readings"][1].append(
                dict(packet["row_readings"][1][-1])
            ),
            lambda packet: packet["row_readings"][0].append(
                dict(packet["row_readings"][0][0])
            ),
            lambda packet: packet["row_readings"][1][0].update(confidence=0.99),
        ):
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(evidence)
                mutate(changed["physical_header_lines"])
                self.assertFalse(physical_header_valid(changed))

    def test_malformed_row_keeps_later_original_rows_without_a_successful_prefix(self):
        engine = Mock(
            side_effect=[
                ([], 0),
                (None, 0),
                ([], 0),
                ([["IC50", 0.99]], 0),
                ([["nM", 0.99]], 0),
            ]
        )
        result = observe_cell(
            controlled_image(), "header", 400, engine, lambda text, _: text.strip()
        )
        self.assertEqual(result.value, "")
        self.assertEqual([part["text"] for part in result.parts], ["", "IC50", "nM"])
        self.assertEqual(
            list(map(len, result.physical_header_lines["row_readings"])), [2, 1, 1]
        )
        self.assertFalse(physical_header_valid(result.evidence(400, [30, 40, 90, 85])))

    def test_render_limit_precedes_engine_and_page_rendering(self):
        for region, dpi in (
            ({"xs": [0, 90000, 91000], "ys": [0, 150]}, 600),
            ({"xs": [0, True, 120], "ys": [0, 80]}, 400),
            ({"xs": [0, 60, 120], "ys": [0, 80]}, True),
        ):
            page = Mock()
            with (
                self.subTest(region=region, dpi=dpi),
                patch(
                    "patent_sar_extractor.core.activity_header_columns.get_ocr_engine"
                ) as engine,
                self.assertRaises(ValueError),
            ):
                observe_header_columns(page, region, 1, dpi)
            engine.assert_not_called()
            page.get_pixmap.assert_not_called()

    def test_every_pixel_row_is_read_once_and_unit_remains_a_line(self):
        result, engine = reading()
        self.assertTrue(physical_header_valid(result))
        self.assertEqual(result["raw_text"], "Target\nIC50\nnM")
        self.assertEqual(engine.call_count, 4)
        packet = result["physical_header_lines"]
        self.assertEqual(packet["version"], 2)
        for call, row, readings in zip(
            engine.call_args_list[1:],
            packet["row_bounds"],
            packet["row_readings"],
            strict=True,
        ):
            self.assertEqual(len(readings), 1)
            border = readings[0]["border_pixels"]
            self.assertEqual(border, result["border_pixels"])
            self.assertEqual(
                call.args[0].shape[:2],
                (row[3] - row[1] + 2 * border, row[2] - row[0] + 2 * border),
            )
        self.assertTrue(engine.call_args_list[0].kwargs["use_det"])
        self.assertTrue(
            all(not call.kwargs["use_det"] for call in engine.call_args_list[1:])
        )
        proof = column_proof(result)
        self.assertEqual(
            validate_header_evidence({"header_observations": {proof_id(proof): proof}}),
            [],
        )

    def test_low_or_malformed_line_score_preserves_raw_without_qualification(self):
        for score in (0.2, True, "0.99", None, float("nan")):
            with self.subTest(score=score):
                result, _ = reading(scores=(0.99, score, 0.99))
                self.assertEqual(result["raw_text"], "Target\nIC50\nnM")
                self.assertEqual(result["text"], "")
                self.assertFalse(physical_header_valid(result))

    def test_overbound_rows_cannot_borrow_a_plausible_detector_read(self):
        engine = Mock(
            return_value=(
                [[[[3, 3], [160, 3], [160, 440], [3, 440]], "IC50 (nM)", 0.99]],
                0,
            )
        )
        result = observe_cell(
            controlled_image(9), "header", 400, engine, lambda text, kind: text
        )
        self.assertEqual(result.value, "")
        self.assertEqual(engine.call_count, 1)
        self.assertEqual(result.detection_parts[0]["text"], "IC50 (nM)")

    def test_invalid_frame_is_rejected_before_line_ocr(self):
        for dpi, border, image in (
            (True, 8, controlled_image()),
            (300, 8, controlled_image()),
            (400, True, controlled_image()),
            (400, 8, np.zeros((3, 3), dtype=np.uint8)),
            (400, 8, np.zeros((3000, 3000, 3), dtype=np.uint8)),
        ):
            with (
                self.subTest(dpi=dpi, border=border, shape=image.shape),
                self.assertRaises(ValueError),
            ):
                header_line_frame(image, border, dpi)

    def test_valid_detector_unit_endpoint_and_target_conflicts_are_not_outvoted(self):
        for old, fresh in (
            ("IC50 (uM)", "IC50 (nM)"),
            ("EC50 (nM)", "IC50 (nM)"),
            ("BRD4 IC50 (nM)", "BRD9 IC50 (nM)"),
            ("nM", "pM"),
        ):
            with self.subTest(old=old, fresh=fresh):
                self.assertTrue(
                    detector_header_conflict([{"text": old, "confidence": 0.99}], fresh)
                )
        self.assertFalse(
            detector_header_conflict(
                [
                    {"text": "Dmax", "confidence": 0.99},
                    {"text": "%", "confidence": 0.99},
                ],
                "Dmax %",
            )
        )

    def test_rehashed_geometry_missing_rows_or_cleared_conflicts_remain_rejected(self):
        result, _ = reading()
        mutations = (
            lambda column: column["physical_header_lines"].update(version=True),
            lambda column: column["physical_header_lines"]["row_bounds"][0].__setitem__(
                2, 9999
            ),
            lambda column: column["parts"].pop(),
            lambda column: column.pop("physical_header_lines"),
            lambda column: column.update(crosses_boundary=True),
            lambda column: column.update(detection_parts=[{"text": "EC50 (nM)"}]),
            lambda column: column.update(confidence=True),
            lambda column: column["physical_header_lines"]["row_readings"][0][0].update(
                border_pixels=True
            ),
            lambda column: column["physical_header_lines"]["row_readings"][0][0].update(
                border_pixels=31
            ),
            lambda column: column["physical_header_lines"].pop("row_readings"),
        )
        for mutate in mutations:
            proof = column_proof(copy.deepcopy(result))
            mutate(proof["observations"][0]["columns"][0])
            with (
                self.subTest(mutate=mutate),
                self.assertRaisesRegex(ValueError, "physical header"),
            ):
                validate_header_evidence(
                    {"header_observations": {proof_id(proof): proof}}
                )
