"""Review-only analysis use cases over read-only workspace rows and safe crops."""

from __future__ import annotations

import hashlib
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from patent_sar_extractor.workers.analysis_protocol import ADMET_VERSION

from .analysis_cache import AnalysisCache, cache_key
from .analysis_chemistry import (
    chemistry_identity,
    recognized_smiles,
    validate_batch,
)
from .analysis_models import (
    ADMETResponse,
    AnalysisEngine,
    EvidenceSummary,
    RecognitionResponse,
)
from .analysis_process import BoundedAnalysisRunner
from .analysis_results import admet_response, compound, recognition_response
from .analysis_runtime import (
    AnalysisSettings,
    admet_bundle,
    child_environment,
    decimer_model_key,
    executable,
    interpreter_key,
)
from .analysis_summary import summarize
from .errors import WebError
from .pdf import crop_image, render_page
from .service import WorkspaceService
from .storage import now

_WORKERS = Path(__file__).resolve().parents[1] / "workers"
_WRAPPER = Path(__file__).resolve().parents[1] / "core/ocsr/wrapper_decimer.py"
_RESEARCH_WARNING = "Local model predictions are research estimates, not experimental results or formal pipeline acceptance. Model applicability has not been independently validated."


class AnalysisService:
    def __init__(
        self,
        state_root: str | Path,
        workspace: WorkspaceService,
        *,
        settings: AnalysisSettings | None = None,
        runner: BoundedAnalysisRunner | None = None,
    ) -> None:
        if Path(state_root).resolve() != workspace.store.root:
            raise WebError(
                400,
                "analysis_workspace",
                "Analysis state must belong to the provided workspace.",
            )
        self.workspace = workspace
        self.settings = settings or AnalysisSettings.from_environment()
        self.cache = AnalysisCache(workspace.store.root)
        self.runner = runner or BoundedAnalysisRunner()
        self._busy = threading.Lock()
        self._closed = threading.Event()
        self._runtime: tuple[str, dict[str, str]] | None = None

    def close(self) -> None:
        """Idempotent cancellation and verified cleanup; never stops extraction/other apps."""
        self._closed.set()
        self.runner.close()

    def configure(self, publish: Callable[[], AnalysisSettings]) -> None:
        """Publish verified paths only while no inference holds a settings snapshot."""
        with self._operation(None):
            self.settings = publish()
            self._runtime = None

    def capabilities(self) -> dict[str, bool]:
        if self._closed.is_set():
            return {"admet": False, "summary": False}
        try:
            python = executable(self.settings.admet_python)
            admet_bundle(self.settings.admet_model_dir)
            identity = interpreter_key(python)
            if self._runtime is None or self._runtime[0] != identity:
                with self._operation(None):
                    self._probe(python, identity, None)
            available = True
        except WebError:
            available = False
        return {"admet": available, "summary": True}

    @contextmanager
    def _operation(self, cancel: threading.Event | None) -> Iterator[None]:
        if not self._busy.acquire(blocking=False):
            raise WebError(
                503,
                "analysis_busy",
                "Another molecular analysis is running; retry when it finishes.",
            )
        try:
            self._check_cancel(cancel)
            yield
        finally:
            self._busy.release()

    def _check_cancel(self, cancel: threading.Event | None) -> None:
        if self._closed.is_set() or (cancel is not None and cancel.is_set()):
            raise WebError(
                503,
                "analysis_cancelled",
                "Analysis was cancelled; no partial result is available.",
            )

    def _worker(
        self,
        python: Path,
        name: str,
        payload: object,
        timeout: float,
        cancel: threading.Event | None,
        *,
        crop: bytes | None = None,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(
            prefix="worker-", dir=self.cache.root
        ) as directory:
            temporary = Path(directory)
            if crop is not None:
                path = temporary / "crop.png"
                path.write_bytes(crop)
                payload = {"image_path": str(path)}
            return self.runner.run(
                [str(python), "-I", str(_WORKERS / name)],
                payload,
                cwd=temporary,
                env=child_environment(self.settings, python, temporary),
                timeout=timeout,
                cancel=cancel,
            )

    def _probe(
        self,
        python: Path,
        identity: str,
        cancel: threading.Event | None,
        deadline: float | None = None,
    ) -> dict[str, str]:
        if self._runtime is not None and self._runtime[0] == identity:
            return self._runtime[1]
        timeout = min(30, self.settings.admet_timeout_seconds)
        if deadline is not None:
            timeout = min(timeout, _remaining(deadline))
        result = self._worker(
            python, "admet_worker.py", {"mode": "probe"}, timeout, cancel
        )
        versions = result.get("versions")
        if (
            set(result) != {"versions"}
            or not isinstance(versions, dict)
            or set(versions)
            != {"admet-ai", "chemprop", "torch", "rdkit", "numpy", "lightning"}
            or any(
                not isinstance(v, str) or not 1 <= len(v) <= 40
                for v in versions.values()
            )
            or versions.get("admet-ai") != ADMET_VERSION
        ):
            raise WebError(
                503,
                "analysis_environment_unavailable",
                "Analysis runtime did not confirm its required versions.",
            )
        self._runtime = (identity, versions)
        return versions

    def admet(
        self, smiles: list[str], *, cancel: threading.Event | None = None
    ) -> ADMETResponse:
        deadline = time.monotonic() + self.settings.admet_timeout_seconds
        with self._operation(cancel):
            values = validate_batch(smiles)
            python = executable(self.settings.admet_python)
            bundle = admet_bundle(self.settings.admet_model_dir)
            identity = interpreter_key(python)
            versions = self._probe(python, identity, cancel, deadline)
            key = cache_key(
                [
                    1,
                    values,
                    bundle.model_sha256,
                    identity,
                    versions,
                    chemistry_identity(),
                    self._adapter_key("admet_worker.py"),
                ]
            )
            cached = self.cache.get("admet", key)
            if cached is not None:
                self._check_cancel(cancel)
                _remaining(deadline)
                return admet_response(cached, values, bundle)
            result = self._worker(
                python,
                "admet_worker.py",
                {
                    "mode": "predict",
                    "smiles": values,
                    "model_dir": str(bundle.root),
                    "model_sha256": bundle.model_sha256,
                },
                _remaining(deadline),
                cancel,
            )
            if (
                set(result) != {"engine", "predictions", "versions"}
                or result["versions"] != versions
            ):
                raise WebError(
                    502,
                    "analysis_protocol",
                    "Model runtime identity changed during inference.",
                )
            warnings = [
                _RESEARCH_WARNING,
                "DrugBank comparisons are disabled; classification outputs are probabilities, not confidence scores.",
            ]
            if any("." in value for value in values):
                warnings.append(
                    "Disconnected molecular fragments were retained, not silently stripped; model applicability requires review."
                )
            payload = {
                "engine": result["engine"],
                "predictions": result["predictions"],
                "generated_at": now(),
                "review_only": True,
                "warnings": warnings,
            }
            response = admet_response(payload, values, bundle)
            self._check_cancel(cancel)
            _remaining(deadline)
            self.cache.put("admet", key, response.model_dump())
            return response

    @staticmethod
    def _adapter_key(worker: str) -> str:
        paths = (
            _WORKERS / worker,
            _WORKERS / "analysis_protocol.py",
            Path(__file__),
            Path(__file__).with_name("analysis_runtime.py"),
            Path(__file__).with_name("analysis_models.py"),
            Path(__file__).with_name("analysis_chemistry.py"),
            Path(__file__).with_name("analysis_results.py"),
        )
        return cache_key([hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])

    def recognize(
        self,
        project_id: str,
        compound_id: str,
        *,
        cancel: threading.Event | None = None,
    ) -> RecognitionResponse:
        deadline = time.monotonic() + self.settings.decimer_timeout_seconds
        with self._operation(cancel):
            project = self.workspace.store.project(project_id)
            row = self.workspace.store.compound(project_id, compound_id)
            dto = compound(row["payload"])
            if row["image_path"] and project["run_root"]:
                data = crop_image(Path(project["run_root"]), row["image_path"])
            elif dto.source.page and dto.source.bbox and project["pdf_rel"]:
                box = dto.source.bbox
                if len(box) != 4 or box[0] >= box[2] or box[1] >= box[3]:
                    raise WebError(
                        422,
                        "invalid_geometry",
                        "Structure crop has invalid source geometry.",
                    )
                data = render_page(
                    self.workspace.store.root,
                    project,
                    dto.source.page,
                    1.5,
                    bbox=box,
                    geometry_space=row["geometry_space"],
                )
            else:
                raise WebError(
                    404, "crop_unavailable", "No safe real structure crop is available."
                )
            if len(data) > 16 * 1024 * 1024:
                raise WebError(
                    413, "image_limit", "Decoded structure crop exceeds its byte limit."
                )
            python = executable(self.settings.decimer_python)
            identity = interpreter_key(python)
            model = decimer_model_key(self.settings.pystow_home)
            self._check_cancel(cancel)
            _remaining(deadline)
            key = cache_key(
                [
                    1,
                    project_id,
                    compound_id,
                    hashlib.sha256(data).hexdigest(),
                    identity,
                    model,
                    chemistry_identity(),
                    self._adapter_key("analysis_decimer_worker.py"),
                    hashlib.sha256(_WRAPPER.read_bytes()).hexdigest(),
                ]
            )
            cached = self.cache.get("recognize", key)
            if cached is not None:
                self._check_cancel(cancel)
                return recognition_response(cached, compound_id)
            result = self._worker(
                python,
                "analysis_decimer_worker.py",
                {},
                _remaining(deadline),
                cancel,
                crop=data,
            )
            if set(result) != {"raw_smiles", "engine"} or (
                result["raw_smiles"] is not None
                and not isinstance(result["raw_smiles"], str)
            ):
                raise WebError(
                    502,
                    "analysis_protocol",
                    "DECIMER returned invalid recognition data.",
                )
            try:
                engine = AnalysisEngine.model_validate(result["engine"])
            except ValidationError as exc:
                raise WebError(
                    502,
                    "analysis_protocol",
                    "DECIMER did not confirm its engine version.",
                ) from exc
            smiles = recognized_smiles(result["raw_smiles"])
            response = recognition_response(
                {
                    "compound_id": compound_id,
                    "status": "recognized" if smiles else "rejected",
                    "smiles": smiles,
                    "engine": engine.model_dump(),
                    "review_only": True,
                    "warnings": [
                        "Crop recognition is research-only and does not update pipeline SMILES, confidence or formal acceptance."
                    ]
                    + (
                        []
                        if smiles
                        else [
                            "DECIMER output was empty or failed bounded RDKit/chemistry QC; inspect the original crop."
                        ]
                    ),
                },
                compound_id,
            )
            self._check_cancel(cancel)
            _remaining(deadline)
            self.cache.put("recognize", key, response.model_dump())
            return response

    def evidence_summary(self, project_id: str) -> EvidenceSummary:
        self._check_cancel(None)
        project = self.workspace.project(project_id)
        rows = self.workspace.result_rows(project_id)
        return summarize(project, [compound(row["payload"]) for row in rows])


def _remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds < 0.05:
        raise WebError(
            504,
            "analysis_timeout",
            "Local analysis exceeded its total request time limit.",
        )
    return min(180, seconds)
