"""Real SQLite/RDKit and conservative evidence-summary regression tests."""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from test_web_support import WebFixture, artifact_run

from patent_sar_extractor.web.analysis import AnalysisService
from patent_sar_extractor.web.analysis_cache import AnalysisCache, cache_key
from patent_sar_extractor.web.analysis_chemistry import (
    canonical_smiles,
    recognized_smiles,
    validate_batch,
)
from patent_sar_extractor.web.analysis_runtime import (
    AnalysisSettings,
    admet_bundle,
    child_environment,
    decimer_model_key,
)
from patent_sar_extractor.web.analysis_summary import numeric_evidence, summarize
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.models import Activity
from patent_sar_extractor.web.service import WorkspaceService


class ChemistryTests(unittest.TestCase):
    def test_real_rdkit_sanitization_and_stereochemistry(self):
        self.assertEqual(canonical_smiles("OCC"), "CCO")
        self.assertEqual(
            validate_batch([" O=C(O)c1ccccc1 ", "OCC", "CCO"])[1:], ["CCO", "CCO"]
        )
        self.assertIn("@", canonical_smiles("C[C@H](O)F"))
        self.assertEqual(recognized_smiles("OCC"), "CCO")
        self.assertEqual(canonical_smiles("[Na+].CC(=O)[O-]"), "CC(=O)[O-].[Na+]")

    def test_bad_query_size_and_titles_are_not_accepted(self):
        for value in (
            "",
            "not-a-SMILES",
            "CCO name",
            "CCO\nCC",
            "[R1]",
            "*CC",
            "[Xe]",
            "C" * 257,
            "C" * 2049,
            "[H][H]",
        ):
            with self.subTest(value=value[:20]), self.assertRaises(WebError):
                canonical_smiles(value)
            self.assertIsNone(recognized_smiles(value))
        for values in ([], ["CC"] * 51, [123]):
            with self.assertRaises(WebError):
                validate_batch(values)

    def test_numeric_exact_range_censoring_and_nonfinite(self):
        for value in ("<0.1", ">=2", "≤ 3", "1-2", "1 – 2", "1e-3 to 2e-3", "≈5"):
            self.assertEqual(numeric_evidence(value), (None, True), value)
        self.assertEqual(numeric_evidence("−2.5e-3"), (-0.0025, False))
        for value in ("1e999", "nan", "inf", "missing", None, True, "2 nM"):
            self.assertEqual(numeric_evidence(value), (None, False), value)


class AnalysisCoreTests(WebFixture, unittest.TestCase):
    def make_service(self):
        workspace = WorkspaceService(self.state)
        analysis = AnalysisService(self.state, workspace, settings=AnalysisSettings())
        self.addCleanup(analysis.close)
        return workspace, analysis

    def test_private_schema_real_persistence_and_no_main_schema_mutation(self):
        workspace, analysis = self.make_service()
        with workspace.store.connect() as connection:
            before = list(
                connection.execute("SELECT sql FROM sqlite_master ORDER BY name")
            )
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        key = cache_key(["real", "identity"])
        analysis.cache.put("admet", key, {"value": 1.25})
        self.assertEqual(AnalysisCache(self.state).get("admet", key), {"value": 1.25})
        self.assertIsNone(analysis.cache.get("recognize", key))
        self.assertEqual(analysis.cache.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(analysis.cache.root.stat().st_mode & 0o777, 0o700)
        with sqlite3.connect(analysis.cache.path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        with workspace.store.connect() as connection:
            self.assertEqual(
                before,
                list(connection.execute("SELECT sql FROM sqlite_master ORDER BY name")),
            )

    def test_cache_corruption_and_future_schema_are_visible(self):
        _, analysis = self.make_service()
        with sqlite3.connect(analysis.cache.path) as connection:
            connection.execute(
                "INSERT INTO analysis_cache VALUES('admet','bad','NaN','now')"
            )
        with self.assertRaises(WebError) as error:
            analysis.cache.get("admet", "bad")
        self.assertEqual(error.exception.code, "analysis_cache_error")
        with sqlite3.connect(analysis.cache.path) as connection:
            connection.execute("PRAGMA user_version=2")
        with self.assertRaises(WebError) as error:
            AnalysisCache(self.state)
        self.assertEqual(error.exception.code, "analysis_schema")

    def test_cache_symlink_and_wrong_workspace_are_rejected(self):
        self.state.mkdir(mode=0o700)
        (self.state / "analysis").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(WebError):
            AnalysisCache(self.state)
        workspace = WorkspaceService(self.state)
        with self.assertRaises(WebError):
            AnalysisService(self.root / "other", workspace)

    def test_null_or_scalar_cache_is_not_a_silent_cache_miss(self):
        _, analysis = self.make_service()
        for payload in ("null", "42", "[]"):
            with sqlite3.connect(analysis.cache.path) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO analysis_cache VALUES('admet','corrupt',?,'now')",
                    (payload,),
                )
            with self.assertRaises(WebError) as error:
                analysis.cache.get("admet", "corrupt")
            self.assertEqual(error.exception.code, "analysis_cache_error")

    def test_independent_units_targets_assays_and_censored_values(self):
        workspace, analysis = self.make_service()
        run = artifact_run(self.root / "run", self.pdf, current=False)
        project = workspace.import_run(run)
        compounds = workspace.compounds(project.id)
        compounds[0].smiles = None
        compounds[0].activities = [
            Activity(
                name="IC50", value="1", unit="nM", target="A", assay="one", page=1
            ),
            Activity(
                name="IC50", value="<0.1", unit="nM", target="A", assay="one", page=1
            ),
            Activity(
                name="IC50", value="2-4", unit="nM", target="A", assay="one", page=1
            ),
            Activity(name="IC50", value="9", unit="uM", target="A", page=1),
            Activity(name="IC50", value="8", unit="nM", target="B", page=1),
            Activity(
                name="IC50", value="7", unit="nM", target="A", assay="two", page=1
            ),
            Activity(name="Ki", value="NaN", unit=None, page=999),
        ]
        compounds[1].activities = []
        summary = summarize(project, compounds)
        group = next(a for a in summary.activities if a.rows == 3)
        self.assertEqual(
            (group.numeric_rows, group.censored_rows, group.min, group.max),
            (1, 2, 1.0, 1.0),
        )
        self.assertEqual(len(summary.activities), 5)
        self.assertEqual(summary.source_pages, [1])
        self.assertEqual(summary.acceptance.state, "historical")
        self.assertEqual(summary.counts.smiles, 1)
        self.assertTrue(any("out-of-document" in text for text in summary.limitations))
        self.assertTrue(any("assay conditions" in text for text in summary.limitations))
        self.assertEqual(analysis.evidence_summary(project.id).counts.compounds, 2)

    def test_absent_environment_invalid_settings_and_closed_service(self):
        _, analysis = self.make_service()
        self.assertEqual(analysis.capabilities(), {"admet": False, "summary": True})
        with self.assertRaises(WebError) as invalid:
            analysis.admet(["bad"])
        self.assertEqual(invalid.exception.status, 422)
        with self.assertRaises(WebError) as unavailable:
            analysis.admet(["CCO"])
        self.assertEqual(unavailable.exception.status, 503)
        for timeout in (0, 181, float("nan")):
            with self.assertRaises(WebError):
                AnalysisSettings(admet_timeout_seconds=timeout)
        analysis.close()
        analysis.close()
        self.assertFalse(analysis.capabilities()["summary"])
        with self.assertRaises(WebError) as cancelled:
            analysis.admet(["CCO"])
        self.assertEqual(cancelled.exception.code, "analysis_cancelled")

    def test_model_paths_must_not_be_missing_or_symlinked(self):
        for root in (None, self.root / "absent"):
            with self.assertRaises(WebError):
                admet_bundle(root)
            with self.assertRaises(WebError):
                decimer_model_key(root)
        model = self.root / "model"
        model.mkdir()
        (model / "manifest.json").symlink_to(self.pdf)
        with self.assertRaises(WebError):
            admet_bundle(model)
        env = child_environment(
            AnalysisSettings(), Path("/usr/bin/python3.12"), self.root
        )
        self.assertNotIn("HOME", env)
        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["PATENTSAR_DECIMER_PERSISTENT"], "0")
