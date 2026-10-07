from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from patent_sar_extractor.application.activity_policy import (
    _activity_acceptance_errors,
    _extract_active_cpds,
)
from patent_sar_extractor.application.binding_policy import (
    _binding_acceptance_errors,
    _load_reusable_bindings,
)
from patent_sar_extractor.application.pipeline_io import (
    _elapsed_since,
    _strict_gates_enabled,
)
from patent_sar_extractor.application.smiles_policy import (
    _smiles_acceptance_errors,
    _smiles_results_can_be_reused,
)
from patent_sar_extractor.application.stage_cache import (
    _write_step_manifest,
)
from patent_sar_extractor.application.structure_cache import (
    _load_reusable_structure_chunk,
    _merge_structure_chunk_metadata,
    _structure_chunk_fingerprint,
)
from patent_sar_extractor.application.worker_policy import (
    _activity_timeout_seconds,
    _gpu_env_extra,
    _production_smiles_ocr_options,
)
from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    PAGE_CLASSIFICATION_SCHEMA,
    PAGE_CLASSIFICATION_SCHEMA_VERSION,
    REVIEW_EXCERPT_METADATA_SCHEMA,
    REVIEW_EXCERPT_METADATA_SCHEMA_VERSION,
    STEREO_EVIDENCE_VERSION,
    STRUCTURES_SCHEMA,
    STRUCTURES_SCHEMA_VERSION,
    VISIBLE_LABEL_CACHE_SCHEMA,
    VISIBLE_LABEL_CACHE_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
    ruleset_ref,
)
from patent_sar_extractor.core import (
    activity_coordinates as activity_coordinates_module,
)
from patent_sar_extractor.core import (
    binding_observations,
    binding_spatial,
)
from patent_sar_extractor.core import env_runner as env_runner_module
from patent_sar_extractor.core import page_ocr_cache as page_ocr_cache_module
from patent_sar_extractor.core.activity_coordinates import (
    coordinate_candidates,
    extract_coordinate_tables,
)
from patent_sar_extractor.core.activity_headers import infer_value_keys
from patent_sar_extractor.core.activity_models import ActivityRow
from patent_sar_extractor.core.activity_observations import (
    has_usable_values,
    merge_rows,
)
from patent_sar_extractor.core.activity_text import extract_text_tables
from patent_sar_extractor.core.binding_arbitration import _drop_fail_closed_bindings
from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.core.binding_candidates import _merge_binding_candidates
from patent_sar_extractor.core.binding_spatial import (
    _enforce_authoritative_structure_table_source,
)
from patent_sar_extractor.core.binding_tables import _extract_structure_table_bindings
from patent_sar_extractor.core.formal_export import qualified_records
from patent_sar_extractor.core.formal_structure import (
    FORMAL_SCOPE,
    SOURCE_EXECUTION_MODE,
)
from patent_sar_extractor.core.health_check import (
    _parse_tensorflow_gpu_probe,
    _tensorflow_gpu_probe_is_compatible,
)
from patent_sar_extractor.core.ocsr import run_smiles as run_smiles_module
from patent_sar_extractor.core.ocsr import smiles_converter as smiles_converter_module
from patent_sar_extractor.core.ocsr.run_smiles import (
    validate_strict_binding_input,
    validate_strict_smiles_results,
)
from patent_sar_extractor.core.ocsr.smiles_cache import (
    SmilesCache,
    compute_image_sha256,
)
from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import check_source_stereochemistry
from patent_sar_extractor.core.page_classifier import classify_pdf
from patent_sar_extractor.core.page_ocr_cache import (
    build_cache_metadata,
    load_page_ocr_cache,
    update_page_ocr_cache,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.qa_files import _read_xlsx_values
from patent_sar_extractor.core.qa_report import build_qa_report, write_qa_report
from patent_sar_extractor.core.review_excerpt import create_review_excerpt_pdf
from patent_sar_extractor.core.runtime_env import tensorflow_cuda_caps_support_gpu
from patent_sar_extractor.core.structure_page_evidence import _is_structure_table_page
from patent_sar_extractor.core.structure_page_locator import _covered_active_cpds
from patent_sar_extractor.smiles_artifact import build_smiles_artifact

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


class StrictAcceptanceTests(unittest.TestCase):
    def _write_json(self, path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _image(self, directory: Path, name: str) -> str:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (160, 100), "white")
        ImageDraw.Draw(image).line(
            [(20, 30), (60, 60), (100, 30)], fill="black", width=2
        )
        image.save(path)
        return str(path)

    def _text_pdf(self, path: Path, page_texts: list[str]) -> None:
        import fitz

        doc = fitz.open()
        try:
            for text in page_texts:
                page = doc.new_page()
                page.insert_text((72, 72), text)
            doc.save(path)
        finally:
            doc.close()

    def _labeled_structure_image(
        self, directory: Path, name: str, label: str = "110"
    ) -> str:
        from PIL import Image, ImageDraw

        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (240, 96), "white")
        draw = ImageDraw.Draw(img)
        # A simple molecule-like trace in the upper band plus a printed
        # compound number below it.  The number must not be sent to OCSR.
        draw.line(
            [(20, 30), (70, 18), (120, 30), (170, 18), (220, 30)], fill="black", width=3
        )
        draw.text((108, 70), label, fill="black")
        img.save(path)
        return str(path)

    @staticmethod
    def _binding(cpd: str, structure_id: str, image_path: str) -> dict:
        return {
            "cpd": cpd,
            "cpd_id": cpd,
            "compound_id": cpd,
            "structure_id": structure_id,
            "image_path": image_path,
            "display_image_path": image_path,
            "binding_rule": "direct_structure_label",
            "visible_label_candidates": [{"label": cpd, "source": "page_strict"}],
            "accuracy_status": "confirmed",
            "evidence_tier": "strong",
            "fail_closed": False,
        }

    def test_merge_direct_visual_label_prefers_upper_final_product_over_lower_route_crop(
        self,
    ):
        top_product = {
            "cpd": "Compound 81",
            "cpd_id": "Compound 81",
            "compound_id": "Compound 81",
            "structure_id": "S0348",
            "structure_index": 348,
            "page_no": 164,
            "image_path": "top-product.png",
            "binding_rule": "direct_structure_label",
            "visible_label": "81",
            "visible_label_candidates": [{"label": "81", "source": "page_strict"}],
            "visual_label_source": "cache_confirmed",
            "product_context_nearby": True,
            "product_context_distance": 0,
            "struct_x0": 215.04,
            "struct_y0": 186.72,
            "struct_width": 193.92,
            "struct_height": 63.84,
            "struct_area": 12380.09,
            "fail_closed": False,
        }
        lower_route_crop = {
            "cpd": "Compound 81",
            "cpd_id": "Compound 81",
            "compound_id": "Compound 81",
            "structure_id": "S0351",
            "structure_index": 351,
            "page_no": 164,
            "image_path": "lower-route-crop.png",
            "binding_rule": "direct_structure_label",
            "visible_label": "81",
            "visible_label_candidates": [{"label": "81", "source": "page_strict"}],
            "visual_label_source": "cache_confirmed",
            "product_context_nearby": True,
            "product_context_distance": 0,
            "struct_x0": 249.6,
            "struct_y0": 264.48,
            "struct_width": 289.44,
            "struct_height": 62.88,
            "struct_area": 18199.99,
            "fail_closed": False,
        }

        merged = _merge_binding_candidates(
            [lower_route_crop], [top_product], active_cpds=["Compound 81"]
        )

        self.assertEqual("S0348", merged[0]["structure_id"])

    def test_pair_heading_order_binding_is_confirmed_when_strict_ocr_reads_suffix_only(
        self,
    ):
        binding = {
            "cpd": "Compound 5-1",
            "compound_id": "Compound 5-1",
            "structure_id": "S0041",
            "page_no": 76,
            "binding_rule": "ocr_pair_heading_structure_order",
            "visible_label": "1",
            "visible_labels": ["1"],
            "visible_label_candidates": [{"label": "1", "source": "page_strict"}],
            "pair_heading_sequence_confirmed": True,
            "pair_heading_base": 5,
            "pair_heading_suffix": "1",
            "struct_width": 156.48,
            "struct_height": 102.24,
            "struct_area": 16006.0,
        }

        checked = annotate_binding_accuracy(binding)

        self.assertEqual("confirmed", checked["accuracy_status"])
        self.assertFalse(checked["fail_closed"])

    def test_cpd_letter_pair_order_binding_ignores_partner_a_label_bleed(self):
        binding = {
            "cpd": "Compound 6",
            "compound_id": "Compound 6",
            "structure_id": "S0050",
            "page_no": 34,
            "binding_rule": "cpd_letter_pair_row_order",
            "visible_label": "6A",
            "visible_labels": ["6A"],
            "visible_label_candidates": [{"label": "6A", "source": "page_strict"}],
            "cpd_letter_pair_sequence_confirmed": True,
            "cpd_letter_pair_partner": "6A",
            "struct_width": 155.0,
            "struct_height": 190.0,
            "struct_area": 29450.0,
        }

        checked = annotate_binding_accuracy(binding)

        self.assertEqual("confirmed", checked["accuracy_status"])
        self.assertFalse(checked["fail_closed"])

    @staticmethod
    def _smiles(cpd: str, structure_id: str, raw: str) -> dict:
        checked = qc_smiles(raw)
        return {
            "image_hash": "a" * 64,
            "stereochemistry": check_source_stereochemistry(
                checked,
                {
                    "version": STEREO_EVIDENCE_VERSION,
                    "image_sha256": "a" * 64,
                    "image_size": [100, 100],
                    "unknown_bond_boxes": [],
                },
            ),
            "cpd_id": cpd,
            "structure_id": structure_id,
            "raw_smiles": raw,
            "canonical_smiles": checked["canonical_smiles"],
            "inchikey": checked["inchikey"],
            "mol_formula": checked["mol_formula"],
            "mol_weight": checked["mol_weight"],
            "ring_count": checked["ring_count"],
            "chiral_centers": checked["chiral_centers"],
            "rdkit_valid": checked["rdkit_valid"],
            "OCSR_quality_flag": checked["quality_flag"],
            "suspicious_elements": checked["suspicious_elements"],
        }

    def test_smiles_qc_rejects_suspicious_element(self) -> None:
        suspicious = qc_smiles("CC[Cu]")
        clean = qc_smiles("CCCl")
        self.assertTrue(suspicious["rdkit_valid"])
        self.assertEqual(suspicious["quality_flag"], "suspicious_element")
        self.assertEqual(suspicious["suspicious_elements"], ["Cu"])
        self.assertFalse(smiles_converter_module._is_clean_rdkit_result(suspicious))
        self.assertEqual(clean["quality_flag"], "ok")
        self.assertTrue(smiles_converter_module._is_clean_rdkit_result(clean))

    def test_ocsr_qc_preserves_cf_and_detached_text_noise_for_review(self) -> None:
        raw = (
            "CC.C[CH3+].N#Cc1ccc(OCCNC(=O)c2ccc(N3CCC(CC3)Cc3ccc4c(c3)noc4C3CCC(=O)NC3=O)nn2)"
            "cc1[Cf].[CH3+].[CH3+]"
        )

        cleaned, checked, _dummy_cleanup = smiles_converter_module._qc_ocr_smiles(raw)

        self.assertEqual(cleaned, raw)
        self.assertIn("[Cf]", cleaned or "")
        self.assertIn(".", cleaned or "")
        self.assertNotEqual(checked["quality_flag"], "ok")
        self.assertFalse(smiles_converter_module._is_clean_rdkit_result(checked))

    def test_ocsr_qc_refuses_to_invent_a_ring_digit_repair(self) -> None:
        raw = (
            r"C1=CC2=C(CCN(C1)C3CC(C3)N4CCC(CC4)N5C=CC(=NC5)C(=O)"
            r"N[C@@H]6CC[C@H](CC6)OC7=CC=C(C#N)C(=C7)Cl)C8=C1C"
            r"(=C(NC(=O)/C=C\C(=O)O)O8)C9CCC(=O)NC9=O"
        )

        cleaned, checked, _dummy_cleanup = smiles_converter_module._qc_ocr_smiles(raw)

        self.assertEqual(cleaned, raw)
        self.assertEqual(checked["quality_flag"], "invalid_smiles")
        self.assertNotIn("ocr_repair", checked)
        self.assertFalse(smiles_converter_module._is_clean_rdkit_result(checked))

    def test_activity_merge_preserves_source_order_and_flags_conflicts(self) -> None:
        rows = [
            ActivityRow(
                cpd="Compound 8",
                activity_values={"IC50": "A"},
                cell_line_data={"Dmax": "60"},
                confidence=0.95,
            ),
            ActivityRow(
                cpd="Compound 2", activity_values={"IC50": "B"}, confidence=0.95
            ),
            ActivityRow(
                cpd="Compound 8",
                activity_values={"IC50": "C"},
                cell_line_data={"Dmax": "61"},
                confidence=0.75,
            ),
        ]
        merged = merge_rows(rows)
        self.assertEqual(
            [row.cpd for row in merged], ["Compound 8", "Compound 2", "Compound 8"]
        )
        self.assertEqual(merged[0].activity_values["IC50"], "A")
        self.assertEqual(merged[0].cell_line_data["Dmax"], "60")
        self.assertEqual(merged[2].activity_values["IC50"], "C")
        self.assertEqual(merged[2].cell_line_data["Dmax"], "61")

    def test_ruled_ar_degradation_schema_requires_observed_order_and_units(
        self,
    ) -> None:
        self.assertEqual(
            infer_value_keys(
                "AR degradation", "No. LNCaP AR Dmax (%) LNCaP AR DC50 (nM)", 2
            ),
            ["LNCaP AR Dmax (%)", "LNCaP AR DC50 (nM)"],
        )
        self.assertEqual(
            infer_value_keys("AR degradation", "No. DC50", 1), ["DC50 (unit unknown)"]
        )

    def test_prefixed_letter_grade_activity_table_decodes_legend_and_continuation(
        self,
    ) -> None:
        page_texts = {
            "0": (
                "The IRF5 HiBiT degradation results are shown in the table below. "
                "The letter codes for DC5o (nM) include: A (<1 nM); "
                "B (1 - 10 nM); G (not tested). Table 10. IRF5 HiBiT Degradation "
                "I-# IRF5-HiBiT-B8, DC5o (nM) I-1 A 1-2 G"
            ),
            "1": "IRF5 HiBiT deg. I-# DC5o (nM) I-3 B",
        }

        rows = extract_text_tables([0, 1], page_texts).rows

        self.assertEqual(
            [row.cpd for row in rows], ["Compound I-1", "Compound 1-2", "Compound I-3"]
        )
        self.assertEqual(list(rows[0].activity_values.values()), ["<1 nM"])
        self.assertEqual(list(rows[1].activity_values.values()), ["not tested"])
        self.assertEqual(list(rows[2].activity_values.values()), ["1 - 10 nM"])
        self.assertTrue(has_usable_values(rows[0]))
        self.assertFalse(has_usable_values(rows[1]))
        self.assertIn("source label 1-2", rows[1].notes)

    def test_explicit_not_tested_activity_is_excluded_across_command_annotation(
        self,
    ) -> None:
        payload = {
            "rows": [
                {"cpd": "Compound 1", "activity_values": {"DC50": "not tested"}},
                {"cpd": "Compound 2", "activity_values": {"DC50": "ND"}},
                {"cpd": "Compound 3", "activity_values": {"DC50": "> 10,000 nM"}},
            ],
        }

        self.assertEqual(_extract_active_cpds(payload), ["Compound 3"])

    def test_coordinate_activity_candidates_exclude_synthesis_unit_noise(self) -> None:
        page_texts = {
            "0": "Step 2 product was prepared in 1 mL DMSO at 25 C with 4 nM impurity.",
            "1": "Table 10 IRF5 HiBiT degradation DC5o (nM) I-1 A I-2 B",
            "2": "IRF5 HiBiT deg. DC5o (nM) I-3 B I-4 C",
        }

        self.assertEqual(
            coordinate_candidates([0, 1, 2], page_texts),
            [1, 2],
        )

    def test_ruled_activity_detection_precedes_coordinate_ocr(self) -> None:
        with (
            patch.object(
                activity_coordinates_module,
                "detect_ruled_table_regions",
                return_value=[],
            ),
            patch.object(
                activity_coordinates_module,
                "page_tokens",
                side_effect=AssertionError(
                    "coordinate OCR must not run without a detected grid"
                ),
            ),
        ):
            self.assertEqual(extract_coordinate_tables([object()], [0]).rows, [])

    def test_page_ocr_cache_rejects_foreign_legacy_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / "WO2026041143.pdf"
            cache_path = root / "page_ocr_cache.json"
            self._text_pdf(
                pdf_path,
                [
                    "WO2026041143 current patent activity IC50 table",
                    "WO2026041143 current patent synthesis examples",
                ],
            )
            stale_pages = {
                str(i): "WO 2024/037616 stale cache text" for i in range(220)
            }
            current_metadata = build_cache_metadata(str(pdf_path), total_pages=2)
            legacy_metadata = {
                "cache_version": "pdf_identity_v1",
                "pdf_sha256": current_metadata["pdf_sha256"],
                "pdf_size": current_metadata["pdf_size"],
                "page_count": current_metadata["page_count"],
            }
            cache_path.write_text(
                json.dumps(
                    {
                        "metadata": legacy_metadata,
                        "page_texts": stale_pages,
                        "ocr_line_map": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            cache = update_page_ocr_cache(
                str(pdf_path),
                [0, 1],
                str(cache_path),
                workers=1,
                min_native_chars=5,
            )

            self.assertIn("WO2026041143 current patent", cache["page_texts"]["0"])
            self.assertNotIn("WO 2024/037616", cache["page_texts"]["0"])
            loaded = load_page_ocr_cache(str(cache_path))
            self.assertEqual(loaded.get("metadata", {}).get("page_count"), 2)

    def test_page_ocr_cache_refills_empty_current_pdf_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / "WO2026041143.pdf"
            cache_path = root / "page_ocr_cache.json"
            self._text_pdf(pdf_path, ["WO2026041143 current patent example 1"])

            cache = update_page_ocr_cache(
                str(pdf_path),
                [0],
                str(cache_path),
                workers=1,
                min_native_chars=5,
            )
            cache["page_texts"]["0"] = ""
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False), encoding="utf-8"
            )

            refilled = update_page_ocr_cache(
                str(pdf_path),
                [0],
                str(cache_path),
                workers=1,
                min_native_chars=5,
            )

            self.assertIn("WO2026041143 current patent", refilled["page_texts"]["0"])

    def test_parallel_page_cache_skips_ocr_engine_for_native_text_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf_path = root / "native-text.pdf"
            cache_path = root / "page_ocr_cache.json"
            self._text_pdf(
                pdf_path,
                [
                    "Example 1 synthesis description with enough native text for deterministic classification.",
                    "Table 1 activity IC50 data with enough native text for deterministic classification.",
                ],
            )

            with patch.object(
                page_ocr_cache_module,
                "_build_ocr_engine",
                side_effect=AssertionError(
                    "OCR engine must not load for native-text pages"
                ),
            ):
                cache = update_page_ocr_cache(
                    str(pdf_path),
                    [0, 1],
                    str(cache_path),
                    workers=2,
                    min_native_chars=30,
                    force=True,
                )

            self.assertEqual(set(cache["page_texts"]), {"0", "1"})

    def test_clean_chinese_dc50_dmax_rows_are_auto_accepted(self) -> None:
        rows = extract_text_tables(
            [0],
            text_map={
                "0": (
                    "表1化合物对Jurkat细胞VAV1蛋白的降解活性\n"
                    "化合物编号 DC50(nM) Dmax(%)\n"
                    "化合物1 A 98.1\n"
                    "化合物6 A 97\n"
                    "化合物65 A 97.7\n"
                    "化合物70 A 96\n"
                    "* DC50≤10nM为A"
                )
            },
        ).rows

        self.assertEqual(
            [row.cpd for row in rows],
            ["Compound 1", "Compound 6", "Compound 65", "Compound 70"],
        )
        self.assertTrue(all(not row.needs_review for row in rows))
        self.assertTrue(all(row.confidence >= 0.88 for row in rows))

    def test_activity_merging_never_discards_an_unrelated_context(self) -> None:
        noisy = ActivityRow(
            cpd="Compound 1",
            activity_values={
                "DC50(nμM)": "A",
                "Dmax(%)": "98.1",
                "表2化合物小鼠PK参数 value 1": "8557",
            },
            page_no=53,
            table_id="表1/表2",
            source="ocr_text_table_flat",
            confidence=0.5,
            needs_review=True,
            notes="Generic OCR flat text-table extraction from Chinese/English mixed activity table.",
        )
        specific = ActivityRow(
            cpd="Compound 1",
            activity_values={
                "Jurkat VAV1 DC50 grade": "A",
                "Jurkat VAV1 Dmax (%)": "98.1",
            },
            page_no=53,
            table_id="表1",
            source="ocr_chinese_dc50_dmax",
            confidence=0.9,
            needs_review=False,
        )

        merged = merge_rows([noisy, specific])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0].needs_review)
        self.assertEqual(
            merged[0].activity_values["表2化合物小鼠PK参数 value 1"], "8557"
        )
        self.assertEqual(merged[0].activity_values["Jurkat VAV1 Dmax (%)"], "98.1")

    def test_flattened_structure_table_continuation_pages_are_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / "flattened_structure_table.pdf"
            out_dir = root / "classification"
            self._text_pdf(
                pdf_path,
                [
                    "Compound No Structure Chemical Name LC-MS 7 phenyl dione 399.1 8 pyridine dione 300.1",
                    (
                        "63 phenyl dione 387.1 64 pyridine dione 449.1 "
                        "65 thienyl dione 467.0 70 oxazole dione 459.1"
                    ),
                    "测试例1 化合物对Jurkat细胞VAV1蛋白的降解活性 DC50 Dmax 化合物65 A 97.7",
                ],
            )

            result = classify_pdf(str(pdf_path), str(out_dir), force_ocr_cache=True)

            self.assertIn(1, result["synthesis_pages"])
            self.assertIn(2, result["activity_pages"])
            self.assertTrue(
                artifact_identity_matches(
                    result,
                    PAGE_CLASSIFICATION_SCHEMA,
                    PAGE_CLASSIFICATION_SCHEMA_VERSION,
                )
            )
            self.assertIn("candidate_pages", result)
            self.assertNotIn("core_pages", result)
            self.assertFalse((root / "core_pdf").exists())

    def test_review_excerpt_is_versioned_and_isolated_from_formal_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / "input.pdf"
            excerpt_path = root / "review_excerpt.pdf"
            metadata_path = root / "review_excerpt_metadata.json"
            self._text_pdf(
                pdf_path,
                [
                    "Background and summary",
                    "Example 1 Preparation of Compound 1 MS m/z 301.2 yield 75%",
                    "What is claimed is: 1. A compound",
                ],
            )

            metadata = create_review_excerpt_pdf(
                str(pdf_path),
                str(excerpt_path),
                str(metadata_path),
            )

            self.assertTrue(excerpt_path.is_file())
            self.assertTrue(metadata_path.is_file())
            self.assertTrue(
                artifact_identity_matches(
                    metadata,
                    REVIEW_EXCERPT_METADATA_SCHEMA,
                    REVIEW_EXCERPT_METADATA_SCHEMA_VERSION,
                )
            )
            self.assertGreaterEqual(metadata["page_count_excerpt"], 1)
            self.assertNotIn("page_count_core", metadata)

    def test_abbreviated_ex_structure_table_pages_are_classified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf_path = root / "abbreviated-structure-table.pdf"
            output_dir = root / "classification"
            self._text_pdf(
                pdf_path,
                [
                    "Table 1 Ex. Structure 7 25 NH2 40 41 42 43",
                    "Ex. Structure 27 HN 35 43 50 NH2 51 53 NH 41",
                ],
            )

            result = classify_pdf(str(pdf_path), str(output_dir), force_ocr_cache=True)

            self.assertEqual(result["synthesis_pages"], [0, 1])

    def test_locator_accepts_flattened_structure_table_rows(self) -> None:
        flattened = (
            "63 3-(2-氯-3-{5-[(1,3-恶唑-2-基)甲基]噻吩-2-基}苯基)哌啶-2.6-二酮 387.1 "
            "64 3-(2-氯-3-{5-[3-(二氟甲基)-2-氧代吡啶-1(2H)-基]噻吩-2-基}苯基)哌啶-2.6-二酮 449.1 "
            "65 3-(2-氯-3-{5-[2-氧代-3-(三氟甲基)吡啶-1(2H)-基]噻吩-2-基}苯基)哌啶-2.6-二酮 467.0 "
            "70 3-(2-氯-3-{5-[3-甲氧基-2-氧代吡啶-1(2H)-基]噻吩-2-基}苯基)哌啶-2.6-二酮 459.1"
        )

        self.assertTrue(_is_structure_table_page(flattened))

    def test_locator_accepts_prefixed_series_structure_table_and_continuations(
        self,
    ) -> None:
        header = "Table 1. Exemplary Compounds I-# Structure I-1 I-2"
        continuation = "WO2026/156070 PCT/US2026/011254 1-3 I-4 1-5 I-6 361"
        prose = (
            "Intermediate I-3 was dissolved in DCM and stirred overnight. "
            "The resulting material was purified by chromatography and analyzed by NMR."
        )

        self.assertTrue(_is_structure_table_page(header))
        self.assertTrue(_is_structure_table_page(continuation))
        self.assertFalse(_is_structure_table_page(prose))
        self.assertEqual(
            _covered_active_cpds(
                [10, 11],
                {10: header, 11: continuation},
                ["Compound 1", "Compound 3", "Compound 6"],
            ),
            {
                "Compound 1": [10],
                "Compound 3": [11],
                "Compound 6": [11],
            },
        )

    def test_binder_binds_flattened_structure_table_continuation_rows(self) -> None:
        structures = [
            {
                "id": "S0111",
                "idx": 111,
                "page_no": 50,
                "x0": 161.3,
                "y0": 260.6,
                "x1": 335.5,
                "y1": 325.9,
                "image_path": "/tmp/s111.png",
            },
            {
                "id": "S0115",
                "idx": 115,
                "page_no": 50,
                "x0": 164.6,
                "y0": 629.3,
                "x1": 332.2,
                "y1": 731.0,
                "image_path": "/tmp/s115.png",
            },
        ]
        pages_text = {
            49: (
                "63 phenyl dione 387.1 64 pyridine dione 449.1 "
                "65 thienyl dione 467.0 66 pyridine dione 429.1 "
                "70 oxazole dione 459.1"
            )
        }
        ocr_line_map = {
            49: [
                {"y0": 257.28, "text": "65"},
                {"y0": 289.92, "text": "467.0"},
                {"y0": 633.6, "text": "70"},
                {"y0": 677.76, "text": "459.1"},
            ]
        }

        bindings = _extract_structure_table_bindings(
            structures,
            pages_text,
            ["Compound 65", "Compound 70"],
            [],
            ocr_line_map=ocr_line_map,
        )

        self.assertEqual(
            [(binding["cpd"], binding["structure_id"]) for binding in bindings],
            [("Compound 65", "S0111"), ("Compound 70", "S0115")],
        )

    def test_authoritative_series_table_pairs_noncontiguous_labels_by_page_geometry(
        self,
    ) -> None:
        structures = [
            {
                "id": "S0001",
                "idx": 1,
                "page_no": 10,
                "x0": 150.0,
                "y0": 100.0,
                "x1": 360.0,
                "y1": 200.0,
                "image_path": "/tmp/s0001.png",
            },
            {
                "id": "S0003",
                "idx": 3,
                "page_no": 10,
                "x0": 150.0,
                "y0": 300.0,
                "x1": 360.0,
                "y1": 400.0,
                "image_path": "/tmp/s0003.png",
            },
        ]
        ocr_line_map = {
            9: [
                {"y0": 150.0, "text": "1-1"},
                {"y0": 250.0, "text": "I-2"},
                {"y0": 350.0, "text": "I-3"},
                {"y0": 450.0, "text": "I-4"},
                {"y0": 550.0, "text": "I-5"},
                {"y0": 650.0, "text": "I-6"},
            ]
        }

        bindings = (
            binding_spatial._extract_authoritative_structure_table_sequence_bindings(
                structures,
                {},
                ["Compound 1", "Compound 3"],
                {"authoritative_structure_table_pages": [9]},
                ocr_line_map=ocr_line_map,
            )
        )

        self.assertEqual(
            [(binding["cpd"], binding["structure_id"]) for binding in bindings],
            [("Compound 1", "S0001"), ("Compound 3", "S0003")],
        )
        self.assertTrue(
            all(
                binding["authoritative_table_sequence_confirmed"]
                for binding in bindings
            )
        )

    def test_authoritative_series_table_resolves_duplicated_out_of_sequence_source_label(
        self,
    ) -> None:
        structures = []
        lines = []
        source_labels = [1254, 1255, 1266, 1257, 1265, 1266, 1267]
        for idx, source_label in enumerate(source_labels):
            y0 = 100.0 + idx * 120.0
            structures.append(
                {
                    "id": f"S{idx:04d}",
                    "idx": idx,
                    "page_no": 10,
                    "x0": 150.0,
                    "y0": y0,
                    "x1": 360.0,
                    "y1": y0 + 100.0,
                    "image_path": f"/tmp/s{idx:04d}.png",
                }
            )
            lines.append({"y0": y0 + 50.0, "text": f"I-{source_label}"})

        bindings = (
            binding_spatial._extract_authoritative_structure_table_sequence_bindings(
                structures,
                {},
                [
                    "Compound 1254",
                    "Compound 1255",
                    "Compound 1256",
                    "Compound 1257",
                    "Compound 1265",
                    "Compound 1266",
                    "Compound 1267",
                ],
                {"authoritative_structure_table_pages": [9]},
                ocr_line_map={9: lines},
            )
        )

        self.assertEqual(
            [binding["cpd"] for binding in bindings],
            [
                "Compound 1254",
                "Compound 1255",
                "Compound 1256",
                "Compound 1257",
                "Compound 1265",
                "Compound 1266",
                "Compound 1267",
            ],
        )
        corrected = next(
            binding for binding in bindings if binding["cpd"] == "Compound 1256"
        )
        self.assertEqual(corrected["authoritative_table_source_label"], "I-1266")
        self.assertTrue(corrected["authoritative_table_label_corrected"])
        self.assertIn(
            "duplicated and out of sequence",
            corrected["authoritative_table_label_correction_reason"],
        )

    def test_binder_does_not_treat_synthesis_routes_as_flattened_tables(self) -> None:
        structures = [
            {
                "id": "S0001",
                "idx": 1,
                "page_no": 40,
                "x0": 150.0,
                "y0": 250.0,
                "x1": 330.0,
                "y1": 330.0,
                "image_path": "/tmp/s0001.png",
            },
            {
                "id": "S0002",
                "idx": 2,
                "page_no": 40,
                "x0": 155.0,
                "y0": 380.0,
                "x1": 335.0,
                "y1": 455.0,
                "image_path": "/tmp/s0002.png",
            },
        ]
        pages_text = {
            39: (
                "化合物6的合成路线如下所示 中间体A4 1-2 第一步 反应液 加入 "
                "phenyl dione LC-MS 405.1 第二步 pyridine dione 目标化合物6 407.1"
            )
        }
        ocr_line_map = {
            39: [
                {"y0": 248.0, "text": "1"},
                {"y0": 300.0, "text": "405.1"},
                {"y0": 379.0, "text": "6"},
                {"y0": 430.0, "text": "407.1"},
            ]
        }

        bindings = _extract_structure_table_bindings(
            structures,
            pages_text,
            ["Compound 1", "Compound 6"],
            [],
            ocr_line_map=ocr_line_map,
        )

        self.assertEqual(bindings, [])

    def test_visible_label_cache_drops_signature_mismatches_when_ocr_is_unavailable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_path = self._image(base, "structure.png")
            struct = {
                "id": "S0001",
                "page_no": 1,
                "x0": 10.0,
                "y0": 20.0,
                "x1": 140.0,
                "y1": 120.0,
                "image_path": image_path,
            }
            stale_cache = {
                "S0001": {
                    **artifact_identity(
                        VISIBLE_LABEL_CACHE_SCHEMA, VISIBLE_LABEL_CACHE_SCHEMA_VERSION
                    ),
                    "structure_id": "S0001",
                    "page_no": 99,
                    "structure_signature": {
                        "page_no": 99,
                        "bbox": [0.0, 0.0, 1.0, 1.0],
                        "image_sha1": "stale",
                    },
                    "visible_labels": ["6"],
                    "visible_label_candidates": [
                        {"label": "6", "source": "page_strict"}
                    ],
                    "cache_complete": True,
                }
            }

            cache = binding_observations._filter_visible_label_cache_for_structures(
                stale_cache, [struct]
            )

            self.assertNotIn("S0001", cache)
            self.assertEqual(
                binding_observations._visible_label_candidates_for_structure(
                    struct, cache
                ),
                [],
            )

    def test_visible_label_cache_rejects_legacy_integer_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            struct = {
                "id": "S0001",
                "page_no": 1,
                "x0": 10.0,
                "y0": 20.0,
                "x1": 140.0,
                "y1": 120.0,
                "image_path": self._image(base, "structure.png"),
            }
            legacy = {
                "cache_version": 7,
                "cache_complete": True,
                "structure_signature": binding_observations._structure_cache_signature(
                    struct
                ),
            }

            self.assertFalse(
                binding_observations._visible_cache_item_matches_structure(
                    legacy, struct
                )
            )

    def test_strict_visual_label_allows_short_internal_numeric_annotations(
        self,
    ) -> None:
        binding = self._binding("Compound 121", "S121", "/tmp/structure_121.png")
        binding.update(
            {
                "visible_label_candidates": [
                    {"label": "121", "source": "page_strict"},
                    {"label": "2", "source": "page_strict"},
                ],
                "visible_labels": ["2", "121"],
                "struct_area": 8984,
                "struct_width": 193,
                "struct_height": 47,
                "product_context_nearby": True,
                "product_context_distance": 0,
            }
        )

        checked = annotate_binding_accuracy(binding)

        self.assertEqual(checked["accuracy_status"], "confirmed")
        self.assertFalse(checked["fail_closed"])

        merged_fragment = dict(binding)
        merged_fragment["binding_rule"] = "direct_structure_label_merged_fragment"
        checked_merged = annotate_binding_accuracy(merged_fragment)
        self.assertEqual(checked_merged["accuracy_status"], "confirmed")
        self.assertFalse(checked_merged["fail_closed"])

        two_digit_target = dict(binding)
        two_digit_target["cpd"] = two_digit_target["cpd_id"] = two_digit_target[
            "compound_id"
        ] = "Compound 18"
        two_digit_target["visible_label_candidates"] = [
            {"label": "18", "source": "page_strict"},
            {"label": "10", "source": "page_strict"},
        ]
        two_digit_target["visible_labels"] = ["10", "18"]
        checked_two_digit = annotate_binding_accuracy(two_digit_target)
        self.assertEqual(checked_two_digit["accuracy_status"], "confirmed")
        self.assertFalse(checked_two_digit["fail_closed"])

        competing_suffix = dict(binding)
        competing_suffix["cpd"] = competing_suffix["cpd_id"] = competing_suffix[
            "compound_id"
        ] = "Compound 128"
        competing_suffix["visible_label_candidates"] = [
            {"label": "128", "source": "page_strict"},
            {"label": "128A", "source": "page_strict"},
        ]
        competing_suffix["visible_labels"] = ["128", "128A"]
        checked_suffix = annotate_binding_accuracy(competing_suffix)
        self.assertEqual(checked_suffix["accuracy_status"], "review_required")
        self.assertTrue(checked_suffix["fail_closed"])

    def test_structure_table_row_evidence_ignores_lower_internal_alphanumeric_labels(
        self,
    ) -> None:
        table_binding = self._binding("Compound 70", "S70", "/tmp/structure_70.png")
        table_binding.update(
            {
                "binding_rule": "structure_table_row_order",
                "visible_label": "35A",
                "visible_labels": ["35A"],
                "visible_label_candidates": [{"label": "35A", "source": "page_strict"}],
                "struct_area": 17046,
                "struct_width": 168,
                "struct_height": 102,
            }
        )

        checked_table = annotate_binding_accuracy(table_binding)

        self.assertEqual(checked_table["accuracy_status"], "confirmed")
        self.assertFalse(checked_table["fail_closed"])

        direct_binding = dict(table_binding)
        direct_binding["binding_rule"] = "direct_structure_label"
        checked_direct = annotate_binding_accuracy(direct_binding)
        self.assertEqual(checked_direct["accuracy_status"], "review_required")
        self.assertTrue(checked_direct["fail_closed"])

    def test_partial_authoritative_structure_table_does_not_delete_visual_fallbacks(
        self,
    ) -> None:
        binding = self._binding("Compound 128", "S128", "/tmp/structure_128.png")
        binding.update({"page_no": 199})
        profile = {
            "active_cpds": ["Compound 18", "Compound 121", "Compound 128"],
            "authoritative_structure_table_pages": [200],
            "authoritative_structure_table_cpds": ["Compound 128"],
        }

        kept = _enforce_authoritative_structure_table_source([binding], profile)

        self.assertEqual([row["cpd"] for row in kept], ["Compound 128"])

    def test_structure_chunk_metadata_merge_reindexes_without_losing_image_paths(
        self,
    ) -> None:
        merged = _merge_structure_chunk_metadata(
            "WO1234567890",
            [
                {
                    "structures": [
                        {
                            "structure_index": 0,
                            "structure_id": "S0000",
                            "page_no": 1,
                            "image_path": "/tmp/c0/s0.png",
                        },
                        {
                            "structure_index": 1,
                            "structure_id": "S0001",
                            "page_no": 2,
                            "image_path": "/tmp/c0/s1.png",
                        },
                    ],
                },
                {
                    "structures": [
                        {
                            "structure_index": 0,
                            "structure_id": "S0000",
                            "page_no": 3,
                            "image_path": "/tmp/c1/s0.png",
                        },
                    ],
                },
            ],
        )

        self.assertEqual(merged["total_structures"], 3)
        self.assertEqual(
            [row["structure_id"] for row in merged["structures"]],
            ["S0000", "S0001", "S0002"],
        )
        self.assertEqual(
            [row["structure_index"] for row in merged["structures"]], [0, 1, 2]
        )
        self.assertEqual(merged["structures"][2]["source_structure_id"], "S0000")
        self.assertEqual(merged["structures"][2]["image_path"], "/tmp/c1/s0.png")

    def test_structure_chunk_cache_reuses_only_matching_pdf_pages_and_rules(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            pdf = base / "WO123.pdf"
            pdf.write_bytes(b"%PDF chunk cache identity")
            locate_json = base / "structure_pages/locator.json"
            crop_regions_json = base / "structure_pages/crop_regions.json"
            self._write_json(locate_json, {"selected_pages": [1, 2, 3]})
            self._write_json(crop_regions_json, {"1": [0, 0, 100, 100]})
            chunk_output = base / "structures/.chunks/chunk_000"
            chunk_meta_path = chunk_output / "metadata.json"
            payload = {
                **artifact_identity(STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION),
                "patent_number": "WO123",
                "total_structures": 1,
                "structures": [
                    {"structure_id": "S0000", "page_no": 1, "image_path": "s0.png"}
                ],
            }
            self._write_json(chunk_meta_path, payload)
            fingerprint = _structure_chunk_fingerprint(
                pdf_path=str(pdf),
                dependencies=[str(locate_json), str(crop_regions_json)],
                chunk_index=0,
                chunk_pages=[1, 2],
                chunk_size=2,
                crop_regions={"1": [0, 0, 100, 100]},
                gpu_mode="auto",
            )
            _write_step_manifest(str(chunk_meta_path), fingerprint)

            reused = _load_reusable_structure_chunk(str(chunk_output), fingerprint)

            self.assertEqual(reused, payload)
            changed_pages = _structure_chunk_fingerprint(
                pdf_path=str(pdf),
                dependencies=[str(locate_json), str(crop_regions_json)],
                chunk_index=0,
                chunk_pages=[2, 3],
                chunk_size=2,
                crop_regions={"1": [0, 0, 100, 100]},
                gpu_mode="auto",
            )
            self.assertIsNone(
                _load_reusable_structure_chunk(str(chunk_output), changed_pages)
            )

    def test_binding_cache_with_matching_manifest_is_rejected_when_strict_gate_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            pdf = base / "WO123.pdf"
            pdf.write_bytes(b"%PDF binding cache identity")
            structures = base / "structures/metadata.json"
            activity = base / "activity/activity_data.json"
            locator = base / "structure_pages/locator.json"
            ocr_cache = base / "page_classification/page_ocr_cache.json"
            self._write_json(structures, {"total_structures": 2})
            self._write_json(activity, {"active_cpds": ["Compound 1", "Compound 2"]})
            self._write_json(locator, {})
            self._write_json(ocr_cache, {})
            image = self._image(base, "structures/s1.png")
            bind_json = base / "structure_bindings/bindings.json"
            stale_payload = {
                **artifact_identity(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION),
                "execution_mode": SOURCE_EXECUTION_MODE,
                "final_bindings": [self._binding("Compound 1", "S0001", image)],
            }
            complete = write_binding_result(
                bind_json.parent,
                patent_id="CONTROL",
                bindings=[
                    self._binding("Compound 1", "S0001", image),
                    self._binding("Compound 2", "S0002", image),
                ],
                detected_style="control",
                include_intermediates=False,
                total_structures=2,
                total_compound_blocks=0,
                table_pages=[],
                table_covered_count=0,
                no_binding=[],
                unbound_pages=[],
            )
            stale_payload = {
                **complete,
                "final_bindings": complete["final_bindings"][:1],
            }
            self._write_json(bind_json, stale_payload)
            fingerprint = {
                "step": "bind",
                "pdf_sha256": "same",
                "dependency_sha256": {},
                "params_digest": "same",
                "params": {},
                "ruleset": ruleset_ref(),
            }
            _write_step_manifest(str(bind_json), fingerprint)

            self.assertIsNone(_load_reusable_bindings(str(bind_json), fingerprint, {}))

            self._write_json(bind_json, complete)
            reusable = _load_reusable_bindings(str(bind_json), fingerprint, {})
            self.assertIsNotNone(reusable)
            self.assertEqual(
                [row["cpd"] for row in reusable.get("final_bindings", [])],
                ["Compound 1", "Compound 2"],
            )

    def test_decimer_auto_gpu_fails_closed_for_unsupported_tensorflow_cuda_caps(
        self,
    ) -> None:
        caps = ["sm_50", "sm_60", "sm_70", "sm_75", "compute_80"]
        self.assertTrue(tensorflow_cuda_caps_support_gpu(caps, "8.6"))
        self.assertTrue(tensorflow_cuda_caps_support_gpu(caps, "sm_75"))
        self.assertFalse(tensorflow_cuda_caps_support_gpu(caps, "12.0"))

        output = (
            "TensorFlow startup log\n"
            'PATENTSAR_GPU_PROBE={"devices":["/physical_device:GPU:0"],'
            '"cuda_compute_capabilities":["sm_75","compute_80"]}\n'
        )
        probe = _parse_tensorflow_gpu_probe(output)
        self.assertTrue(_tensorflow_gpu_probe_is_compatible(probe, "8.6"))
        self.assertFalse(_tensorflow_gpu_probe_is_compatible(probe, "12.0"))
        self.assertFalse(
            _tensorflow_gpu_probe_is_compatible({**probe, "devices": []}, "8.6")
        )

        def fake_build_gpu_env(*, python_path: str = "", base_env=None, extra_env=None):
            return dict(extra_env or {})

        with (
            patch(
                "patent_sar_extractor.application.worker_policy._decimer_tensorflow_gpu_safe",
                return_value=False,
            ),
            patch(
                "patent_sar_extractor.application.worker_policy.get_python",
                return_value="/tmp/python",
            ),
            patch(
                "patent_sar_extractor.application.worker_policy.build_gpu_env",
                side_effect=fake_build_gpu_env,
            ),
        ):
            env = _gpu_env_extra("decimer", gpu_mode="auto")

        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "-1")
        self.assertEqual(env["PATENTSAR_DECIMER_ENABLE_GPU"], "0")
        self.assertEqual(env["LD_PRELOAD"], "")
        self.assertEqual(env["LD_LIBRARY_PATH"], "")

        with (
            patch(
                "patent_sar_extractor.application.worker_policy._decimer_tensorflow_gpu_safe",
                return_value=False,
            ),
            patch(
                "patent_sar_extractor.application.worker_policy.get_python",
                return_value="/tmp/python",
            ),
            patch(
                "patent_sar_extractor.application.worker_policy.build_gpu_env",
                side_effect=fake_build_gpu_env,
            ),
        ):
            smiles_env = _gpu_env_extra("smiles_engine", gpu_mode="auto")

        self.assertEqual(smiles_env["CUDA_VISIBLE_DEVICES"], "-1")
        self.assertEqual(smiles_env["PATENTSAR_DECIMER_ENABLE_GPU"], "0")
        self.assertNotIn("MOLSCRIBE_DEVICE", smiles_env)

    def test_streamed_env_runner_filters_tensorflow_warning_floods(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "emit_logs.py"
            script.write_text(
                "import sys\n"
                "print('Error in PredictCost() noisy tensor line')\n"
                "print('2026 [INFO] structure_extraction: useful progress')\n"
                "sys.stderr.write('Unable to register cuDNN factory\\n')\n"
                "sys.stderr.write('normal stderr progress\\n')",
                encoding="utf-8",
            )
            buffer = io.StringIO()
            with (
                patch.dict(os.environ, {"PATENTSAR_BASE_PYTHON": sys.executable}),
                contextlib.redirect_stdout(buffer),
            ):
                proc = env_runner_module.run_in_env(
                    "base",
                    str(script),
                    timeout=10,
                    stream_output=True,
                )

        streamed = buffer.getvalue()
        self.assertEqual(proc.returncode, 0)
        self.assertIn("useful progress", streamed)
        self.assertIn("normal stderr progress", streamed)
        self.assertNotIn("PredictCost", streamed)
        self.assertNotIn("cuDNN factory", streamed)

    def test_external_python_runner_removes_parent_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "show_pythonpath.py"
            script.write_text(
                "import os\nprint(os.environ.get('PYTHONPATH', ''))\n",
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {"PATENTSAR_BASE_PYTHON": sys.executable}),
                patch.dict(
                    os.environ,
                    {"PYTHONPATH": "/tmp/incompatible-parent-site-packages"},
                ),
            ):
                proc = env_runner_module.run_in_env("base", str(script), timeout=30)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")

    def test_decimer_environment_requires_real_segmentation_module(self) -> None:
        self.assertEqual(
            env_runner_module.ENV_REQUIRED_MODULES["decimer"],
            ["decimer_segmentation"],
        )

    def test_pipeline_elapsed_times_do_not_go_negative_on_fast_cache_reuse(
        self,
    ) -> None:
        with patch(
            "patent_sar_extractor.application.pipeline_io.time.time", return_value=100.0
        ):
            self.assertEqual(_elapsed_since(100.2), 0.0)
            self.assertEqual(_elapsed_since(99.94), 0.1)

    def test_activity_timeout_scales_for_large_scanned_patents_and_stays_bounded(
        self,
    ) -> None:
        self.assertEqual(_activity_timeout_seconds({"activity_pages": []}), 1800)
        self.assertEqual(
            _activity_timeout_seconds({"activity_pages": list(range(180))}), 1800
        )
        self.assertEqual(
            _activity_timeout_seconds({"activity_pages": list(range(361))}), 3610
        )
        self.assertEqual(
            _activity_timeout_seconds({"activity_pages": list(range(5000))}), 10800
        )
        self.assertEqual(_activity_timeout_seconds({"activity_pages": "invalid"}), 1800)

    def test_smiles_cache_empty_result_does_not_block_retry(self) -> None:
        class FakeEngine:
            def __init__(self, **_kwargs):
                pass

            def predict(self, _image_path: str, timeout: int = 60) -> dict:
                return {
                    "engine": "fake",
                    "status": "success",
                    "raw_smiles": "CCO",
                    "molblock": None,
                    "confidence": 1.0,
                    "error": None,
                    "elapsed_sec": 0.0,
                }

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_path = self._image(base, "structure.png")
            cache_path = base / "smiles.sqlite"
            cache = SmilesCache(str(cache_path))
            cache.save_result(
                compute_image_sha256(image_path),
                "fake",
                {
                    "status": "failed",
                    "raw_smiles": None,
                    "quality_flag": "empty_prediction",
                    "error": "old model load failure",
                },
            )

            with patch.dict(smiles_converter_module.ENGINE_MAP, {"fake": FakeEngine}):
                converter = smiles_converter_module.SmilesConverter(
                    engines=["fake"],
                    fallback_engines=[],
                    cache_path=str(cache_path),
                    preprocess=False,
                )
                result = converter.convert_one(
                    {
                        "cpd": "Compound 1",
                        "structure_id": "S0001",
                        "image_path": image_path,
                    }
                )

        self.assertEqual(result["OCSR_status"], "success")
        self.assertEqual(result["canonical_smiles"], "CCO")
        self.assertTrue(result["engine_attempts"][0]["ignored_cached_empty"])

    def test_smiles_cache_non_clean_result_does_not_block_retry(self) -> None:
        class FakeEngine:
            def __init__(self, **_kwargs):
                pass

            def predict(self, _image_path: str, timeout: int = 60) -> dict:
                return {
                    "engine": "decimer",
                    "status": "success",
                    "raw_smiles": "CCO",
                    "molblock": None,
                    "confidence": 1.0,
                    "error": None,
                    "elapsed_sec": 0.0,
                }

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_path = self._image(base, "structure.png")
            cache_path = base / "smiles.sqlite"
            cache = SmilesCache(str(cache_path))
            cache.save_result(
                compute_image_sha256(image_path),
                "decimer",
                {
                    "status": "success",
                    "raw_smiles": "C1CC",
                    "rdkit_valid": False,
                    "quality_flag": "invalid",
                    "error": None,
                },
            )

            with patch.dict(
                smiles_converter_module.ENGINE_MAP, {"decimer": FakeEngine}
            ):
                converter = smiles_converter_module.SmilesConverter(
                    engines=["decimer"],
                    fallback_engines=[],
                    cache_path=str(cache_path),
                    preprocess=False,
                )
                result = converter.convert_one(
                    {
                        "cpd": "Compound 1",
                        "structure_id": "S0001",
                        "image_path": image_path,
                    }
                )

        self.assertEqual(result["OCSR_status"], "success")
        self.assertEqual(result["canonical_smiles"], "CCO")
        self.assertTrue(result["engine_attempts"][0]["ignored_cached_non_clean"])

    def test_ocsr_input_masks_visible_compound_label_before_decimer(self) -> None:
        observed_paths = []

        class InspectingEngine:
            def __init__(self, **_kwargs):
                pass

            def predict(self, image_path: str, timeout: int = 60) -> dict:
                observed_paths.append(image_path)
                return {
                    "engine": "decimer",
                    "status": "success",
                    "raw_smiles": "CCO",
                    "molblock": None,
                    "confidence": 1.0,
                    "error": None,
                    "elapsed_sec": 0.0,
                }

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_path = self._labeled_structure_image(base, "structure_110.png", "110")
            binding = self._binding("Compound 110", "S0110", image_path)
            binding["visible_label"] = "110"

            with patch.dict(
                smiles_converter_module.ENGINE_MAP, {"decimer": InspectingEngine}
            ):
                converter = smiles_converter_module.SmilesConverter(
                    engines=["decimer"],
                    fallback_engines=[],
                    cache_path="",
                    preprocess=False,
                )
                result = converter.convert_one(
                    binding, preprocess_dir=str(base / "ocsr_inputs")
                )

            self.assertEqual(result["OCSR_status"], "success")
            self.assertTrue(result.get("ocsr_label_masked"))
            self.assertEqual(result["structure_image"], image_path)
            self.assertNotEqual(observed_paths[0], image_path)

            from PIL import Image

            original = Image.open(image_path).convert("L")
            cleaned = Image.open(observed_paths[0]).convert("L")
            # The upper molecule trace is preserved.
            self.assertLess(
                min(original.crop((10, 10, 230, 45)).get_flattened_data()), 80
            )
            self.assertLess(
                min(cleaned.crop((10, 10, 230, 45)).get_flattened_data()), 80
            )
            # The label band has been blanked before OCSR.
            self.assertLess(
                min(original.crop((100, 64, 150, 90)).get_flattened_data()), 80
            )
            self.assertGreater(
                min(cleaned.crop((100, 64, 150, 90)).get_flattened_data()), 240
            )

    def test_ocsr_label_mask_does_not_erase_wide_lower_structure_fragment(self) -> None:
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_path = base / "structure_without_visible_label.png"
            img = Image.new("RGB", (260, 120), "white")
            draw = ImageDraw.Draw(img)
            draw.line(
                [(10, 30), (70, 18), (130, 30), (190, 18), (250, 30)],
                fill="black",
                width=3,
            )
            draw.line(
                [(95, 86), (132, 96), (170, 84), (210, 94)], fill="black", width=3
            )
            draw.text((116, 76), "N", fill="black")
            img.save(image_path)

            output, info = smiles_converter_module._mask_visible_label_for_ocsr(
                str(image_path),
                {"cpd": "Compound 138", "visible_label": "138"},
                str(base / "ocsr_inputs"),
            )

        self.assertEqual(output, str(image_path))
        self.assertEqual(info, {})

    def test_clean_fallback_clears_prior_suspicious_engine_state(self) -> None:
        class SuspiciousEngine:
            def __init__(self, **_kwargs):
                pass

            def predict(self, _image_path: str, timeout: int = 60) -> dict:
                return {
                    "engine": "suspicious",
                    "status": "success",
                    "raw_smiles": "CC[Hg]",
                    "molblock": None,
                    "confidence": 1.0,
                    "error": None,
                    "elapsed_sec": 0.0,
                }

        class CleanFallbackEngine:
            def __init__(self, **_kwargs):
                pass

            def predict(self, _image_path: str, timeout: int = 60) -> dict:
                return {
                    "engine": "clean",
                    "status": "success",
                    "raw_smiles": "CCCl",
                    "molblock": None,
                    "confidence": 1.0,
                    "error": None,
                    "elapsed_sec": 0.0,
                }

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_path = self._image(base, "structure.png")
            with patch.dict(
                smiles_converter_module.ENGINE_MAP,
                {"suspicious": SuspiciousEngine, "clean": CleanFallbackEngine},
            ):
                converter = smiles_converter_module.SmilesConverter(
                    engines=["suspicious"],
                    fallback_engines=["clean"],
                    cache_path="",
                    preprocess=False,
                )
                result = converter.convert_one(
                    {
                        "cpd": "Compound 1",
                        "structure_id": "S0001",
                        "image_path": image_path,
                    }
                )

        self.assertEqual(result["OCSR_status"], "success")
        self.assertEqual(result["OCSR_quality_flag"], "ok")
        self.assertEqual(result["raw_smiles"], "CCCl")
        self.assertNotIn("suspicious_elements", result)

    def test_smiles_cache_purge_keeps_only_clean_successes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cache = SmilesCache(str(Path(temp) / "smiles.sqlite"))
            cache.save_result(
                "clean",
                "fake",
                {
                    "status": "success",
                    "raw_smiles": "CCO",
                    "rdkit_valid": True,
                    "quality_flag": "ok",
                },
            )
            cache.save_result(
                "empty",
                "fake",
                {
                    "status": "failed",
                    "raw_smiles": None,
                    "rdkit_valid": False,
                    "quality_flag": "empty_prediction",
                },
            )
            cache.save_result(
                "suspicious",
                "fake",
                {
                    "status": "success",
                    "raw_smiles": "CC[Cu]",
                    "rdkit_valid": True,
                    "quality_flag": "suspicious_element",
                },
            )
            cache.save_result(
                "legacy_suspicious",
                "fake",
                {
                    "status": "success",
                    "raw_smiles": "CC[Cu]",
                    "rdkit_valid": True,
                    "quality_flag": "ok",
                },
            )

            purged = cache.purge_non_clean()

            self.assertEqual(purged, 3)
            self.assertIsNotNone(cache.get_cached_result("clean", "fake"))
            self.assertIsNone(cache.get_cached_result("empty", "fake"))
            self.assertIsNone(cache.get_cached_result("suspicious", "fake"))
            self.assertIsNone(cache.get_cached_result("legacy_suspicious", "fake"))

    def test_strict_gates_reject_old_activity_duplicate_structure_and_extra_smiles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_path = self._image(base, "structure.png")
            old_activity = {
                "rows": [{"cpd": "Compound 1", "activity_values": {"IC50": "A"}}],
                "ruleset": {"name": "legacy", "version": "0"},
            }
            self.assertIn(
                "Malformed or incompatible activity producer output",
                _activity_acceptance_errors(old_activity, ["Compound 1"]),
            )
            bindings = [
                self._binding("Compound 1", "S1", image_path),
                self._binding("Compound 2", "S1", image_path),
            ]
            binding_payload = {"final_bindings": bindings}
            with self.assertRaises(ValueError):
                _binding_acceptance_errors(binding_payload)
            smiles = [
                self._smiles("Compound 1", "S1", "CCCl"),
                self._smiles("Compound 2", "S1", "CCO"),
                self._smiles("Compound 3", "S3", "CCN"),
            ]
            self.assertIn(
                "SMILES records do not map one-to-one to confirmed bindings in order.",
                _smiles_acceptance_errors(smiles, binding_payload),
            )
            smiles_path = base / "smiles.json"
            self._write_json(smiles_path, smiles)
            with self.assertRaises(ValueError):
                qualified_records(bindings, smiles)

    def test_direct_smiles_runner_reapplies_strict_binding_and_result_gates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_path = self._image(base, "structure.png")
            binding = self._binding("Compound 1", "S1", image_path)
            payload = {
                **artifact_identity(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION),
                "execution_mode": "production_structure_led",
                "final_bindings": [binding],
            }
            bindings_path = base / "bindings.json"
            self._write_json(bindings_path, payload)
            self.assertEqual(
                validate_strict_binding_input(str(bindings_path), [binding]), []
            )
            clean = self._smiles("Compound 1", "S1", "CCCl")
            self.assertEqual(validate_strict_smiles_results([binding], [clean]), [])
            suspicious = self._smiles("Compound 1", "S1", "CC[Cu]")
            self.assertTrue(validate_strict_smiles_results([binding], [suspicious]))

    def test_pipeline_does_not_reuse_existing_smiles_that_fail_strict_gate(
        self,
    ) -> None:
        binding = self._binding("Compound 1", "S1", "/tmp/structure.png")
        payload = {
            **artifact_identity(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION),
            "execution_mode": "production_activity_led",
            "final_bindings": [binding],
        }
        clean = self._smiles("Compound 1", "S1", "CCCl")
        stale = self._smiles("Compound 1", "S1", "CC[Hg]")

        clean_reusable, clean_errors = _smiles_results_can_be_reused([clean], payload)
        stale_reusable, stale_errors = _smiles_results_can_be_reused([stale], payload)

        self.assertTrue(clean_reusable)
        self.assertEqual(clean_errors, [])
        self.assertFalse(stale_reusable)
        self.assertTrue(any("requires review" in error for error in stale_errors))

    def test_smiles_runner_defaults_to_decimer_only(self) -> None:
        class FakeConverter:
            created_with = None
            cache = None

            def __init__(self, *, engines, fallback_engines, **_kwargs):
                class FakeEngine:
                    def is_available(self) -> bool:
                        return True

                FakeConverter.created_with = {
                    "engines": list(engines),
                    "fallback_engines": list(fallback_engines),
                }
                self.engines = {name: FakeEngine() for name in engines}

            def convert_batch(self, bindings, **_kwargs):
                return [
                    self_outer._smiles(binding["cpd"], binding["structure_id"], "CCO")
                    for binding in bindings
                ]

        self_outer = self
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_path = self._image(base, "structure.png")
            bindings_path = base / "bindings.json"
            output_path = base / "smiles.json"
            csv_path = base / "smiles.csv"
            self._write_json(
                bindings_path, [self._binding("Compound 1", "S1", image_path)]
            )

            argv = [
                "run_smiles.py",
                "--input",
                str(bindings_path),
                "--output",
                str(output_path),
                "--csv-output",
                str(csv_path),
                "--include-intermediates",
                "--diagnostic-unvalidated-input",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(run_smiles_module, "SmilesConverter", FakeConverter),
            ):
                run_smiles_module.main()

        self.assertEqual(
            FakeConverter.created_with,
            {
                "engines": ["decimer"],
                "fallback_engines": [],
            },
        )

    def test_production_pipeline_uses_decimer_only_ocsr_options(self) -> None:
        self.assertEqual(
            _production_smiles_ocr_options(),
            {
                "engine": "decimer",
                "fallback": "",
            },
        )

    def test_production_ocsr_surface_has_no_legacy_engine_chain(self) -> None:
        from patent_sar_extractor.core.ocsr.smiles_converter import ENGINE_MAP

        self.assertEqual(ENGINE_MAP, {"decimer": ENGINE_MAP["decimer"]})
        ocsr_root = SOURCE_ROOT / "patent_sar_extractor" / "core" / "ocsr"
        for relative in (
            "engines/molscribe_engine.py",
            "engines/molnextr_engine.py",
            "engines/molvec_engine.py",
            "wrapper_molnextr.py",
        ):
            self.assertFalse((ocsr_root / relative).exists(), relative)

    def test_clean_minimal_source_export_preserves_catalog_and_original_activity_order(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_2 = self._image(base, "images/structure_2.png")
            image_1 = self._image(base, "images/structure_1.png")
            activity = {
                **artifact_identity(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION),
                "metadata": {},
                "active_cpds": ["Compound 2", "Compound 1"],
                "rows": [
                    {
                        "cpd": "Compound 2",
                        "activity_values": {"IC50 (nM)": "A"},
                        "cell_line_data": {"Dmax (%)": "61"},
                        "needs_review": False,
                    },
                    {
                        "cpd": "Compound 1",
                        "activity_values": {"IC50 (nM)": "B"},
                        "cell_line_data": {"Dmax (%)": "42"},
                        "needs_review": False,
                    },
                ],
            }
            bindings = [
                self._binding("Compound 2", "S2", image_2),
                self._binding("Compound 1", "S1", image_1),
            ]
            binding_payload = write_binding_result(
                base / "structure_bindings",
                patent_id="TEST",
                bindings=bindings,
                detected_style="control",
                include_intermediates=False,
                total_structures=2,
                total_compound_blocks=0,
                table_pages=[],
                table_covered_count=0,
                no_binding=[],
                unbound_pages=[],
            )
            smiles = [
                self._smiles("Compound 2", "S2", "CCCl"),
                self._smiles("Compound 1", "S1", "CCO"),
            ]
            self._write_json(base / "activity/activity_data.json", activity)
            self._write_json(base / "structure_bindings/bindings.json", binding_payload)
            self._write_json(
                base / "smiles/smiles_results.json",
                {
                    **build_smiles_artifact(list(reversed(smiles))),
                    "formal_acceptance_scope": FORMAL_SCOPE,
                    "binding_execution_mode": SOURCE_EXECUTION_MODE,
                },
            )
            self._write_json(base / "structures/metadata.json", {"total_structures": 2})
            self._write_json(base / "structure_pages/locator.json", {})
            self._write_json(
                base / "page_classification/page_classification.json",
                {
                    **artifact_identity(
                        PAGE_CLASSIFICATION_SCHEMA, PAGE_CLASSIFICATION_SCHEMA_VERSION
                    ),
                    "page_count": 1,
                    "activity_pages": [0],
                },
            )
            self._write_json(
                base / "pipeline_summary.json",
                {"status": "complete", "patent_id": "TEST"},
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        SOURCE_ROOT
                        / "patent_sar_extractor/workers/gen_final_results.py"
                    ),
                    "--bindings",
                    str(base / "structure_bindings/bindings.json"),
                    "--smiles",
                    str(base / "smiles/smiles_results.json"),
                    "--activity",
                    str(base / "activity/activity_data.json"),
                    "--classification",
                    str(base / "page_classification/page_classification.json"),
                    "--output-dir",
                    str(base / "final_results"),
                    "--patent",
                    "TEST",
                    "--rdkit-python",
                    sys.executable,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)

            from openpyxl import Workbook

            wrong = Workbook()
            wrong.active.title = "Final Results"
            wrong.active.append(["Cpd ID"])
            wrong.active.append(["Compound 999"])
            wrong_activity = wrong.create_sheet("Activity Results")
            wrong_activity.append(["Cpd ID", "IC50 (nM)"])
            wrong_activity.append(["Compound 999", "Z"])
            wrong.save(base / "final_results/AAA_STALE_final.xlsx")
            (base / "final_results/AAA_STALE_final.sdf").write_text(
                "$$$$\n" * 99, encoding="utf-8"
            )

            qa = write_qa_report(str(base), patent_id="TEST")
            self.assertTrue(qa["acceptance"]["ok"], msg=qa["acceptance"]["hard_errors"])
            self.assertEqual(
                qa["acceptance"]["excel"]["path"],
                str(base / "final_results/TEST_final.xlsx"),
            )
            self.assertEqual(qa["acceptance"]["sdf_record_count"], 2)
            self.assertTrue(
                (base / "final_results/TEST_final_qa_report.json").is_file()
            )
            self.assertTrue((base / "final_results/TEST_final_qa_report.md").is_file())
            workbook = _read_xlsx_values(base / "final_results/TEST_final.xlsx")
            activity_rows = workbook["sheets"]["Activity Results"]["rows"]
            self.assertEqual(
                [row[0] for row in activity_rows[1:]], ["Compound 2", "Compound 1"]
            )
            self.assertEqual(activity_rows[1][1:3], ["A", "61"])
            self.assertEqual(activity_rows[2][1:3], ["B", "42"])
            stale_payload = dict(binding_payload)
            stale_payload["accuracy_summary"] = {
                "total": 2,
                "confirmed": 1,
                "review_required": 0,
            }
            self._write_json(base / "structure_bindings/bindings.json", stale_payload)
            stale_qa = build_qa_report(str(base), patent_id="TEST")
            self.assertIn(
                "Binding accuracy summary is missing, stale, or inconsistent with current-rule confirmation.",
                stale_qa["acceptance"]["hard_errors"],
            )

    def test_removed_partial_export_mode_cannot_bypass_ownership_and_chemistry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image_1 = self._image(base, "images/structure_1.png")
            image_2 = self._image(base, "images/structure_2.png")
            activity = {
                **artifact_identity(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION),
                "metadata": {},
                "active_cpds": ["Compound 1", "Compound 2"],
                "rows": [
                    {
                        "cpd": "Compound 1",
                        "activity_values": {"IC50 (nM)": "A"},
                        "needs_review": False,
                    },
                    {
                        "cpd": "Compound 2",
                        "activity_values": {"IC50 (nM)": "B"},
                        "needs_review": False,
                    },
                ],
            }
            binding_payload = {
                **artifact_identity(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION),
                "execution_mode": "production_activity_led",
                "accuracy_summary": {"total": 2, "confirmed": 1, "review_required": 1},
                "final_bindings": [
                    self._binding("Compound 1", "S1", image_1),
                    {
                        **self._binding("Compound 2", "S2", image_2),
                        "accuracy_status": "review_required",
                        "fail_closed": True,
                        "review_reason": "partial-review candidate",
                    },
                ],
            }
            smiles = [self._smiles("Compound 1", "S1", "CCO")]
            self._write_json(base / "activity/activity_data.json", activity)
            self._write_json(base / "structure_bindings/bindings.json", binding_payload)
            self._write_json(
                base / "smiles/smiles_results.json",
                build_smiles_artifact(smiles),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        SOURCE_ROOT
                        / "patent_sar_extractor/workers/gen_final_results.py"
                    ),
                    "--bindings",
                    str(base / "structure_bindings/bindings.json"),
                    "--smiles",
                    str(base / "smiles/smiles_results.json"),
                    "--activity",
                    str(base / "activity/activity_data.json"),
                    "--output-dir",
                    str(base / "final_results"),
                    "--patent",
                    "TESTPARTIAL",
                    "--allow-partial",
                    "--rdkit-python",
                    sys.executable,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((base / "final_results/TESTPARTIAL_final.xlsx").exists())

    def test_partial_mode_keeps_review_bindings_for_partial_export(self) -> None:
        confirmed = self._binding("Compound 1", "S1", "/tmp/s1.png")
        review = {
            **self._binding("Compound 2", "S2", "/tmp/s2.png"),
            "accuracy_status": "review_required",
            "fail_closed": True,
        }

        strict = _drop_fail_closed_bindings(
            [confirmed, review], ["Compound 1", "Compound 2"]
        )
        partial = _drop_fail_closed_bindings(
            [confirmed, review],
            ["Compound 1", "Compound 2"],
            keep_review_bindings=True,
        )

        self.assertEqual([row["cpd"] for row in strict], ["Compound 1"])
        self.assertEqual([row["cpd"] for row in partial], ["Compound 1", "Compound 2"])
        self.assertTrue(partial[1]["partial_review_candidate"])

    def test_pipeline_defaults_to_review_only_partial_gates_unless_strict_requested(
        self,
    ) -> None:
        class Args:
            strict_gates = False

        self.assertFalse(_strict_gates_enabled(Args()))
        Args.strict_gates = True
        self.assertTrue(_strict_gates_enabled(Args()))


if __name__ == "__main__":
    unittest.main()
