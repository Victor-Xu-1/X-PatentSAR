"""Analysis adapters under the existing real session/CSRF middleware.

Model mocks here isolate DTO/error/cache behavior; actual offline inference is
separately exercised by the opt-in real tests and external smoke evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_web_support import BASE_URL, WebFixture, artifact_run

from patent_sar_extractor.web.analysis_children import alive, read_child
from patent_sar_extractor.web.analysis_process import BoundedAnalysisRunner
from patent_sar_extractor.web.analysis_runtime import (
    AnalysisSettings,
    Endpoint,
    ModelBundle,
    child_environment,
)
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.owner import WorkspaceOwner
from patent_sar_extractor.web.routes_analysis import _cancellable

VERSIONS = {
    "admet-ai": "2.0.1",
    "chemprop": "2.2.2",
    "torch": "2.8.0+cpu",
    "rdkit": "2026.3.1",
    "numpy": "2.2.6",
    "lightning": "2.6.1",
}


class ModelBoundary(BoundedAnalysisRunner):
    """A model-boundary mock, never a product runtime or proof of inference."""

    def __init__(self):
        super().__init__()
        self.calls = []
        self.raw_smiles = "OCC"
        self.bad = False

    def run(self, command, payload, **kwargs):
        self.calls.append(payload)
        if "image_path" in payload:
            self.crop = Path(payload["image_path"]).read_bytes()
            return {
                "raw_smiles": self.raw_smiles,
                "engine": {"name": "DECIMER", "version": "2.8.0"},
            }
        if payload == {"mode": "probe"}:
            return {"versions": VERSIONS.copy()}
        properties = [
            {
                "key": "molecular_weight",
                "label": "Molecular Weight",
                "value": 46.069,
                "unit": "Dalton",
                "kind": "descriptor",
            },
            {
                "key": "hERG",
                "label": "hERG Blocking",
                "value": 0.3,
                "unit": "probability [0,1]",
                "kind": "prediction",
            },
        ]
        if self.bad:
            properties[1]["value"] = float("nan")
        return {
            "engine": {
                "name": "ADMET-AI",
                "version": "2.0.1",
                "model_sha256": "a" * 64,
            },
            "predictions": [
                {"smiles": value, "properties": properties}
                for value in payload["smiles"]
            ],
            "versions": VERSIONS.copy(),
        }


class AnalysisAPITests(WebFixture, unittest.TestCase):
    def test_unverified_analysis_shutdown_still_closes_queue_and_retains_owner(self):
        app = self.app()
        with patch.object(
            app.state.analysis,
            "close",
            side_effect=WebError(503, "analysis_shutdown", "Shutdown is unverified."),
        ), patch.object(app.state.queue, "close", wraps=app.state.queue.close) as stopped:
            with self.assertRaises(ExceptionGroup):
                with TestClient(app, base_url=BASE_URL):
                    self.assertTrue(app.state.ready)
            stopped.assert_called_once()
        self.assertFalse(app.state.ready)
        self.assertFalse(app.state.queue.thread.is_alive())
        other = WorkspaceOwner(self.state)
        try:
            with self.assertRaises(WebError):
                other.acquire()
        finally:
            other.release()
            app.state.analysis.close()
            app.state.owner.release()

    def app(self, **kwargs):
        app = super().app(
            analysis_settings=getattr(self, "settings", AnalysisSettings()),
            analysis_runner=getattr(self, "boundary", None),
            **kwargs,
        )
        self.analysis = app.state.analysis
        self.addCleanup(self.analysis.close)
        return app

    def mock_runtime(self):
        self.boundary = ModelBoundary()
        self.settings = AnalysisSettings(
            admet_python=Path(sys.executable),
            decimer_python=Path(sys.executable),
            admet_model_dir=self.root / "models",
            pystow_home=self.root / "models",
        )
        bundle = ModelBundle(
            self.root / "models",
            "a" * 64,
            {
                "molecular_weight": Endpoint(
                    "molecular_weight",
                    "Molecular Weight",
                    "Dalton",
                    "descriptor",
                    False,
                ),
                "hERG": Endpoint(
                    "hERG", "hERG Blocking", "probability [0,1]", "prediction", True
                ),
            },
        )
        for target, value in (
            ("patent_sar_extractor.web.analysis.admet_bundle", bundle),
            ("patent_sar_extractor.web.analysis.interpreter_key", "boundary-fixture"),
            ("patent_sar_extractor.web.analysis.decimer_model_key", "model-fixture"),
        ):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_authentication_csrf_and_invalid_request_fields(self):
        with TestClient(self.app(), base_url=BASE_URL) as client:
            self.assertEqual(
                client.post(
                    "/api/v1/analysis/admet", json={"smiles": ["CCO"]}
                ).status_code,
                401,
            )
            self.assertEqual(
                client.get("/api/v1/projects/no/evidence-summary").status_code, 401
            )
            client.get("/api/v1/session")
            self.assertEqual(
                client.post(
                    "/api/v1/analysis/admet", json={"smiles": ["CCO"]}
                ).status_code,
                403,
            )
        with self.client() as client:
            for body in (
                {"smiles": []},
                {"smiles": ["CC"] * 51},
                {"smiles": [123]},
                {"smiles": ["C" * 2049]},
                {"smiles": ["CCO"], "path": "/etc/passwd"},
            ):
                response = client.post("/api/v1/analysis/admet", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("/etc/passwd", response.text)
            self.assertEqual(
                client.post(
                    "/api/v1/projects/no/compounds/no/recognize",
                    json={"path": "/etc/passwd"},
                ).status_code,
                422,
            )

    def test_real_validation_and_missing_environment_are_explicit(self):
        with self.client() as client:
            bad = client.post("/api/v1/analysis/admet", json={"smiles": ["not-SMILES"]})
            self.assertEqual(
                (bad.status_code, bad.json()["error"]["code"]), (422, "invalid_smiles")
            )
            valid = client.post("/api/v1/analysis/admet", json={"smiles": ["CCO"]})
            self.assertEqual(valid.status_code, 503)
            self.assertNotIn(str(self.root), valid.text)
            self.assertEqual(
                client.get("/api/v1/projects/no/evidence-summary").status_code, 404
            )

    def test_dto_order_duplicate_canonicalization_and_persistent_cache(self):
        self.mock_runtime()
        with self.client() as client:
            first = client.post(
                "/api/v1/analysis/admet", json={"smiles": ["OCC", "CCO"]}
            )
            self.assertEqual(first.status_code, 200, first.text)
            dto = first.json()
            self.assertEqual(
                set(dto),
                {"engine", "generated_at", "review_only", "predictions", "warnings"},
            )
            self.assertEqual([p["smiles"] for p in dto["predictions"]], ["CCO", "CCO"])
            self.assertTrue(dto["review_only"])
            self.assertEqual(
                dto["predictions"][0]["properties"][1]["unit"], "probability [0,1]"
            )
            self.assertTrue(self.analysis.capabilities()["admet"])
            count = len(self.boundary.calls)
            self.assertEqual(
                client.post(
                    "/api/v1/analysis/admet", json={"smiles": ["OCC", "CCO"]}
                ).json(),
                dto,
            )
            self.assertEqual(len(self.boundary.calls), count)
        with self.client() as client:
            before = sum(p.get("mode") == "predict" for p in self.boundary.calls)
            response = client.post(
                "/api/v1/analysis/admet", json={"smiles": ["OCC", "CCO"]}
            )
            self.assertEqual(response.json(), dto)
            self.assertEqual(
                sum(p.get("mode") == "predict" for p in self.boundary.calls), before
            )

    def test_bad_model_values_are_never_cached(self):
        self.mock_runtime()
        self.boundary.bad = True
        with self.client() as client:
            response = client.post("/api/v1/analysis/admet", json={"smiles": ["CCO"]})
            self.assertEqual(response.status_code, 502)
            with sqlite3.connect(self.analysis.cache.path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM analysis_cache"
                    ).fetchone()[0],
                    0,
                )

    def test_real_crop_cached_research_only_original_artifacts_unchanged(self):
        self.mock_runtime()
        run = artifact_run(self.root / "run", self.pdf, current=False)
        before = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in run.rglob("*")
            if p.is_file()
        }
        with self.client(import_runs=[run]) as client:
            project = client.get("/api/v1/projects").json()["items"][0]
            path = f"/api/v1/projects/{project['id']}/compounds/Compound%201/recognize"
            response = client.post(path, json={})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["smiles"], "CCO")
            self.assertTrue(response.json()["review_only"])
            self.assertTrue(self.boundary.crop.startswith(b"\x89PNG"))
            count = len(self.boundary.calls)
            self.assertEqual(client.post(path, json={}).json(), response.json())
            self.assertEqual(len(self.boundary.calls), count)
            self.assertFalse(list(self.analysis.cache.root.glob("worker-*")))
            self.assertEqual(
                client.get(f"/api/v1/projects/{project['id']}").json()["acceptance"][
                    "state"
                ],
                "historical",
            )
            summary = client.get(f"/api/v1/projects/{project['id']}/evidence-summary")
            self.assertEqual(summary.status_code, 200, summary.text)
            self.assertEqual(
                set(summary.json()),
                {
                    "project_id",
                    "generated_at",
                    "acceptance",
                    "counts",
                    "activities",
                    "targets",
                    "limitations",
                    "source_pages",
                },
            )
            self.assertEqual(summary.json()["source_pages"], [1])
            self.assertEqual(summary.json()["counts"]["compounds"], 2)
        self.assertEqual(
            before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
        )

    def test_qc_rejection_and_unsafe_crop(self):
        self.mock_runtime()
        self.boundary.raw_smiles = "*CC"
        run = artifact_run(self.root / "run", self.pdf, current=False)
        with self.client(import_runs=[run]) as client:
            project = client.get("/api/v1/projects").json()["items"][0]
            path = f"/api/v1/projects/{project['id']}/compounds/Compound%201/recognize"
            response = client.post(path, json={})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "rejected")
            self.assertIsNone(response.json()["smiles"])
            (run / "crop.png").unlink()
            (run / "crop.png").symlink_to(self.pdf)
            self.assertEqual(client.post(path, json={}).status_code, 404)


class DisconnectTests(WebFixture, unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_sets_event_and_reaps_actual_owned_child(self):
        runner = BoundedAnalysisRunner()
        self.addCleanup(runner.close)
        pid_file = self.root / "disconnect.pid"
        code = "import os,pathlib,time;pathlib.Path('disconnect.pid').write_text(str(os.getpid()));time.sleep(30)"

        class Request:
            async def is_disconnected(self):
                return pid_file.exists()

        def operation(*, cancel: threading.Event):
            return runner.run(
                [sys.executable, "-I", "-c", code],
                {},
                cwd=self.root,
                env=child_environment(
                    AnalysisSettings(), Path(sys.executable), self.root
                ),
                timeout=10,
                cancel=cancel,
            )

        with self.assertRaises(WebError) as error:
            await _cancellable(Request(), operation)
        self.assertEqual(error.exception.code, "analysis_cancelled")
        self.assertIsNone(read_child(int(pid_file.read_text())))

    async def test_asgi_task_cancellation_cleans_owned_child(self):
        runner = BoundedAnalysisRunner()
        self.addCleanup(runner.close)
        pid_file = self.root / "abort.pid"

        class Request:
            async def is_disconnected(self):
                return False

        def operation(*, cancel: threading.Event):
            return runner.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import pathlib,os,time;pathlib.Path('abort.pid').write_text(str(os.getpid()));time.sleep(30)",
                ],
                {},
                cwd=self.root,
                env=child_environment(
                    AnalysisSettings(), Path(sys.executable), self.root
                ),
                timeout=10,
                cancel=cancel,
            )

        task = asyncio.create_task(_cancellable(Request(), operation))
        for _ in range(200):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        self.assertTrue(pid_file.exists())
        owned = read_child(int(pid_file.read_text()))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(alive(owned))
