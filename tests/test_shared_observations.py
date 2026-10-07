"""Same original/model/image reuses raw observations, never old QA or properties."""

import hashlib
from pathlib import Path
from unittest.mock import patch

from test_existing_compound_completion import (
    CompletionAnalysis,
    ControlledConverter,
    ExistingCompoundCompletionTests,
)
from test_uniform_recognition import observation

from patent_sar_extractor.cli import build_parser
from patent_sar_extractor.core.ocsr.smiles_cache import SmilesCache
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.observation_cache import (
    cache_path,
    import_observations,
    merge_snapshots,
    safe_snapshot,
)
from patent_sar_extractor.web.prediction_worker import run_predictions


class SharedObservationTests(ExistingCompoundCompletionTests):
    def raw_cache(self, name="raw.sqlite", raw="CCO"):
        path = self.root / name
        cache = SmilesCache(str(path))
        cache.save_result(
            "b" * 64,
            "decimer:raw-v2:" + "a" * 64,
            {"status": "success", "raw_smiles": raw, "model_fingerprint": "a" * 64},
        )
        return path

    def test_import_does_not_write_compounds_audit_or_acceptance(self):
        before = self.service.store.compound(self.project.id, "Compound 1")
        project = self.service.store.project(self.project.id)
        result = import_observations(self.service, self.project.id, self.raw_cache())
        self.assertEqual(result["raw_observations"], 1)
        self.assertFalse(result["model_loaded"])
        self.assertEqual(
            self.service.store.compound(self.project.id, "Compound 1"), before
        )
        self.assertEqual(self.service.store.project(self.project.id), project)

    def test_exact_key_conflict_cannot_overwrite_existing_raw_observation(self):
        target = self.root / "target.sqlite"
        first = safe_snapshot(self.raw_cache())
        second = safe_snapshot(self.raw_cache("other.sqlite", "CCN"))
        merge_snapshots(target, [first])
        before = target.read_bytes()
        with self.assertRaises(WebError) as rejected:
            merge_snapshots(target, [first, second])
        self.assertEqual(rejected.exception.code, "recognition_cache_conflict")
        self.assertEqual(target.read_bytes(), before)

    def test_foreign_model_and_symlink_cache_are_rejected(self):
        path = self.raw_cache()
        cache = SmilesCache(str(path))
        cache.save_result(
            "b" * 64,
            "decimer:raw-v2:" + "a" * 64,
            {"status": "success", "raw_smiles": "CCO", "model_fingerprint": "c" * 64},
        )
        with self.assertRaises(WebError):
            safe_snapshot(path)
        link = self.root / "link.sqlite"
        link.symlink_to(path)
        with self.assertRaises(WebError):
            safe_snapshot(link)

    def test_import_busy_guard_uses_same_workspace_lease(self):
        self.prepare()
        with self.assertRaises(WebError) as rejected:
            import_observations(self.service, self.project.id, self.raw_cache())
        self.assertEqual(rejected.exception.code, "recognition_cache_busy")

    def test_per_original_cache_isolation_and_cli_contract(self):
        project = self.service.store.project(self.project.id)
        first = cache_path(self.state, project)
        second = cache_path(self.state, {**project, "sha256": "a" * 64})
        self.assertNotEqual(first, second)
        args = build_parser().parse_args(
            [
                "import-ocsr-cache",
                "--cache",
                "raw.sqlite",
                "--project-id",
                self.project.id,
                "--state-dir",
                str(self.state),
            ]
        )
        self.assertEqual((args.cache, args.project_id), ("raw.sqlite", self.project.id))

    def test_auto_published_raw_cache_reuses_next_project_without_model_loading(self):
        row = self.prepare()

        class Recording(ControlledConverter):
            def __init__(self, *args, **kwargs):
                from patent_sar_extractor.core.ocsr.smiles_cache import SmilesCache

                self.cache = SmilesCache(kwargs["cache_path"])

            def convert_one(self, binding, **kwargs):
                result = super().convert_one(binding, **kwargs)
                self.cache.save_result(
                    result["image_hash"],
                    "decimer:raw-v2:" + "a" * 64,
                    {
                        "status": "success",
                        "raw_smiles": result["raw_smiles"],
                        "model_fingerprint": "a" * 64,
                    },
                )
                return result

        with patch(
            "patent_sar_extractor.core.ocsr.smiles_converter.SmilesConverter", Recording
        ):
            run_predictions(self.service, CompletionAnalysis(), row)
        with self.service.store.connect(write=True) as db:
            db.execute("UPDATE jobs SET status='complete' WHERE id=?", (row["id"],))
        # A new projection is a new source/audit basis, but exactly the same
        # original crop/model may be rechecked from raw model cache.
        self.service.refresh(self.project.id)
        from test_corpus_predictions import CorpusPredictionTests

        next_row = CorpusPredictionTests.job(self)[0]

        class NoInference:
            def __init__(self, *args, **kwargs):
                from patent_sar_extractor.core.ocsr.smiles_cache import SmilesCache

                self.cache = SmilesCache(kwargs["cache_path"])

            def convert_one(self, binding, **kwargs):
                raw = self.cache.get_cached_result(
                    hashlib.sha256(
                        Path(binding["image_path"]).read_bytes()
                    ).hexdigest(),
                    "decimer:raw-v2:" + "a" * 64,
                )
                if raw is None:
                    raise AssertionError("A repeat must not load a model")
                return observation(binding, raw["raw_smiles"])

            def close(self):
                pass

            def finalize_batch(self, records, **kwargs):
                return records

        with patch(
            "patent_sar_extractor.core.ocsr.smiles_converter.SmilesConverter",
            NoInference,
        ):
            run_predictions(self.service, CompletionAnalysis(), next_row)
        self.assertEqual(
            self.service.effective_compound(self.project.id, "Compound 8").smiles, "CCO"
        )
