"""Focused release boundaries and data-only incoming-PR transforms."""

from __future__ import annotations

import json
import unittest

from tools import version_policy as policy


def authority(version="0.1.0"):
    return f'from typing import Final\n__version__: Final = "{version}"\n'


def fixture(version="0.1.0"):
    package = {
        "name": "x-patentsar-frontend",
        "version": version,
        "dependencies": {"safe": "2.0.0"},
    }
    lock = {
        **package,
        "lockfileVersion": 3,
        "packages": {
            "": dict(package),
            "node_modules/safe": {"version": "2.0.0", "integrity": "sha512-proof"},
        },
    }
    return {
        policy.AUTHORITY: authority(version),
        policy.PACKAGE: json.dumps(package, indent=2) + "\n",
        policy.LOCK: json.dumps(lock, indent=2) + "\n",
    }


class ReleaseNumberTests(unittest.TestCase):
    def test_increment_and_both_rollovers(self):
        for old, new in (
            ("0.1.0", "0.1.1"),
            ("0.1.98", "0.1.99"),
            ("0.1.99", "0.2.0"),
            ("0.9.99", "1.0.0"),
            ("1.9.99", "2.0.0"),
            ("9.9.99", "10.0.0"),
        ):
            with self.subTest(old=old):
                self.assertEqual(str(policy.ReleaseNumber.parse(old).next()), new)

    def test_reject_invalid_noncanonical_or_out_of_range_numbers(self):
        for value in (
            None,
            True,
            1,
            "v0.1.0",
            "0.01.1",
            "00.1.0",
            "0.1.100",
            "0.10.0",
            "0.1.-1",
            "0.1.1-beta",
            "0.1.01",
            "0.1.0\n",
            "9" * 33,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.ReleaseNumber.parse(value)

    def test_one_literal_authority_is_required_and_never_executed(self):
        for value in (
            authority() + authority(),
            "__version__: Final = dangerous()\n",
            '__version__ = "0.1.0"\n',
            '__version__: Final = "bad"\n',
            'raise RuntimeError("must not execute")\n' + authority(),
        ):
            if value.startswith("raise"):
                self.assertEqual(str(policy.authority_version(value)), "0.1.0")
            else:
                with self.assertRaises(ValueError):
                    policy.authority_version(value)

    def test_prepare_is_idempotent_and_only_updates_three_version_locations(self):
        files = fixture()
        before = json.loads(files[policy.LOCK])
        changes = policy.prepare_versions(authority(), files)
        self.assertEqual(set(changes), set(policy.VERSION_PATHS))
        final = {**files, **changes}
        self.assertEqual(str(policy.verify_versions(authority(), final)), "0.1.1")
        self.assertEqual(policy.prepare_versions(authority(), final), {})
        after = json.loads(final[policy.LOCK])
        self.assertEqual(
            after["packages"]["node_modules/safe"],
            before["packages"]["node_modules/safe"],
        )
        self.assertEqual(after["dependencies"], before["dependencies"])
        self.assertEqual(files, fixture(), "Incoming source must not be mutated")

    def test_main_advance_requires_exactly_one_next_number(self):
        with self.assertRaises(ValueError):
            policy.verify_versions(authority("0.1.1"), fixture("0.1.1"))
        with self.assertRaises(ValueError):
            policy.prepare_versions(authority(), fixture("1.0.0"))
        with self.assertRaises(ValueError):
            policy.verify_versions(authority(), fixture("0.1.2"))

    def test_foreign_or_duplicate_or_mismatched_metadata_fails(self):
        for path, replacement in (
            (policy.PACKAGE, '{"name":"foreign","version":"0.1.0"}'),
            (
                policy.PACKAGE,
                '{"name":"x-patentsar-frontend","version":"0.1.0","version":"0.1.1"}',
            ),
            (policy.PACKAGE, fixture("0.2.0")[policy.PACKAGE]),
            (
                policy.LOCK,
                '{"name":"x-patentsar-frontend","version":"0.1.0","packages":{}}',
            ),
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                policy.prepare_versions(authority(), {**fixture(), path: replacement})


if __name__ == "__main__":
    unittest.main()
