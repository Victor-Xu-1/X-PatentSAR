"""Shared actual native-PDF route fixtures, not chemical-model accuracy proof."""

import hashlib
import tempfile
from pathlib import Path

import fitz

from patent_sar_extractor.core.binding_source_headings import (
    observed_heading_blocks,
    select_heading_bindings,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy


class NativeReactionFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-native-route-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.document.new_page(width=660, height=660)
        self.page = self.document[0]
        self.page.insert_text((35, 40), "Preparation of Compound 037B", fontsize=12)
        self.page.insert_text((35, 610), "Step 1: Preparation", fontsize=11)
        self.structures = []

    def molecule(self, identity, left, top):
        bounds = [left, top, left + 85, top + 90]
        self.page.draw_polyline(
            [
                (left + 15, top + 25),
                (left + 42, top + 8),
                (left + 70, top + 25),
                (left + 70, top + 58),
                (left + 42, top + 75),
                (left + 15, top + 58),
                (left + 15, top + 25),
            ],
            width=1.5,
        )
        image = self.root / f"{identity}.png"
        self.page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(bounds)).save(
            image
        )
        self.structures.append(
            {
                "id": identity,
                "idx": len(self.structures) + 1,
                "page_no": 1,
                "image_path": str(image),
                **dict(zip(("x0", "y0", "x1", "y1"), bounds, strict=True)),
            }
        )

    def arrow(
        self,
        tail,
        tip,
        *,
        opposite_head=False,
        filled=False,
        outline=True,
        stem_inset=0,
        fill_opacity=1,
    ):
        dx, dy = tip[0] - tail[0], tip[1] - tail[1]
        length = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / length, dy / length
        self.page.draw_line(tail, (tip[0] - ux * stem_inset, tip[1] - uy * stem_inset))
        for x, y, direction in [(tip[0], tip[1], 1)] + (
            [(tail[0], tail[1], -1)] if opposite_head else []
        ):
            self.page.draw_polyline(
                [
                    (x - direction * ux * 7 - uy * 4, y - direction * uy * 7 + ux * 4),
                    (x, y),
                    (x - direction * ux * 7 + uy * 4, y - direction * uy * 7 - ux * 4),
                ],
                closePath=filled,
                color=(0, 0, 0) if not filled or outline else None,
                fill=(0, 0, 0) if filled else None,
                fill_opacity=fill_opacity,
            )

    def select(self):
        self.sections = []
        blocks = observed_heading_blocks(
            self.document, [0], {}, source_sections=self.sections
        )
        return select_heading_bindings(
            self.document,
            self.structures,
            blocks,
            {},
            str(self.root / "bindings"),
            {},
            all_structures=self.structures,
            source_sections=self.sections,
        )

    def assert_product(self, identity):
        bindings, issues = self.select()
        self.assertEqual(issues, [])
        self.assertEqual(
            [(b["cpd"], b["structure_id"]) for b in bindings],
            [("Compound 037B", identity)],
        )
        self.assertEqual(
            annotate_binding_accuracy(bindings[0])["accuracy_status"], "confirmed"
        )
        return bindings[0]

    def pair(self):
        self.molecule("S1", 70, 100)
        self.molecule("S2", 280, 100)

    def saved_source(self, *, filled=False, source_transform=None):
        from recognition_source_support import complete_observation_artifact

        from patent_sar_extractor import contracts
        from patent_sar_extractor.artifact_io import write_json_atomic
        from patent_sar_extractor.core.binding_artifacts import write_binding_result
        from patent_sar_extractor.core.structure_inventory import inventory_packet

        self.pair()
        self.arrow((180, 145), (250, 145), filled=filled)
        if source_transform is not None:
            source_transform()
        pdf = self.root / "original.pdf"
        pdf.write_bytes(self.document.tobytes(no_new_id=True))
        original_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        binding = self.assert_product("S2")
        payload = write_binding_result(
            self.root / "structure_bindings",
            patent_id="Synthetic",
            bindings=[binding],
            detected_style="native_original_route",
            include_intermediates=False,
            total_structures=2,
            total_compound_blocks=1,
            table_pages=[],
            table_covered_count=0,
            no_binding=[],
            unbound_pages=[],
            source_sections=self.sections,
            original_pdf_sha256=original_sha,
        )
        self.assertEqual(payload["source_issues"], [])
        metadata = {
            **contracts.artifact_identity(
                contracts.STRUCTURES_SCHEMA, contracts.STRUCTURES_SCHEMA_VERSION
            ),
            "total_structures": 2,
            "structures": [
                {
                    "structure_id": s["id"],
                    "page_no": s["page_no"],
                    "bbox_pdf": [s[k] for k in ("x0", "y0", "x1", "y1")],
                    "image_path": s["image_path"],
                }
                for s in self.structures
            ],
            "source_inventory": inventory_packet(
                1,
                [
                    {
                        "page_no": 1,
                        "status": "detected",
                        "scope": "full_page",
                        "candidates": 2,
                    }
                ],
            ),
        }
        structures = self.root / "structures/metadata.json"
        write_json_atomic(structures, metadata)
        write_json_atomic(
            str(structures) + ".manifest.json",
            {
                **contracts.artifact_identity(
                    contracts.STEP_MANIFEST_SCHEMA,
                    contracts.STEP_MANIFEST_SCHEMA_VERSION,
                ),
                "fingerprint": {
                    "step": "structures",
                    "pdf_sha256": original_sha,
                    "params": {
                        "structure_pages": [0],
                        "structure_worker_contract_version": contracts.STRUCTURE_WORKER_VERSION,
                    },
                },
            },
        )
        observations = complete_observation_artifact(
            payload,
            pdf=pdf,
            structures=structures,
            binding_dir=self.root / "structure_bindings",
        )
        return pdf, original_sha, metadata, payload, observations
