"""Software-owned directions; no source rewrite or invented potency thresholds."""

import unittest
from unittest.mock import patch

import test_sar_api as support
from test_sar_api import ROOT, nonce
from test_web_support import WebFixture

from patent_sar_extractor.web.activity_rank_values import rank_direction
from patent_sar_extractor.web.sar.indicator_policy import setup_defaults


class IndicatorConventionTests(unittest.TestCase):
    def test_raw_and_negative_log_potencies_are_opposite(self):
        for name in ("IC50", "EC 50", "DC₅₀", "AC-50", "GI50", "XC50", "K_i", "Kd"):
            with self.subTest(name=name):
                self.assertEqual(
                    rank_direction(name, "nM", None, "numeric"), ("lower", "potency")
                )
        for name in ("pIC50", "pEC 50", "pDC₅₀", "pKi", "pKd"):
            with self.subTest(name=name):
                self.assertEqual(
                    rank_direction(name, None, None, "numeric"),
                    ("higher", "log_potency"),
                )

    def test_units_conflicting_headers_and_unknown_objectives_are_not_guessed(self):
        for name, unit in (
            ("IC50", "%"),
            ("pIC50", "nM"),
            ("IC50 / pIC50", None),
            ("IC50 / EC50", "nM"),
            ("log EC50", None),
            ("Ymin", None),
            ("Dmax", "nM"),
            ("Ratio", None),
            ("MW", "Da"),
            ("LogP", None),
            ("t_half", "h"),
            ("Day 50 signal", None),
            ("IC50 ratio", None),
        ):
            with self.subTest(name=name, unit=unit):
                self.assertEqual(
                    rank_direction(name, unit, None, "numeric")[0], "unknown"
                )

    def test_effect_and_remaining_rules_require_matching_context(self):
        self.assertEqual(
            rank_direction("Dmax", "%", None, "numeric"), ("higher", "effect_percent")
        )
        self.assertEqual(
            rank_direction("Ymin", None, "cell proliferation", "numeric"),
            ("lower", "ymin_remaining"),
        )
        self.assertEqual(
            rank_direction("Ymin", "%", "protein degradation", "numeric")[0], "lower"
        )
        self.assertEqual(
            rank_direction("Ymin", "nM", "protein degradation", "numeric")[0], "unknown"
        )
        self.assertEqual(
            rank_direction("Cell viability", "%", None, "numeric")[0], "lower"
        )
        self.assertEqual(
            rank_direction("Inhibition", "%", None, "numeric")[0], "higher"
        )
        self.assertEqual(
            rank_direction("A–G grade", None, None, "letter")[0], "unknown"
        )

    def test_exact_contexts_remain_separate_and_mixed_metrics_have_no_default(self):
        contexts = [
            {
                "id": "a" * 64,
                "metric_id": "m",
                "name": "Ymin",
                "unit": None,
                "context": {"assay": "cell proliferation"},
            },
            {
                "id": "b" * 64,
                "metric_id": "m",
                "name": "Ymin",
                "unit": None,
                "context": {"assay": "unknown signal"},
            },
        ]
        policies, metrics = setup_defaults(contexts)
        self.assertEqual(policies["a" * 64].direction, "lower")
        self.assertEqual(policies["b" * 64].direction, "unknown")
        self.assertEqual(
            metrics["m"].model_dump(),
            {"direction": "unknown", "rule": "mixed_contexts"},
        )


class SARIndicatorDefaultAPITests(WebFixture, unittest.TestCase):
    dataset = support.SARAPITests.dataset
    region = support.SARAPITests.region
    completed = support.SARAPITests.completed

    def test_profile_defaults_are_current_read_only_metadata(self):
        with self.client() as client:
            dataset = self.dataset(client)
            prefix = ROOT + "/datasets/" + dataset["id"]
            before = client.get(prefix + "/molecules").json()
            profile = client.get(prefix + "/profile").json()
            context = profile["contexts"][0]
            expected = {"direction": "lower", "rule": "potency"}
            self.assertEqual(profile.get("policy_defaults"), {context["id"]: expected})
            self.assertEqual(
                profile.get("metric_defaults"), {dataset["metrics"][0]["id"]: expected}
            )
            self.assertEqual(client.get(prefix).json(), dataset)
            self.assertEqual(client.get(prefix + "/molecules").json(), before)
            self.assertEqual(client.get(prefix + "/jobs").json()["items"], [])

    def test_new_known_direction_conflicts_are_rejected_before_any_job(self):
        with self.client() as client:
            dataset = self.dataset(client)
            region = self.region(client, dataset)
            prefix = ROOT + "/datasets/" + dataset["id"]
            profile = client.get(prefix + "/profile").json()
            for suffix, request in (
                (
                    "/jobs",
                    {
                        "region_id": region["id"],
                        "metric_id": dataset["metrics"][0]["id"],
                        "direction": "higher",
                    },
                ),
                (
                    "/studies",
                    {
                        "title": "Controlled",
                        "policies": [
                            {
                                "context_id": profile["contexts"][0]["id"],
                                "direction": "higher",
                            }
                        ],
                    },
                ),
            ):
                reply = client.post(
                    prefix + suffix,
                    json={
                        "request_id": nonce(),
                        "expected_dataset_revision": 1,
                        **request,
                    },
                )
                self.assertEqual(reply.status_code, 422, reply.text)
                self.assertEqual(
                    reply.json()["error"]["code"], "sar_indicator_direction"
                )
            self.assertEqual(client.get(prefix + "/jobs").json()["items"], [])

    def test_correct_request_replay_keeps_original_input_identity(self):
        with self.client() as client:
            dataset = self.dataset(client)
            region = self.region(client, dataset)
            prefix = ROOT + "/datasets/" + dataset["id"]
            body = {
                "request_id": nonce(),
                "expected_dataset_revision": 1,
                "region_id": region["id"],
                "metric_id": dataset["metrics"][0]["id"],
                "direction": "lower",
                "confirm_context": True,
            }
            first = client.post(prefix + "/jobs", json=body)
            self.assertEqual(first.status_code, 202, first.text)
            job = self.completed(client, first.json())
            original = client.get(
                ROOT + "/jobs/" + job["id"] + "/export?format=json"
            ).json()
            with patch(
                "patent_sar_extractor.web.sar.queue.validate_direction",
                side_effect=AssertionError("replayed work must not be reinterpreted"),
            ):
                again = client.post(prefix + "/jobs", json=body)
            self.assertEqual(again.json()["id"], job["id"])
            self.assertEqual(again.json()["input_sha256"], job["input_sha256"])
            self.assertEqual(
                client.get(ROOT + "/jobs/" + job["id"] + "/export?format=json").json(),
                original,
            )
