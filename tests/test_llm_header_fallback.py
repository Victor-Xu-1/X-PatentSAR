"""General unfamiliar table labels on real controlled PDFs, no patent-specific IDs."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.application.header_resolution import make_header_resolver
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_header_roles import candidate_schemas
from patent_sar_extractor.core.activity_models import TableContext
from patent_sar_extractor.integrations.llm.config import EvidenceResolutionConfig


class HeaderAPIFallbackTests(unittest.TestCase):
    def pdf(self, root, header="Material Code", reverse=False):
        path = root / "original.pdf"
        doc = fitz.open()
        page = doc.new_page(width=620, height=310)
        xs, ys = [40, 270, 580], [65, 110, 155, 200, 245]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        page.insert_text((40, 45), "Table 1. Binding activity")
        matrix = [
            [header, "Ki (nM)"],
            ["17", "0.12345"],
            ["22A", "<2.34567"],
            ["22B", "ND"],
        ]
        for row, values in enumerate(matrix):
            if reverse:
                values = list(reversed(values))
            for col, value in enumerate(values):
                page.insert_text((xs[col] + 12, ys[row] + 26), value, fontsize=11)
        doc.save(path)
        doc.close()
        return path

    def policy(self, **changes):
        return EvidenceResolutionConfig(
            mode="on-error",
            data_consent=True,
            endpoint="https://api.example.org/v1",
            model="controlled",
            api_key="controlled-only",
            **changes,
        )

    def selected(self, request, **kwargs):
        wire = kwargs["json"]
        supplied = json.loads(wire["messages"][-1]["content"])
        self.assertNotIn("0.12345", json.dumps(wire))
        self.assertNotIn("2.34567", json.dumps(wire))
        self.assertNotIn("Compound 22A", json.dumps(wire))
        candidate = supplied["candidates"][0]
        content = json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "observation_ids": candidate["observation_ids"],
                    }
                ]
            }
        )
        return json.dumps(
            {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        ).encode()

    def test_api_selects_source_proved_id_role_then_original_values_are_extracted(self):
        for reverse in (False, True):
            with (
                self.subTest(reverse=reverse),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                pdf = self.pdf(root, reverse=reverse)
                output = root / "activity"
                with (
                    patch(
                        "patent_sar_extractor.application.header_resolution.get_evidence_resolution_config",
                        return_value=self.policy(),
                    ),
                    patch(
                        "patent_sar_extractor.integrations.llm.client.bounded_post",
                        side_effect=self.selected,
                    ) as api,
                ):
                    resolver = make_header_resolver(
                        str(pdf),
                        str(output),
                        ("Compound 17", "Compound 22A", "Compound 22B"),
                    )
                    result = extract(
                        str(pdf),
                        {"activity_pages": [0]},
                        str(output),
                        header_resolver=resolver,
                    )
                self.assertEqual(api.call_count, 1)
                self.assertEqual(
                    [row.cpd for row in result["rows"]],
                    ["Compound 17", "Compound 22A", "Compound 22B"],
                )
                self.assertEqual(
                    [row.activity_values["Ki (nM)"] for row in result["rows"]],
                    ["0.12345", "<2.34567", "ND"],
                )
                self.assertTrue(all(not row.needs_review for row in result["rows"]))
                proof = result["rows"][0].activity_sources[0]["header_resolution"]
                self.assertEqual(proof["physical_column"], 1 if reverse else 0)
                self.assertTrue(proof["applied"])
                self.assertFalse(proof["formal_acceptance_changed"])

    def test_normal_supported_header_and_unproved_catalog_never_call_api(self):
        for label, catalog in (
            ("Compound ID", ("Compound 17", "Compound 22A", "Compound 22B")),
            ("Material Code", ("Compound 17",)),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                pdf = self.pdf(root, header=label)
                with (
                    patch(
                        "patent_sar_extractor.application.header_resolution.get_evidence_resolution_config",
                        return_value=self.policy(),
                    ),
                    patch(
                        "patent_sar_extractor.integrations.llm.client.bounded_post"
                    ) as api,
                ):
                    resolver = make_header_resolver(
                        str(pdf), str(root / "activity"), catalog
                    )
                    extract(
                        str(pdf),
                        {"activity_pages": [0]},
                        str(root / "activity"),
                        header_resolver=resolver,
                    )
                api.assert_not_called()

    def test_abstention_invalid_refs_or_failed_receipt_never_admit_header(self):
        for content in (
            '{"candidates":[]}',
            '{"candidates":[{"candidate_id":"invented","observation_ids":["fake"]}]}',
        ):
            with (
                self.subTest(content=content),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                pdf = self.pdf(root)
                response = json.dumps(
                    {
                        "choices": [
                            {"finish_reason": "stop", "message": {"content": content}}
                        ]
                    }
                ).encode()
                with (
                    patch(
                        "patent_sar_extractor.application.header_resolution.get_evidence_resolution_config",
                        return_value=self.policy(),
                    ),
                    patch(
                        "patent_sar_extractor.integrations.llm.client.bounded_post",
                        return_value=response,
                    ),
                ):
                    resolver = make_header_resolver(
                        str(pdf),
                        str(root / "activity"),
                        ("Compound 17", "Compound 22A", "Compound 22B"),
                    )
                    result = extract(
                        str(pdf),
                        {"activity_pages": [0]},
                        str(root / "activity"),
                        header_resolver=resolver,
                    )
                self.assertEqual(result["rows"], [])

    def test_invalid_catalog_suffix_values_or_unit_never_form_candidate(self):
        context = TableContext(caption="Binding activity")
        catalog = frozenset({"Compound 8A", "Compound 8B"})
        valid = [["Material Code", "Ki (nM)"], ["8A", "1"], ["8B", "2"]]
        self.assertEqual(set(candidate_schemas(context, valid, catalog)), {0})
        for matrix in (
            [valid[0], ["8", "1"], valid[2]],
            [valid[0], ["8A", "unknown value"], valid[2]],
            [["Material Code", "Ki"], *valid[1:]],
        ):
            self.assertEqual(candidate_schemas(context, matrix, catalog), {})

    def test_off_is_no_pdf_read_no_context_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch(
                    "patent_sar_extractor.application.header_resolution.get_evidence_resolution_config",
                    return_value=EvidenceResolutionConfig(),
                ),
                patch(
                    "patent_sar_extractor.application.header_resolution._pdf_sha256"
                ) as original,
            ):
                self.assertIsNone(
                    make_header_resolver(
                        "absent.pdf", str(root / "activity"), ("Compound 1",)
                    )
                )
            original.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])
