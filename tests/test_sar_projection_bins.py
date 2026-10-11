"""Compact current-chart leaves retain the captured wire/validation contract."""

import json
import sys
import unittest
from unittest.mock import Mock

from pydantic import TypeAdapter, ValidationError

from patent_sar_extractor.web.sar.study_models import StudyBin, StudyReport
from patent_sar_extractor.web.sar.study_projection_models import CurrentStudyReport
from patent_sar_extractor.web.sar.study_view_groups import GroupBins


def leaf_type():
    domain = Mock()
    domain.for_members.return_value = {
        "bins": [
            {
                "label": "source grade",
                "kind": "ordinal",
                "observations": 2,
                "molecules": 1,
                "strong": False,
            }
        ]
    }
    return type(GroupBins(domain).for_members(["original-id"])[0])


class ProjectionBinTests(unittest.TestCase):
    def test_full_current_schema_only_changes_internal_component_names(self):
        names = {
            "CurrentStudyReport": "StudyReport",
            "CurrentStudyDistribution": "StudyDistribution",
            "CurrentStudyScaffold": "StudyScaffold",
            "CurrentStudyRegion": "StudyRegionSummary",
            "CurrentStudyFragment": "StudyFragment",
            "CurrentStudyBin": "StudyBin",
        }

        def wire_schema(value):
            if isinstance(value, dict):
                return {
                    names.get(key, key): wire_schema(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [wire_schema(item) for item in value]
            if isinstance(value, str):
                for current, captured in names.items():
                    if value in {current, "#/$defs/" + current}:
                        return value.replace(current, captured)
            return value

        self.assertEqual(
            wire_schema(CurrentStudyReport.model_json_schema()),
            StudyReport.model_json_schema(),
        )

    def test_per_group_leaf_avoids_per_instance_dict_and_field_inventory(self):
        cls = leaf_type()
        value = cls(label="strong", kind="strength", observations=2, molecules=1)
        self.assertFalse(hasattr(value, "__dict__"))
        self.assertFalse(hasattr(value, "__pydantic_fields_set__"))
        captured = StudyBin(
            label="strong", kind="strength", observations=2, molecules=1
        )
        original_size = sum(
            sys.getsizeof(item)
            for item in (
                captured,
                captured.__dict__,
                captured.__pydantic_fields_set__,
            )
        )
        self.assertLess(sys.getsizeof(value), original_size)

    def test_scalar_schema_and_defaults_stay_identical_to_captured_bins(self):
        schema = TypeAdapter(leaf_type()).json_schema()
        expected = StudyBin.model_json_schema()
        schema.pop("title")
        expected.pop("title")
        self.assertEqual(schema, expected)
        body = {
            "label": "unclassified",
            "kind": "unresolved",
            "observations": 0,
            "molecules": 3,
        }
        leaf = leaf_type()(**body)
        self.assertEqual(leaf.model_dump(), StudyBin(**body).model_dump())
        self.assertFalse(leaf.strong)

    def test_json_read_and_nested_dump_preserve_raw_names_and_scalar_values(self):
        cls = leaf_type()
        body = {
            "label": "专利原文 A / <1 nM",
            "kind": "ordinal",
            "observations": 3,
            "molecules": 2,
            "strong": True,
        }
        decoded = TypeAdapter(cls).validate_json(json.dumps(body).encode())
        self.assertEqual(decoded.model_dump(), body)
        self.assertEqual(TypeAdapter(list[cls]).dump_python([decoded]), [body])

    def test_leaf_instances_and_cache_reads_remain_independently_mutable(self):
        domain = Mock()
        domain.for_members.return_value = {
            "bins": [
                {
                    "label": "missing",
                    "kind": "missing",
                    "observations": 0,
                    "molecules": 2,
                }
            ]
        }
        cache = GroupBins(domain)
        first = cache.for_members(["A", "B"])
        first[0].molecules = 99
        first[0].label = "edited view only"
        second = cache.for_members(["B", "A"])
        self.assertEqual(second[0].molecules, 2)
        self.assertEqual(second[0].label, "missing")
        self.assertIsNot(first[0], second[0])
        self.assertEqual(domain.for_members.call_count, 1)

    def test_invalid_and_extra_values_remain_refused_by_constructor_and_json(self):
        cls = leaf_type()
        valid = {
            "label": "strong",
            "kind": "strength",
            "observations": 2,
            "molecules": 1,
            "strong": True,
        }
        for field, invalid in (
            ("label", None),
            ("kind", []),
            ("observations", float("nan")),
            ("observations", float("inf")),
            ("molecules", 1.25),
            ("molecules", "not a count"),
            ("strong", []),
            ("unexpected", 0),
        ):
            body = {**valid, field: invalid}
            with self.subTest(field=field, invalid=invalid):
                with self.assertRaises(ValidationError):
                    StudyBin(**body)
                with self.assertRaises(ValidationError):
                    cls(**body)
                with self.assertRaises(ValidationError):
                    TypeAdapter(cls).validate_json(json.dumps(body).encode())


if __name__ == "__main__":
    unittest.main()
