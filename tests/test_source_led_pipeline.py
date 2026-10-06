"""Bounded source-led application controls; no recognizer/model is loaded."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor import contracts
from patent_sar_extractor.application.pipeline import execute_pipeline
from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.stage_activity import execute_activity
from patent_sar_extractor.application.stage_locate import execute_locate
from patent_sar_extractor.core.activity_join import activity_for_compound
from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.smiles_artifact import build_smiles_artifact
from patent_sar_extractor.workers.final_data import load_data


def proved_binding(label, structure_id, image=""):
    return annotate_binding_accuracy(
        {
            "cpd": label,
            "compound_id": label,
            "prefix": "Compound",
            "structure_id": structure_id,
            "image_path": image,
            "page_no": 1,
            "binding_rule": "direct_structure_label",
            "struct_area": 10000,
            "struct_width": 100,
            "struct_height": 100,
            "visible_label_candidates": [{"label": label, "source": "pdf_clip"}],
            "visible_label": label,
            "product_context_nearby": True,
            "product_context_distance": 0,
        }
    )


def state_for(root, stage):
    original = root / "original.pdf"
    original.write_bytes(b"controlled fingerprint input, not a patent")
    classification = root / "classification.json"
    classification.write_text("{}")
    progress = PipelineProgress()
    log = {"steps": {}, "main_chain": [stage], "status": "running"}
    progress.bind(str(root), log)
    return PipelineContext(
        args=Namespace(pdf=str(original), gpu_mode="off"),
        progress=progress,
        base_dir=str(root),
        patent_id="CONTROL",
        step_dirs={stage: str(root / stage)},
        classify_json=str(classification),
        pipeline_log=log,
        classification={"activity_pages": []},
    )


class SourceLedPipelineTests(unittest.TestCase):
    def test_writer_preserves_complete_proved_compound_identifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = write_binding_result(
                Path(temporary),
                patent_id="CONTROL",
                bindings=[proved_binding("Compound 1-2-3AB", "s1")],
                detected_style="original",
                include_intermediates=False,
                total_structures=1,
                total_compound_blocks=1,
                table_pages=[],
                table_covered_count=0,
                no_binding=[],
                unbound_pages=[],
            )
            self.assertEqual(payload["final_bindings"][0]["cpd"], "Compound 1-2-3AB")
            self.assertEqual(payload["source_issues"], [])

    def test_registry_executes_exact_controller_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            called = []
            args = Namespace(
                pdf="original.pdf", patent_id="CONTROL", output=temporary, force=False
            )
            with patch(
                "patent_sar_extractor.application.pipeline._load_io_config",
                return_value={},
            ):
                patches = [
                    patch(
                        f"patent_sar_extractor.application.pipeline.execute_{stage}",
                        side_effect=lambda state, stage=stage: called.append(stage),
                    )
                    for stage in contracts.CORE_STAGE_ORDER
                ]
                for active in patches:
                    active.start()
                try:
                    execute_pipeline(args, PipelineProgress())
                finally:
                    for active in reversed(patches):
                        active.stop()
            self.assertEqual(called, list(contracts.CORE_STAGE_ORDER))

    def test_one_writer_promotes_complete_proved_catalog_without_activity(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            bindings = [
                proved_binding("Compound 42", "s1"),
                proved_binding("Compound 42A", "s2"),
            ]
            write_binding_result(
                output,
                patent_id="CONTROL",
                bindings=[],
                detected_style="original_cell_and_caption",
                include_intermediates=False,
                total_structures=2,
                total_compound_blocks=0,
                table_pages=[],
                table_covered_count=0,
                no_binding=[],
                unbound_pages=[],
                catalog_bindings=bindings,
            )
            payload = json.loads((output / "bindings.json").read_text())
            self.assertEqual(
                [r["cpd"] for r in payload["final_bindings"]],
                ["Compound 42", "Compound 42A"],
            )
            self.assertEqual(payload["execution_mode"], "production_structure_led")
            self.assertEqual(
                payload["compound_catalog"]["formal_acceptance_scope"],
                "proved_printed_identifier_structure_corpus",
            )

    def test_export_keeps_numbered_structures_with_zero_or_partial_activity(self):
        for activities in (
            [],
            [{"cpd": "Compound 42", "activity_values": {"IC50 (nM)": "17"}}],
        ):
            with (
                self.subTest(activities=activities),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                bound = [
                    proved_binding("Compound 42", "s1"),
                    proved_binding("Compound 42A", "s2"),
                ]
                binding = root / "bindings.json"
                write_binding_result(
                    root,
                    patent_id="CONTROL",
                    bindings=bound,
                    detected_style="original",
                    include_intermediates=False,
                    total_structures=2,
                    total_compound_blocks=0,
                    table_pages=[],
                    table_covered_count=0,
                    no_binding=[],
                    unbound_pages=[],
                )
                smiles = root / "smiles.json"
                smiles.write_text(json.dumps(build_smiles_artifact([])))
                activity = root / "activity.json"
                activity.write_text(json.dumps({"rows": activities}))
                examples, *_ = load_data(
                    str(binding), str(smiles), activity_path=str(activity)
                )
                self.assertEqual(
                    [r["cpd"] for r in examples], ["Compound 42", "Compound 42A"]
                )

    def test_activity_join_cannot_borrow_parent_value_for_split_child(self):
        self.assertEqual(
            activity_for_compound({"Compound 4": {"IC50": "17"}}, "Compound 4-2"), {}
        )

    def test_classified_activity_loss_is_retained_until_final_qa(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = state_for(root, "activity")
            state.classification = {"activity_pages": [7]}

            def writer(pdf, classification, output, **kwargs):
                directory = Path(output)
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "activity_data.json").write_text(
                    json.dumps(
                        {
                            **contracts.artifact_identity(
                                contracts.ACTIVITY_SCHEMA,
                                contracts.ACTIVITY_SCHEMA_VERSION,
                            ),
                            "rows": [],
                        }
                    )
                )

            with patch(
                "patent_sar_extractor.application.stage_activity._run_activity_rules",
                side_effect=writer,
            ):
                execute_activity(state)
            self.assertEqual(
                state.pipeline_log["steps"]["activity"]["status"], "failed"
            )
            self.assertTrue(
                state.pipeline_log["steps"]["activity"]["acceptance_errors"]
            )
            self.assertTrue(state.pipeline_log["scientific_errors"])

    def test_locator_does_not_receive_activity_targets_or_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = state_for(Path(temporary), "locate")
            state.active_cpds = ["Compound 999"]
            state.act_json = "/not-an-upstream-stage/activity.json"
            with (
                patch(
                    "patent_sar_extractor.application.stage_locate._step_fingerprint",
                    return_value={},
                ) as fingerprint,
                patch(
                    "patent_sar_extractor.application.stage_locate._fingerprint_matches",
                    return_value=False,
                ),
                patch(
                    "patent_sar_extractor.application.stage_locate._write_step_manifest"
                ),
                patch(
                    "patent_sar_extractor.application.stage_locate.locate_structure_pages",
                    return_value={"selected_pages": []},
                ) as locate,
            ):
                execute_locate(state)
            self.assertEqual(locate.call_args.args[2], [])
            self.assertNotIn(
                state.act_json, fingerprint.call_args.kwargs["dependencies"]
            )
            self.assertNotIn("active_cpds", fingerprint.call_args.kwargs["params"])


if __name__ == "__main__":
    unittest.main()
