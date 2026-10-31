"""Bounded original pages may carry a complete multi-page catalogue ancestry."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.caption_role_identity import catalogue_declaration_id
from patent_sar_extractor.core.caption_role_links import MAX_CONTINUATION_DEPTH
from patent_sar_extractor.core.declaration_page_identity import page_source_digest
from patent_sar_extractor.core.source_evidence_identity import SourceEvidenceLimit


def encoded(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def generated_chain(count=4):
    """Identity-only facts; semantic admission is tested on real generated PDFs."""
    scope = None
    for page in range(count):
        current = {
            "version": 1,
            "page_no": page + 1,
            "sources": [{"text": "Original literal 原文 " + "x" * 350000}],
            "observations": [],
        }
        if scope is not None:
            current["continuation"] = {
                "previous": scope,
                "direction": "above",
                "previous_axes": {"xs": [0, 100], "ys": [0, 30, 100]},
                "current_axes": {"xs": [0, 100], "ys": [0, 30, 100]},
                "previous_tail": {"literal": "Original tail"},
            }
        scope = current
    return scope


def page_record(scope):
    return {
        "status": "identity_only_control",
        "catalogue_scopes": [scope],
        "page_context": [],
        "page_grids": [],
    }


class CaptionAncestryIdentityTests(unittest.TestCase):
    def test_complete_ancestry_larger_than_one_region_keeps_canonical_digest(self):
        source = page_record(generated_chain())
        before = copy.deepcopy(source)
        self.assertGreater(len(encoded(source["catalogue_scopes"][0])), 1024 * 1024)
        self.assertEqual(
            page_source_digest(source), hashlib.sha256(encoded(source)).hexdigest()
        )
        self.assertEqual(source, before)

    def test_single_original_page_fact_still_cannot_exceed_one_region(self):
        source = page_record(generated_chain(1))
        source["catalogue_scopes"][0]["sources"][0]["text"] *= 4
        with self.assertRaises(SourceEvidenceLimit):
            page_source_digest(source)

    def test_total_page_budget_remains_exact_and_no_ancestry_is_omitted(self):
        source = page_record(generated_chain())
        payload = encoded(source)
        with patch(
            "patent_sar_extractor.core.declaration_page_identity.MAX_PAGE_BYTES",
            len(payload),
        ):
            original = page_source_digest(source)
        with (
            patch(
                "patent_sar_extractor.core.declaration_page_identity.MAX_PAGE_BYTES",
                len(payload) - 1,
            ),
            self.assertRaises(SourceEvidenceLimit),
        ):
            page_source_digest(source)
        source["catalogue_scopes"][0]["continuation"]["previous"]["sources"][0][
            "text"
        ] += "changed"
        self.assertNotEqual(page_source_digest(source), original)

    def test_continuation_cycle_is_refused_before_canonical_json_recursion(self):
        scope = generated_chain(2)
        scope["continuation"]["previous"] = scope
        with self.assertRaises((ValueError, SourceEvidenceLimit)):
            page_source_digest(page_record(scope))

    def test_region_wrapper_keeps_every_ancestor_and_the_exact_old_canonical_bytes(
        self,
    ):
        for count in (1, 4):
            scope = generated_chain(count)
            record = {
                "status": "observed_original_table_declaration",
                "page_source": "a" * 64,
                "caption_role": scope,
            }
            with self.subTest(count=count):
                self.assertEqual(
                    catalogue_declaration_id("a" * 64, scope),
                    hashlib.sha256(encoded(record)).hexdigest(),
                )
                self.assertEqual(
                    catalogue_declaration_id("a" * 64, json.loads(encoded(scope))),
                    catalogue_declaration_id("a" * 64, scope),
                )

    def test_local_combined_fields_cannot_evade_the_original_region_limit(self):
        source = page_record(generated_chain(1))
        scope = source["catalogue_scopes"][0]
        # Neither individual field is too large; the same local fact is.
        scope["observations"] = [{"text": "y" * 800000}]
        with self.assertRaises(SourceEvidenceLimit):
            page_source_digest(source)

    def test_existing_ancestry_depth_limit_is_not_increased(self):
        scope = {"sources": []}
        for _ in range(MAX_CONTINUATION_DEPTH + 1):
            scope = {"continuation": {"previous": scope}, "sources": []}
        with self.assertRaisesRegex(SourceEvidenceLimit, "depth"):
            page_source_digest(page_record(scope))

    def test_generated_original_catalogue_uses_same_scope_for_page_and_region_identity(
        self,
    ):
        from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
        from patent_sar_extractor.core.caption_role_proof import caption_role_status
        from patent_sar_extractor.core.structure_declaration_catalogues import (
            catalogue_declarations,
        )
        from tests.test_caption_role_continuation import two_pages

        document, structures, boxes, grids, pages = two_pages()
        with document:
            result = bind_caption_grids(
                document,
                structures,
                boxes,
                pages,
                grids_for_page=lambda page: grids[page.number + 1],
            )
        self.assertEqual(result.issues, [])
        scope = next(
            role for (number, _box), role in result.roles.items() if number == 2
        )
        self.assertEqual(caption_role_status(scope, 2, scope["table_bbox"]), "compound")
        self.assertIn("continuation", scope)
        local = {**scope, "continuation": {**scope["continuation"], "previous": None}}
        limit = max(
            len(encoded(local)), len(encoded(scope["continuation"]["previous"]))
        )
        self.assertLess(limit, len(encoded(scope)))
        with (
            patch(
                "patent_sar_extractor.core.declaration_page_identity.MAX_COMPONENT_BYTES",
                limit,
            ),
            patch(
                "patent_sar_extractor.core.caption_role_identity.MAX_SOURCE_REGION_BYTES",
                limit,
            ),
        ):
            identity = page_source_digest(page_record(scope))
            source = {"catalogue_scopes": [scope], "page_diagrams": [], "page_no": 2}
            declarations = catalogue_declarations(
                source, identity, identifier_lists=lambda _body: []
            )
        self.assertEqual(len(declarations), 1)
        self.assertEqual(declarations[0]["role"], "compound")
        expected = {
            "status": "observed_original_table_declaration",
            "page_source": identity,
            "caption_role": scope,
        }
        self.assertEqual(
            declarations[0]["source_region"],
            hashlib.sha256(encoded(expected)).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
