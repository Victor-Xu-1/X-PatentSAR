"""Complete rejected ancestry is not a single original local source region."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.core.binding_source_diagnostics import (
    retain_binding_diagnostics,
)
from patent_sar_extractor.core.caption_role_links import MAX_CONTINUATION_DEPTH
from patent_sar_extractor.core.source_evidence_identity import SourceEvidenceLimit
from patent_sar_extractor.core.source_role_observations import (
    RoleObservationBuffer,
    serialize_role_observations,
    validate_role_catalog,
)
from patent_sar_extractor.web.attempts import CheckpointCopy, VerifiedCheckpoint
from patent_sar_extractor.web.files import SafeFiles


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def original_chain(count=4):
    scope = None
    for number in range(count):
        current = {
            "version": 1,
            "page_no": number + 1,
            "sources": [{"original_rows": ["Literal 原文 " + "x" * 7800] * 45}],
            "observations": [],
        }
        if scope is not None:
            current["continuation"] = {
                "previous": scope,
                "direction": "above",
                "previous_axes": {"xs": [0, 100], "ys": [0, 30, 100]},
                "current_axes": {"xs": [0, 100], "ys": [0, 30, 100]},
                "previous_tail": {"original_text": "Original literal tail"},
            }
        scope = current
    return scope


def issue(scope):
    return {
        "cpd": "Example 09B",
        "page_no": 4,
        "reason": "missing_caption_structure",
        "evidence": {
            "proposal": {
                "page": 4,
                "label": "09B",
                "bbox": [0, 30, 100, 100],
                "caption_role": scope,
            }
        },
    }


class DiagnosticCaptionAncestryTests(unittest.TestCase):
    def retain(self, source):
        buffer = RoleObservationBuffer()
        retained = retain_binding_diagnostics(
            [source], buffer, original_pdf_sha256="a" * 64
        )
        return retained, serialize_role_observations(buffer)

    def test_rejected_large_complete_chain_keeps_every_original_and_canonical_id(self):
        source = issue(original_chain())
        before = copy.deepcopy(source)
        self.assertGreater(len(encoded(source)), 1024 * 1024)
        retained, catalog = self.retain(source)
        key = retained[0]["evidence"]["source_diagnostic"]
        self.assertEqual(key, hashlib.sha256(encoded(catalog[key])).hexdigest())
        self.assertEqual(catalog[key]["proposal"], source["evidence"]["proposal"])
        self.assertEqual(catalog[key]["status"], "unresolved")
        self.assertEqual(retained[0]["reason"], source["reason"])
        self.assertEqual(source, before)
        validate_role_catalog(catalog, original_pdf_sha256="a" * 64)

    def test_nested_original_binding_ownership_uses_the_same_diagnostic_identity(self):
        for owner_path in (
            ("page_boundary", "other_role"),
            ("exact_caption_evidence", "ownership", "caption_role"),
            ("exact_caption_evidence", "ownership", "page_boundary", "other_role"),
        ):
            with self.subTest(owner_path=owner_path):
                source = issue(original_chain())
                owner = source["evidence"]["proposal"]
                scope = owner.pop("caption_role")
                for field in owner_path[:-1]:
                    owner[field] = {}
                    owner = owner[field]
                owner[owner_path[-1]] = scope
                retained, catalog = self.retain(source)
                key = retained[0]["evidence"]["source_diagnostic"]
                self.assertEqual(key, hashlib.sha256(encoded(catalog[key])).hexdigest())
                self.assertEqual(catalog[key]["proposal"], source["evidence"]["proposal"])

    def test_combined_local_envelope_and_each_ancestor_keep_one_region_limit(self):
        source = issue(original_chain())
        source["evidence"]["proposal"]["other_original_rows"] = ["x" * 7800] * 100
        with self.assertRaises(SourceEvidenceLimit):
            self.retain(source)
        source = issue(original_chain())
        source["evidence"]["proposal"]["caption_role"]["continuation"]["previous"][
            "sources"
        ][0]["original_rows"] *= 4
        with self.assertRaises(SourceEvidenceLimit):
            self.retain(source)

    def test_unknown_nested_inventory_cannot_acquire_caption_partition_permission(self):
        source = issue(original_chain())
        proposal = source["evidence"]["proposal"]
        proposal["original_role_chain"] = proposal.pop("caption_role")
        with self.assertRaises(SourceEvidenceLimit):
            self.retain(source)

    def test_exact_total_limit_is_independent_of_local_and_catalog_limits(self):
        source = issue(original_chain())
        _retained, catalog = self.retain(source)
        size = len(encoded(next(iter(catalog.values()))))
        target = "patent_sar_extractor.core.caption_record_identity.MAX_ARTIFACT_BYTES"
        with patch(target, size):
            self.assertEqual(self.retain(source)[1], catalog)
        with patch(target, size - 1), self.assertRaises(SourceEvidenceLimit):
            self.retain(source)
        with (
            patch(
                "patent_sar_extractor.core.source_role_observations.MAX_ROLE_CATALOG_BYTES",
                size - 1,
            ),
            self.assertRaisesRegex(ValueError, "catalog"),
        ):
            self.retain(source)

    def test_cycle_missing_ancestor_and_existing_depth_cap_still_refuse(self):
        scope = {"sources": []}
        for _ in range(MAX_CONTINUATION_DEPTH + 1):
            scope = {"sources": [], "continuation": {"previous": scope}}
        cyclic = {"sources": []}
        cyclic["continuation"] = {"previous": cyclic}
        for value in (scope, cyclic, {"continuation": {"direction": "above"}}):
            with (
                self.subTest(value_type=type(value).__name__),
                self.assertRaises(ValueError),
            ):
                self.retain(issue(value))

    def test_raw_roundtrip_checkpoint_and_mutation_preserve_unresolved_ownership(self):
        source = issue(original_chain())
        retained, catalog = self.retain(source)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = {"source_role_observations": catalog, "source_issues": retained}
            write_json_atomic(root / "diagnostics.json", payload, shared=True)
            self.assertEqual(load_json(root / "diagnostics.json", {}), payload)
            copy_to = CheckpointCopy(root, root / "next")
            copy_to.checkpoint(
                VerifiedCheckpoint(
                    "bind",
                    "diagnostics.json",
                    payload,
                    {"fingerprint": {"params": {}, "dependency_sha256": {}}},
                )
            )
            self.assertEqual(
                SafeFiles(copy_to.target).json("diagnostics.json"), payload
            )
        changed = copy.deepcopy(catalog)
        observation = next(iter(changed.values()))
        observation["proposal"]["caption_role"]["continuation"]["previous"][
            "sources"
        ][0]["original_rows"][0] += " changed"
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_role_catalog(changed)
        with self.assertRaisesRegex(ValueError, "document"):
            validate_role_catalog(catalog, original_pdf_sha256="b" * 64)
        observation["status"] = "confirmed"
        with self.assertRaisesRegex(ValueError, "diagnostic"):
            validate_role_catalog(changed)

    def test_actual_generated_continuation_and_pending_consumer_share_bounded_identity(
        self,
    ):
        from test_caption_role_continuation import two_pages

        from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
        from patent_sar_extractor.core.caption_pending_roles import (
            pending_caption_index,
        )

        document, drawings, boxes, grids, pages = two_pages()
        drawings[2].pop(0)
        boxes[2].pop(0)
        with document:
            result = bind_caption_grids(
                document,
                drawings,
                boxes,
                pages,
                grids_for_page=lambda page: grids[page.number + 1],
            )
        source = next(
            i for i in result.issues if i["reason"] == "missing_caption_structure"
        )
        _retained, catalog = self.retain(source)
        local = copy.deepcopy(next(iter(catalog.values())))
        local["proposal"]["caption_role"]["continuation"]["previous"] = None
        limit = len(encoded(local))
        role = next(iter(catalog.values()))["proposal"]["caption_role"]
        while "continuation" in role:
            role = role["continuation"]["previous"]
            current = copy.deepcopy(role)
            if "continuation" in current:
                current["continuation"]["previous"] = None
            limit = max(limit, len(encoded(current)))
        self.assertLess(limit, len(encoded(next(iter(catalog.values())))))
        with (
            patch(
                "patent_sar_extractor.core.caption_record_identity.MAX_SOURCE_REGION_BYTES",
                limit,
            ),
            patch(
                "patent_sar_extractor.core.source_evidence_identity.MAX_SOURCE_REGION_BYTES",
                limit,
            ),
        ):
            retained, repeated = self.retain(source)
            self.assertEqual(repeated, catalog)
            index = pending_caption_index(repeated, "a" * 64)
        self.assertTrue(index)
        self.assertEqual({v["status"] for v in repeated.values()}, {"unresolved"})
        self.assertEqual(retained[0]["reason"], "missing_caption_structure")


if __name__ == "__main__":
    unittest.main()
