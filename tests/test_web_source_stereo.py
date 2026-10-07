"""Presentation retains history without promoting it to fresh source evidence."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from patent_sar_extractor.web.stereochemistry_models import StereoEvidence


class SourceStereoPresentationTests(unittest.TestCase):
    def test_both_declared_epochs_are_readable_without_certification(self):
        for version in (1, 2):
            with self.subTest(version=version):
                model = StereoEvidence(
                    version=version,
                    image_sha256="a" * 64,
                    image_size=[100, 100],
                    unknown_bond_boxes=[],
                    status="no_unknown_detected",
                    reason="Absence of a risk hit is not absolute proof.",
                    assigned_centers=1,
                    unassigned_centers=0,
                    assigned_double_bonds=0,
                    absolute_configuration_verified=False,
                )
                self.assertEqual(model.version, version)
                self.assertFalse(model.absolute_configuration_verified)
                with self.assertRaises(ValidationError):
                    StereoEvidence.model_validate({**model.model_dump(), "version": 3})
                with self.assertRaises(ValidationError):
                    StereoEvidence.model_validate(
                        {
                            **model.model_dump(),
                            "absolute_configuration_verified": True,
                        }
                    )
