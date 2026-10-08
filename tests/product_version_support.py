"""Shared controlled release fixtures; no test cases or compatibility authority."""

from __future__ import annotations

import copy
import json
from unittest.mock import patch

from test_prediction_support import (
    PredictionFixture,
    controlled_stage,
    controlled_summary,
)

from patent_sar_extractor import contracts as core
from patent_sar_extractor.web.admet_history import seal_admet_stage, write_admet_stage
from patent_sar_extractor.web.descriptor_fields import (
    compute_descriptors,
    descriptor_engine,
)
from patent_sar_extractor.web.descriptor_models import DescriptorSummary
from patent_sar_extractor.web.processes import runtime_identity
from patent_sar_extractor.web.recognition_storage import RecognitionStore, crop_digest
from patent_sar_extractor.web.storage import now

OLD_RELEASE = "0.1.0"


def incompatible_identities():
    """Negative fixture data, not a second compatibility predicate."""
    original = runtime_identity()
    for field, value in (
        ("product", {"name": "Foreign", "version": OLD_RELEASE}),
        ("product", {"name": core.PRODUCT_NAME, "version": "0.1.100"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "00.1.0"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "0.01.0"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "0.10.0"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "0.1.01"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "v0.1.0"}),
        ("product", {**core.product_ref(), "unreviewed": True}),
        ("product", {"name": core.PRODUCT_NAME, "version": True}),
        ("pipeline_contract", {"name": "foreign", "version": "3.0.0"}),
        ("pipeline_contract", {**core.pipeline_contract_ref(), "version": "2.0.0"}),
        ("ruleset", {**core.ruleset_ref(), "version": "2.0.0"}),
    ):
        yield field, {**copy.deepcopy(original), field: value}
    yield "missing", {"product": core.product_ref()}
    yield "extra", {**original, "unreviewed": True}
    yield "null", None


class ProductVersionObservationFixture(PredictionFixture):
    """Reusable non-TestCase setup for source/job-bound observation regressions."""

    def setUp(self):
        with patch.object(core, "__version__", OLD_RELEASE):
            super().setUp()
        self.recognitions = RecognitionStore(self.service.store)

    def seed_old(self, *, terminal=True):
        with patch.object(core, "__version__", OLD_RELEASE):
            row, root, source = self.draft()
            prediction = controlled_summary(source, "CCO", row["id"])
            descriptors = DescriptorSummary(
                status="complete",
                properties=compute_descriptors("CCO"),
                engine=descriptor_engine(),
                source_fingerprint=source,
                smiles_sha256=prediction.smiles_sha256,
                job_id=row["id"],
                generated_at=now(),
            )
            record = json.loads((self.run / "smiles/smiles_results.json").read_bytes())[
                "records"
            ][0]
            record["model_fingerprint"] = "a" * 64
            raw = self.service.store.compound(self.project.id, "Compound 1")
            crop = crop_digest(self.run, raw["image_path"])
            self.recognitions.put(
                self.project.id,
                "Compound 1",
                source=source,
                crop=crop,
                record=record,
                job_id=row["id"],
            )
            self.service.predictions.put(self.project.id, "Compound 1", prediction)
            self.service.descriptors.put(self.project.id, "Compound 1", descriptors)
            write_admet_stage(root, row, controlled_stage(), core_completed=False)
            if terminal:
                stamp = now()
                seal_admet_stage(self.state, root, row, "complete", stamp)
                with self.service.store.connect(write=True) as connection:
                    connection.execute(
                        "UPDATE jobs SET status='complete',finished_at=? WHERE id=?",
                        (stamp, row["id"]),
                    )
        return (
            self.service.store.job(row["id"]),
            root,
            source,
            prediction,
            descriptors,
            record,
            crop,
        )

    def saved_rows(self):
        with self.service.store.connect() as connection:
            return {
                table: [
                    tuple(row) for row in connection.execute(f"SELECT * FROM {table}")
                ]
                for table in (
                    "projects",
                    "compounds",
                    "jobs",
                    "admet_predictions",
                    "molecular_descriptors",
                    "compound_recognitions",
                    "corrections",
                    "correction_audit",
                )
            }
