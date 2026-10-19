"""Existing environments are verified, never repaired through a download fallback."""

import hashlib
import json
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.web.environment_models import (
    EnvironmentComponent,
    EnvironmentOperationRequest,
)
from patent_sar_extractor.web.environment_specs import component_catalog
from patent_sar_extractor.workers.environment_errors import EnvironmentFailure
from patent_sar_extractor.workers.environment_recipes import EnvironmentProvisioner
from tests.test_environment_recipes import RecipeFixture


class ExistingTextOCRReuseTests(RecipeFixture):
    def source(self):
        models = self.root / "existing-models"
        models.mkdir()
        content = b"controlled model bytes, not recognition evidence"
        (models / "weights.bin").write_bytes(content)
        self.spec = {
            "models": [
                {
                    "file": "weights.bin",
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ]
        }
        return {"python": "/usr/bin/python3", "models": str(models)}

    def ready(self, ids, context, **_kwargs):
        metadata = {item["id"]: item for item in component_catalog()}
        return [
            EnvironmentComponent.model_validate(
                {
                    **metadata[key],
                    "status": "ready",
                    "location": context.bindings()[key],
                    "detected_version": "controlled",
                    "checks": [
                        {
                            "name": "control",
                            "ok": True,
                            "message": "Native probe is controlled in this test",
                        }
                    ],
                }
            )
            for key in ids
        ]

    def test_local_copy_uses_one_owned_plan_and_never_installs_or_downloads(self):
        source = self.source()
        bindings = {**self.payload["bindings"], "text-ocr": source["python"]}
        plan = self.plan(
            action="reuse",
            component_ids=["text-ocr", "text-ocr-models"],
            bindings=bindings,
            reuse_source=source,
        )
        original = (Path(source["models"]) / "weights.bin").read_bytes()
        with (
            patch(
                "patent_sar_extractor.workers.text_ocr_reuse.recipe",
                return_value=self.spec,
            ),
            patch.object(
                EnvironmentProvisioner,
                "install",
                side_effect=AssertionError("No installation fallback"),
            ),
            patch(
                "patent_sar_extractor.workers.environment_assets.download",
                side_effect=AssertionError("No network fallback"),
            ),
        ):
            result = EnvironmentProvisioner(
                plan, threading.Event(), self.ready
            ).execute()
        self.assertEqual(set(result["bindings"]), {"text-ocr", "text-ocr-models"})
        self.assertEqual(result["bindings"]["text-ocr"], source["python"])
        destination = Path(result["bindings"]["text-ocr-models"])
        self.assertTrue(destination.is_relative_to(self.install))
        self.assertEqual((destination / "weights.bin").read_bytes(), original)
        self.assertEqual(
            (Path(source["models"]) / "weights.bin").read_bytes(), original
        )
        self.assertEqual((destination / "weights.bin").stat().st_mode & 0o777, 0o600)

    def test_reuse_request_requires_the_complete_pair_and_exact_sources(self):
        source = self.source()
        body = {
            "action": "reuse",
            "component_ids": ["text-ocr", "text-ocr-models"],
            "reuse_source": source,
            "request_id": "existing-environment-123",
            "expected_revision": 0,
        }
        self.assertEqual(
            EnvironmentOperationRequest.model_validate(body).reuse_source, source
        )
        for delta in (
            {"reuse_source": None},
            {"component_ids": ["base"]},
            {"reuse_source": {**source, "python": "/mnt/e/python"}},
            {"reuse_source": {**source, "models": "/tmp/../outside"}},
            {"reuse_source": {**source, "url": "https://invalid.test"}},
            {"action": "install"},
        ):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                EnvironmentOperationRequest.model_validate({**body, **delta})

    def test_bad_runtime_stops_before_copy_or_fallback(self):
        source = self.source()
        plan = self.plan(
            action="reuse",
            component_ids=["text-ocr", "text-ocr-models"],
            bindings={**self.payload["bindings"], "text-ocr": source["python"]},
            reuse_source=source,
        )

        def bad(ids, context, **kwargs):
            cards = self.ready(ids, context, **kwargs)
            return [
                card.model_copy(update={"status": "incompatible"}) for card in cards
            ]

        with self.assertRaises(EnvironmentFailure):
            EnvironmentProvisioner(plan, threading.Event(), bad).execute()
        self.assertEqual(list(self.install.iterdir()), [self.marker])

    def test_reuse_selection_survives_saved_plan_and_rejects_other_actions(self):
        source = self.source()
        source["models"] = "/mnt/e/operator-owned/existing-model"
        plan = self.plan(
            action="reuse",
            component_ids=["text-ocr", "text-ocr-models"],
            bindings={**self.payload["bindings"], "text-ocr": source["python"]},
            reuse_source=source,
        )
        self.assertEqual(plan.reuse_source, source)
        saved = json.loads(self.plan_file.read_text())
        for action in ("inspect", "install"):
            saved["action"] = action
            self.plan_file.write_text(json.dumps(saved))
            with self.assertRaises(ValueError):
                from patent_sar_extractor.workers.environment_plan import read_plan

                read_plan(self.plan_file)

    def test_cancel_and_prefix_collision_preserve_source_and_user_files(self):
        source = self.source()
        plan = self.plan(
            action="reuse",
            component_ids=["text-ocr", "text-ocr-models"],
            bindings={**self.payload["bindings"], "text-ocr": source["python"]},
            reuse_source=source,
        )
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            EnvironmentProvisioner(plan, cancelled, self.ready).execute()
        prefix = self.install / ("text-ocr-models-reused-" + self.identifier)
        prefix.mkdir(mode=0o700)
        marker = prefix / "user.txt"
        marker.write_text("preserve")
        with (
            patch(
                "patent_sar_extractor.workers.text_ocr_reuse.recipe",
                return_value=self.spec,
            ),
            self.assertRaises(FileExistsError),
        ):
            EnvironmentProvisioner(plan, threading.Event(), self.ready).execute()
        self.assertEqual(marker.read_text(), "preserve")
        self.assertEqual(
            (Path(source["models"]) / "weights.bin").stat().st_size,
            self.spec["models"][0]["size"],
        )

    def test_symlinked_or_changed_source_cannot_supply_a_model_copy(self):
        source = self.source()
        plan = self.plan(
            action="reuse",
            component_ids=["text-ocr", "text-ocr-models"],
            bindings={**self.payload["bindings"], "text-ocr": source["python"]},
            reuse_source=source,
        )
        model = Path(source["models"]) / "weights.bin"
        original = self.root / "original.bin"
        model.rename(original)
        model.symlink_to(original)
        with (
            patch(
                "patent_sar_extractor.workers.text_ocr_reuse.recipe",
                return_value=self.spec,
            ),
            self.assertRaises(ValueError),
        ):
            EnvironmentProvisioner(plan, threading.Event(), self.ready).execute()
        self.assertEqual(list(self.install.iterdir()), [self.marker])


@unittest.skipUnless(
    os.environ.get("PATENTSAR_TEST_TEXT_OCR_PYTHON")
    and os.environ.get("PATENTSAR_TEST_TEXT_OCR_MODELS"),
    "Explicit approved isolated OCR sources required",
)
class NativeExistingTextOCRReuseTests(RecipeFixture):
    def test_real_offline_pair_verification_and_managed_copy(self):
        from patent_sar_extractor.core.text_ocr.identity import model_files, recipe
        from patent_sar_extractor.web.environment_inspection import inspect_components

        source = {
            "python": os.environ["PATENTSAR_TEST_TEXT_OCR_PYTHON"],
            "models": os.environ["PATENTSAR_TEST_TEXT_OCR_MODELS"],
        }
        before = model_files(Path(source["models"]), recipe())
        plan = self.plan(
            action="reuse",
            component_ids=["text-ocr", "text-ocr-models"],
            bindings={**self.payload["bindings"], "text-ocr": source["python"]},
            reuse_source=source,
        )
        result = EnvironmentProvisioner(
            plan, threading.Event(), inspect_components
        ).execute()
        self.assertEqual(result["bindings"]["text-ocr"], source["python"])
        target = Path(result["bindings"]["text-ocr-models"])
        self.assertTrue(target.is_relative_to(self.install))
        self.assertEqual(model_files(target, recipe()), before)
        self.assertEqual(model_files(Path(source["models"]), recipe()), before)
        self.assertEqual(len(list(target.iterdir())), 3)
        self.assertTrue(all(card["status"] == "ready" for card in result["components"]))
