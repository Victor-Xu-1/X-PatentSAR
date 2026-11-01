"""Bounded native JSON encoding preserves source bytes, limits and uncertainty."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from patent_sar_extractor import artifact_immutable
from patent_sar_extractor.artifact_catalog import pack_shared_json, read_artifact_json
from patent_sar_extractor.artifact_immutable import freeze_json, readonly_container
from patent_sar_extractor.artifact_nodes import compact_json
from patent_sar_extractor.core.composite_source_identity import composite_source_digest
from patent_sar_extractor.core.source_evidence_identity import SourceEvidenceLimit


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value, *, partitions=(), maximum=4096, component_limit=2048):
    return composite_source_digest(
        value,
        set(partitions),
        maximum=maximum,
        component_limit=component_limit,
        label="generated control",
    )


class ImmutableSourceEncodingTests(unittest.TestCase):
    def measured_size(self, value):
        measure = getattr(artifact_immutable, "immutable_json_size", None)
        self.assertTrue(
            callable(measure), "Graph-measured immutable sizes are required"
        )
        return measure(value)

    def packet(self):
        return {
            "状态": 'unresolved\n原文 🧪 "quoted"',
            "z": [None, True, False, 1, 1.0, -0.0, 1e-7],
            "a": {"nested": ["\\", "\t", "é"]},
        }

    def native_calls(self, observer):
        return [
            call for call in observer.call_args_list if call.kwargs.get("_one_shot")
        ]

    def test_measured_components_use_native_encoding_without_changing_the_digest(self):
        source = freeze_json(self.packet())
        expected = hashlib.sha256(canonical(source)).hexdigest()
        original = json.JSONEncoder.iterencode
        with patch.object(
            json.JSONEncoder, "iterencode", autospec=True, side_effect=original
        ) as encode:
            self.assertEqual(digest(source), expected)
        self.assertEqual(
            len(self.native_calls(encode)),
            1,
            "A preflighted immutable component should not repeat Python token encoding",
        )

    def test_graph_measurement_covers_every_nested_container_and_utf8_scalar(self):
        source = freeze_json(self.packet())
        for value in (source, source["z"], source["a"], source["a"]["nested"]):
            with self.subTest(kind=type(value).__name__):
                self.assertEqual(self.measured_size(value), len(canonical(value)))
        self.assertIsNone(self.measured_size({"_json_size": 2}))
        self.assertIsNone(self.measured_size("not a measured container"))

    def test_wire_roundtrip_retains_measurements_but_never_serializes_metadata(self):
        source = freeze_json({"status": "unresolved", "text": "原文 " * 200})
        packet = {"first": source, "second": source}
        wire = compact_json(pack_shared_json(packet))
        restored = read_artifact_json(wire)
        self.assertEqual(restored, packet)
        self.assertNotIn("_json_size", wire)
        # Pinned from the deployed pre-change codec. Repacking a decoded graph
        # was already non-idempotent; source metadata must not change the first
        # wire representation or its values, rather than invent that contract.
        self.assertEqual(
            hashlib.sha256(wire.encode("utf-8")).hexdigest(),
            "2540207ea136219372820e55386c9abdfe42583841c7ee942d5ed0827802cefe",
        )
        for key in ("first", "second"):
            self.assertEqual(
                self.measured_size(restored[key]), len(canonical(restored[key]))
            )
            self.assertEqual(
                digest(restored[key]), hashlib.sha256(canonical(source)).hexdigest()
            )

    def test_plain_and_unmeasured_containers_keep_the_bounded_streaming_path(self):
        for source in (self.packet(), readonly_container("object", {"text": "source"})):
            original = json.JSONEncoder.iterencode
            with (
                self.subTest(kind=type(source).__name__),
                patch.object(
                    json.JSONEncoder, "iterencode", autospec=True, side_effect=original
                ) as encode,
            ):
                self.assertEqual(
                    digest(source), hashlib.sha256(canonical(source)).hexdigest()
                )
                # Ignore the independent expected-byte calculation above.
                self.assertFalse(encode.call_args_list[0].kwargs.get("_one_shot"))
            self.assertIsNone(self.measured_size(source))

    def test_oversized_measured_components_refuse_without_native_allocation(self):
        source = freeze_json({"text": "界" * 400})
        original = json.JSONEncoder.iterencode
        with (
            patch.object(
                json.JSONEncoder, "iterencode", autospec=True, side_effect=original
            ) as encode,
            self.assertRaises(SourceEvidenceLimit),
        ):
            digest(source, maximum=2048, component_limit=64)
        self.assertFalse(self.native_calls(encode))

    def test_partitioned_total_and_component_boundaries_are_unchanged(self):
        source = {
            "parts": [freeze_json({"text": "A" * 40}), freeze_json({"text": "界" * 20})]
        }
        size = len(canonical(source))
        partitions = {(), ("parts",)}
        self.assertEqual(
            digest(source, partitions=partitions, maximum=size, component_limit=80),
            hashlib.sha256(canonical(source)).hexdigest(),
        )
        for maximum, component in ((size - 1, 80), (size, 50)):
            with (
                self.subTest(maximum=maximum, component=component),
                self.assertRaises(SourceEvidenceLimit),
            ):
                digest(
                    source,
                    partitions=partitions,
                    maximum=maximum,
                    component_limit=component,
                )

    def test_mutable_working_copies_are_remeasured_and_keep_independent_values(self):
        source = freeze_json(self.packet())
        mutable = copy.deepcopy(source)
        self.assertIsNone(self.measured_size(mutable))
        before = digest(source)
        mutable["z"].append("changed")
        self.assertNotEqual(digest(mutable), before)
        self.assertEqual(digest(source), before)

    def test_measurement_is_readonly_and_a_changed_internal_measurement_is_not_trusted(
        self,
    ):
        source = freeze_json({"status": "unresolved", "text": "source"})
        with self.assertRaises(TypeError):
            source._json_size = 2
        # Privileged in-process corruption is not a serialized admission flag.
        object.__setattr__(source, "_json_size", 2)
        with self.assertRaisesRegex(ValueError, "size"):
            digest(source)


if __name__ == "__main__":
    unittest.main()
