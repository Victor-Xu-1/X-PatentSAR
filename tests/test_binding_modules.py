"""Single binder ownership and real original-PDF module integration regressions."""

from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.binding_spatial import (
    SpatialBindings,
    _resolve_claim_conflicts,
    collect_spatial_bindings,
)
from patent_sar_extractor.core.binding_types import (
    BindingCandidate,
    SourceOwnership,
)
from patent_sar_extractor.core.structure_binder import bind


class BindingModuleTests(unittest.TestCase):
    def test_original_heading_tokens_are_complete_and_slash_groups_are_not_split(self):
        from patent_sar_extractor.core.binding_source_headings import (
            observed_heading_blocks,
        )

        with fitz.open() as doc:
            page = doc.new_page()
            labels = ["42", "42A", "1-2-3AB", "AB-12", "1/2"]
            for index, label in enumerate(labels):
                page.insert_text((72, 72 + index * 30), f"Compound {label}: Synthesis")
            blocks = observed_heading_blocks(doc, [0], {})
        self.assertEqual(
            [row["cpd"] for row in blocks],
            [f"Compound {label}" for label in labels[:-1]],
        )

    def test_unlabelled_generic_segments_never_invent_compound_ids(self):
        from patent_sar_extractor.core.binding_source_headings import (
            select_heading_bindings,
        )

        segments = [
            {
                "id": "S1",
                "idx": 1,
                "page_no": 1,
                "x0": 100.0,
                "y0": 100.0,
                "x1": 240.0,
                "y1": 200.0,
                "image_path": "missing.png",
            }
        ]
        with fitz.open() as document:
            document.new_page()
            with (
                patch(
                    "patent_sar_extractor.core.binding_source_headings._load_visible_label_cache",
                    return_value={},
                ),
                patch(
                    "patent_sar_extractor.core.binding_source_headings._refine_visible_label_cache_with_page_ocr",
                    return_value={},
                ),
            ):
                selection, issues = select_heading_bindings(
                    document,
                    segments,
                    [],
                    {},
                    "unused",
                    {},
                )
        self.assertEqual(selection, [])
        self.assertEqual(issues, [])

    def test_recognized_series_with_zero_pairings_reserves_its_sources(self):
        # Real series parser, no segmented molecules: withholding cannot give
        # a generic strategy ownership of these printed labels or pages.
        lines = {0: [(float(n * 80), f"I-{n}") for n in range(1, 7)]}
        with fitz.open() as document:
            document.new_page()
            spatial = collect_spatial_bindings(
                document,
                [],
                {0: ""},
                lines,
                [f"Compound {n}" for n in range(1, 7)],
                {"authoritative_structure_table_pages": [0]},
                frozenset({0}),
            )
        self.assertEqual(spatial.candidates, ())
        self.assertEqual(spatial.ownership.page_indices, frozenset({0}))
        self.assertEqual(
            spatial.ownership.label_keys, frozenset(str(n) for n in range(1, 7))
        )
        self.assertEqual(
            spatial.restore(
                [
                    {
                        "cpd": "Compound 1",
                        "structure_id": "synthetic-fallback",
                        "page_no": 2,
                    }
                ],
                ["Compound 1"],
            ),
            [],
        )

    def test_module_imports_are_explicit_acyclic_and_have_one_bind_and_writer(self):
        core = Path(__file__).resolve().parents[1] / "src/patent_sar_extractor/core"
        paths = [
            *core.glob("binding_*.py"),
            core / "visible_label_cache.py",
            core / "structure_binder.py",
        ]
        graph = {path.stem: set() for path in paths}
        definitions = {}
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    self.assertNotIn(node.name, definitions, node.name)
                    definitions[node.name] = path.stem
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertTrue(all(alias.name != "*" for alias in node.names))
                    dependency = (node.module or "").split(".")[-1]
                    if dependency in graph:
                        graph[path.stem].add(dependency)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotEqual(node.func.id, "globals")
        stack = []
        visited = set()

        def visit(module):
            self.assertNotIn(module, stack, f"Cycle: {stack} -> {module}")
            if module in visited:
                return
            stack.append(module)
            for dependency in graph[module]:
                visit(dependency)
            stack.pop()
            visited.add(module)

        for module in graph:
            visit(module)
        self.assertEqual(definitions["bind"], "structure_binder")
        self.assertEqual(definitions["write_binding_result"], "binding_artifacts")
        self.assertEqual(definitions["_merge_binding_candidates"], "binding_candidates")
        self.assertEqual(definitions["_get_ocr_line_coords"], "binding_ocr")
        self.assertEqual(
            list(inspect.signature(bind).parameters),
            [
                "pdf_path",
                "profile",
                "output_dir",
                "structures_path",
                "include_intermediates",
                "cpd_prefix_pattern",
            ],
        )

    def test_observed_conflicts_are_withheld_instead_of_ranked_as_success(self):
        candidates = [
            BindingCandidate(
                "7A",
                "S1",
                0,
                "exact_caption",
                MappingProxyType(
                    {"cpd": "Compound 7A", "structure_id": "S1", "page_no": 1}
                ),
            ),
            BindingCandidate(
                "7A",
                "S2",
                1,
                "exact_caption",
                MappingProxyType(
                    {"cpd": "Compound 7A", "structure_id": "S2", "page_no": 2}
                ),
            ),
            BindingCandidate(
                "8",
                "S3",
                1,
                "numbered_cell",
                MappingProxyType(
                    {"cpd": "Compound 8", "structure_id": "S3", "page_no": 2}
                ),
            ),
        ]
        accepted, conflicts = _resolve_claim_conflicts(candidates)
        self.assertEqual([candidate.label_key for candidate in accepted], ["8"])
        self.assertEqual(
            {conflict.reason for conflict in conflicts}, {"ambiguous_compound_owner"}
        )
        self.assertEqual({conflict.label_key for conflict in conflicts}, {"7A"})

    def test_one_segment_cannot_acquire_two_observed_compound_owners(self):
        candidates = [
            BindingCandidate(
                label,
                "S1",
                0,
                "exact_caption",
                MappingProxyType(
                    {"cpd": f"Compound {label}", "structure_id": "S1", "page_no": 1}
                ),
            )
            for label in ("7A", "7B")
        ]
        accepted, conflicts = _resolve_claim_conflicts(candidates)
        self.assertEqual(accepted, ())
        self.assertEqual(
            {conflict.reason for conflict in conflicts}, {"ambiguous_structure_owner"}
        )

    def test_generic_restore_cannot_promote_claimed_page_id_or_label(self):
        ownership = SourceOwnership(
            frozenset({0}), frozenset({"S-caption"}), frozenset({"7A"})
        )
        spatial = SpatialBindings((), ownership, (), True)
        candidates = [
            {"cpd": "Compound 1", "structure_id": "S-cell", "page_no": 1},
            {"cpd": "Compound 2", "structure_id": "S-caption", "page_no": 2},
            {"cpd": "Compound 7A", "structure_id": "S-alternative", "page_no": 3},
            {"cpd": "Compound 8", "structure_id": "S-unclaimed", "page_no": 3},
        ]
        self.assertEqual(
            [
                binding["cpd"]
                for binding in spatial.restore(
                    candidates,
                    ["Compound 1", "Compound 2", "Compound 7A", "Compound 8"],
                )
            ],
            ["Compound 8"],
        )

    def pdf_fixture(self, root, *, missing_second=False, extra_caption=False):
        pdf = root / "original.pdf"
        structures = []
        with fitz.open() as doc:
            page = doc.new_page()
            for x in (50, 100, 280):
                page.draw_line((x, 90), (x, 315))
            for y in (90, 115, 215, 315):
                page.draw_line((50, y), (280, y))
            page.insert_text((53, 105), "Cmpd No.", fontsize=7)
            page.insert_text((140, 105), "Structure", fontsize=9)
            for number, top in ((1, 125), (2, 225)):
                page.insert_text((65, top + 30), f"{number}.", fontsize=10)
                if missing_second and number == 2:
                    continue
                bounds = (110.0, float(top), 265.0, float(top + 80))
                image = root / f"segment-{number}.png"
                page.get_pixmap(clip=fitz.Rect(bounds)).save(image)
                structures.append(
                    {
                        "structure_id": f"S{number}",
                        "structure_index": number,
                        "page_no": 1,
                        "bbox_pdf": bounds,
                        "image_path": str(image),
                    }
                )
            if extra_caption:
                page = doc.new_page()
                bounds = (110.0, 125.0, 265.0, 205.0)
                page.insert_text((145, 220), "Compound 3A", fontsize=10)
                image = root / "caption.png"
                page.get_pixmap(clip=fitz.Rect(bounds)).save(image)
                structures.append(
                    {
                        "structure_id": "S3A",
                        "structure_index": 3,
                        "page_no": 2,
                        "bbox_pdf": bounds,
                        "image_path": str(image),
                    }
                )
            text_map = {index: page.get_text("text") for index, page in enumerate(doc)}
            doc.save(pdf)
        metadata = root / "metadata.json"
        metadata.write_text(
            json.dumps(
                {"patent_number": "MODULE-REGRESSION", "structures": structures}
            ),
            encoding="utf-8",
        )
        profile = {
            "structure_candidate_pages": list(text_map),
            "authoritative_structure_table_pages": [0],
            "authoritative_structure_table_cpds": ["Compound 1", "Compound 2"],
            "ocr_text_map": text_map,
            "ocr_line_map": {
                0: [{"y0": 155.0, "text": "1."}, {"y0": 255.0, "text": "2."}]
            },
        }
        return pdf, metadata, profile

    def test_complete_cells_and_suffix_caption_bypass_every_generic_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf, metadata, profile = self.pdf_fixture(root, extra_caption=True)
            profile["active_cpds"] = ["Compound 3A", "Compound 1", "Compound 2"]
            with (
                patch(
                    "patent_sar_extractor.core.structure_binder.observed_heading_blocks",
                    side_effect=AssertionError("Generic heading scan must not start"),
                ),
                patch(
                    "patent_sar_extractor.core.structure_binder.select_heading_bindings",
                    side_effect=AssertionError("Generic selection must not start"),
                ),
            ):
                result = bind(str(pdf), profile, str(root / "bindings"), str(metadata))
            self.assertEqual(
                [binding["cpd"] for binding in result["bindings"]],
                ["Compound 1", "Compound 2", "Compound 3A"],
            )
            self.assertEqual(result["detected_style"], "original_cell_caption_heading")
            self.assertEqual(result["bound"], 3)
            self.assertTrue(
                all(
                    binding["accuracy_status"] == "confirmed"
                    for binding in result["bindings"]
                )
            )
            saved = json.loads(Path(result["output_files"]["json"]).read_text())
            self.assertEqual(saved["final_bindings"], result["bindings"])

    def test_unsegmented_observed_cell_cannot_be_filled_by_generic_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf, metadata, profile = self.pdf_fixture(root, missing_second=True)
            profile["active_cpds"] = ["Compound 1", "Compound 2"]
            with patch(
                "patent_sar_extractor.core.structure_binder.select_heading_bindings",
                side_effect=AssertionError("Recognized grid may not compete"),
            ):
                result = bind(str(pdf), profile, str(root / "bindings"), str(metadata))
            self.assertEqual(
                [binding["cpd"] for binding in result["bindings"]], ["Compound 1"]
            )
            self.assertEqual(result["bound"], 1)

    def test_partial_cells_limit_generic_inputs_and_restoration_rejects_competitors(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf, metadata, profile = self.pdf_fixture(root)
            with fitz.open(pdf) as doc:
                doc.new_page().insert_text(
                    (72, 72), "Observed unclaimed original source, no exact caption"
                )
                replacement = root / "partial.pdf"
                doc.save(replacement)
            payload = json.loads(metadata.read_text())
            payload["structures"].append(
                {
                    "structure_id": "S3",
                    "structure_index": 3,
                    "page_no": 2,
                    "bbox_pdf": [110, 125, 265, 205],
                    "image_path": payload["structures"][0]["image_path"],
                }
            )
            metadata.write_text(json.dumps(payload), encoding="utf-8")
            profile["active_cpds"] = ["Compound 1", "Compound 2", "Compound 3"]
            profile["structure_candidate_pages"] = [0, 1]
            profile["ocr_text_map"][1] = (
                "Observed unclaimed original source, no exact caption"
            )
            competitors = [
                {"cpd": "Compound 1", "structure_id": "S3", "page_no": 2},
                {"cpd": "Compound 3", "structure_id": "S1", "page_no": 2},
            ]
            with (
                patch(
                    "patent_sar_extractor.core.structure_binder.observed_heading_blocks",
                    return_value=[{"cpd": "Compound 3", "page_no": 2, "y0": 72}],
                ),
                patch(
                    "patent_sar_extractor.core.structure_binder.select_heading_bindings",
                    return_value=(competitors, []),
                ) as selected,
            ):
                result = bind(
                    str(replacement), profile, str(root / "bindings"), str(metadata)
                )
            self.assertEqual(
                [structure["id"] for structure in selected.call_args.args[1]], ["S3"]
            )
            self.assertEqual(
                [block["cpd"] for block in selected.call_args.args[2]], ["Compound 3"]
            )
            self.assertEqual(
                [binding["cpd"] for binding in result["bindings"]],
                ["Compound 1", "Compound 2"],
            )
