"""Literal nonfinal roles agree across original headings, tables and SAR scope."""

import unittest

from patent_sar_extractor.core.activity_grid_roles import characterization_roles
from patent_sar_extractor.core.binding_labels import _is_intermediate
from patent_sar_extractor.core.caption_role_semantics import catalog_title_role
from patent_sar_extractor.core.cpd_filter import is_intermediate
from patent_sar_extractor.core.source_cell_claims import cell_source_conflict
from patent_sar_extractor.core.source_section_roles import (
    heading_list_hint,
    nonfinal_original_label,
    section_heading,
)
from patent_sar_extractor.web.sar.csv_inputs import mapped_inputs
from patent_sar_extractor.web.sar.models import CSVMapping
from patent_sar_extractor.web.sar.source_scope import source_exclusion

INTERMEDIATE_LABELS = ("中间体", "中間体", "中間體")


class SourceRoleTermTests(unittest.TestCase):
    def test_mixed_catalogue_keeps_explicit_final_categories_instead_of_excluding_all(
        self,
    ):
        for intermediate in INTERMEDIATE_LABELS:
            for final in ("化合物", "实施例", "實施例", "実施例", "终产物", "終產物"):
                with self.subTest(intermediate=intermediate, final=final):
                    self.assertEqual(
                        catalog_title_role(f"Table 47. {intermediate}及{final}"),
                        "mixed",
                    )

    def test_characterization_identifiers_do_not_disguise_biological_measurements(self):
        for label in INTERMEDIATE_LABELS:
            with self.subTest(label=label):
                matrix = [
                    [f"{label}编号", "Characterization"],
                    [f"{label}12", "1H NMR (400 MHz)"],
                ]
                self.assertEqual(
                    characterization_roles(
                        matrix, "Table 47. Compound characterization"
                    ),
                    {"data_start": 1, "columns": ["identifier", "nmr"]},
                )
                measured = [[f"{label}编号", "IC50 (nM)"], [f"{label}12", "4.2"]]
                self.assertIsNone(
                    characterization_roles(
                        measured, "Table 47. Compound characterization"
                    )
                )

    def test_cell_claims_and_literal_heading_groups_cannot_drop_the_role(self):
        for label in INTERMEDIATE_LABELS:
            with self.subTest(label=label):
                self.assertTrue(
                    cell_source_conflict({"text": f"{label}12"}, "12", "id")
                )
                raw = f"{label} 2 and 19B: Preparation"
                source = section_heading(raw)
                self.assertEqual(source["identifiers"], ["2", "19B"])
                self.assertEqual(source["role"], "intermediate_section")
                self.assertTrue(heading_list_hint(f"{label} 2, 19B"))

    def test_csv_keeps_original_final_ids_but_excludes_explicit_intermediate_aliases(
        self,
    ):
        for label in INTERMEDIATE_LABELS:
            with self.subTest(label=label):
                data = f"id,smiles,IC50 (nM)\nCompound 1,CO,10\n{label}2,CC,0.1\nI-255,CCC,1\n".encode()
                rows, _metrics, count = mapped_inputs(
                    data,
                    CSVMapping(
                        token="a" * 32,
                        title="Controlled source roles",
                        request_id="b" * 32,
                        id_column="id",
                        smiles_column="smiles",
                        activity_columns=["IC50 (nM)"],
                    ),
                )
                self.assertEqual([row.label for row in rows], ["Compound 1", "I-255"])
                self.assertEqual(
                    [row.observations[0].source_row for row in rows], [1, 3]
                )
                self.assertEqual(
                    count, 3
                )  # Original input count is not silently reduced.
                self.assertEqual(sum(len(row.observations) for row in rows), 2)

    def test_record_filters_share_the_declared_role_without_guessing_namespaces(self):
        for label in ("Intermediate", *INTERMEDIATE_LABELS):
            with self.subTest(label=label):
                self.assertTrue(_is_intermediate({"cpd": f"{label}12"}))
                self.assertTrue(is_intermediate({"label": f"{label}12"}))
        self.assertFalse(_is_intermediate({"cpd": "I-255"}))
        self.assertFalse(is_intermediate({"cpd": "I-255"}))
        # Free-form text is not an additional declared binder field.
        self.assertFalse(
            _is_intermediate({"cpd": "Compound 12", "label": "Intermediate"})
        )

    def test_known_intermediate_compound_titles_cannot_become_final_catalogues(self):
        for label in INTERMEDIATE_LABELS:
            for compounds in ("化合物", " compounds"):
                title = f"Table 47. {label}{compounds}"
                with self.subTest(title=title):
                    self.assertEqual(catalog_title_role(title), "nonfinal")

    def test_literal_nonfinal_heading_and_sar_scope_use_the_same_role(self):
        for label in INTERMEDIATE_LABELS:
            raw = f"{label} 12: Preparation"
            with self.subTest(label=label):
                source = section_heading(raw)
                self.assertIsNotNone(source)
                self.assertEqual(source["role"], "intermediate_section")
                self.assertEqual(source["line_text"], raw)
                self.assertTrue(nonfinal_original_label(raw))
                self.assertEqual(source_exclusion(f"{label}12"), "intermediate")

    def test_role_alias_does_not_rewrite_original_identifier_or_title(self):
        for label in INTERMEDIATE_LABELS:
            raw = f"[0042] {label} ００８-Ｂ: Preparation"
            with self.subTest(label=label):
                source = section_heading(raw)
                self.assertIsNotNone(source)
                self.assertEqual(source["identifier"], "008-B")
                self.assertEqual(source["line_text"], raw)

    def test_intermediate_reference_does_not_relabel_a_final_compound_heading(self):
        for label in INTERMEDIATE_LABELS:
            raw = f"Compound 12: Synthesis from {label} 7"
            with self.subTest(label=label):
                self.assertEqual(section_heading(raw)["role"], "compound_heading")
                self.assertFalse(nonfinal_original_label(raw))
                self.assertIsNone(source_exclusion(f"Compound {label}-12"))


if __name__ == "__main__":
    unittest.main()
