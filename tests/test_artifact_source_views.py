"""Versioned immutable evidence views; storage is not scientific acceptance."""

import copy
import hashlib
import json
import math
import unittest
from unittest.mock import patch

from patent_sar_extractor.artifact_catalog import (
    LITERAL,
    MARKER,
    READONLY,
    REFERENCE,
    expand_shared_json,
    pack_shared_json,
    read_artifact_json,
)
from patent_sar_extractor.artifact_immutable import FrozenDict, FrozenList, freeze_json
from patent_sar_extractor.artifact_nodes import JsonGraph, compact_json


class ArtifactSourceViewTests(unittest.TestCase):
    def roundtrip(self, value):
        return read_artifact_json(
            compact_json(pack_shared_json(value)), strict_numbers=True
        )

    def test_freeze_preserves_original_values_order_number_types_and_digest(self):
        source = {"原文": [1, 1.0, -0.0, None, True], "raw": {"value": "不改原文"}}
        before = compact_json(source)
        frozen = freeze_json(source)
        restored = self.roundtrip({"evidence": frozen})["evidence"]
        self.assertIsInstance(restored, FrozenDict)
        self.assertIsInstance(restored["原文"], FrozenList)
        self.assertEqual(compact_json(restored), before)
        self.assertIs(type(restored["原文"][0]), int)
        self.assertIs(type(restored["原文"][1]), float)
        self.assertEqual(math.copysign(1, restored["原文"][2]), -1)
        source["原文"].append("later edit")
        self.assertEqual(compact_json(frozen), before)
        self.assertEqual(
            hashlib.sha256(before.encode()).digest(),
            hashlib.sha256(compact_json(restored).encode()).digest(),
        )

    def test_mutation_and_reinitialization_are_explicitly_rejected(self):
        frozen = freeze_json({"rows": [1, 2]})
        for action in (
            lambda: frozen.update({"rows": []}),
            lambda: frozen.clear(),
            lambda: frozen.pop("rows"),
            lambda: frozen.popitem(),
            lambda: frozen.setdefault("other", 3),
            lambda: frozen.__init__({"rows": []}),
            lambda: frozen.__setitem__("rows", []),
            lambda: frozen.__delitem__("rows"),
            lambda: frozen.__ior__({"other": 2}),
            lambda: frozen["rows"].append(3),
            lambda: frozen["rows"].clear(),
            lambda: frozen["rows"].extend([3]),
            lambda: frozen["rows"].insert(0, 3),
            lambda: frozen["rows"].pop(),
            lambda: frozen["rows"].remove(1),
            lambda: frozen["rows"].reverse(),
            lambda: frozen["rows"].sort(),
            lambda: frozen["rows"].__init__([]),
            lambda: frozen["rows"].__setitem__(0, 3),
            lambda: frozen["rows"].__delitem__(0),
            lambda: frozen["rows"].__iadd__([3]),
            lambda: frozen["rows"].__imul__(2),
        ):
            with self.subTest(action=action), self.assertRaises(TypeError):
                action()
        self.assertEqual(frozen, {"rows": [1, 2]})

    def test_equal_mutable_and_source_views_never_change_each_others_mutability(self):
        raw = {"value": [1, 2]}
        frozen = freeze_json(raw)
        restored = self.roundtrip({"working": raw, "source": frozen, "other": frozen})
        restored["working"]["value"].append(3)
        with self.assertRaises(TypeError):
            restored["source"]["value"].append(3)
        working = copy.deepcopy(restored)
        working["source"]["value"].append(4)
        self.assertEqual(working["other"]["value"], [1, 2])
        self.assertEqual(restored["source"], raw)

    def test_source_root_and_reserved_looking_original_objects_roundtrip(self):
        for raw in (
            {REFERENCE: "printed literal", READONLY: False},
            {LITERAL: {REFERENCE: "printed literal", READONLY: True}},
            {"nested": [{REFERENCE: "original"}]},
        ):
            with self.subTest(raw=raw):
                for payload in (freeze_json(raw), {"row": freeze_json(raw)}):
                    restored = self.roundtrip(payload)
                    self.assertEqual(restored, payload)
                    self.assertIsInstance(
                        restored
                        if isinstance(payload, FrozenDict)
                        else restored["row"],
                        FrozenDict,
                    )

    def test_v1_history_is_readable_and_its_mutable_values_remain_independent(self):
        source = {"text": "original " * 100, "rows": [1, 2]}
        graph = JsonGraph()
        key = graph.visit(source)
        packet = {
            "first": {REFERENCE: key},
            "second": {REFERENCE: key},
            MARKER: {"version": 1, "objects": {key: source}},
        }
        restored = expand_shared_json(packet)
        restored["first"]["rows"].append(3)
        self.assertEqual(restored["second"], source)
        # The v1 grammar did not reserve this two-key original literal.
        packet["literal"] = {REFERENCE: "original", READONLY: True}
        self.assertEqual(expand_shared_json(packet)["literal"], packet["literal"])

    def test_source_mutability_cannot_be_downgraded_by_version_or_flag_changes(self):
        encoded = pack_shared_json({"source": freeze_json({"values": [1, 2]})})
        for change in ("version", "flag", "missing", "content"):
            packet = copy.deepcopy(encoded)
            if change == "version":
                packet[MARKER]["version"] = 1
            elif change == "flag":
                packet["source"][READONLY] = False
            elif change == "missing":
                packet["source"].pop(READONLY)
            else:
                key = packet["source"][REFERENCE]
                packet[MARKER]["objects"][key]["values"] = [3, 4]
            with self.subTest(change=change), self.assertRaises(ValueError):
                expand_shared_json(packet)

    def test_explicit_source_reference_to_scalar_is_invalid(self):
        graph = JsonGraph()
        key = graph.visit("not a source container")
        packet = {
            "source": {REFERENCE: key, READONLY: True},
            MARKER: {"version": 2, "objects": {key: "not a source container"}},
        }
        with self.assertRaises(ValueError):
            expand_shared_json(packet)

    def test_logical_bytes_unique_nodes_edges_and_depth_stay_bounded(self):
        for setting, limit, value in (
            ("MAX_EXPANDED_BYTES", 30, {"rows": ["原文" * 10]}),
            ("MAX_NODES", 3, {"rows": [1, 2, 3]}),
            ("MAX_EDGES", 3, {"rows": [1, 2, 3]}),
            ("MAX_DEPTH", 2, {"rows": [[[1]]]}),
        ):
            with (
                self.subTest(setting=setting),
                patch(f"patent_sar_extractor.artifact_nodes.{setting}", limit),
                self.assertRaises(ValueError),
            ):
                freeze_json(value)

    def test_shared_pool_and_mutable_wrappers_share_one_allocation_budget(self):
        frozen = freeze_json({"rows": [{"value": index} for index in range(8)]})
        payload = {"copies": [frozen] * 4}
        with (
            patch("patent_sar_extractor.artifact_nodes.MAX_EXPANDED_NODES", 20),
            patch(
                "patent_sar_extractor.artifact_materialization.readonly_container",
                side_effect=AssertionError("No restoration before budget preflight"),
            ),
            self.assertRaisesRegex(ValueError, "node expansion"),
        ):
            pack_shared_json(payload)

    def test_wire_byte_preflight_includes_catalog_metadata_and_utf8_exactly(self):
        payload = {"source": freeze_json({"原文": "原始 observations " * 60})}
        encoded = pack_shared_json(payload)
        exact = len(compact_json(encoded).encode("utf-8"))
        with patch("patent_sar_extractor.artifact_nodes.MAX_ARTIFACT_BYTES", exact):
            self.assertEqual(pack_shared_json(payload), encoded)
        with (
            patch("patent_sar_extractor.artifact_nodes.MAX_ARTIFACT_BYTES", exact - 1),
            self.assertRaisesRegex(ValueError, "byte bound"),
        ):
            pack_shared_json(payload)

    def test_changed_shared_reference_cannot_hide_behind_a_previously_cached_source(
        self,
    ):
        encoded = pack_shared_json({"first": freeze_json({"values": [1, 2]})})
        encoded["second"] = {REFERENCE: encoded["first"][REFERENCE]}
        with self.assertRaisesRegex(ValueError, "mutability"):
            expand_shared_json(encoded)

    def test_json_encoded_source_view_is_not_a_second_scientific_proof(self):
        source = freeze_json({"status": "review_required", "fail_closed": True})
        restored = self.roundtrip({"source": source})
        self.assertEqual(json.loads(json.dumps(restored)), {"source": dict(source)})
        self.assertNotIn("core_accepted", restored)


if __name__ == "__main__":
    unittest.main()
