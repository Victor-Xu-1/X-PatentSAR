"""Focused complete native study, evidence and recovery tests on synthetic data."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.contracts import product_ref
from patent_sar_extractor.core.identifier_order import natural_identifier_key
from patent_sar_extractor.core.sar.chemistry import prepare_structure
from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.study_contexts import context_identity
from patent_sar_extractor.core.sar.study_priority import pareto_fronts
from patent_sar_extractor.core.sar.study_statistics import assess, distribution
from patent_sar_extractor.core.sar.values import parse_value
from patent_sar_extractor.web.descriptor_fields import DESCRIPTOR_KEYS
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.sar.assets import atomic_json, digest
from patent_sar_extractor.web.sar.engine import engine_identity
from patent_sar_extractor.web.sar.models import Dataset, Molecule, Pair, Region, SARJob
from patent_sar_extractor.web.sar.study_models import StudyReport, StudyRequest
from patent_sar_extractor.web.sar.study_publication import verify_study
from patent_sar_extractor.workers import study_analysis, study_pairs

CONTEXT = {
    "target": "controlled target",
    "assay": "binding",
    "cell_line": "not applicable",
    "duration": "1h",
}
METRIC = {
    "id": "activity",
    "name": "IC50",
    "unit": "nM",
    "target": CONTEXT["target"],
    "assay": CONTEXT["assay"],
}


def observation(value, **kwargs):
    return {
        "metric_id": "activity",
        "value": str(value),
        "unit": "nM",
        "context": dict(CONTEXT),
        **kwargs,
    }


def policy(**kwargs):
    return {
        "context_id": context_identity(observation("1")),
        "direction": "lower",
        "grade_order": [],
        "strong_threshold": 5.0,
        "threshold_inclusive": True,
        **kwargs,
    }


def molecule(identifier, smiles, value="1", **kwargs):
    prepared = prepare_structure(smiles)
    return Molecule(
        id=identifier,
        label=identifier,
        smiles=prepared["smiles"],
        molfile=prepared["molfile"],
        graph_sha256=prepared["graph_sha256"],
        eligible=prepared["eligible"],
        issues=prepared["issues"],
        observations=[observation(value)],
        **kwargs,
    ).model_dump()


class StudyAnalysisTests(unittest.TestCase):
    def setUp(self):
        base = os.environ.get("PATENTSAR_WEB_TEST_ROOT", tempfile.gettempdir())
        Path(base).mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="sar-study-", dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / uuid.uuid4().hex
        self.root.mkdir(mode=0o700)

    def packet(self, rows=None, regions=1, cores=0, policies=None, confirmed=False):
        rows = rows or [
            molecule("ID1", "COc1ccc(Cl)cc1", "10"),
            molecule("ID2", "CCOc1ccc(Cl)cc1"),
            molecule("ID3", "CCOc1ccc(Br)cc1", "0.1"),
        ]
        dataset = Dataset(
            id=uuid.uuid4().hex,
            title="Controlled study",
            source_kind="csv",
            source_sha256="a" * 64,
            row_count=len(rows),
            input_row_count=len(rows),
            eligible_count=sum(row["eligible"] for row in rows),
            issue_count=sum(bool(row["issues"]) for row in rows),
            metrics=[METRIC],
            created_at="2026-01-01T00:00:00Z",
        )
        variable = []
        for index in range(regions):
            reference = rows[index % len(rows)]
            variable.append(
                Region(
                    id=uuid.uuid4().hex,
                    dataset_id=dataset.id,
                    molecule_id=reference["id"],
                    dataset_revision=1,
                    graph_sha256=reference["graph_sha256"],
                    atom_indices=[0] if index == 0 else [0, 1],
                    attachment_count=1,
                    created_at=dataset.created_at,
                    name=f"Variable {index + 1}",
                ).model_dump()
            )
        core_regions = [
            Region(
                id=uuid.uuid4().hex,
                dataset_id=dataset.id,
                molecule_id=rows[0]["id"],
                dataset_revision=1,
                graph_sha256=rows[0]["graph_sha256"],
                atom_indices=[2, 3, 4, 5, 7, 8],
                attachment_count=2,
                created_at=dataset.created_at,
                name=f"Confirmed core {index + 1}",
                kind="core",
            ).model_dump()
            for index in range(cores)
        ]
        request = StudyRequest(
            request_id=uuid.uuid4().hex,
            title="Controlled functional report",
            expected_dataset_revision=1,
            policies=policies or [policy()],
            region_ids=[region["id"] for region in variable],
            core_ids=[core["id"] for core in core_regions],
            confirm_context=confirmed,
            candidate_count=5,
        )
        return {
            "schema": 2,
            "job_id": self.root.name,
            "engine_sha256": engine_identity(),
            "producer": {"product": product_ref(), "rdkit_version": version("rdkit")},
            "dataset": dataset.model_dump(),
            "molecules": rows,
            "regions": variable,
            "cores": core_regions,
            "request": request.model_dump(),
        }

    def write(self, packet):
        atomic_json(self.root, "input.json", packet)
        return digest(packet)

    def run_packet(self, packet):
        result = study_analysis.analyse_study(self.root, self.write(packet))
        report = StudyReport.model_validate(
            SafeFiles(self.root).json("report.json", optional=False)
        )
        self.assertEqual(result["report_sha256"], digest(report.model_dump()))
        return result, report

    def test_native_subprocess_full_report_is_accepted_by_parent(self):
        packet = self.packet(regions=2, cores=1)
        input_sha = self.write(packet)
        source = str(Path(study_analysis.__file__).resolve().parents[2])
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json,sys;from pathlib import Path;from patent_sar_extractor.workers.study_analysis import analyse_study;print(json.dumps(analyse_study(Path(sys.argv[1]),sys.argv[2])))",
                str(self.root),
                input_sha,
            ],
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": source,
                "PYTHONDONTWRITEBYTECODE": "1",
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "CUDA_VISIBLE_DEVICES": "-1",
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        reply = json.loads(result.stdout)
        safe = SafeFiles(self.root)
        report = safe.json("report.json", optional=False)
        pairs = [
            Pair.model_validate(pair)
            for index in range(reply["chunks"])
            for pair in safe.json(f"chunk-{index:04d}.json")["pairs"]
        ]
        job = SARJob(
            id=self.root.name,
            dataset_id=packet["dataset"]["id"],
            region_id=packet["regions"][0]["id"],
            metric_id="activity",
            kind="study",
            status="running",
            total=7,
            created_at="2026-01-01T00:00:00Z",
            input_sha256=input_sha,
        )
        self.assertEqual(
            verify_study(
                safe, job, {"engine_sha256": packet["engine_sha256"]}, reply, pairs
            ),
            reply["report_sha256"],
        )
        self.assertEqual(report["strict_pair_count"], 4)
        self.assertEqual(report["matched_pair_count"], 2)
        self.assertEqual(report["comparable_pair_count"], 2)
        self.assertEqual(safe.json("progress.json")["processed"], 7)
        self.assertEqual(safe.json("progress.json")["matched"], 2)
        self.assertTrue(
            all(
                summary["independent_backgrounds"] == 1 for summary in report["regions"]
            )
        )
        self.assertTrue(
            any(
                group["assignment_kind"] == "confirmed_core"
                for group in report["scaffolds"]
            )
        )
        self.assertFalse(report["article_algorithm_reproduced"])

    def test_distributions_count_repeats_without_best_only_or_average(self):
        rows = [molecule("ID1", "CCO"), molecule("ID2", "CCN"), molecule("ID3", "CCC")]
        rows[0]["observations"] = [observation("A"), observation("A")]
        rows[1]["observations"] = [observation("A"), observation("B")]
        rows[2]["observations"] = [observation("NA")]
        _, report = self.run_packet(
            self.packet(
                rows,
                regions=0,
                policies=[policy(grade_order=["A", "B"], strong_threshold=None)],
            )
        )
        distribution = report.distributions[0]
        strongest = next(bucket for bucket in distribution.bins if bucket.label == "A")
        self.assertEqual((strongest.observations, strongest.molecules), (3, 2))
        self.assertEqual(distribution.strong_molecules, 1)
        self.assertEqual(distribution.unresolved_molecules, 1)
        self.assertEqual(distribution.missing_molecules, 1)
        self.assertEqual(
            report.rows[1].activity_status[policy()["context_id"]], "indeterminate"
        )
        self.assertIn("activity_unresolved_retained_in_report", report.warnings)

    def test_interval_strength_and_numeric_bins_never_use_midpoints(self):
        selected = policy(strong_threshold=5.0, threshold_inclusive=False)
        values = ("<5", "<=5", "[1,4]", "[1,10]", "5", "6", "unexpected 1")
        obs = {str(index): [observation(value)] for index, value in enumerate(values)}
        assessments = {
            identifier: assess(readings, selected, False)
            for identifier, readings in obs.items()
        }
        result = distribution(list(obs), obs, selected, assessments)
        self.assertEqual(result["strong_molecules"], 2)
        self.assertEqual(
            sum(bucket["observations"] for bucket in result["bins"]), len(values)
        )
        self.assertTrue(
            any(bucket["kind"] == "unsupported" for bucket in result["bins"])
        )
        self.assertFalse(assessments["3"]["strong"])

    def test_same_grade_is_priority_tie_not_numeric_pair_equality(self):
        ranks = {"A": 0, "B": 1}
        selected = [{"direction": "lower", "grade_order": ["A", "B"]}]
        fronts = pareto_fronts(
            {
                "a": (parse_value("A", ranks),),
                "b": (parse_value("A", ranks),),
                "c": (parse_value("B", ranks),),
            },
            selected,
        )
        self.assertEqual(fronts, {"a": 1, "b": 1, "c": 2})
        interval_policy = [
            {"direction": "lower", "grade_order": []},
            {"direction": "lower", "grade_order": []},
        ]
        fronts = pareto_fronts(
            {
                "a": (parse_value("[1,5]", {}), parse_value("1", {})),
                "b": (parse_value("[1,5]", {}), parse_value("2", {})),
            },
            interval_policy,
        )
        self.assertEqual(fronts, {"a": 1, "b": 1})
        packet = self.packet(
            policies=[policy(grade_order=["A", "B"], strong_threshold=None)]
        )
        for row in packet["molecules"]:
            row["observations"] = [observation("A")]
        _, report = self.run_packet(packet)
        pair = SafeFiles(self.root).json("chunk-0000.json")["pairs"][0]
        self.assertEqual(pair["comparison"], "indeterminate")
        self.assertIsNone(pair["fold_change"])
        self.assertEqual(report.comparable_pair_count, 0)

    def test_missing_conditions_confirmation_never_makes_priority_known(self):
        rows = [molecule("ID1", "CCO"), molecule("ID2", "CCN")]
        for row in rows:
            row["observations"][0]["context"]["duration"] = None
        selected = policy(context_id=context_identity(rows[0]["observations"][0]))
        _, report = self.run_packet(
            self.packet(rows, regions=0, policies=[selected], confirmed=True)
        )
        self.assertEqual(report.candidates, [])
        self.assertTrue(all(row.candidate_status == "unranked" for row in report.rows))
        self.assertIn("context_user_confirmed", report.warnings)

    def test_exact_context_selection_does_not_mix_assays_or_units(self):
        rows = [molecule("ID1", "CCO", "10"), molecule("ID2", "CCN", "1")]
        rows[1]["observations"][0]["context"]["assay"] = "different assay"
        rows[0]["observations"].append(observation("0.01", unit="uM"))
        _, report = self.run_packet(self.packet(rows, regions=0, confirmed=True))
        self.assertEqual(report.rows[0].values[policy()["context_id"]], ["10"])
        self.assertEqual(report.rows[1].values[policy()["context_id"]], [])
        self.assertEqual(report.distributions[0].missing_molecules, 1)
        self.assertEqual(report.observation_count, 3)

    def test_original_natural_order_and_unverified_rows_are_all_retained(self):
        rows = [molecule("ID10", None), molecule("ID2", "CCO"), molecule("ID1", "CCN")]
        _, report = self.run_packet(self.packet(rows, regions=0))
        self.assertEqual([row.label for row in report.rows], ["ID1", "ID2", "ID10"])
        self.assertEqual(
            [row.label for row in report.rows],
            sorted([row["label"] for row in rows], key=natural_identifier_key),
        )
        self.assertEqual(report.molecule_count, 3)
        self.assertFalse(report.rows[-1].eligible)
        self.assertEqual(sum(group.molecule_count for group in report.scaffolds), 3)

    def test_descriptor_domain_keeps_sar_graph_and_manual_null_and_supplied_logs(self):
        rows = [
            molecule("ID1", "C" * 257),
            molecule(
                "ID2",
                "CCO",
                properties={"logP": None, "Solubility_AqSolDB": -3.2},
                property_origins={
                    "logP": "manual_null",
                    "Solubility_AqSolDB": "imported",
                },
            ),
        ]
        _, report = self.run_packet(self.packet(rows, regions=0))
        large, ordinary = report.rows
        self.assertTrue(large.eligible)
        self.assertTrue(all(large.properties[key] is None for key in DESCRIPTOR_KEYS))
        self.assertIn("descriptor_out_of_domain", large.reasons)
        self.assertIsNone(ordinary.properties["logP"])
        self.assertEqual(ordinary.property_origins["logP"], "manual_null")
        self.assertEqual(ordinary.properties["Solubility_AqSolDB"], -3.2)
        self.assertEqual(
            ordinary.property_origins["molecular_weight"], "computed_rdkit"
        )

    def test_actual_model_evidence_is_secondary_and_imported_prediction_is_unknown(
        self,
    ):
        rows = [
            molecule(
                "ID1",
                "CCO",
                predictions={"hERG": 0.9},
                prediction_origin="verified_project_model",
            ),
            molecule(
                "ID2",
                "CCN",
                predictions={"hERG": 0.1},
                prediction_origin="verified_project_model",
            ),
            molecule(
                "ID3", "CCC", predictions={"hERG": 0.0}, prediction_origin="imported"
            ),
        ]
        _, report = self.run_packet(self.packet(rows, regions=0))
        self.assertEqual(report.candidates[0].molecule_id, "ID2")
        self.assertIn("predicted_liability_requires_review", report.rows[0].reasons)
        self.assertIn("imported_predictions_unverified", report.rows[2].reasons)
        self.assertEqual(report.rows[2].predictions["hERG"], 0.0)
        self.assertIn(
            "prediction_evidence_unknown_or_unverified", report.rows[2].reasons
        )

    def test_1191_alias_rows_complete_without_filling_candidates_with_one_graph(self):
        base = molecule("ID1", "CCO")
        rows = [
            {**base, "id": f"ID{index}", "label": f"ID{index}"}
            for index in range(1, 1192)
        ]
        _, report = self.run_packet(self.packet(rows, regions=0))
        self.assertEqual(len(report.rows), 1191)
        self.assertEqual(report.observation_count, 1191)
        self.assertEqual(len(report.candidates), 1)
        self.assertEqual(
            sum(
                "graph_identical_selection_alias" in row.reasons for row in report.rows
            ),
            1190,
        )
        self.assertEqual(SafeFiles(self.root).json("progress.json")["processed"], 1191)

    def test_identical_graph_conflicts_are_not_best_only_alias_selection(self):
        rows = [molecule("ID1", "CCO", "1"), molecule("ID2", "OCC", "10")]
        _, report = self.run_packet(self.packet(rows, regions=0))
        self.assertEqual(report.candidates, [])
        self.assertTrue(
            all(
                "graph_alias_measurements_conflict" in row.reasons
                for row in report.rows
            )
        )
        self.assertEqual(
            [row.values[policy()["context_id"]] for row in report.rows], [["1"], ["10"]]
        )

    def test_confirmed_core_overlap_is_explicit_and_does_not_replace_murcko(self):
        _, report = self.run_packet(self.packet(cores=2))
        cores = [
            group
            for group in report.scaffolds
            if group.assignment_kind == "confirmed_core"
        ]
        self.assertEqual(len(cores), 2)
        self.assertTrue(all(group.molecule_count == 3 for group in cores))
        self.assertIn("confirmed_core_groups_overlap", report.warnings)
        self.assertTrue(
            any(group.assignment_kind == "murcko" for group in report.scaffolds)
        )

    def test_conflicting_repeats_in_one_alias_cannot_promote_another_alias(self):
        rows = [molecule("ID1", "CCO", "1"), molecule("ID2", "OCC", "1")]
        rows[0]["observations"].append(observation("10"))
        _, report = self.run_packet(self.packet(rows, regions=0))
        self.assertEqual(report.candidates, [])
        self.assertTrue(
            all(
                "graph_alias_measurements_conflict" in row.reasons
                for row in report.rows
            )
        )

    def test_deadline_preserves_native_chunks_and_resume_reuses_descriptors(self):
        rows = [
            molecule("ID1", "COc1ccc(Cl)cc1", "10"),
            *[molecule(f"ID{index}", "CCOc1ccc(Cl)cc1") for index in range(2, 57)],
        ]
        packet = self.packet(rows, regions=2)
        input_sha = self.write(packet)
        original = study_pairs.make_pair
        calls = 0

        def deadline(*args):
            nonlocal calls
            calls += 1
            if calls == 26:
                raise TimeoutError("study_deadline_exceeded")
            return original(*args)

        with (
            patch.object(study_pairs, "make_pair", side_effect=deadline),
            self.assertRaises(TimeoutError),
        ):
            study_analysis.analyse_study(self.root, input_sha)
        chunk = self.root / "chunk-0000.json"
        sealed = (chunk.read_bytes(), chunk.stat().st_mtime_ns)
        self.assertFalse((self.root / "report.json").exists())
        with (
            patch.object(
                study_analysis,
                "describe",
                side_effect=AssertionError("cached descriptor was recomputed"),
            ),
            patch.object(study_pairs, "make_pair", wraps=original) as native,
        ):
            result = study_analysis.analyse_study(self.root, input_sha)
        self.assertEqual(native.call_count, 85)
        self.assertEqual((chunk.read_bytes(), chunk.stat().st_mtime_ns), sealed)
        self.assertEqual(result["chunks"], 5)
        self.assertEqual(SafeFiles(self.root).json("progress.json")["processed"], 166)

    def test_rehashed_pair_proof_tampering_is_rejected(self):
        packet = self.packet()
        input_sha = self.write(packet)
        study_analysis.analyse_study(self.root, input_sha)
        chunk = SafeFiles(self.root).json("chunk-0000.json")
        chunk["pairs"][0]["variable_atom_indices"] = [999]
        chunk["pairs_sha256"] = digest(chunk["pairs"])
        atomic_json(self.root, "chunk-0000.json", chunk)
        with self.assertRaises(SARInputError) as error:
            study_analysis.analyse_study(self.root, input_sha)
        self.assertEqual(error.exception.code, "study_pair_checkpoint_proof")

    def test_descriptor_checkpoint_order_and_engine_tampering_are_rejected(self):
        packet = self.packet(regions=0)
        input_sha = self.write(packet)
        study_analysis.analyse_study(self.root, input_sha)
        chunk = SafeFiles(self.root).json("descriptors-0000.json")
        chunk["rows"].reverse()
        chunk["rows_sha256"] = digest(chunk["rows"])
        atomic_json(self.root, "descriptors-0000.json", chunk)
        with self.assertRaises(SARInputError):
            study_analysis.analyse_study(self.root, input_sha)
        packet["engine_sha256"] = "0" * 64
        with self.assertRaises(SARInputError) as error:
            study_analysis.analyse_study(self.root, self.write(packet))
        self.assertEqual(error.exception.code, "study_input_identity")

    def test_budgets_policy_conflicts_and_foreign_region_fail_before_report(self):
        packet = self.packet()
        with (
            patch.object(study_analysis, "MAX_COMPARISONS", 1),
            self.assertRaises(SARInputError),
        ):
            study_analysis.analyse_study(self.root, self.write(packet))
        with (
            patch.object(study_analysis, "MAX_ROWS", 2),
            self.assertRaises(SARInputError),
        ):
            study_analysis.analyse_study(self.root, self.write(packet))
        with (
            patch.object(study_analysis, "MAX_OBSERVATIONS", 2),
            self.assertRaises(SARInputError),
        ):
            study_analysis.analyse_study(self.root, self.write(packet))
        packet["request"]["policies"][0]["grade_order"] = ["A", "B"]
        with self.assertRaises(SARInputError) as error:
            study_analysis.analyse_study(self.root, self.write(packet))
        self.assertEqual(error.exception.code, "study_policy_strength_conflict")
        self.assertFalse((self.root / "report.json").exists())
        vectors = {str(index): (parse_value(str(index), {}),) for index in range(5001)}
        with self.assertRaises(SARInputError) as error:
            pareto_fronts(vectors, [{"direction": "lower", "grade_order": []}])
        self.assertEqual(error.exception.code, "study_ranking_limit")


if __name__ == "__main__":
    unittest.main()
