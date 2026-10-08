"""Real-RDKit proof/refusal fixtures for the independent SAR core only."""

from __future__ import annotations

import hashlib
import itertools
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from rdkit import Chem

from patent_sar_extractor.core.sar.chemistry import prepare_structure
from patent_sar_extractor.core.sar.drawing import draw_structure
from patent_sar_extractor.core.sar.limits import MAX_MOLFILE_BYTES
from patent_sar_extractor.core.sar.matching import compare_structure, validate_region
from patent_sar_extractor.web.sar.models import Molecule, MoleculeDrawing


def prepared(smiles):
    result = prepare_structure(smiles)
    if not result["eligible"]:
        raise AssertionError(result["issues"])
    return result["molfile"]


class PreparationTests(unittest.TestCase):
    def test_raw_smiles_and_atom_order_are_immutable(self):
        raw = "OC(=O)[C@@H](N)C.[Na+]"
        result = prepare_structure(raw)
        self.assertTrue(result["eligible"], result["issues"])
        self.assertEqual(result["smiles"], raw)
        self.assertEqual(
            result["graph_sha256"],
            hashlib.sha256(result["molfile"].encode()).hexdigest(),
        )
        mol = Chem.MolFromMolBlock(result["molfile"], removeHs=False)
        self.assertEqual(
            [a.GetSymbol() for a in mol.GetAtoms()],
            ["O", "C", "O", "C", "N", "C", "Na"],
        )
        self.assertEqual(prepare_structure(raw), result)

    def test_chemical_identity_is_not_the_drawing_identity(self):
        first = prepare_structure("CCO.[Na+]")
        second = prepare_structure("[Na+].OCC")
        self.assertTrue(first["eligible"] and second["eligible"])
        self.assertEqual(first["chemical_sha256"], second["chemical_sha256"])
        self.assertNotEqual(first["graph_sha256"], second["graph_sha256"])
        for changed in (
            "CCO",
            "[13CH3]CO.[Na+]",
            "CC[O-].[Na+]",
            "CC=O.[Na+]",
            "CCO.[Na+].[Na+]",
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(
                    first["chemical_sha256"],
                    prepare_structure(changed)["chemical_sha256"],
                )

    def test_missing_query_and_unsupported_are_not_chemical_identities(self):
        for raw in (
            None,
            "",
            "C*",
            "[C,N]",
            "CC name",
            "C |a:0|",
            "[Pt@SP1](Cl)(Br)(F)I",
        ):
            with self.subTest(raw=raw):
                result = prepare_structure(raw)
                self.assertFalse(result["eligible"])
                self.assertIsNone(result["chemical_sha256"])
                self.assertEqual(result["smiles"], raw)
                self.assertTrue(
                    all(code.replace("_", "").isalnum() for code in result["issues"])
                )

    def test_drawing_coordinates_use_persisted_indices(self):
        block = prepared("N[C@@H](C)C(=O)O.[Cl-]")
        result = draw_structure(block)
        self.assertIn("<svg", result["svg"])
        self.assertTrue(result["svg"].endswith("</svg>"))
        self.assertEqual([a["index"] for a in result["atoms"]], list(range(7)))
        self.assertEqual(
            [a["element"] for a in result["atoms"]],
            ["N", "C", "C", "C", "O", "O", "Cl"],
        )
        for atom in result["atoms"]:
            self.assertTrue(0 <= atom["x"] <= 1 and 0 <= atom["y"] <= 1)
        self.assertEqual(draw_structure(block), result)
        self.assertEqual(
            ET.fromstring(result["svg"]).tag, "{http://www.w3.org/2000/svg}svg"
        )

    def test_molfile_cannot_silently_discard_a_stereo_annotation(self):
        mol = Chem.MolFromSmiles("CC")
        block = Chem.MolToMolBlock(mol).replace("  1  2  1  0", "  1  2  1  1")
        result = prepare_structure("CC", block)
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["chemical_sha256"])
        v3000 = Chem.MolToMolBlock(mol, forceV3000=True).replace(
            "M  V30 1 1 1 2", "M  V30 1 1 1 2 CFG=1"
        )
        self.assertFalse(prepare_structure("CC", v3000)["eligible"])
        self.assertFalse(
            prepare_structure("CC", Chem.MolToMolBlock(mol).replace("2D", "3D"))[
                "eligible"
            ]
        )

    def test_canonical_identity_includes_stereo_and_tautomer(self):
        for left, right in (
            ("F[C@](Cl)(Br)I", "F[C@@](Cl)(Br)I"),
            ("FC(Cl)(Br)I", "F[C@](Cl)(Br)I"),
            ("F/C=C/F", "F/C=C\\F"),
            ("FC=CF", "F/C=C/F"),
            ("CC(=O)C", "CC(O)=C"),
            ("[2H]OC", "CO"),
        ):
            with self.subTest(left=left, right=right):
                self.assertNotEqual(
                    prepare_structure(left)["chemical_sha256"],
                    prepare_structure(right)["chemical_sha256"],
                )
        self.assertEqual(
            prepare_structure("[H]OC")["chemical_sha256"],
            prepare_structure("CO")["chemical_sha256"],
        )

    def test_supplied_molfile_is_byte_exact_and_chemical_mismatch_refuses(self):
        original = prepared("OC(=O)[C@@H](N)C")
        changed = "untrusted <script>title</script>" + original
        result = prepare_structure("C[C@H](N)C(=O)O", changed)
        self.assertTrue(result["eligible"], result["issues"])
        self.assertEqual(result["molfile"], changed)
        self.assertNotIn("<script>", draw_structure(changed)["svg"])
        self.assertEqual(
            result["graph_sha256"], hashlib.sha256(changed.encode()).hexdigest()
        )
        self.assertEqual(
            result["chemical_sha256"],
            prepare_structure("OC(=O)[C@@H](N)C")["chemical_sha256"],
        )
        mismatch = prepare_structure("CCC", original)
        self.assertFalse(mismatch["eligible"])
        self.assertIn("smiles_molfile_mismatch", mismatch["issues"])
        self.assertIsNone(mismatch["chemical_sha256"])
        crlf = original.replace("\n", "\r\n")
        result = prepare_structure("OC(=O)[C@@H](N)C", crlf)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["molfile"], crlf)
        self.assertEqual(
            result["chemical_sha256"],
            prepare_structure("OC(=O)[C@@H](N)C")["chemical_sha256"],
        )
        self.assertNotEqual(
            result["graph_sha256"],
            prepare_structure("OC(=O)[C@@H](N)C")["graph_sha256"],
        )

    def test_independent_smiles_and_atom_budgets(self):
        self.assertTrue(prepare_structure("[13CH2]" * 300)["eligible"])
        self.assertTrue(prepare_structure("C" * 512)["eligible"])
        for raw, code in (
            ("C" * 513, "structure_limit_exceeded"),
            ("C" * 8193, "smiles_limit_exceeded"),
        ):
            with self.subTest(code=code):
                result = prepare_structure(raw)
                self.assertFalse(result["eligible"])
                self.assertIn(code, result["issues"])

    def test_v3000_and_explicit_unsupported_mdl(self):
        for raw in ("F[C@](Cl)(Br)I", "FC=CF", "F/C=C/F"):
            block = Chem.MolToMolBlock(Chem.MolFromSmiles(raw), forceV3000=True)
            result = prepare_structure(raw, block)
            self.assertTrue(result["eligible"], result["issues"])
            self.assertEqual(result["molfile"], block)
        simple = Chem.MolToMolBlock(Chem.MolFromSmiles("CC"))
        query = Chem.MolToMolBlock(Chem.MolFromSmarts("[#6]~[#6]"))
        for block in (
            simple.replace("  1  2  1  0", "  1  2  1  4"),
            simple + "$$$$\n",
            simple + simple,
            "X" * MAX_MOLFILE_BYTES + simple,
            query,
        ):
            with self.subTest(prefix=block[:15]):
                result = prepare_structure("CC", block)
                self.assertFalse(result["eligible"])
                self.assertIsNone(result["chemical_sha256"])
        enhanced = Chem.MolToMolBlock(
            Chem.MolFromSmiles("F[C@](Cl)(Br)I"), forceV3000=True
        )
        enhanced = enhanced.replace(
            "M  V30 END CTAB",
            "M  V30 BEGIN COLLECTION\nM  V30 MDLV30/STEREL1 ATOMS=(1 2)\nM  V30 END COLLECTION\nM  V30 END CTAB",
        )
        self.assertIn(
            "unsupported_mdl_stereo",
            prepare_structure("F[C@](Cl)(Br)I", enhanced)["issues"],
        )

    def test_invalid_valence_unpaired_direction_and_chiral_assertion(self):
        for raw in ("C(F)(F)(F)(F)F", "C/C", "C[C@H](C)O", "[CH3:1]O"):
            with self.subTest(raw=raw):
                self.assertFalse(prepare_structure(raw)["eligible"])

    def test_shared_molecule_drawing_shape_excludes_internal_identity(self):
        result = prepare_structure("N[C@@H](F)CC")
        public = {
            key: value for key, value in result.items() if key != "chemical_sha256"
        }
        molecule = Molecule(id="molecule", label="molecule", **public)
        drawing = MoleculeDrawing(molecule=molecule, **draw_structure(molecule.molfile))
        self.assertEqual(len(drawing.atoms), 5)
        self.assertNotIn("chemical_sha256", molecule.model_dump())
        self.assertEqual([atom.index for atom in drawing.atoms], list(range(5)))

    def test_standalone_drawing_and_selection_reject_invalid_raw_molfile(self):
        for function in (draw_structure, lambda block: validate_region(block, [0])):
            with self.assertRaisesRegex(ValueError, "^invalid_molfile$"):
                function("untrusted <script> structure")

    def test_private_parser_input_is_not_printed_to_native_stderr(self):
        code = """from rdkit import Chem
from patent_sar_extractor.core.sar.chemistry import prepare_structure
raw = "C_PRIVATE_STRUCTURE_SENTINEL" * 100
result = prepare_structure(raw)
assert not result["eligible"]
block = Chem.MolToMolBlock(Chem.MolFromSmiles("CO"))
block = "PRIVATE_STRUCTURE_SENTINEL" + block
block = block.replace("  1  2  1  0", "  1 99  1  0")
result = prepare_structure("CO", block)
assert not result["eligible"]
print("safe_parser_errors")
"""
        child = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertNotIn("PRIVATE_STRUCTURE_SENTINEL", child.stdout + child.stderr)
        self.assertEqual(child.stderr, "")

    def test_controller_repeat_id_identity_fixture(self):
        first, second = prepare_structure("CCO"), prepare_structure("OCC")
        self.assertTrue(first["eligible"] and second["eligible"])
        self.assertEqual(first["chemical_sha256"], second["chemical_sha256"])
        self.assertNotEqual(first["graph_sha256"], second["graph_sha256"])


class RegionTests(unittest.TestCase):
    def test_one_and_two_ended_regions(self):
        self.assertEqual(validate_region(prepared("COc1ncccc1"), [0]), 1)
        self.assertEqual(
            validate_region(prepared("n1ccccc1COCc1ccccc1F"), [6, 7, 8]), 2
        )

    def test_invalid_regions_fail_closed(self):
        block = prepared("COCC.[Na+]")
        for indices in ([], [0, 0], [True], [-1], [99], [0, 2], [4], [0, 1, 2, 3, 4]):
            with self.subTest(indices=indices), self.assertRaises(ValueError):
                validate_region(block, indices)


class MatchingTests(unittest.TestCase):
    def compare(self, reference, candidate, indices):
        return compare_structure(prepared(reference), prepared(candidate), indices)

    def test_terminal_substituent_and_two_ended_linker(self):
        self.assertEqual(
            self.compare("COc1ncccc1", "CCOc1ncccc1", [0])["match_status"], "matched"
        )
        self.assertEqual(
            self.compare("n1ccccc1COCc1ccccc1F", "n1ccccc1CCOCc1ccccc1F", [6, 7, 8])[
                "match_status"
            ],
            "matched",
        )

    def test_controller_cpu_worker_terminal_fixture(self):
        reference = "COc1ccc(Cl)cc1"
        self.assertEqual(validate_region(prepared(reference), [0]), 1)
        self.assertEqual(
            self.compare(reference, "CCOc1ccc(Cl)cc1", [0])["match_status"], "matched"
        )
        self.assertEqual(
            self.compare(reference, "CCOc1ccc(Br)cc1", [0])["match_status"],
            "not_matched",
        )

    def test_optional_compiled_reference_reuses_one_safe_reference_parse(self):
        from patent_sar_extractor.core.sar import matching

        reference = prepared("COc1ccc(Cl)cc1")
        positive, negative = prepared("CCOc1ccc(Cl)cc1"), prepared("CCOc1ccc(Br)cc1")
        indices = [0]
        with patch.object(
            matching, "read_molfile", wraps=matching.read_molfile
        ) as parser:
            matcher = matching.compile_reference(reference, indices)
            indices.append(1)
            self.assertEqual(matcher.compare(positive)["match_status"], "matched")
            self.assertEqual(matcher.compare(negative)["match_status"], "not_matched")
            self.assertEqual(matcher.compare(positive)["match_status"], "matched")
        self.assertEqual(
            [call.args[0] for call in parser.call_args_list].count(reference), 1
        )
        self.assertEqual(
            matcher.compare(positive),
            matching.compare_structure(reference, positive, [0]),
        )
        with self.assertRaisesRegex(ValueError, "^invalid_molfile$"):
            matching.compile_reference("private unsupported input", [0])

    def test_fixed_graph_isotope_charge_or_extra_salt_cannot_match(self):
        for candidate in (
            "CCOc1ccccc1",
            "CCO[13c]1ncccc1",
            "CCOc1[nH+]cccc1",
            "CCOc1ncccc1.[Na+]",
        ):
            with self.subTest(candidate=candidate):
                self.assertEqual(
                    self.compare("COc1ncccc1", candidate, [0])["match_status"],
                    "not_matched",
                )

    def test_boundary_tetrahedral_parity_not_unqualified_cip(self):
        self.assertEqual(
            self.compare("F[C@](Cl)(Br)I", "F[C@](Cl)(Br)C", [4])["match_status"],
            "matched",
        )
        self.assertEqual(
            self.compare("F[C@](Cl)(Br)I", "F[C@@](Cl)(Br)C", [4])["match_status"],
            "not_matched",
        )
        self.assertEqual(
            self.compare("FC(Cl)(Br)I", "F[C@](Cl)(Br)C", [4])["match_status"],
            "not_matched",
        )

    def test_multiple_region_interpretations_are_ambiguous(self):
        result = self.compare("CC", "CCC", [0])
        self.assertEqual(result["match_status"], "ambiguous")
        self.assertIn("ambiguous_region_mapping", result["reasons"])

    def test_ring_symmetry_is_harmless_only_for_the_same_region_and_anchor(self):
        self.assertEqual(
            self.compare("Cc1ccccc1", "Oc1ccccc1", [0])["match_status"], "matched"
        )
        self.assertEqual(
            self.compare("NCOC", "NCCOC", [1, 2])["match_status"], "matched"
        )
        self.assertEqual(
            self.compare("NOC", "NOOC", [1])["match_status"], "not_matched"
        )

    def test_preserved_salts_and_lost_or_changed_salts(self):
        reference = "COc1ncccc1.[Na+]"
        self.assertEqual(
            self.compare(reference, "CCOc1ncccc1.[Na+]", [0])["match_status"], "matched"
        )
        for candidate in ("CCOc1ncccc1", "CCOc1ncccc1.[K+]", "CCOc1ncccc1.[Na+].[Na+]"):
            with self.subTest(candidate=candidate):
                self.assertEqual(
                    self.compare(reference, candidate, [0])["match_status"],
                    "not_matched",
                )

    def test_fixed_stereo_away_from_boundary_and_virtual_h_at_boundary(self):
        reference = "N[C@@H](C)C(=O)O"
        self.assertEqual(
            self.compare(reference, "N[C@@H](C)C(=O)OC", [5])["match_status"], "matched"
        )
        for candidate in ("N[C@H](C)C(=O)OC", "NC(C)C(=O)OC"):
            self.assertEqual(
                self.compare(reference, candidate, [5])["match_status"], "not_matched"
            )
        self.assertEqual(
            self.compare("N[C@@H](F)CC", "N[C@@H](F)CO", [3, 4])["match_status"],
            "matched",
        )
        self.assertEqual(
            self.compare("N[C@@H](F)CC", "N[C@H](F)CO", [3, 4])["match_status"],
            "not_matched",
        )

    def test_all_atom_permutations_preserve_mapping_parity_not_raw_tags(self):
        reference = prepared("F[C@](Cl)(Br)I")
        candidate = Chem.MolFromSmiles("F[C@](Cl)(Br)C")
        for order in itertools.permutations(range(5)):
            with self.subTest(order=order):
                mol = Chem.RenumberAtoms(candidate, list(order))
                self.assertEqual(
                    compare_structure(reference, Chem.MolToMolBlock(mol), [4])[
                        "match_status"
                    ],
                    "matched",
                )
                # Reparse a noncanonical SMILES too: this changes neighbor/bond
                # insertion order, not merely atom numbers in an existing Mol.
                reparsed = prepared(Chem.MolToSmiles(mol, canonical=False))
                self.assertEqual(
                    compare_structure(reference, reparsed, [4])["match_status"],
                    "matched",
                )
                mol.GetAtomWithIdx(order.index(1)).InvertChirality()
                self.assertEqual(
                    compare_structure(reference, Chem.MolToMolBlock(mol), [4])[
                        "match_status"
                    ],
                    "not_matched",
                )

    def test_virtual_h_parity_after_reparsing_all_atom_permutations(self):
        reference = prepared("N[C@@H](F)CC")
        candidate = Chem.MolFromSmiles("N[C@@H](F)CO")
        for order in itertools.permutations(range(5)):
            with self.subTest(order=order):
                mol = Chem.RenumberAtoms(candidate, list(order))
                block = prepared(Chem.MolToSmiles(mol, canonical=False))
                self.assertEqual(
                    compare_structure(reference, block, [3, 4])["match_status"],
                    "matched",
                )
                mol.GetAtomWithIdx(order.index(1)).InvertChirality()
                block = prepared(Chem.MolToSmiles(mol, canonical=False))
                self.assertEqual(
                    compare_structure(reference, block, [3, 4])["match_status"],
                    "not_matched",
                )

    def test_fixed_reference_atom_order_and_selection_move_together(self):
        reference = Chem.MolFromSmiles("N[C@@H](F)CC")
        candidate = prepared("N[C@@H](F)CO")
        for order in ([4, 3, 2, 1, 0], [1, 0, 4, 3, 2]):
            mol = Chem.RenumberAtoms(reference, order)
            indices = [order.index(3), order.index(4)]
            self.assertEqual(
                compare_structure(Chem.MolToMolBlock(mol), candidate, indices)[
                    "match_status"
                ],
                "matched",
            )

    def test_extra_unmapped_branch_is_not_a_connected_variable_region(self):
        result = self.compare("NC1CCOC1", "NC(C)CCO", [2, 3, 4, 5])
        self.assertEqual(result["match_status"], "not_matched")
        self.assertIn("candidate_variable_disconnected", result["reasons"])

    def test_fixed_linker_end_or_attachment_bond_change_is_refused(self):
        self.assertEqual(
            self.compare("n1ccccc1COCc1ccccc1F", "n1ccccc1CCOCc1ccccc1Cl", [6, 7, 8])[
                "match_status"
            ],
            "not_matched",
        )
        self.assertEqual(self.compare("CN", "C=O", [1])["match_status"], "not_matched")

    def test_double_bond_carrier_transport_including_priority_flip(self):
        reference, candidate = "Cl/C(F)=C(/Br)I", "C/C(F)=C(/Br)I"
        left, right = Chem.MolFromSmiles(reference), Chem.MolFromSmiles(candidate)
        self.assertNotEqual(
            left.GetBondWithIdx(2).GetStereo(), right.GetBondWithIdx(2).GetStereo()
        )
        self.assertEqual(
            self.compare(reference, candidate, [0])["match_status"], "matched"
        )
        self.assertEqual(
            self.compare(reference, "C/C(F)=C(\\Br)I", [0])["match_status"],
            "not_matched",
        )
        self.assertEqual(
            self.compare("ClC(F)=C(Br)I", candidate, [0])["match_status"], "not_matched"
        )
        self.assertEqual(
            self.compare("ClC(F)=C(Br)I", "CC(F)=C(Br)I", [0])["match_status"],
            "matched",
        )
        for order in ([5, 4, 3, 2, 1, 0], [2, 1, 0, 5, 4, 3]):
            reordered = Chem.RenumberAtoms(right, order)
            self.assertEqual(
                compare_structure(
                    prepared(reference), Chem.MolToMolBlock(reordered), [0]
                )["match_status"],
                "matched",
            )

    def test_unsupported_boundary_stereo_is_not_a_false_match(self):
        result = self.compare("N/C=C/F", "N/C=C/Cl", [0, 1])
        self.assertEqual(result["match_status"], "ineligible")
        self.assertIn("unsupported_boundary_bond_stereo", result["reasons"])
        result = self.compare("F[C@]1(Cl)CCCO1", "F[C@]1(Cl)CCCCO1", [3, 4, 5, 6])
        self.assertEqual(result["match_status"], "ineligible")

    def test_mapping_and_search_budgets_are_explicit_ambiguity(self):
        reference, candidate = (
            prepared("CC" + ".[He]" * 6),
            prepared("CCC" + ".[He]" * 6),
        )
        result = compare_structure(reference, candidate, [0])
        self.assertEqual(result["match_status"], "ambiguous")
        self.assertIn("mapping_limit_exceeded", result["reasons"])
        with patch("patent_sar_extractor.core.sar.graphs.MAX_SEARCH_STATES", 1):
            result = self.compare("COc1ncccc1", "CCOc1ncccc1", [0])
        self.assertEqual(result["match_status"], "ambiguous")
        self.assertIn("mapping_search_limit_exceeded", result["reasons"])

    def test_long_exact_linker_mapping_is_bounded_and_useful(self):
        self.assertEqual(
            self.compare("N" + "C" * 300 + "F", "N" + "C" * 300 + "Cl", [301])[
                "match_status"
            ],
            "matched",
        )

    def test_invalid_inputs_and_region_do_not_expose_raw_chemistry(self):
        block = prepared("CO")
        for ref, candidate, indices in (
            ("raw <script> secret", block, [0]),
            (block, "raw <script> secret", [0]),
            (block, block, [0, 1]),
        ):
            result = compare_structure(ref, candidate, indices)
            self.assertEqual(result["match_status"], "ineligible")
            self.assertTrue(
                all(code.replace("_", "").isalnum() for code in result["reasons"])
            )


if __name__ == "__main__":
    unittest.main()
