"""The label-reference consumer keeps complete, bounded original ancestry."""

import copy
import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_label_roles import caption_label_index
from patent_sar_extractor.core.source_binding_proof import annotate_source_binding
from patent_sar_extractor.core.source_document import document_sha256
from patent_sar_extractor.core.source_evidence_identity import SourceEvidenceLimit
from tests.test_caption_role_continuation import binding, two_pages


def encoded(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def reference_record(entry, source_sha):
    return {
        "status": "observed_original_caption",
        "original_pdf_sha256": source_sha,
        "identifier": entry["cpd"].removeprefix("Compound "),
        "structure_id": entry["structure_id"],
        "page_no": entry["page_no"],
        "structure_bbox": [
            entry["struct_" + axis] for axis in ("x0", "y0", "x1", "y1")
        ],
        "exact_caption_evidence": entry["exact_caption_evidence"],
    }


def local_budget(record):
    local = copy.deepcopy(record)
    ownership = local["exact_caption_evidence"]["ownership"]
    roles = [ownership.get("caption_role")]
    if "page_boundary" in ownership:
        roles.append(ownership["page_boundary"].get("other_role"))
    sizes = []
    for role in roles:
        while isinstance(role, dict) and "continuation" in role:
            previous = role["continuation"]["previous"]
            role["continuation"]["previous"] = None
            sizes.append(len(encoded(role)))
            role = previous
        if role is not None:
            sizes.append(len(encoded(role)))
    return max(len(encoded(local)), *sizes)


@contextmanager
def bounded_regions(limit):
    # Smaller generated originals exercise the unchanged production boundary;
    # no semantic validator, observation, digest or admission result is mocked.
    with ExitStack() as stack:
        for module in ("source_evidence_identity", "caption_record_identity"):
            stack.enter_context(
                patch(
                    f"patent_sar_extractor.core.{module}.MAX_SOURCE_REGION_BYTES", limit
                )
            )
        yield


class CaptionReferenceIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="caption-reference-identity-")
        cls.addClassCleanup(temporary.cleanup)
        cls.originals, cls.pdfs = {}, {}
        for split in (False, True):
            document, drawings, boxes, grids, pages = two_pages(split=split)
            with document:
                source = Path(temporary.name) / f"original-{split}.pdf"
                document.save(source)
                source_sha = document_sha256(document)
                result = bind_caption_grids(
                    document,
                    drawings,
                    boxes,
                    pages,
                    grids_for_page=lambda page, grids=grids: grids[page.number + 1],
                )
            if result.issues:
                raise AssertionError(result.issues)
            entries = [
                {
                    **binding(pair),
                    "binding_rule": "original_caption_cell",
                    "source_pdf_sha256": source_sha,
                }
                for pair in result.bindings
            ]
            cls.originals[split] = source_sha, entries
            cls.pdfs[split] = source

    def test_confirmed_current_and_cross_page_sources_keep_every_ancestor(self):
        observed = 0
        for split, (source_sha, entries) in self.originals.items():
            for entry in entries:
                record = reference_record(entry, source_sha)
                limit = local_budget(record)
                if limit >= len(encoded(record)):
                    continue  # This source has no prior-page inventory.
                with self.subTest(split=split, structure=entry["structure_id"]):
                    observed += 1
                    self.assertEqual(
                        annotate_source_binding(entry)["accuracy_status"], "confirmed"
                    )
                    original = copy.deepcopy(entry)
                    with bounded_regions(limit):
                        index = caption_label_index([entry], source_sha)
                    keys = [key for sources in index.values() for key in sources]
                    self.assertEqual(
                        keys, [hashlib.sha256(encoded(record)).hexdigest()]
                    )
                    self.assertEqual(entry, original)
        self.assertEqual(observed, 6)

    def test_serialized_and_additional_sources_use_identical_original_identity(self):
        source_sha, entries = self.originals[False]
        continued = entries[-1]
        original = reference_record(continued, source_sha)
        limit = local_budget(original)
        root = copy.deepcopy(entries[0])
        root["additional_sources"] = [json.loads(encoded(continued))]
        with bounded_regions(
            max(limit, local_budget(reference_record(root, source_sha)))
        ):
            index = caption_label_index([root], source_sha)
        self.assertIn(
            hashlib.sha256(encoded(original)).hexdigest(),
            index[continued["exact_caption_evidence"]["page_no"]],
        )

    def test_short_originals_keep_the_previous_canonical_reference_keys(self):
        for source_sha, entries in self.originals.values():
            index = caption_label_index(entries, source_sha)
            self.assertEqual(
                {key for page in index.values() for key in page},
                {
                    hashlib.sha256(
                        encoded(reference_record(entry, source_sha))
                    ).hexdigest()
                    for entry in entries
                },
            )

    def test_original_heading_consumer_reuses_the_same_complete_source_index(self):
        for split, (source_sha, entries) in self.originals.items():
            limit = max(local_budget(reference_record(e, source_sha)) for e in entries)
            sections = []
            with fitz.open(self.pdfs[split]) as document, bounded_regions(limit):
                self.assertEqual(document_sha256(document), source_sha)
                blocks = observed_heading_blocks(
                    document,
                    [0, 1],
                    {},
                    source_sections=sections,
                    source_regions={0: [], 1: []},
                    source_bindings=entries,
                )
            self.assertEqual(blocks, [], "Bare original cell IDs are not new headings")
            self.assertFalse(any(s["role"] == "compound_heading" for s in sections))

    def test_local_and_total_identity_boundaries_remain_exact(self):
        source_sha, entries = self.originals[False]
        entry = entries[-1]
        record = reference_record(entry, source_sha)
        with (
            bounded_regions(local_budget(record) - 1),
            self.assertRaises(SourceEvidenceLimit),
        ):
            caption_label_index([entry], source_sha)
        maximum = "patent_sar_extractor.core.caption_record_identity.MAX_ARTIFACT_BYTES"
        with patch(maximum, len(encoded(record))):
            self.assertTrue(caption_label_index([entry], source_sha))
        with (
            patch(maximum, len(encoded(record)) - 1),
            self.assertRaises(SourceEvidenceLimit),
        ):
            caption_label_index([entry], source_sha)

    def test_unknown_nested_chains_do_not_acquire_a_caption_inventory_permission(self):
        source_sha, entries = self.originals[False]
        entry = copy.deepcopy(entries[-1])
        original = copy.deepcopy(reference_record(entry, source_sha))
        packet = entry["exact_caption_evidence"]
        packet["unregistered_inventory"] = copy.deepcopy(
            packet["ownership"]["caption_role"]
        )
        self.assertEqual(annotate_source_binding(entry)["accuracy_status"], "confirmed")
        with (
            bounded_regions(local_budget(original)),
            self.assertRaises(SourceEvidenceLimit),
        ):
            caption_label_index([entry], source_sha)

    def test_changed_original_ancestry_and_foreign_source_still_cannot_exempt_a_heading(
        self,
    ):
        source_sha, entries = self.originals[False]
        for mutation in ("document", "ancestor", "identifier"):
            entry = copy.deepcopy(entries[-1])
            if mutation == "document":
                entry["source_pdf_sha256"] = "f" * 64
            elif mutation == "ancestor":
                entry["exact_caption_evidence"]["ownership"]["caption_role"][
                    "continuation"
                ]["previous_axes"]["xs"][0] += 1
            else:
                entry["cpd"] = "Compound 99"
            with self.subTest(mutation=mutation):
                self.assertEqual(caption_label_index([entry], source_sha), {})


if __name__ == "__main__":
    unittest.main()
