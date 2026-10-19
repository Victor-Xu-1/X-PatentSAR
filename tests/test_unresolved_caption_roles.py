"""An unresolved original catalogue cell is not a synthesis-heading occurrence."""

import copy
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_heading_label_roles as controls
from test_caption_source_roles import catalog as original_catalog

from patent_sar_extractor.core.binding_preparation import load_binding_input
from patent_sar_extractor.core.binding_source_diagnostics import (
    retain_binding_diagnostics,
)
from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_label_roles import (
    PENDING_ROLE,
    validate_caption_references,
)
from patent_sar_extractor.core.caption_pending_roles import (
    pending_caption_index,
    pending_caption_reference,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_evidence import original_heading_lines
from patent_sar_extractor.core.source_document import document_sha256
from patent_sar_extractor.core.source_role_observations import (
    RoleObservationBuffer,
    serialize_role_observations,
)
from patent_sar_extractor.core.table_cells import read_cell


class UnresolvedCaptionRoleTests(unittest.TestCase):
    def setUp(self):
        self.control = controls.HeadingLabelRoleTests(
            "test_full_binder_preserves_true_heading_but_reuses_exact_label_cell_roles"
        )
        self.control.setUp()
        self.addCleanup(self.control.doCleanups)

    def missing_structure(self, **options):
        def missing(*args, **kwargs):
            directory, structures, patent = load_binding_input(*args, **kwargs)
            return (
                directory,
                [s for s in structures if s.get("structure_id", s.get("id")) != "S17"],
                patent,
            )

        with patch(
            "patent_sar_extractor.core.structure_binder.load_binding_input",
            side_effect=missing,
        ):
            return self.control.run_binding(**options)

    def test_missing_drawing_stays_unresolved_without_reclassifying_its_catalogue_label(
        self,
    ):
        _source, _result, payload = self.missing_structure()
        self.assertTrue(
            any(
                i["reason"] == "missing_caption_structure"
                for i in payload["source_issues"]
            )
        )
        headings = [
            s for s in payload["source_sections"] if s["role"] == "compound_heading"
        ]
        self.assertEqual([s["identifier"] for s in headings], ["19"])
        pending = [
            s
            for s in payload["source_sections"]
            if s["role"] == "unresolved_structure_label_reference"
        ]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "unresolved")
        self.assertTrue(
            reference_issues(payload, payload["compound_catalog"]["entries"])
        )
        self.assertTrue(coverage_errors(payload))
        self.assertNotIn(
            "Compound 17", [b["cpd"] for b in payload["compound_catalog"]["entries"]]
        )

    def test_scanned_closed_catalogue_retains_missing_drawing_error_and_occurrence(
        self,
    ):
        _source, _result, payload = self.missing_structure(raster=True)
        self.assertEqual(
            [
                s["identifier"]
                for s in payload["source_sections"]
                if s["role"] == "compound_heading"
            ],
            ["19"],
        )
        pending = [s for s in payload["source_sections"] if s["role"] == PENDING_ROLE]
        self.assertEqual(len(pending), 1)
        self.assertNotIn("identifier", pending[0])
        self.assertTrue(coverage_errors(payload))

    def test_unqualified_identity_never_becomes_a_binding_or_a_second_heading(self):
        def unresolved(page, bounds, *args, **kwargs):
            observed = read_cell(page, bounds, *args, **kwargs)
            return replace(observed, needs_review=True) if bounds[0] < 100 else observed

        with patch(
            "patent_sar_extractor.core.caption_grid_binding.read_cell",
            side_effect=unresolved,
        ):
            _source, _result, payload = self.control.run_binding()
        self.assertTrue(
            any(
                i["reason"] == "unread_or_conflicting_caption"
                for i in payload["source_issues"]
            )
        )
        self.assertEqual(
            [
                s["identifier"]
                for s in payload["source_sections"]
                if s["role"] == "compound_heading"
            ],
            ["19"],
        )
        self.assertNotIn(
            "Compound 17", [b["cpd"] for b in payload["compound_catalog"]["entries"]]
        )
        self.assertTrue(coverage_errors(payload))

    def test_same_identifier_outside_the_caption_cell_is_still_a_separate_heading(self):
        _source, _result, payload = self.missing_structure(extra_heading=True)
        self.assertEqual(
            [
                s["identifier"]
                for s in payload["source_sections"]
                if s["role"] == "compound_heading"
            ],
            ["19", "17"],
        )
        self.assertTrue(
            any(
                p.get("cpd") == "Compound 17"
                and p["reason"]
                == "original_heading_identifier_without_proved_structure"
                for p in reference_issues(
                    payload, payload["compound_catalog"]["entries"]
                )
            )
        )

    def test_unknown_catalogue_role_does_not_suppress_an_original_heading(self):
        # This ambiguous title is not positive final-catalogue evidence. The
        # existing final source gate must still refuse a proposed admission;
        # the new role index cannot turn that refusal into an alias or success.
        with (
            patch(
                "patent_sar_extractor.core.structure_binder.observed_heading_blocks",
                wraps=observed_heading_blocks,
            ) as observer,
            self.assertRaisesRegex(ValueError, "Unproved or nonfinal original grid"),
        ):
            self.missing_structure(catalog_title="Table 47. Structures")
        sections = observer.call_args.kwargs["source_sections"]
        self.assertFalse(any(s["role"] == PENDING_ROLE for s in sections))
        self.assertTrue(
            any(
                s.get("identifier") == "17" and s["role"] == "compound_heading"
                for s in sections
            )
        )

    def test_cleared_flags_cannot_remove_the_original_unresolved_source(self):
        _source, _result, payload = self.missing_structure()
        payload["source_issues"] = []
        payload["strict_coverage"]["unresolved_sources"] = []
        self.assertTrue(
            any(
                p["reason"] == "missing_caption_structure"
                for p in reference_issues(
                    payload, payload["compound_catalog"]["entries"]
                )
            )
        )
        self.assertTrue(coverage_errors(payload))

    def test_changed_or_missing_occurrence_proof_cannot_be_promoted(self):
        _source, _result, payload = self.missing_structure()
        for fault in (
            "status",
            "bbox",
            "text",
            "page",
            "source",
            "diagnostic",
            "identifier",
            "omitted",
        ):
            altered = copy.deepcopy(payload)
            reference = next(
                s for s in altered["source_sections"] if s["role"] == PENDING_ROLE
            )
            if fault == "status":
                reference["status"] = "confirmed"
            elif fault == "bbox":
                reference["bbox"] = [40, 490, 200, 515]
            elif fault == "text":
                reference["line_text"] = "Compound 99"
            elif fault == "page":
                reference["page_no"] = True
            elif fault == "source":
                reference["line_source"] = "cell_ocr"
            elif fault == "diagnostic":
                reference["source_diagnostics"] = ["f" * 64]
            elif fault == "identifier":
                reference["identifier"] = "17"
            else:
                altered["source_role_observations"] = {}
            altered["source_reference_scope"] = reference_scope(
                altered["source_sections"],
                altered["source_reference_scope"]["original_pdf_sha256"],
            )
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                reference_issues(altered, altered["compound_catalog"]["entries"])

    def test_pending_references_require_the_same_original_raw_locator(self):
        _source, _result, payload = self.missing_structure()
        reference = next(
            s for s in payload["source_sections"] if s["role"] == PENDING_ROLE
        )
        origin = reference["original_pdf_sha256"]
        index = pending_caption_index(payload["source_role_observations"], origin)
        line = {
            "text": reference["line_text"],
            "source": reference["line_source"],
            "geometry_space": reference["geometry_space"],
            "bbox": reference["bbox"],
        }
        self.assertEqual(pending_caption_reference(line, 1, index, origin), reference)
        for name, value in (
            ("text", "Compound 19"),
            ("bbox", [0, 0, 400, 200]),
            ("source", "page_ocr"),
            ("bbox", [float("nan"), 95, 130, 125]),
        ):
            with self.subTest(field=name, value=value):
                self.assertIsNone(
                    pending_caption_reference({**line, name: value}, 1, index, origin)
                )

    def test_multiple_rejected_attempts_are_retained_without_choosing_a_winner(self):
        _source, _result, payload = self.missing_structure()
        reference = next(
            s for s in payload["source_sections"] if s["role"] == PENDING_ROLE
        )
        diagnostic = copy.deepcopy(
            payload["source_role_observations"][reference["source_diagnostics"][0]]
        )
        diagnostic["proposal"]["rejected_attempt_context"] = (
            "independent retained observation"
        )
        catalog = serialize_role_observations(
            [*payload["source_role_observations"].values(), diagnostic]
        )
        index = pending_caption_index(catalog, reference["original_pdf_sha256"])
        line = {
            "text": reference["line_text"],
            "source": reference["line_source"],
            "geometry_space": reference["geometry_space"],
            "bbox": reference["bbox"],
        }
        observed = pending_caption_reference(
            line, 1, index, reference["original_pdf_sha256"]
        )
        self.assertEqual(len(observed["source_diagnostics"]), 2)
        self.assertEqual(observed["status"], "unresolved")
        self.assertNotIn("identifier", observed)

    def test_series_prefix_leading_zeros_and_suffix_survive_without_identity_admission(
        self,
    ):
        document, structures, boxes = original_catalog(prefixed=True)
        with document:
            origin = document_sha256(document)
            observed = bind_caption_grids(
                document, {1: structures[1][1:]}, {1: boxes[1][1:]}, [1]
            )
            buffer = RoleObservationBuffer()
            retain_binding_diagnostics(
                observed.issues, buffer, original_pdf_sha256=origin
            )
            index = pending_caption_index(serialize_role_observations(buffer), origin)
            line = next(
                line
                for line in original_heading_lines(document[0])
                if "I-004A" in line["text"]
            )
            reference = pending_caption_reference(line, 1, index, origin)
        self.assertIsNotNone(reference)
        self.assertEqual(reference["line_text"], "Compound I-004A")
        self.assertEqual(reference["status"], "unresolved")
        self.assertNotIn("identifier", reference)

    def test_source_carrier_and_catalogue_role_must_replay_not_just_diagnostic_flags(
        self,
    ):
        _source, _result, payload = self.missing_structure()
        reference = next(
            s for s in payload["source_sections"] if s["role"] == PENDING_ROLE
        )
        origin = reference["original_pdf_sha256"]
        original = payload["source_role_observations"][
            reference["source_diagnostics"][0]
        ]
        for fault in ("origin", "role"):
            changed = copy.deepcopy(original)
            if fault == "origin":
                carrier = next(
                    r
                    for r in changed["proposal"]["observations"]
                    if r.get("method") == "native_cell"
                )
                carrier["source_observation"]["origin"] = "raster"
            else:
                changed["proposal"]["caption_role"]["role"] = "unknown"
            catalog = serialize_role_observations([changed])
            with self.subTest(fault=fault):
                self.assertEqual(pending_caption_index(catalog, origin), {})
        with self.assertRaisesRegex(ValueError, "downgraded"):
            validate_caption_references([reference], {"version": 4}, [])


if __name__ == "__main__":
    unittest.main()
