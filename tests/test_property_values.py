"""One effective-value accessor preserves manual/model provenance in consumers."""

from __future__ import annotations

import csv
import io
import json
import unittest

from patent_sar_extractor.web.exports import export_csv, export_json
from patent_sar_extractor.web.models import (
    Acceptance,
    Compound,
    Confidence,
    CorrectionMetadata,
    PDFInfo,
    Project,
    Source,
    Summary,
)
from patent_sar_extractor.web.prediction_models import (
    METRIC_KEYS,
    METRIC_SPECS,
    PredictionEngine,
    PredictionMetric,
    PredictionSummary,
)
from patent_sar_extractor.web.property_values import effective_property_values
from patent_sar_extractor.web.table_query_values import column_values
from patent_sar_extractor.workers.analysis_protocol import (
    ADMET_BUNDLE_SHA256,
    ADMET_VERSION,
)


def row(**changes: object) -> Compound:
    return Compound.model_validate(
        {
            "id": "Compound 1",
            "display_id": "Compound 1",
            "smiles": "CCO",
            "activities": [],
            "source": Source(),
            "confidence": Confidence(reason="Controlled fixture"),
            **changes,
        }
    )


def prediction() -> PredictionSummary:
    return PredictionSummary(
        status="complete",
        properties=[
            PredictionMetric(
                key=key,
                label=METRIC_SPECS[key][0],
                unit=METRIC_SPECS[key][1],
                kind=METRIC_SPECS[key][2],
                value=1.0,
            )
            for key in METRIC_KEYS
        ],
        source_fingerprint="a" * 64,
        smiles_sha256="b" * 64,
        engine=PredictionEngine(
            name="ADMET-AI", version=ADMET_VERSION, model_sha256=ADMET_BUNDLE_SHA256
        ),
        generated_at="2026-10-04T01:00:00+00:00",
        job_id="c" * 32,
    )


def project() -> Project:
    return Project(
        id="project",
        title="Controlled export",
        patent_id="WO-test",
        created_at="now",
        updated_at="now",
        pdf=PDFInfo(available=True, page_count=1, sha256="a" * 64),
        is_historical=False,
        summary=Summary(),
        acceptance=Acceptance(state="accepted"),
        last_job=None,
    )


class EffectivePropertyTests(unittest.TestCase):
    def test_manual_zero_null_and_negative_values_precede_complete_model_without_mutating_it(
        self,
    ):
        source = prediction()
        saved = source.model_dump_json()
        compound = row(
            admet=source,
            property_overrides={"logP": -2.5, "tpsa": None, "molecular_weight": 0},
            property_basis_smiles="OCC",
        )
        values = effective_property_values(compound)
        self.assertEqual(values["logP"], -2.5)
        self.assertIsNone(values["tpsa"])
        self.assertEqual(values["molecular_weight"], 0)
        self.assertEqual(values["hydrogen_bond_acceptors"], 1)
        self.assertEqual(source.model_dump_json(), saved)
        self.assertEqual(compound.admet.model_dump_json(), saved)

    def test_explicit_null_is_not_filled_even_when_prediction_is_missing_or_stale(self):
        for observation in (None, PredictionSummary(status="stale"), prediction()):
            compound = row(
                admet=observation, property_overrides={"logP": None, "tpsa": 0}
            )
            with self.subTest(status=observation.status if observation else None):
                self.assertEqual(column_values(compound, "property:logP"), [])
                self.assertEqual(column_values(compound, "property:tpsa"), [0])
                self.assertIsNone(effective_property_values(compound)["logP"])

    def test_stale_source_bound_correction_cannot_supply_manual_properties(self):
        compound = row(
            admet=prediction(),
            property_overrides={"logP": 5},
            correction=CorrectionMetadata(
                revision=1, stale=True, has_changes=True, updated_at="now"
            ),
        )
        self.assertEqual(effective_property_values(compound)["logP"], 1)

    def test_csv_values_are_effective_but_model_producer_and_original_values_remain_json_evidence(
        self,
    ):
        original = prediction()
        compound = row(
            admet=original,
            property_overrides={"logP": -4.93, "tpsa": None},
            property_basis_smiles="OCC",
        )
        exported = next(
            csv.DictReader(
                io.StringIO(
                    b"".join(export_csv(project(), [compound])).decode("utf-8-sig")
                )
            )
        )
        self.assertEqual(exported["LogP"], "-4.93")
        self.assertEqual(exported["TPSA_A2"], "")
        self.assertEqual(exported["MW_Dalton"], "1.0")
        self.assertEqual(exported["admet_engine"], "ADMET-AI")
        self.assertEqual(exported["admet_source_fingerprint"], "a" * 64)
        self.assertEqual(exported["admet_smiles_sha256"], "b" * 64)
        self.assertEqual(exported["manual_property_keys"], "logP; tpsa")
        self.assertEqual(exported["property_basis_smiles"], "OCC")
        self.assertEqual(exported["review_only"], "True")
        packet = json.loads(b"".join(export_json(project(), [compound])))
        self.assertEqual(packet["items"][0]["admet"], original.model_dump(mode="json"))
        self.assertEqual(
            packet["items"][0]["property_overrides"], {"logP": -4.93, "tpsa": None}
        )
        self.assertNotIn("property_basis_smiles", packet["items"][0])

    def test_empty_addons_are_absent_from_raw_serialization(self):
        compound = row()
        for key in ("structure_molfile", "property_overrides", "property_basis_smiles"):
            self.assertNotIn(key, compound.model_dump())
        with_defaults = row(structure_molfile=None, property_overrides={})
        self.assertEqual(compound.model_dump_json(), with_defaults.model_dump_json())
