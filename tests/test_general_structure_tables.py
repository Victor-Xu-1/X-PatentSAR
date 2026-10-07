"""Header-owned structure cells in wide and reordered original tables."""

from __future__ import annotations

import unittest

import fitz

from patent_sar_extractor.core.binding_spatial import (
    _extract_authoritative_structure_table_sequence_bindings,
)
from patent_sar_extractor.core.numbered_structure_binding import bind_numbered_tables
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy


class GeneralStructureTableTests(unittest.TestCase):
    def observe(self, headers):
        doc = fitz.open()
        self.addCleanup(doc.close)
        page = doc.new_page(width=760, height=520)
        xs = [40 + 100 * i for i in range(len(headers) + 1)]
        ys = [80, 110, 260, 410]
        structure_column = headers.index("Structure") if "Structure" in headers else 1
        id_column = next(
            (i for i, h in enumerate(headers) if h in ("Ex #", "Compound ID")), 0
        )
        for i, header in enumerate(headers):
            page.insert_text((xs[i] + 4, 98), header, fontsize=8)
        structures = []
        for row, label in enumerate(("17", "18")):
            y0, y1 = ys[row + 1 : row + 3]
            page.insert_text((xs[id_column] + 5, y0 + 65), label, fontsize=10)
            for column, header in enumerate(headers):
                if header not in ("Ex #", "Compound ID", "Structure"):
                    page.insert_text(
                        (xs[column] + 5, y0 + 65),
                        "7" if header == "Procedures" else "412.3",
                        fontsize=10,
                    )
            structures.append(
                {
                    "id": f"S{label}",
                    "idx": row,
                    "page_no": 1,
                    "x0": xs[structure_column] + 10,
                    "x1": xs[structure_column + 1] - 10,
                    "y0": y0 + 20,
                    "y1": y1 - 20,
                    "image_path": f"/controlled/{label}.png",
                }
            )
        return bind_numbered_tables(
            doc,
            structures,
            [0],
            None,
            grids_for_page=lambda _page: [{"xs": xs, "ys": ys}],
        ), structures

    def test_six_column_example_table_does_not_bind_procedure_or_mass_as_identifier(
        self,
    ):
        result, _ = self.observe(
            ["Ex #", "Procedures", "Structure", "Name", "LCMS", "NMR"]
        )
        self.assertEqual([b.label for b in result.bindings], ["17", "18"])
        self.assertEqual(result.observed_keys, frozenset({"17", "18"}))
        self.assertEqual(result.issues, ())

    def test_structure_column_before_identifier_keeps_exact_row_ownership(self):
        result, _ = self.observe(["Structure", "LCMS", "Compound ID", "Name"])
        self.assertEqual([b.label for b in result.bindings], ["17", "18"])
        self.assertEqual(result.issues, ())

    def test_header_owned_nonadjacent_proof_is_rechecked_by_formal_gate(self):
        result, structures = self.observe(["Ex #", "Procedures", "Structure", "LCMS"])
        bindings = _extract_authoritative_structure_table_sequence_bindings(
            structures, {}, [], {}, numbered_result=result
        )
        self.assertEqual(len(bindings), 2)
        self.assertEqual(
            annotate_binding_accuracy(bindings[0])["accuracy_status"], "confirmed"
        )
        proof = dict(bindings[0]["numbered_table_cell_evidence"])
        proof["label_bbox"] = [140, 110, 240, 260]
        self.assertTrue(
            annotate_binding_accuracy(
                {**bindings[0], "numbered_table_cell_evidence": proof}
            )["fail_closed"]
        )

    def test_nonstructure_header_is_not_an_alias_for_a_molecular_column(self):
        result, _ = self.observe(["Ex #", "Procedures", "Name", "LCMS"])
        self.assertFalse(result.recognized)
        self.assertEqual(result.bindings, ())


if __name__ == "__main__":
    unittest.main()
