"""Focused pure Lead regressions with real RDKit and controlled model packets."""

from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from patent_sar_extractor.web.activity_columns import ActivityColumnCatalog
from patent_sar_extractor.web.descriptor_fields import (
    compute_descriptors,
    descriptor_engine,
)
from patent_sar_extractor.web.descriptor_models import DescriptorSummary
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.lead_activity import activity_evidence
from patent_sar_extractor.web.lead_chemistry import chemical_features, similarity
from patent_sar_extractor.web.lead_endpoints import LEAD_ENDPOINTS
from patent_sar_extractor.web.lead_models import LeadAssessment
from patent_sar_extractor.web.lead_scoring import prioritize_leads
from patent_sar_extractor.web.models import (
    Activity,
    Compound,
    Confidence,
    CorrectionMetadata,
    Recognition,
    Review,
    Source,
)
from patent_sar_extractor.web.prediction_identity import smiles_digest
from patent_sar_extractor.web.prediction_models import (
    PredictionMetric,
    PredictionSummary,
)
from patent_sar_extractor.workers.analysis_protocol import ADMET_BUNDLE_SHA256

_SMILES = (
    "COc1ccc(C(=O)N)cc1",
    "CCNc1ncnc2ccccc12",
    "CCOc1ccccc1N",
    "CN1CCN(c2ccccc2)CC1",
    "CC(=O)Nc1ccc(F)cc1",
    "OC1CCCCC1",
    "O=C(O)c1ccncc1",
    "CCN(CC)C(=O)c1ccccc1",
    "COc1ncc(CN)cc1",
    "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
    "O=C(NCCO)c1ccccc1",
    "NCCc1ccncc1",
)


def measurement(
    value, *, name="IC50", unit="nM", target="Target", assay="binding", page=20
):
    return Activity(
        name=name, value=value, unit=unit, target=target, assay=assay, page=page
    )


def compound(number=1, *, smiles=None, value=10.0, activities=None, endpoints=None):
    smiles = smiles or _SMILES[(number - 1) % len(_SMILES)]
    probabilities = {key: 0.05 for key in LEAD_ENDPOINTS}
    probabilities.update(HIA_Hou=0.9, Bioavailability_Ma=0.8)
    if endpoints is not None:
        probabilities = endpoints
    properties = compute_descriptors(smiles) + [
        PredictionMetric(
            key="Solubility_AqSolDB",
            label="LogS",
            value=-3.0,
            unit="log(mol/L)",
            kind="prediction",
        )
    ]
    return Compound(
        id=f"Compound {number}",
        display_id=f"Compound {number}",
        structure_id=f"S{number}",
        structure_image_url=f"/controlled/structure/{number}",
        smiles=smiles,
        recognition=Recognition(
            status="valid",
            quality_flag="ok",
            stereochemistry={
                "version": 3,
                "image_sha256": "a" * 64,
                "image_size": [100, 100],
                "unknown_bond_boxes": [],
                "status": "no_unknown_detected",
                "reason": "Controlled original-source evidence, not a model run.",
                "assigned_centers": 0,
                "unassigned_centers": 0,
                "assigned_double_bonds": 0,
                "absolute_configuration_verified": False,
            },
        ),
        activities=[measurement(value)] if activities is None else activities,
        source=Source(page=5, bbox=[1.0, 1.0, 100.0, 100.0], source_label=str(number)),
        confidence=Confidence(level="high", reason="Controlled proved-ID fixture"),
        record_kind="structure_activity",
        # Explicit synthetic model_copy is only scoring input. It is not API
        # validation evidence; the controller verifies its shared endpoint DTO.
        admet=PredictionSummary(
            status="complete",
            properties=properties,
            source_fingerprint=hashlib.sha256(f"source-{number}".encode()).hexdigest(),
            smiles_sha256=smiles_digest(smiles),
            job_id="d" * 32,
            generated_at="2026-10-08T00:00:00Z",
            engine={
                "name": "ADMET-AI",
                "version": "2.0.1",
                "model_sha256": ADMET_BUNDLE_SHA256,
            },
        ).model_copy(update={"endpoints": probabilities}),
    )


def catalog(rows):
    columns = ActivityColumnCatalog()
    for row in rows:
        columns.observe(row.activities)
    return columns.columns()


def evaluate(rows):
    return prioritize_leads(rows, catalog(rows))


class LeadScoringTests(unittest.TestCase):
    def test_target_eight_continuous_ranks_deterministic_project_inputs(self):
        rows = [compound(index) for index in range(1, 13)]
        before = [row.model_dump() for row in rows]
        first = evaluate(rows)
        # The caller joins all pages before ranking; chunk/order is irrelevant.
        second = evaluate(list(reversed(rows[6:])) + list(reversed(rows[:6])))
        self.assertEqual(first, second)
        chosen = sorted(
            item.rank for item in first.values() if item.status == "selected"
        )
        self.assertEqual(chosen, list(range(1, 9)))
        self.assertEqual(before, [row.model_dump() for row in rows])
        self.assertTrue(
            all(
                item.review_only and item.policy_version == "2"
                for item in first.values()
            )
        )

    def test_fewer_qualified_candidates_not_padded(self):
        rows = [compound(1), compound(2, activities=[]), compound(3, value="<1")]
        result = evaluate(rows)
        self.assertEqual(result[rows[0].id].rank, 1)
        self.assertEqual(
            [result[row.id].status for row in rows[1:]], ["unranked", "unranked"]
        )

    def test_ties_midrank_and_natural_identifier_tiebreak(self):
        rows = [compound(10), compound(2), compound(1)]
        observations = activity_evidence(rows, catalog(rows))
        self.assertEqual({item.potency for item in observations.values()}, {50.0})
        with patch(
            "patent_sar_extractor.web.lead_scoring.physchem_score",
            return_value=(100.0, []),
        ):
            result = evaluate(rows)
        self.assertEqual(result["Compound 1"].rank, 1)

    def test_numeric_potency_zero_negative_unknown_unit_are_not_best(self):
        for value in (0, -1, "0", "-0", "<1", ">1", "1-3", "10 nM", "ND", None):
            with self.subTest(value=value):
                result = evaluate([compound(1, value=value), compound(2, value=10)])
                self.assertEqual(result["Compound 1"].status, "unranked")
        for unit in (None, "unknown", "mg/mL", "%"):
            with self.subTest(unit=unit):
                self.assertEqual(
                    evaluate([compound(1, activities=[measurement(1, unit=unit)])])[
                        "Compound 1"
                    ].status,
                    "unranked",
                )

    def test_explicit_log_potency_higher_and_concentration_lower(self):
        for name, unit, best in (("IC50", "nM", 1), ("pIC50", None, 3)):
            rows = [
                compound(index, activities=[measurement(index, name=name, unit=unit)])
                for index in range(1, 4)
            ]
            observed = activity_evidence(rows, catalog(rows))
            self.assertEqual(observed[f"Compound {best}"].potency, 100.0)

    def test_ymin_only_proved_context_and_negative_readings_not_clamped(self):
        rows = [
            compound(
                index,
                activities=[
                    measurement(
                        value,
                        name="CAL-51 Prolif Ymin",
                        unit="%",
                        assay="cell proliferation",
                    )
                ],
            )
            for index, value in enumerate((-3, -1, 10), 1)
        ]
        observed = activity_evidence(rows, catalog(rows))
        self.assertEqual([observed[row.id].potency for row in rows], [100.0, 50.0, 0.0])
        for name, assay, unit in (
            ("Ymin", "signal", "%"),
            ("Ymin", "degradation", None),
        ):
            self.assertEqual(
                evaluate(
                    [
                        compound(
                            1,
                            activities=[
                                measurement(-3, name=name, assay=assay, unit=unit)
                            ],
                        )
                    ]
                )["Compound 1"].status,
                "unranked",
            )
        self.assertEqual(rows[0].activities[0].value, -3)

    def test_counter_toxicity_negative_and_unknown_assays_not_potency(self):
        for name, target, assay in (
            ("IC50", "hERG", "binding"),
            ("EC50", "Target", "cytotoxicity"),
            ("IC50", "Target", "counter-screen"),
            ("Inactive IC50", "Target", "binding"),
            ("No inhibition IC50", "Target", "binding"),
            ("Response signal", "Target", "assay"),
            ("Grade", "Target", "assay"),
        ):
            with self.subTest(name=name, assay=assay):
                value = "+++" if name == "Grade" else 1
                item = evaluate(
                    [
                        compound(
                            1,
                            activities=[
                                measurement(
                                    value, name=name, target=target, assay=assay
                                )
                            ],
                        )
                    ]
                )["Compound 1"]
                self.assertEqual(item.status, "unranked")

    def test_supported_ordinal_grade_and_mixed_types_fail_closed(self):
        for name, assay, values in (
            ("Anti-proliferation activity grade", "proliferation", ["+++", "++", "+"]),
            ("Protein degradation grade", "Western blot", ["A", "B", "D"]),
        ):
            rows = [
                compound(
                    index,
                    activities=[measurement(value, name=name, unit=None, assay=assay)],
                )
                for index, value in enumerate(values, 1)
            ]
            self.assertEqual(
                activity_evidence(rows, catalog(rows))["Compound 1"].potency, 100.0
            )
        mixed = [
            compound(1, activities=[measurement("++", name="Inhibition", unit="%")]),
            compound(2, activities=[measurement(50, name="Inhibition", unit="%")]),
        ]
        self.assertTrue(
            all(item.status == "unranked" for item in evaluate(mixed).values())
        )

    def test_repeat_observations_use_worst_not_best_and_do_not_inflate_counts(self):
        rows = [
            compound(1, activities=[measurement(1), measurement(100), measurement(1)]),
            compound(2, value=10),
            compound(3, value=50),
        ]
        observed = activity_evidence(rows, catalog(rows))
        self.assertEqual(observed["Compound 1"].potency, 0.0)
        self.assertEqual(observed["Compound 1"].coverage, 1.0)
        self.assertEqual(observed["Compound 2"].potency, 100.0)
        rows[0].activities.reverse()
        self.assertEqual(observed, activity_evidence(rows, catalog(rows)))

    def test_censored_repeat_does_not_borrow_its_exact_sibling(self):
        rows = [
            compound(1, activities=[measurement(1), measurement("<0.5")]),
            compound(2, value=10),
        ]
        self.assertEqual(evaluate(rows)["Compound 1"].status, "unranked")

    def test_full_project_exact_context_coverage_and_percentile_aggregation(self):
        rows = [
            compound(
                1,
                activities=[
                    measurement(1),
                    measurement(100, unit="uM", target="Other"),
                ],
            ),
            compound(
                2,
                activities=[
                    measurement(10),
                    measurement(10, unit="uM", target="Other"),
                ],
            ),
            compound(3, activities=[measurement(100)]),
        ]
        observed = activity_evidence(rows, catalog(rows))
        self.assertEqual(observed["Compound 1"].potency, 50.0)
        self.assertEqual(observed["Compound 1"].coverage, 1.0)
        self.assertEqual(observed["Compound 3"].coverage, 0.5)
        self.assertEqual(observed["Compound 3"].total_columns, 2)

    def test_unknown_extra_column_not_an_independent_rankable_endpoint(self):
        rows = [
            compound(
                1,
                activities=[
                    measurement(1),
                    measurement(12, name="Unknown signal", unit=None),
                ],
            ),
            compound(2, value=2),
        ]
        observed = activity_evidence(rows, catalog(rows))
        self.assertEqual(observed["Compound 1"].coverage, 1.0)
        self.assertEqual(observed["Compound 1"].excluded_columns, 1)

    def test_missing_invalid_or_stale_admet_overview_is_unranked(self):
        row = compound()
        for endpoints in (
            {},
            {"hERG": 0.0},
            {**row.admet.endpoints, "hERG": float("nan")},
            {**row.admet.endpoints, "hERG": -0.1},
            {**row.admet.endpoints, "hERG": 1.1},
            {**row.admet.endpoints, "hERG": True},
            {**row.admet.endpoints, "extra": 0.1},
        ):
            with self.subTest(endpoints=endpoints):
                packet = row.admet.model_copy(update={"endpoints": endpoints})
                current = row.model_copy(update={"admet": packet})
                self.assertEqual(evaluate([current])[row.id].status, "unranked")
        for packet in (
            None,
            PredictionSummary(status="stale"),
            PredictionSummary.model_validate(
                row.admet.model_dump(exclude={"endpoints"})
            ),
        ):
            self.assertEqual(
                evaluate([row.model_copy(update={"admet": packet})])[row.id].status,
                "unranked",
            )

    def test_old_graph_prediction_never_reassociated(self):
        row = compound()
        stale = row.admet.model_copy(update={"smiles_sha256": "e" * 64})
        self.assertEqual(
            evaluate([row.model_copy(update={"admet": stale})])[row.id].status,
            "unranked",
        )

    def test_each_core_risk_direction_lower_and_review_is_explicit(self):
        for key in ("hERG", "AMES", "DILI", "ClinTox"):
            with self.subTest(key=key):
                row = compound()
                risky = row.model_copy(
                    update={
                        "id": "Compound 99",
                        "display_id": "Compound 99",
                        "admet": row.admet.model_copy(
                            update={"endpoints": {**row.admet.endpoints, key: 0.9}}
                        ),
                    }
                )
                result = evaluate([row, risky])
                self.assertEqual(result[risky.id].status, "not_selected")
                self.assertTrue(result[risky.id].risk_review_required)
                self.assertLess(
                    result[risky.id].components["admet"],
                    result[row.id].components["admet"],
                )

    def test_high_model_risk_cohort_is_prioritized_with_review_not_experimentally_vetoed(
        self,
    ):
        rows = [compound(index) for index in range(1, 13)]
        for row in rows:
            row.admet.endpoints["DILI"] = 0.99
        selected = [
            value for value in evaluate(rows).values() if value.status == "selected"
        ]
        self.assertEqual(len(selected), 8)
        self.assertTrue(all(value.risk_review_required for value in selected))
        self.assertTrue(
            all(
                any("待复核" in message for message in value.warnings)
                for value in selected
            )
        )
        self.assertTrue(all(row.admet.endpoints["DILI"] == 0.99 for row in rows))

    def test_single_core_liability_is_not_averaged_away_and_increasing_risk_is_monotonic(
        self,
    ):
        from patent_sar_extractor.web.lead_chemistry import admet_score

        baseline = compound().admet.endpoints
        scores = [
            admet_score({**baseline, "DILI": value}) for value in (0.05, 0.4, 0.8, 0.99)
        ]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertGreater(scores[0] - scores[-1], 20)

    def test_absorption_higher_and_cyp_lower_are_beneficial(self):
        from patent_sar_extractor.web.lead_chemistry import admet_score

        row = compound()
        base = admet_score(row.admet.endpoints)
        for key in ("HIA_Hou", "Bioavailability_Ma"):
            self.assertLess(admet_score({**row.admet.endpoints, key: 0.0}), base)
        for key in LEAD_ENDPOINTS:
            if not key.startswith("CYP"):
                continue
            self.assertLess(admet_score({**row.admet.endpoints, key: 1.0}), base)

    def test_anonymous_unproved_invalid_review_and_stale_correction_rejected(self):
        row = compound()
        variants = [
            row.model_copy(update={"id": "source-structure:abc"}),
            row.model_copy(
                update={"confidence": Confidence(level="review", reason="Unproved")}
            ),
            row.model_copy(update={"flags": ["ambiguous_binding"]}),
            row.model_copy(
                update={
                    "recognition": Recognition(
                        status="invalid", quality_flag="stereo_source_conflict"
                    )
                }
            ),
            row.model_copy(
                update={
                    "correction": CorrectionMetadata(
                        revision=1, stale=True, has_changes=True, updated_at="now"
                    )
                }
            ),
        ]
        for decision in ("rejected", "needs_review"):
            variants.append(
                row.model_copy(
                    update={
                        "review": Review(
                            decision=decision, note="", revision=1, updated_at="now"
                        )
                    }
                )
            )
        for variant in variants:
            with self.subTest(variant=variant.id):
                self.assertEqual(evaluate([variant])[variant.id].status, "ineligible")

    def test_no_activity_retains_structures_smiles_and_properties(self):
        row = compound(activities=[])
        before = row.model_dump()
        self.assertEqual(evaluate([row])[row.id].status, "unranked")
        self.assertEqual(row.model_dump(), before)
        self.assertTrue(row.smiles and len(row.admet.properties) == 6)

    def test_manual_explicit_null_not_backfilled(self):
        row = compound()
        current = row.model_copy(update={"property_overrides": {"logP": None}})
        self.assertEqual(evaluate([current])[row.id].status, "unranked")
        self.assertIsNone(current.property_overrides["logP"])

    def test_missing_invalid_physchem_not_recommended(self):
        row = compound()
        for update in (
            {"molecular_weight": 0.0},
            {"tpsa": -1.0},
            {"logP": float("inf")},
            {"hydrogen_bond_donors": 1.5},
        ):
            with self.subTest(update=update):
                bad = row.model_copy(update={"property_overrides": update})
                self.assertEqual(evaluate([bad])[row.id].status, "unranked")

    def test_large_protac_domain_warning_is_not_universal_ro5_veto(self):
        row = compound()
        current = row.model_copy(
            update={
                "property_overrides": {
                    "molecular_weight": 950.0,
                    "tpsa": 230.0,
                    "hydrogen_bond_donors": 8.0,
                    "hydrogen_bond_acceptors": 15.0,
                }
            }
        )
        item = evaluate([current])[row.id]
        self.assertEqual(item.status, "selected")
        self.assertTrue(any("适用域" in warning for warning in item.warnings))

    def test_duplicate_exact_graph_one_slot_enantiomers_isotopes_preserved(self):
        rows = [
            compound(1, smiles="C[C@H](O)c1ccccc1"),
            compound(2, smiles="C[C@H](O)c1ccccc1"),
            compound(3, smiles="C[C@@H](O)c1ccccc1"),
            compound(4, smiles="[13CH3][C@H](O)c1ccccc1"),
        ]
        features = [chemical_features(row.smiles) for row in rows]
        self.assertEqual(features[0].graph, features[2].graph)
        self.assertNotEqual(features[0].isomer, features[2].isomer)
        self.assertNotEqual(features[0].graph, features[3].graph)
        self.assertLess(similarity(features[0], features[2]), 1.0)
        result = evaluate(rows)
        self.assertEqual(sum(result[row.id].status == "selected" for row in rows), 3)
        self.assertTrue(all(result[row.id].status == "selected" for row in rows[2:]))

    def test_smiles_alias_duplicate_salts_not_stripped(self):
        rows = [
            compound(1, smiles="CCO"),
            compound(2, smiles="OCC"),
            compound(3, smiles="CCO.[Na+]"),
        ]
        result = evaluate(rows)
        self.assertEqual(sum(item.status == "selected" for item in result.values()), 2)
        self.assertEqual(result["Compound 3"].status, "selected")
        self.assertTrue(
            any("多个片段" in message for message in result["Compound 3"].warnings)
        )

    def test_diversity_cannot_rescue_weak_quality_and_similarity_work_linear(self):
        rows = [compound(index, value=float(index)) for index in range(1, 13)]
        with patch(
            "patent_sar_extractor.web.lead_scoring.similarity", wraps=similarity
        ) as comparisons:
            result = evaluate(rows)
        self.assertEqual(result["Compound 12"].status, "not_selected")
        self.assertLess(result["Compound 12"].components["potency"], 50)
        self.assertLessEqual(comparisons.call_count, 8 * len(rows))
        self.assertTrue(
            all(
                item.rank is None
                for item in result.values()
                if item.status != "selected"
            )
        )

    def test_alias_only_pool_bounded_greedy_not_duplicate_max_loop(self):
        base = compound(1, smiles="CCO")
        rows = [
            base.model_copy(
                update={"id": f"Compound {index}", "display_id": f"Compound {index}"}
            )
            for index in range(1, 101)
        ]
        with patch(
            "patent_sar_extractor.web.lead_scoring.similarity", wraps=similarity
        ) as comparisons:
            result = evaluate(rows)
        self.assertEqual(sum(item.status == "selected" for item in result.values()), 1)
        self.assertEqual(comparisons.call_count, len(rows) - 1)

    def test_cancellation_initial_and_during_similarity_returns_no_partial(self):
        rows = [compound(index) for index in range(1, 13)]
        before = [row.model_dump() for row in rows]
        with self.assertRaises(WebError) as failure:
            prioritize_leads(rows, catalog(rows), lambda: True)
        self.assertEqual(failure.exception.code, "lead_cancelled")
        cancelled = False

        def compare(left, right):
            nonlocal cancelled
            cancelled = True
            return similarity(left, right)

        with (
            patch(
                "patent_sar_extractor.web.lead_scoring.similarity", side_effect=compare
            ),
            self.assertRaises(WebError) as failure,
        ):
            prioritize_leads(rows, catalog(rows), lambda: cancelled)
        self.assertEqual(failure.exception.code, "lead_cancelled")
        self.assertEqual(before, [row.model_dump() for row in rows])

    def test_row_molecule_observation_bounds_refuse_not_partial(self):
        base = compound()
        for rows in (
            [base] * 25_001,
            [
                base.model_copy(update={"id": f"Compound {index}"})
                for index in range(1, 5_002)
            ],
        ):
            with (
                patch(
                    "patent_sar_extractor.web.lead_scoring.chemical_features"
                ) as features,
                self.assertRaises(WebError) as failure,
            ):
                evaluate(rows)
            self.assertEqual(failure.exception.code, "lead_limit")
            features.assert_not_called()
        excess = base.model_copy(update={"activities": base.activities * 100_001})
        with self.assertRaises(WebError) as failure:
            prioritize_leads([excess], catalog([base]))
        self.assertEqual(failure.exception.code, "lead_limit")

    def test_duplicate_ids_and_incomplete_context_catalog_fail_closed(self):
        row = compound()
        for rows, columns, code in (
            ([row, row], catalog([row]), "lead_identity"),
            ([row], [], "lead_activity_context"),
            ([row], catalog([row]) * 2, "lead_activity_context"),
        ):
            with self.assertRaises(WebError) as failure:
                prioritize_leads(rows, columns)
            self.assertEqual(failure.exception.code, code)

    def test_current_admet_cannot_mix_old_graph_descriptor_packet(self):
        row = compound()
        descriptors = DescriptorSummary(
            status="complete",
            properties=compute_descriptors(row.smiles),
            source_fingerprint=row.admet.source_fingerprint,
            smiles_sha256="e" * 64,
            engine=descriptor_engine(),
            job_id="d" * 32,
            generated_at="2026-10-08T00:00:00Z",
        )
        current = row.model_copy(update={"descriptors": descriptors})
        self.assertEqual(evaluate([current])[row.id].status, "unranked")

    def test_source_epoch_invalid_manual_and_invalid_page_are_ineligible(self):
        row = compound()
        old_evidence = row.recognition.stereochemistry.model_copy(update={"version": 2})
        variants = [
            row.model_copy(
                update={
                    "recognition": row.recognition.model_copy(
                        update={"stereochemistry": old_evidence}
                    )
                }
            ),
            row.model_copy(update={"structure_molfile": "invalid manual molfile"}),
            row.model_copy(
                update={"source": row.source.model_copy(update={"page": 0})}
            ),
        ]
        for variant in variants:
            self.assertEqual(evaluate([variant])[row.id].status, "ineligible")

    def test_murcko_novelty_operates_only_inside_quality_pool(self):
        rows = [
            compound(1, smiles="NC(=O)c1ccccc1"),
            compound(2, smiles="NC(=O)c1ccc(F)cc1"),
            compound(3, smiles="NC(=O)c1ccncc1"),
        ]
        with patch(
            "patent_sar_extractor.web.lead_scoring.physchem_score",
            return_value=(100.0, []),
        ):
            result = evaluate(rows)
        self.assertEqual(result["Compound 1"].rank, 1)
        self.assertEqual(result["Compound 3"].rank, 2)
        self.assertEqual(result["Compound 1"].scaffold, result["Compound 2"].scaffold)
        self.assertNotEqual(
            result["Compound 1"].scaffold, result["Compound 3"].scaffold
        )
        self.assertIsNone(result["Compound 1"].nearest_similarity)
        self.assertTrue(0 <= result["Compound 3"].nearest_similarity <= 1)

    def test_structural_alert_only_warns_and_lead_scores_have_same_formula(self):
        row = compound(smiles="O=[N+]([O-])c1ccccc1")
        result = evaluate([row])[row.id]
        self.assertEqual(result.status, "selected")
        self.assertTrue(any("结构警报" in message for message in result.warnings))
        quality = sum(
            result.components[key] * weight
            for key, weight in {
                "potency": 0.35,
                "coverage": 0.2,
                "admet": 0.2,
                "physchem": 0.15,
                "evidence": 0.1,
            }.items()
        )
        self.assertAlmostEqual(
            result.score, 0.8 * quality + 0.2 * result.components["diversity"], places=5
        )

    def test_empty_or_all_unproved_inputs_normal_result_no_missing_field_error(self):
        self.assertEqual(prioritize_leads([], []), {})
        rows = [compound(1), compound(2)]
        for row in rows:
            row.id = "source-structure:" + row.id
            row.smiles = None
            row.admet = None
        self.assertTrue(
            all(item.status == "ineligible" for item in evaluate(rows).values())
        )

    def test_page_provenance_evidence_reduces_score_not_fabricates_proof(self):
        rows = [compound(1), compound(2, activities=[measurement(10, page=None)])]
        with patch(
            "patent_sar_extractor.web.lead_scoring.physchem_score",
            return_value=(100.0, []),
        ):
            result = evaluate(rows)
        self.assertEqual(result["Compound 1"].components["evidence"], 100.0)
        self.assertEqual(result["Compound 2"].components["evidence"], 60.0)
        self.assertTrue(
            any(
                "缺少有效原文页" in message for message in result["Compound 2"].warnings
            )
        )

    def test_schema_strict_finite_bounded_and_selection_identity(self):
        for values in (
            {"status": "selected"},
            {"status": "selected", "rank": 1},
            {"status": "not_selected", "rank": 1},
            {"score": float("nan")},
            {"score": 101.0},
            {"rank": True},
            {"activity_coverage": -0.1},
            {"nearest_similarity": 1.1},
            {"components": {"potency": float("inf")}},
            {"components": {"unknown": 10.0}},
            {"warnings": ["x" * 301]},
            {"reasons": ["one\ntwo"]},
            {"reasons": ["x"] * 13},
            {"review_only": False},
            {"risk_review_required": "true"},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                LeadAssessment(**values)
        valid = LeadAssessment(
            status="selected", rank=1, score=80.0, components={"potency": 90.0}
        )
        self.assertTrue(valid.review_only)


if __name__ == "__main__":
    unittest.main()
