"""Complete large page evidence stays bounded and independently replayable."""

import copy
import hashlib
import io
import json
import unittest
from unittest.mock import patch

from test_source_body_context import token

from patent_sar_extractor.core.source_evidence_identity import (
    SourceEvidenceLimit,
    proof_id,
)
from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
from patent_sar_extractor.core.source_window_chunks import observe_source_window
from patent_sar_extractor.core.structure_declaration_proof import _pages
from patent_sar_extractor.core.structure_declaration_scopes import (
    PAGE_ROLE,
    PAGE_STATUS,
    declaration_scopes,
    validate_declaration_page,
)


def complete_page(*, rows=550):
    width, height = 520, 12000
    words = [token("Table 42. Compounds 原文", 8, width=220)]
    words.extend(
        token(f"original-{index:04d}-" + "x" * 1200, 40 + index * 18, width=190)
        for index in range(rows)
    )
    layout = SourceLayout((), (0, 0, width, height))
    tokens = SourceTokens(words, layout, scan_bounds=layout.raster_bounds)
    return {
        "status": PAGE_STATUS,
        "version": 2,
        "original_pdf_sha256": "a" * 64,
        "page_no": 1,
        "page_size": [width, height],
        "page_context": observe_source_window(tokens, [0, 0, width, height]),
        "page_diagrams": [{"id": "D1", "bbox": [230, 95, 355, 165]}],
        "page_grids": [],
        "catalogue_scopes": [],
    }


class DeclarationPageIdentityTests(unittest.TestCase):
    def test_large_complete_page_is_replayable_without_omission(self):
        source = complete_page()
        validate_declaration_page(source)
        self.assertGreater(len(json.dumps(source).encode()), 1024 * 1024)
        with self.assertRaises(SourceEvidenceLimit):
            proof_id(source)  # Small-region identity keeps its existing limit.
        scopes = declaration_scopes(source)
        self.assertEqual(len(scopes), 1)
        self.assertEqual(scopes[0]["role"], "unresolved")
        self.assertEqual([item["id"] for item in scopes[0]["diagrams"]], ["D1"])
        self.assertEqual(declaration_scopes(json.loads(json.dumps(source))), scopes)

    def test_small_page_identity_remains_compatible_with_old_canonical_json(self):
        from patent_sar_extractor.core.structure_declaration_scopes import (
            declaration_page_id,
        )

        source = complete_page(rows=2)
        self.assertEqual(declaration_page_id(source), proof_id(source))

    def test_stream_identity_matches_full_canonical_json_for_large_page(self):
        from patent_sar_extractor.core.structure_declaration_scopes import (
            declaration_page_id,
        )

        source = complete_page()
        encoded = json.dumps(
            source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.assertGreater(len(encoded), 1024 * 1024)
        self.assertEqual(
            declaration_page_id(source), hashlib.sha256(encoded).hexdigest()
        )

    def test_scope_and_page_identity_share_one_validation_pass(self):
        from patent_sar_extractor.core import structure_declaration_scopes as scopes

        source = complete_page(rows=2)
        with patch.object(
            scopes, "validate_declaration_page", wraps=scopes.validate_declaration_page
        ) as validate:
            identity, declarations = scopes.declaration_scopes_with_identity(source)
        validate.assert_called_once_with(source)
        self.assertEqual(identity, proof_id(source))
        self.assertEqual(declarations, scopes.declaration_scopes(source))

    def test_component_and_page_budgets_refuse_without_truncating(self):
        from patent_sar_extractor.core.structure_declaration_scopes import (
            declaration_page_id,
        )

        source = complete_page(rows=2)
        encoded = json.dumps(
            source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        expected = hashlib.sha256(encoded).hexdigest()
        with patch(
            "patent_sar_extractor.core.declaration_page_identity.MAX_PAGE_BYTES",
            len(encoded),
        ):
            self.assertEqual(declaration_page_id(source), expected)
        with (
            patch(
                "patent_sar_extractor.core.declaration_page_identity.MAX_PAGE_BYTES",
                len(encoded) - 1,
            ),
            self.assertRaisesRegex(SourceEvidenceLimit, "page exceeds.*page 1"),
        ):
            declaration_page_id(source)
        with (
            patch(
                "patent_sar_extractor.core.declaration_page_identity.MAX_COMPONENT_BYTES",
                64,
            ),
            self.assertRaisesRegex(SourceEvidenceLimit, "component exceeds.*page 1"),
        ):
            declaration_page_id(source)

    def test_page_identity_rejects_a_changed_original_diagram(self):
        from patent_sar_extractor.core.structure_declaration_scopes import (
            declaration_page_id,
        )

        source = complete_page()
        identity = declaration_page_id(source)
        section = {
            "role": PAGE_ROLE,
            "status": PAGE_STATUS,
            "page_no": 1,
            "region_id": identity,
            "source": source,
        }
        scope = {
            "version": 6,
            "declaration_page_ids": [identity],
            "declaration_reference_ids": [],
            "original_pdf_sha256": "a" * 64,
        }
        self.assertEqual(_pages([section], scope, current=True), [section])
        changed = copy.deepcopy(section)
        changed["source"]["page_diagrams"][0]["bbox"][0] += 1
        with self.assertRaisesRegex(ValueError, "declaration identity"):
            _pages([changed], scope, current=True)
        missing = copy.deepcopy(section)
        missing["source"]["page_context"].pop()
        with self.assertRaises(ValueError):
            _pages([missing], scope, current=True)

    def test_large_page_survives_shared_artifact_storage_and_replay(self):
        from patent_sar_extractor.artifact_catalog import read_artifact_json
        from patent_sar_extractor.artifact_io import artifact_json_bytes
        from patent_sar_extractor.core.structure_declaration_scopes import (
            declaration_page_id,
        )

        source = complete_page()
        identity = declaration_page_id(source)
        section = {
            "role": PAGE_ROLE,
            "status": PAGE_STATUS,
            "page_no": 1,
            "region_id": identity,
            "source": source,
        }
        scope = {
            "version": 6,
            "declaration_page_ids": [identity],
            "declaration_reference_ids": [],
            "original_pdf_sha256": "a" * 64,
        }
        payload = {"source_sections": [section], "source_reference_scope": scope}
        encoded = artifact_json_bytes(payload, shared=True)
        saved = read_artifact_json(io.StringIO(encoded.decode("utf-8")))
        self.assertEqual(saved, payload)
        self.assertEqual(
            _pages(
                saved["source_sections"], saved["source_reference_scope"], current=True
            ),
            saved["source_sections"],
        )
