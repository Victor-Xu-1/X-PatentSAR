"""Large original source populations, not OCSR or scientific acceptance."""

import unittest

import fitz

from patent_sar_extractor.core.activity_header_evidence import proof_id
from patent_sar_extractor.core.ruled_structure_headers import observe_ruled_header
from patent_sar_extractor.core.source_document import document_sha256
from patent_sar_extractor.core.structure_column_anchors import (
    column_anchor_roles,
    observe_column_anchor,
)
from patent_sar_extractor.core.structure_column_population import (
    column_population_issues,
)
from patent_sar_extractor.core.table_geometry import page_tokens


class StructureColumnPopulationTests(unittest.TestCase):
    def test_more_than_one_thousand_original_rows_keep_the_last_source_and_gap(self):
        count = 1205
        xs, ys = [40, 175, 380], [65, *[100 + 18 * n for n in range(count + 1)]]
        with fitz.open() as doc:
            page = doc.new_page(width=520, height=ys[-1] + 30)
            page.insert_text((40, 45), "Table A. Compounds", fontsize=10)
            page.insert_text((50, 80), "Compound No.", fontsize=10)
            page.insert_text((240, 80), "Structure", fontsize=10)
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            diagrams = []
            for n in range(count):
                top = ys[n + 1]
                page.insert_text((60, top + 11), f"C{n:06d}", fontsize=8)
                box = [215, top + 2, 355, top + 16]
                page.draw_rect(fitz.Rect(box))
                diagrams.append({"id": f"S{n}", "bbox": box})
            tokens = page_tokens(page)
            header = observe_ruled_header(
                page, tokens, {"xs": xs, "ys": ys}, document_sha256(doc)
            )
            self.assertEqual(
                header["role_cells"]["observations"][0]["method"], "native_cells"
            )
            source = observe_column_anchor(tokens, header, diagrams)
            roles = column_anchor_roles(source)
            identity = proof_id(source)
            section = {
                "role": "structure_column_anchor",
                "page_no": 1,
                "region_id": identity,
                "source": source,
            }
            represented = {
                (identity, n + 1, 0): [{"structure_id": f"S{n}"}] for n in range(count)
            }
            self.assertEqual(column_population_issues(section, roles, represented), [])
            represented.pop((identity, 1104, 0))
            issues = column_population_issues(section, roles, represented)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]["row"], 1104)
            self.assertEqual(issues[0]["observed_structures"], ["S1103"])
