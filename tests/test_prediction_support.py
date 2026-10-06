"""Small controlled backend fixtures; they never certify scientific extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from test_prediction_fields import controlled_prediction
from test_web_support import WebFixture, artifact_run

from patent_sar_extractor.web.correction_storage import correction_source_fingerprint
from patent_sar_extractor.web.models import Stage, StageProgress
from patent_sar_extractor.web.prediction_fields import selected_metrics
from patent_sar_extractor.web.prediction_jobs import enqueue_prediction
from patent_sar_extractor.web.prediction_models import PredictionSummary
from patent_sar_extractor.web.prediction_storage import smiles_digest
from patent_sar_extractor.web.processes import SubprocessRunner
from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import now
from patent_sar_extractor.workers.analysis_protocol import ADMET_BUNDLE_SHA256


def controlled_summary(source, smiles, job_id, *, status="complete"):
    values = {
        "status": status,
        "source_fingerprint": source,
        "smiles_sha256": smiles_digest(smiles),
        "job_id": job_id,
    }
    if status == "complete":
        values.update(
            properties=selected_metrics(controlled_prediction()),
            engine={
                "name": "ADMET-AI",
                "version": "2.0.1",
                "model_sha256": ADMET_BUNDLE_SHA256,
            },
            generated_at=now(),
            warnings=["Controlled test observation, not a scientific model run."],
        )
    return PredictionSummary(**values)


def controlled_stage(*, completed=1, total=1, status="ok"):
    return Stage(
        name="admet",
        status=status,
        count=completed,
        progress=StageProgress(
            completed=completed,
            total=total,
            cache_hits=0,
            failures=0,
            device=None,
            peak_rss_mb=None,
        ),
    )


class PredictionFixture(WebFixture):
    def setUp(self):
        super().setUp()
        self.service = WorkspaceService(self.state)
        self.run = artifact_run(self.root / "controlled-run", self.pdf, rows=1)
        self.project = self.service.import_run(self.run, pdf_path=self.pdf)

    def draft(self, *, running=True):
        with self.service.store.connect(write=True) as connection:
            job_id = enqueue_prediction(
                self.service.store,
                connection,
                self.project.id,
                compound_ids=("Compound 1",),
            )
            if running:
                connection.execute(
                    "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                    (now(), job_id),
                )
        row = self.service.store.job(job_id)
        project = self.service.store.project(self.project.id)
        raw = self.service.store.compound(self.project.id, "Compound 1")
        source = correction_source_fingerprint(project, raw)
        return row, Path(json.loads(row["spec"])["output_dir"]), source


class ControlledPhaseRunner(SubprocessRunner):
    """Real owned processes running explicit controlled phase-contract fixtures."""

    def __init__(self, *, mode="complete", accepted=True):
        super().__init__()
        self.mode = mode
        self.accepted = accepted
        self.started_phases = []

    def command(self, spec):
        return [
            sys.executable,
            "-c",
            # Test helpers are not runtime modules and PYTHONPATH intentionally
            # contains only src. Bind this controlled child to its actual test
            # source, rather than relying on the parent's discovery sys.path.
            (
                f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); "
                "from test_prediction_support import controlled_phase; controlled_phase(*sys.argv[1:])"
            ),
            spec.job_id,
            spec.project_id,
            spec.pdf_path,
            spec.output_dir,
            "admet" if spec.admet_only else "extract",
            self.mode,
            "1" if self.accepted else "0",
        ]

    def start(self, spec):
        if spec.admet_only and self.started_phases and self._children:
            raise AssertionError(
                "Core carrier must be fully stopped before ADMET starts"
            )
        self.started_phases.append("admet" if spec.admet_only else "extract")
        return super().start(spec)


def controlled_phase(job_id, project_id, pdf_path, output_dir, phase, mode, accepted):
    import time

    from patent_sar_extractor.web.admet_history import (
        read_admet_stage,
        write_admet_stage,
    )
    from patent_sar_extractor.web.prediction_worker import wait_for_owner

    output = Path(output_dir)
    if phase == "extract":
        generated = artifact_run(
            output / "controlled-fixture",
            Path(pdf_path),
            rows=1,
            accepted=accepted == "1",
        )
        if mode == "qa_rejected":
            from patent_sar_extractor import contracts

            summary = generated / "pipeline_summary.json"
            packet = json.loads(summary.read_text())
            packet.update(
                status="failed_accuracy_gate",
                main_chain=list(contracts.CORE_STAGE_ORDER),
                steps={name: {"status": "ok"} for name in contracts.CORE_STAGE_ORDER},
            )
            packet["steps"]["qa"] = {
                "status": "failed",
                "strict_acceptance_ok": False,
                "hard_errors": ["Controlled scientific rejection"],
            }
            summary.write_text(json.dumps(packet))
        for path in generated.rglob("*.json"):
            relative = path.relative_to(generated)
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_bytes(path.read_bytes())
        if mode == "qa_rejected":
            raise SystemExit(1)
        return
    service = WorkspaceService(output.parents[2])
    row = wait_for_owner(service, job_id)
    _, core_completed = read_admet_stage(row, output)
    project = service.store.project(project_id)
    raw = service.store.compound(project_id, "Compound 1")
    source = correction_source_fingerprint(project, raw)
    smiles = service.effective_compound(project_id, "Compound 1").smiles
    service.predictions.put(
        project_id,
        "Compound 1",
        controlled_summary(source, smiles, job_id, status="running"),
    )
    write_admet_stage(
        output,
        row,
        controlled_stage(completed=0, status="running"),
        core_completed=core_completed,
    )
    if mode == "failure":
        raise SystemExit(7)
    if mode == "sleep":
        time.sleep(30)
        return
    service.predictions.put(
        project_id, "Compound 1", controlled_summary(source, smiles, job_id)
    )
    from patent_sar_extractor.web.descriptor_fields import (
        compute_descriptors,
        descriptor_engine,
    )
    from patent_sar_extractor.web.descriptor_models import DescriptorSummary

    service.descriptors.put(
        project_id,
        "Compound 1",
        DescriptorSummary(
            status="complete",
            properties=compute_descriptors(smiles),
            engine=descriptor_engine(),
            source_fingerprint=source,
            smiles_sha256=smiles_digest(smiles),
            job_id=job_id,
            generated_at=now(),
        ),
    )
    write_admet_stage(output, row, controlled_stage(), core_completed=core_completed)
