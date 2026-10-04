"""Manual stereo eligibility gates with real SQLite and no scientific model load."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from manual_stereo_fixtures import moved_block, structure_block, unknown_block
from test_prediction_support import PredictionFixture, controlled_summary

from patent_sar_extractor.web.admet_history import read_admet_stage
from patent_sar_extractor.web.analysis import AnalysisService
from patent_sar_extractor.web.correction_fields import prepared_fields
from patent_sar_extractor.web.correction_models import CorrectionRequest, EditableFields
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.prediction_identity import (
    compound_prediction_eligible,
    prediction_eligible,
    readable_digests,
    smiles_digest,
)
from patent_sar_extractor.web.prediction_worker import run_predictions
from patent_sar_extractor.web.processes import SubprocessRunner
from patent_sar_extractor.web.storage import now


class ManualStereoEligibilityTests(unittest.TestCase):
    def test_unknown_and_mixed_representations_have_no_unique_prediction_key(self):
        for kind in ("tetra", "double", "mixed"):
            for version in (False, True):
                smiles, block = unknown_block(kind, v3000=version)
                with self.subTest(kind=kind, v3000=version):
                    self.assertFalse(prediction_eligible(smiles, block))
                    for key in (smiles_digest, readable_digests):
                        with self.assertRaises(WebError) as error:
                            key(smiles, block)
                        self.assertEqual(
                            error.exception.code, "manual_stereo_unresolved"
                        )

    def test_unmarked_manual_potential_stereo_keeps_legacy_identity(
        self,
    ):
        for smiles in ("FC(Cl)Br", "F[C@H](Cl)C(Br)I"):
            self.assertTrue(prediction_eligible(smiles, structure_block(smiles)))
            self.assertEqual(
                smiles_digest(smiles, structure_block(smiles)), smiles_digest(smiles)
            )
        for smiles in (
            "CCO",
            "F[C@H](Cl)Br",
            "F/C=C/F",
            "F/C=C\\F",
            "[13CH3]CO.[Na+].[Cl-]",
        ):
            block = structure_block(smiles, v3000=True)
            self.assertTrue(prediction_eligible(smiles, block))
            self.assertEqual(smiles_digest(smiles, block), smiles_digest(smiles))

    def test_unknown_marker_change_clears_inherited_properties_but_coordinates_do_not(
        self,
    ):
        smiles, block = unknown_block("tetra", v3000=True)
        before = EditableFields(
            display_id="A",
            smiles=smiles,
            activities=[],
            property_overrides={"logP": 0},
            property_basis_smiles=smiles,
        )
        changed = prepared_fields(
            EditableFields(
                display_id="A", smiles=smiles, activities=[], structure_molfile=block
            ),
            before,
        )
        self.assertEqual(changed.property_overrides, {})
        unknown = changed.model_copy(
            update={"property_overrides": {"logP": 0}, "property_basis_smiles": smiles}
        )
        moved = prepared_fields(
            EditableFields(
                display_id="A",
                smiles=smiles,
                activities=[],
                structure_molfile=moved_block(block, v3000=True),
            ),
            unknown,
        )
        self.assertEqual(moved.property_overrides, {"logP": 0})
        self.assertEqual(moved.property_basis_smiles, smiles)
        legacy = prepared_fields(
            EditableFields(display_id="Renamed", smiles=smiles, activities=[]), unknown
        )
        self.assertEqual(legacy.structure_molfile, block)
        self.assertEqual(legacy.property_overrides, {"logP": 0})


class ManualStereoPredictionTests(PredictionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.service.corrections.on_save = None

    def save(self, **changes):
        document = self.service.get_correction(self.project.id, "Compound 1")
        return self.service.put_correction(
            self.project.id,
            "Compound 1",
            CorrectionRequest(
                expected_revision=document.revision,
                expected_source_fingerprint=document.source_fingerprint,
                fields=EditableFields.model_validate(
                    {**document.values.model_dump(), **changes}
                ),
            ),
        )

    def records(self):
        with self.service.store.connect() as connection:
            return [
                dict(row)
                for row in connection.execute("SELECT * FROM admet_predictions")
            ]

    def test_same_smiles_unknown_edit_does_not_reuse_or_rewrite_legacy_prediction(self):
        smiles, block = unknown_block("tetra", v3000=True)
        self.save(smiles=smiles)
        job, _, source = self.draft()
        summary = controlled_summary(source, smiles, job["id"])
        self.service.predictions.put(self.project.id, "Compound 1", summary)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='complete',finished_at=? WHERE id=?",
                (now(), job["id"]),
            )
        before = self.records()
        jobs = self.service.job_ids(self.project.id)
        callback = Mock()
        self.service.corrections.on_save = callback
        self.save(structure_molfile=block)
        callback.assert_not_called()
        result = self.service.results(self.project.id).items[0]
        self.assertEqual(result.admet.status, "unavailable")
        self.assertEqual(result.admet.error.code, "manual_stereo_unresolved")
        self.assertEqual(result.admet.properties, [])
        self.assertEqual(self.records(), before)
        self.assertEqual(self.service.job_ids(self.project.id), jobs)
        read = self.service.predictions.summaries(
            self.project.id,
            [("Compound 1", source, smiles)],
            molfiles={"Compound 1": block},
        )["Compound 1"]
        self.assertEqual(read.status, "unavailable")

    def test_plain_unspecified_coordinate_only_addition_and_move_reuse_cache(self):
        smiles = "FC(Cl)Br"
        self.save(
            smiles=smiles, property_overrides={"logP": 0}, property_basis_smiles=smiles
        )
        job, _, source = self.draft()
        summary = controlled_summary(source, smiles, job["id"])
        self.service.predictions.put(self.project.id, "Compound 1", summary)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='complete',finished_at=? WHERE id=?",
                (now(), job["id"]),
            )
        before = self.records()
        callback = Mock()
        self.service.corrections.on_save = callback
        block = structure_block(smiles, v3000=True)
        for representation in (block, moved_block(block, v3000=True)):
            self.save(structure_molfile=representation)
            result = self.service.results(self.project.id).items[0]
            self.assertEqual(result.admet.model_dump(), summary.model_dump())
            self.assertEqual(result.property_overrides, {"logP": 0})
        callback.assert_not_called()
        self.assertEqual(self.records(), before)

    def test_source_conflict_requires_new_validated_graph_not_coordinates_or_alias(
        self,
    ):
        for flag in ("stereo_source_conflict", "stereo_source_ambiguous"):
            with self.subTest(flag=flag):
                raw = self.service.store.compound(self.project.id, "Compound 1")
                payload = json.loads(raw["payload"])
                payload["smiles"] = "FC(Cl)Br"
                payload["recognition"] = {"status": "invalid", "quality_flag": flag}
                payload["flags"] = [flag]
                with self.service.store.connect(write=True) as connection:
                    connection.execute(
                        "UPDATE compounds SET payload=? WHERE project_id=? AND id=?",
                        (json.dumps(payload), self.project.id, "Compound 1"),
                    )
                callback = Mock()
                self.service.corrections.on_save = callback
                self.save(
                    smiles="FC(Cl)Br",
                    structure_molfile=structure_block("FC(Cl)Br"),
                    display_id="Coordinate-only review",
                )
                callback.assert_not_called()
                result = self.service.results(self.project.id).items[0]
                self.assertFalse(compound_prediction_eligible(result))
                self.assertEqual(
                    result.admet.error.code, "admet_stereo_source_unresolved"
                )
                job, root, source = self.draft()
                analysis = Mock(spec=AnalysisService)
                run_predictions(self.service, analysis, job)
                analysis.admet.assert_not_called()
                stage, _ = read_admet_stage(job, root)
                self.assertEqual((stage.status, stage.skipped), ("empty", 1))
                JobQueue(self.service, SubprocessRunner(), 10)._confirm_predictions(
                    job["id"], decode_spec(job["spec"])
                )
                with self.assertRaises(WebError) as error:
                    self.service.predictions.put(
                        self.project.id,
                        "Compound 1",
                        controlled_summary(source, "FC(Cl)Br", job["id"]),
                    )
                self.assertEqual(error.exception.code, "admet_stereo_source_unresolved")
                with self.service.store.connect(write=True) as connection:
                    connection.execute(
                        "UPDATE jobs SET status='complete',finished_at=? WHERE id=?",
                        (now(), job["id"]),
                    )
                smiles = "F[C@H](Cl)Br"
                self.save(smiles=smiles, structure_molfile=structure_block(smiles))
                callback.assert_called_once()
                self.assertTrue(
                    compound_prediction_eligible(
                        self.service.effective_compound(self.project.id, "Compound 1")
                    )
                )

    def test_explicit_unknown_only_job_seals_empty_and_completion_uses_same_eligibility(
        self,
    ):
        for kind in ("tetra", "double", "mixed"):
            with self.subTest(kind=kind):
                smiles, block = unknown_block(kind, v3000=True)
                self.save(smiles=smiles, structure_molfile=block)
                job, root, _ = self.draft()
                analysis = Mock(spec=AnalysisService)
                analysis.admet.side_effect = AssertionError(
                    "Unknown stereo must not load a model"
                )
                run_predictions(self.service, analysis, job)
                analysis.admet.assert_not_called()
                stage, _ = read_admet_stage(job, root)
                self.assertEqual(stage.status, "empty")
                self.assertEqual(stage.skipped, 1)
                self.assertEqual(
                    (stage.progress.completed, stage.progress.total), (0, 0)
                )
                JobQueue(self.service, SubprocessRunner(), 10)._confirm_predictions(
                    job["id"], decode_spec(job["spec"])
                )
                self.assertEqual(self.records(), [])
                with self.service.store.connect(write=True) as connection:
                    connection.execute(
                        "UPDATE jobs SET status='complete',finished_at=? WHERE id=?",
                        (now(), job["id"]),
                    )

    def test_publication_cannot_bind_a_unique_smiles_key_to_unknown_manual_representation(
        self,
    ):
        smiles, block = unknown_block("double", v3000=True)
        self.save(smiles=smiles, structure_molfile=block)
        job, _, source = self.draft()
        summary = controlled_summary(source, smiles, job["id"])
        with self.assertRaises(WebError) as error:
            self.service.predictions.put(self.project.id, "Compound 1", summary)
        self.assertEqual(error.exception.code, "manual_stereo_unresolved")
        self.assertEqual(self.records(), [])
