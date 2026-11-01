"""Bounded immutable source storage, not source or chemical acceptance."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.artifact_catalog import read_artifact_json
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    COMPOUND_CATALOG_SCHEMA,
    COMPOUND_CATALOG_SCHEMA_VERSION,
    schema_ref,
)
from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.web.attempts import CheckpointCopy, VerifiedCheckpoint
from patent_sar_extractor.web.files import MAX_ARTIFACT_BYTES, SafeFiles


def source_catalog(count, cells=256):
    # Deliberately transport-only. The catalogue adapter is mocked below;
    # these raw cells are NOT a scientifically qualified original proof.
    proof = {
        "bbox": [10, 20, 30, 40],
        "observations": [
            {
                "method": "controlled_source_transport",
                "tokens": [
                    {
                        "text": f"Literal {index}",
                        "bbox": [10, 20, 30, 40],
                        "confidence": 0.99,
                    }
                    for index in range(cells)
                ],
            }
        ],
        "ownership": {},
    }
    rows = [
        {
            "cpd": f"Compound {number}",
            "structure_id": f"controlled-source-{number}",
            "page_no": number,
            "accuracy_status": "review_required",
            "fail_closed": True,
            "exact_caption_evidence": proof,
            "additional_sources": [],
        }
        for number in range(1, count + 1)
    ]
    return {
        "schema": schema_ref(COMPOUND_CATALOG_SCHEMA, COMPOUND_CATALOG_SCHEMA_VERSION),
        "authority": "printed_identifier_and_original_spatial_evidence",
        "entries": rows,
        "numbered_compounds": count,
        "source_observations": count,
    }


def write_control(directory, catalog):
    with patch(
        "patent_sar_extractor.core.binding_artifacts.compound_catalog",
        return_value=catalog,
    ):
        return write_binding_result(
            directory,
            patent_id="CONTROLLED-SOURCE-TRANSPORT",
            bindings=catalog["entries"],
            detected_style="original_cell_caption_heading",
            include_intermediates=False,
            total_structures=len(catalog["entries"]),
            total_compound_blocks=len(catalog["entries"]),
            table_pages=[],
            table_covered_count=0,
            no_binding=[],
            unbound_pages=[],
            original_pdf_sha256="a" * 64,
        )


class BindingSourceGraphTests(unittest.TestCase):
    def test_large_repeated_source_collection_stays_bounded_and_readonly(self):
        catalog = source_catalog(1000)
        original = copy.deepcopy(catalog["entries"][0]["exact_caption_evidence"])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_control(root, catalog)
            path = root / "bindings.json"
            self.assertLessEqual(path.stat().st_size, MAX_ARTIFACT_BYTES)
            restored = SafeFiles(root).json(path.name, optional=False)
        rows = restored["compound_catalog"]["entries"]
        self.assertEqual(len(rows), 1000)
        self.assertIs(
            rows[0]["exact_caption_evidence"], rows[-1]["exact_caption_evidence"]
        )
        self.assertEqual(rows[0]["exact_caption_evidence"], original)
        self.assertEqual(rows[-1]["exact_caption_evidence"], original)
        self.assertEqual(catalog["entries"][0]["exact_caption_evidence"], original)
        self.assertFalse(restored.get("core_accepted", False))
        with self.assertRaises(TypeError):
            rows[0]["exact_caption_evidence"]["observations"][0]["method"] = "changed"
        # Full mutable expansion still has the old node budget. The source view
        # must not silently turn that protection off for deepcopy/export callers.
        with self.assertRaisesRegex(ValueError, "node expansion"):
            copy.deepcopy(restored["compound_catalog"])

    def test_small_source_views_allow_independent_bounded_working_copies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_control(root, source_catalog(2, cells=4))
            restored = SafeFiles(root).json("bindings.json", optional=False)
        rows = restored["compound_catalog"]["entries"]
        with self.assertRaises(TypeError):
            rows[0]["cpd"] = "an unaudited source edit"
        changed = copy.deepcopy(restored)
        changed["compound_catalog"]["entries"][0]["cpd"] = "working copy"
        changed["compound_catalog"]["entries"][0]["exact_caption_evidence"][
            "observations"
        ][0]["tokens"].append({"text": "working copy only"})
        self.assertNotEqual(changed["compound_catalog"]["entries"][0], rows[0])
        self.assertEqual(
            len(rows[1]["exact_caption_evidence"]["observations"][0]["tokens"]), 4
        )
        self.assertEqual(
            len(
                changed["compound_catalog"]["entries"][1]["exact_caption_evidence"][
                    "observations"
                ][0]["tokens"]
            ),
            4,
        )

    def test_ordinary_mutable_alias_bombs_keep_the_existing_node_limit(self):
        value = 0
        for _ in range(22):
            value = [value, value]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ordinary.json"
            write_json_atomic(path, {"previous": "preserved"})
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "node expansion"):
                write_json_atomic(path, {"rows": value}, shared=True)
            self.assertEqual(path.read_bytes(), before)

    def test_large_source_checkpoint_keeps_readonly_sharing_and_literal_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_control(root, source_catalog(1000))
            restored = SafeFiles(root).json("bindings.json", optional=False)
            copy_to = CheckpointCopy(root, root / "next-attempt")
            copy_to.checkpoint(
                VerifiedCheckpoint(
                    "bind",
                    "bindings.json",
                    restored,
                    {"fingerprint": {"params": {}, "dependency_sha256": {}}},
                )
            )
            current = SafeFiles(copy_to.target).json("bindings.json", optional=False)
        self.assertEqual(current, restored)
        entries = current["compound_catalog"]["entries"]
        self.assertIs(
            entries[0]["exact_caption_evidence"], entries[-1]["exact_caption_evidence"]
        )
        with self.assertRaises(TypeError):
            current["compound_catalog"]["entries"][0]["cpd"] = "changed"

    def test_checkpoint_relocates_only_declared_paths_not_original_source_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "structures/source.png"
            image.parent.mkdir()
            image.write_bytes(b"controlled transport asset, not accepted chemistry")
            catalog = source_catalog(2, cells=4)
            proof = catalog["entries"][0]["exact_caption_evidence"]
            proof["observations"][0]["tokens"][0]["text"] = str(image)
            for row in catalog["entries"]:
                row["image_path"] = str(image)
            write_control(root, catalog)
            path = root / "bindings.json"
            original = path.read_bytes()
            restored = SafeFiles(root).json(path.name, optional=False)
            copy_to = CheckpointCopy(root, root / "next-attempt")
            copy_to.checkpoint(
                VerifiedCheckpoint(
                    "bind",
                    path.name,
                    restored,
                    {"fingerprint": {"params": {}, "dependency_sha256": {}}},
                )
            )
            current = SafeFiles(copy_to.target).json(path.name, optional=False)
            row = current["compound_catalog"]["entries"][0]
            copied = Path(row["image_path"])
            self.assertTrue(copied.is_relative_to(copy_to.target))
            self.assertEqual(copied.read_bytes(), image.read_bytes())
            self.assertNotEqual(copied.stat().st_ino, image.stat().st_ino)
            self.assertEqual(
                row["exact_caption_evidence"]["observations"][0]["tokens"][0]["text"],
                str(image),
            )
            self.assertEqual(path.read_bytes(), original)

    def test_source_reference_tampering_or_mutability_downgrade_still_refuses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_control(root, source_catalog(2, cells=4))
            raw = json.loads((root / "bindings.json").read_text())
        self.assertEqual(raw["_shared_json"]["version"], 2)
        for mutation in ("content", "readonly"):
            changed = copy.deepcopy(raw)
            if mutation == "content":
                key = next(iter(changed["_shared_json"]["objects"]))
                changed["_shared_json"]["objects"][key] = {"changed": "source"}
            else:
                self.assertTrue(changed["compound_catalog"].pop("$readonly"))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                read_artifact_json(json.dumps(changed), strict_numbers=True)


if __name__ == "__main__":
    unittest.main()
