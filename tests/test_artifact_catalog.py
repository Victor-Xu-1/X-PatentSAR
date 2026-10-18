"""Shared JSON round trips, resource limits and hostile transport controls."""

import copy
import hashlib
import io
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.artifact_catalog import (
    LITERAL,
    MARKER,
    REFERENCE,
    expand_shared_json,
    pack_shared_json,
    read_artifact_json,
)
from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.artifact_nodes import MAX_DEPTH, JsonGraph, compact_json
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.files import SafeFiles


class ArtifactCatalogTests(unittest.TestCase):
    def payload(self):
        proof = {
            "text": "原文 source " * 200,
            "status": "unresolved",
            "values": [1, 1.0, -0.0],
        }
        return {"observations": [proof, copy.deepcopy(proof)]}

    def roundtrip(self, payload):
        encoded = compact_json(pack_shared_json(payload)).encode("utf-8")
        return read_artifact_json(encoded, strict_numbers=True)

    def test_shared_and_equal_copied_objects_preserve_exact_values_types_and_order(
        self,
    ):
        payload = self.payload()
        original = copy.deepcopy(payload)
        restored = self.roundtrip(payload)
        self.assertEqual(restored, original)
        self.assertEqual(payload, original)
        self.assertEqual(
            list(restored["observations"][0]), ["text", "status", "values"]
        )
        self.assertIs(type(restored["observations"][0]["values"][0]), int)
        self.assertIs(type(restored["observations"][0]["values"][1]), float)
        self.assertEqual(math.copysign(1, restored["observations"][0]["values"][2]), -1)

    def test_reserved_looking_literal_objects_are_not_references_with_or_without_sharing(
        self,
    ):
        for field in (REFERENCE, LITERAL):
            literal = {field: {field: "literal source value"}}
            with self.subTest(field=field):
                self.assertEqual(self.roundtrip(literal), literal)
                source = {**self.payload(), "literal": literal}
                self.assertEqual(self.roundtrip(source), source)

    def test_distinct_dictionary_orders_are_not_merged(self):
        text = "original " * 100
        rows = [{"a": text, "b": text}, {"b": text, "a": text}]
        restored = self.roundtrip({"rows": rows})
        self.assertEqual(
            [list(row) for row in restored["rows"]], [["a", "b"], ["b", "a"]]
        )

    def test_shared_storage_does_not_alias_mutable_record_or_proof_values(self):
        restored = self.roundtrip(self.payload())
        first, second = restored["observations"]
        first["status"] = "a later consumer edit"
        first["values"].append(7)
        self.assertEqual(second["status"], "unresolved")
        self.assertEqual(second["values"], [1, 1.0, -0.0])

    def test_large_repeated_literals_are_hashed_once_not_per_row(self):
        text = "unmodified original observation " * 1000
        with patch(
            "patent_sar_extractor.artifact_nodes.hashlib.sha256", wraps=hashlib.sha256
        ) as digest:
            packed = pack_shared_json({"rows": [{"text": text} for _ in range(1000)]})
        self.assertEqual(
            sum(text.encode() in call.args[0] for call in digest.call_args_list), 1
        )
        self.assertEqual(compact_json(packed).count(text), 1)

    def test_missing_changed_or_unreachable_objects_are_rejected(self):
        encoded = pack_shared_json(self.payload())
        for mutation in ("missing", "changed", "unreachable"):
            changed = copy.deepcopy(encoded)
            objects = changed[MARKER]["objects"]
            key = next(iter(objects))
            if mutation == "missing":
                objects.pop(key)
            elif mutation == "changed":
                objects[key] = "a different original observation"
            else:
                objects["0" * 64] = "unreachable"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                expand_shared_json(changed)

    def test_reference_cycles_and_alias_only_nodes_are_rejected(self):
        for value in ({REFERENCE: "a" * 64}, {"next": {REFERENCE: "a" * 64}}):
            packet = {
                "row": {REFERENCE: "a" * 64},
                MARKER: {"version": 1, "objects": {"a" * 64: value}},
            }
            with self.subTest(value=value), self.assertRaises(ValueError):
                expand_shared_json(packet)

    def test_invalid_reference_and_catalog_types_versions_or_identities_are_rejected(
        self,
    ):
        for field, value in (("version", True), ("version", 2), ("objects", [])):
            packet = pack_shared_json(self.payload())
            packet[MARKER][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                expand_shared_json(packet)
        packet = {
            "row": {REFERENCE: {}},
            MARKER: {"version": 1, "objects": {"a" * 64: "source"}},
        }
        with self.assertRaises(ValueError):
            expand_shared_json(packet)

    def test_duplicate_shared_wire_fields_cannot_be_hidden_by_json_last_value_rules(
        self,
    ):
        encoded = compact_json(pack_shared_json(self.payload()))
        changed = encoded.replace('"version":1', '"version":1,"version":1')
        with self.assertRaises(ValueError):
            read_artifact_json(changed)
        self.assertEqual(read_artifact_json('{"legacy":1,"legacy":2}'), {"legacy": 2})

    def test_plain_legacy_json_and_stream_reads_keep_their_original_contract(self):
        self.assertEqual(
            read_artifact_json(io.StringIO('[1,"原文",null]')), [1, "原文", None]
        )
        self.assertTrue(math.isnan(read_artifact_json('{"legacy":NaN}')["legacy"]))
        with self.assertRaises(ValueError):
            read_artifact_json('{"legacy":NaN}', strict_numbers=True)

    def test_input_cycles_nonfinite_values_and_unsupported_keys_are_explicit(self):
        cycle = []
        cycle.append(cycle)
        for payload in (
            {"cycle": cycle},
            {"bad": math.nan},
            {(1,): "not a JSON key"},
            {MARKER: {}},
        ):
            with self.subTest(keys=list(payload)), self.assertRaises(ValueError):
                pack_shared_json(payload)

    def test_legacy_json_key_coercion_is_preserved_but_collisions_are_rejected(self):
        proof = self.payload()["observations"][0]
        source = {7: proof, None: proof, False: proof, 2.5: proof, "original": proof}
        restored = self.roundtrip(source)
        self.assertEqual(restored, read_artifact_json(compact_json(source)))
        self.assertEqual(list(restored), ["7", "null", "false", "2.5", "original"])
        with self.assertRaisesRegex(ValueError, "competing"):
            pack_shared_json({7: "first source", "7": "different source"})

    def test_unique_node_and_shared_object_limits_are_enforced(self):
        with (
            patch("patent_sar_extractor.artifact_nodes.MAX_NODES", 4),
            self.assertRaisesRegex(ValueError, "node count"),
        ):
            pack_shared_json({"a": 1, "b": 2, "c": 3, "d": 4})
        encoded = pack_shared_json(self.payload())
        with patch("patent_sar_extractor.artifact_catalog.MAX_SHARED_OBJECTS", 1):
            with self.assertRaises(ValueError):
                pack_shared_json(self.payload())
            with self.assertRaises(ValueError):
                expand_shared_json(encoded)

    def test_logical_depth_boundary_is_the_same_before_and_after_reference_encoding(
        self,
    ):
        value = "original " * 100
        for _ in range(MAX_DEPTH - 1):
            value = [value]
        for second in (value, copy.deepcopy(value)):
            payload = {"a": value, "b": second}
            with self.subTest(copied=second is not value):
                self.assertEqual(self.roundtrip(payload), payload)
        with self.assertRaises(ValueError):
            pack_shared_json({"a": [value]})

    def test_reused_subtrees_do_not_bypass_their_full_depth_limit(self):
        shared = [["original " * 100]]
        deep = shared
        for _ in range(MAX_DEPTH - 1):
            deep = [deep]
        with self.assertRaisesRegex(ValueError, "bounds"):
            pack_shared_json({"first_shallow": shared, "then_deep": deep})

    def test_exponential_alias_expansion_is_rejected_without_materializing_it(self):
        graph = JsonGraph()
        key = graph.visit("original" * 100)
        objects = {key: "original" * 100}
        for _ in range(24):
            parent = hashlib.sha256(
                compact_json(["array", [key, key]]).encode()
            ).hexdigest()
            objects[parent] = [{REFERENCE: key}, {REFERENCE: key}]
            key = parent
        packet = {"row": {REFERENCE: key}, MARKER: {"version": 1, "objects": objects}}
        with self.assertRaisesRegex(ValueError, "expansion"):
            expand_shared_json(packet)

    def test_repeated_small_values_cannot_bypass_the_expanded_node_bound(self):
        packet = pack_shared_json({"rows": [self.payload()] * 12})
        with (
            patch("patent_sar_extractor.artifact_nodes.MAX_EXPANDED_NODES", 24),
            self.assertRaisesRegex(ValueError, "node expansion"),
        ):
            expand_shared_json(packet)

    def test_atomic_byte_budget_is_utf8_and_never_replaces_the_previous_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "binding.json"
            write_json_atomic(target, {"previous": "unchanged"})
            previous = target.read_bytes()
            with (
                patch("patent_sar_extractor.artifact_io.MAX_ARTIFACT_BYTES", 128),
                self.assertRaisesRegex(ValueError, "byte bound"),
            ):
                write_json_atomic(target, {"original": "原文" * 100}, shared=True)
            self.assertEqual(target.read_bytes(), previous)
            self.assertEqual(list(Path(temporary).glob("*.tmp")), [])

    def test_native_and_safe_web_readers_share_the_same_logical_payload(self):
        payload = self.payload()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json_atomic(root / "proof.json", payload, shared=True)
            self.assertEqual(load_json(root / "proof.json", {}), payload)
            self.assertEqual(SafeFiles(root).json("proof.json"), payload)

    def test_size_preflight_keeps_safe_regular_file_and_content_read_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "source.json"
            path.write_bytes(b'{"original":1}')
            files = SafeFiles(root)
            with patch.object(
                files, "read", side_effect=AssertionError("No content read")
            ):
                self.assertEqual(files.byte_size(path.name), path.stat().st_size)
            (root / "linked.json").symlink_to(path)
            with self.assertRaises(WebError):
                files.byte_size("linked.json")
            with (
                patch("patent_sar_extractor.web.files.MAX_ARTIFACT_BYTES", 4),
                self.assertRaises(WebError) as failure,
            ):
                files.json(path.name, optional=False)
            self.assertEqual(failure.exception.code, "asset_limit")


if __name__ == "__main__":
    unittest.main()
