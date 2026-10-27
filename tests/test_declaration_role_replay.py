"""Original declaration-role replay over real token/provenance SDK packets."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz
from test_source_body_context import token

from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.source_window_chunks import observe_source_window
from patent_sar_extractor.core.structure_declaration_roles import (
    declaration_label_reference,
    declaration_role_index,
)
from patent_sar_extractor.core.structure_declaration_scopes import (
    PAGE_ROLE,
    PAGE_STATUS,
    declaration_scopes,
    declaration_title_nominations,
    nonfinal_declaration_diagrams,
)
from patent_sar_extractor.core.title_source_capture import attach_title_sources


def original_page(*, weak_boundary=True, weak_title=False, native_boundary=None):
    words = [
        token(
            "Table 13. Intermediate compounds",
            35,
            width=260,
            confidence=0.40 if weak_title else 0.99,
        ),
        token("Compound 901A", 185, width=130),
        token(
            "Compound B80: Preparation", 430, confidence=0.40 if weak_boundary else 0.99
        ),
    ]
    source = {
        "status": PAGE_STATUS,
        "version": 1,
        "original_pdf_sha256": "a" * 64,
        "page_no": 1,
        "page_size": [520, 720],
        "page_grids": [],  # This original token-only control has no printed rules.
        "page_diagrams": [
            {"id": "BEFORE", "bbox": [215, 95, 355, 165]},
            {"id": "AFTER", "bbox": [215, 470, 355, 550]},
        ],
    }
    # Modern title consumers require an actual full original and paired frames.
    # These generated controls use a deterministic SDK reader, never a model.
    with fitz.open() as lettering, fitz.open() as original:
        text_page = lettering.new_page(width=520, height=720)
        for word in words:
            text_page.insert_text(
                (word["bbox"][0], word["bbox"][1] + 10), word["text"], fontsize=8
            )
        image = text_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        page = original.new_page(width=520, height=720)
        page.insert_image(page.rect, stream=image.tobytes("png"))
        if native_boundary is not None:
            page.insert_text((50, 440), native_boundary, fontsize=8)
        layout = source_layout(page)
        source_tokens = SourceTokens(words, layout, scan_bounds=layout.raster_bounds)
        source["page_context"] = observe_source_window(source_tokens, [0, 0, 520, 720])
        nominations = declaration_title_nominations(source)
        parents = [p for chunk in source["page_context"] for p in chunk["sources"]]

        def read_title(image, *, use_det, use_cls):
            return (
                ([], None)
                if use_det
                else ([[words[0]["text"], 0.4 if weak_title else 0.99]], None)
            )

        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            return_value=("rapidocr", read_title),
        ):
            observed = iter(attach_title_sources(page, parents, nominations))
        for chunk in source["page_context"]:
            chunk["sources"] = [next(observed) for _ in chunk["sources"]]
    return source


def section(source):
    return {
        "role": PAGE_ROLE,
        "status": PAGE_STATUS,
        "page_no": 1,
        "region_id": proof_id(source),
        "source": source,
    }


def line(text, top, *, width=190):
    word = token(text, top, width=width)
    return {
        "text": text,
        "bbox": word["bbox"],
        "source": "page_ocr",
        "geometry_space": "rendered",
    }


class DeclarationRoleReplayTests(unittest.TestCase):
    def test_weak_boundary_keeps_the_later_diagram_out_of_the_nonfinal_exclusion(self):
        source = original_page()
        before = copy.deepcopy(source)
        scopes = declaration_scopes(source)
        self.assertEqual(len(scopes), 1)
        self.assertEqual({d["id"] for d in scopes[0]["diagrams"]}, {"BEFORE", "AFTER"})
        self.assertEqual(
            {d["id"] for d in nonfinal_declaration_diagrams(scopes[0])}, {"BEFORE"}
        )
        self.assertEqual(scopes[0]["trusted_bottom"], 430)
        self.assertTrue(scopes[0]["unproved_boundaries"])
        self.assertEqual(source, before)

    def test_later_original_preparation_is_not_skipped_as_an_intermediate_label(self):
        index = declaration_role_index([section(original_page())], "a" * 64)
        self.assertIsNotNone(
            declaration_label_reference(line("Compound 901A", 185, width=130), 1, index)
        )
        self.assertIsNone(
            declaration_label_reference(
                line("Compound B80: Preparation", 430), 1, index
            )
        )

    def test_a_proved_procedure_ends_the_old_scope_but_not_the_page_inventory(self):
        source = original_page(weak_boundary=False)
        scopes = declaration_scopes(source)
        self.assertEqual([d["id"] for d in scopes[0]["diagrams"]], ["BEFORE"])
        self.assertEqual(
            [d["id"] for d in source["page_diagrams"]], ["BEFORE", "AFTER"]
        )
        self.assertEqual(scopes[0]["unproved_boundaries"], [])

    def test_weak_nonfinal_title_is_retained_without_excluding_any_structure(self):
        scopes = declaration_scopes(original_page(weak_title=True))
        self.assertEqual(scopes[0]["role"], "unresolved")
        self.assertTrue(scopes[0]["unproved_nonfinal_role"])
        self.assertEqual(nonfinal_declaration_diagrams(scopes[0]), [])

    def test_valid_conflicting_boundary_lanes_stay_unresolved(self):
        source = original_page(
            weak_boundary=False, native_boundary="Compound B81: Preparation"
        )
        scope = declaration_scopes(source)[0]
        self.assertEqual(scope["trusted_bottom"], 430)
        self.assertEqual(len(scope["unproved_boundaries"]), 2)
        self.assertEqual(
            [d["id"] for d in nonfinal_declaration_diagrams(scope)], ["BEFORE"]
        )

    def test_saved_replay_rederives_the_same_roles_and_exact_original_windows(self):
        source = original_page()
        serialized = json.loads(json.dumps(source))
        self.assertEqual(declaration_scopes(source), declaration_scopes(serialized))
        self.assertEqual(proof_id(source), proof_id(serialized))

    def test_a_foreign_source_cannot_supply_a_nonfinal_reference(self):
        with self.assertRaises(ValueError):
            declaration_role_index([section(original_page())], "b" * 64)

    def test_missing_current_grid_observation_is_not_an_implicit_empty_inventory(self):
        source = original_page()
        source.pop("page_grids")
        with self.assertRaises(ValueError):
            declaration_scopes(source)
