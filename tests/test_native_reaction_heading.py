"""Actual vector-arrow direction, not position or model-graph product guesses."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.core.binding_source_headings import (
    observed_heading_blocks,
    select_heading_bindings,
)
from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.source_evidence_identity import proof_id


class NativeReactionHeadingTests(unittest.TestCase):
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

    def arrow(self, tail, tip, *, opposite_head=False):
        dx, dy = tip[0] - tail[0], tip[1] - tail[1]
        length = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / length, dy / length
        self.page.draw_line(tail, tip)
        for x, y, direction in [(tip[0], tip[1], 1)] + (
            [(tail[0], tail[1], -1)] if opposite_head else []
        ):
            self.page.draw_polyline(
                [
                    (x - direction * ux * 7 - uy * 4, y - direction * uy * 7 + ux * 4),
                    (x, y),
                    (x - direction * ux * 7 + uy * 4, y - direction * uy * 7 - ux * 4),
                ]
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

    def test_original_right_arrow_proves_its_product(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.assert_product("S2")

    def test_original_left_arrow_selects_left_product_not_rightmost(self):
        self.pair()
        self.arrow((250, 145), (180, 145))
        self.assert_product("S1")

    def test_original_up_arrow_selects_top_product_not_last(self):
        self.molecule("S1", 100, 95)
        self.molecule("S2", 100, 310)
        self.arrow((142, 285), (142, 210))
        self.assert_product("S1")

    def test_entire_connected_multi_step_route_selects_only_terminal(self):
        self.pair()
        self.molecule("S3", 490, 100)
        self.arrow((180, 145), (250, 145))
        self.arrow((390, 145), (460, 145))
        self.assert_product("S3")

    def test_two_drawings_without_direction_evidence_stay_unassigned(self):
        self.pair()
        self.assertEqual(self.select()[0], [])

    def test_bidirectional_arrow_does_not_have_a_proved_terminal(self):
        self.pair()
        self.arrow((180, 145), (250, 145), opposite_head=True)
        self.assertEqual(self.select()[0], [])

    def test_an_unconnected_candidate_cannot_be_discarded_for_uniqueness(self):
        self.pair()
        self.molecule("S3", 80, 320)
        self.arrow((180, 145), (250, 145))
        self.assertEqual(self.select()[0], [])

    def test_independent_two_terminal_routes_stay_unassigned(self):
        self.pair()
        self.molecule("S3", 70, 320)
        self.molecule("S4", 280, 320)
        self.arrow((180, 145), (250, 145))
        self.arrow((180, 365), (250, 365))
        self.assertEqual(self.select()[0], [])

    def test_altered_saved_arrow_direction_is_not_current_binding_proof(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        binding = self.assert_product("S2")
        changed = copy.deepcopy(binding)
        observation = changed["original_heading_structure_evidence"]["reaction_source"]
        observation["pages"][0]["segments"][0][0] += 10
        self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])

    def test_rehashed_saved_ink_still_requires_the_actual_original(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        binding = self.assert_product("S2")
        self.assertEqual(original_heading_source_errors(self.document, [binding]), [])
        changed = copy.deepcopy(binding)
        observation = changed["original_heading_structure_evidence"]["reaction_source"]
        # A molecule-internal stroke does not alter the geometric route, but it
        # is not the recorded original. A self-computed digest grants no trust.
        observation["pages"][0]["segments"][0][0] += 1
        observation["identity"] = proof_id(
            {k: v for k, v in observation.items() if k != "identity"}
        )
        self.assertTrue(original_heading_source_errors(self.document, [changed]))

    def test_stripping_the_packet_cannot_disable_original_replay(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        changed = self.assert_product("S2")
        del changed["original_heading_structure_evidence"]["reaction_source"]
        self.assertTrue(original_heading_source_errors(self.document, [changed]))
        self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])

    def test_raster_ink_over_the_vector_arrow_cannot_be_ignored(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        pixels = self.page.get_pixmap(clip=fitz.Rect(175, 135, 255, 155))
        self.page.insert_image(
            fitz.Rect(175, 135, 255, 155), stream=pixels.tobytes("png")
        )
        self.assertEqual(self.select()[0], [])

    def test_arrowhead_beyond_the_procedure_boundary_is_not_a_full_route(self):
        self.molecule("S1", 100, 430)
        self.molecule("S2", 350, 530)
        self.arrow((205, 500), (340, 620))
        self.assertEqual(self.select()[0], [])

    def test_drawn_bonds_inside_molecules_are_not_reaction_edges(self):
        self.pair()
        self.arrow((90, 130), (140, 145))
        self.assertEqual(self.select()[0], [])

    def test_conditions_crossing_a_connection_do_not_grant_ownership(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.insert_text((257, 149), "N", fontsize=12)
        self.assertEqual(self.select()[0], [])

    def test_an_invisible_native_heading_cannot_name_a_visible_route(self):
        self.page.add_redact_annot(fitz.Rect(20, 20, 450, 48))
        self.page.apply_redactions()
        self.page.insert_text(
            (35, 40), "Preparation of Compound 037B", fontsize=12, render_mode=3
        )
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.assertEqual(len(self.select()[0]), 0)

    def test_a_white_overpainted_heading_cannot_name_a_route(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.draw_rect(fitz.Rect(20, 20, 450, 48), color=None, fill=(1, 1, 1))
        self.assertEqual(len(self.select()[0]), 0)

    def test_a_crossing_stroke_is_not_ignored_like_an_empty_cell_frame(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.draw_line((170, 35), (210, 35), width=3)
        self.assertEqual(len(self.select()[0]), 0)

    def test_standalone_and_route_share_the_same_visible_heading_gate(self):
        self.molecule("S1", 70, 100)
        self.page.draw_rect(fitz.Rect(20, 20, 450, 48), color=None, fill=(1, 1, 1))
        self.assertEqual(len(self.select()[0]), 0)

    def test_original_replay_checks_literal_heading_not_only_vector_positions(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        binding = self.assert_product("S2")
        self.page.add_redact_annot(fitz.Rect(20, 20, 450, 48))
        self.page.apply_redactions()
        self.page.insert_text((35, 40), "Preparation of Compound 038B", fontsize=12)
        self.assertTrue(original_heading_source_errors(self.document, [binding]))

    def saved_source(self):
        from recognition_source_support import complete_observation_artifact

        from patent_sar_extractor import contracts
        from patent_sar_extractor.artifact_io import write_json_atomic
        from patent_sar_extractor.core.binding_artifacts import write_binding_result
        from patent_sar_extractor.core.structure_inventory import inventory_packet

        self.pair()
        self.arrow((180, 145), (250, 145))
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

    def test_normal_source_plan_and_final_qa_replay_the_original_route(self):
        from patent_sar_extractor.core.ocsr.candidate_coverage import (
            candidate_coverage_errors,
        )

        pdf, _, metadata, bindings, observations = self.saved_source()
        self.assertEqual(
            [r["cpd_id"] for r in observations["records"]], ["Compound 037B"]
        )
        self.assertEqual([r["cpd_id"] for r in observations["candidate_records"]], [""])
        self.assertEqual(
            candidate_coverage_errors(
                self.root, {"input_pdf": str(pdf)}, metadata, bindings, observations
            ),
            [],
        )

    def test_one_normal_worker_keeps_reactant_unassigned_and_resumes_without_inference(
        self,
    ):
        from test_candidate_stage import CandidateStageControls

        from patent_sar_extractor.artifact_io import load_json

        pdf, _, _, bindings, _ = self.saved_source()
        self.output, self.pdf, self.bindings = self.root, pdf, bindings
        self.metadata_path = self.root / "structures/metadata.json"
        self.bind_path = self.root / "structure_bindings/bindings.json"
        self.invocations = []
        for _ in range(2):
            state = CandidateStageControls.state(self)
            state.n_bound = 1
            CandidateStageControls.execute(self, state)
            self.assertEqual(state.scientific_errors, {})
        self.assertEqual(len(self.invocations), 1)
        self.assertTrue(state.progress.checkpoint_reused)
        observed = load_json(state.smiles_json, {})
        self.assertEqual(
            [(r["cpd_id"], r["structure_id"]) for r in observed["records"]],
            [("Compound 037B", "S2")],
        )
        self.assertEqual(
            [(r["cpd_id"], r["structure_id"]) for r in observed["candidate_records"]],
            [("", "S1")],
        )

    def test_web_reader_requires_safe_original_and_rejects_rehashed_foreign_ink(self):
        from patent_sar_extractor.core.ocsr.candidate_coverage import (
            candidate_coverage_errors,
        )
        from patent_sar_extractor.web.candidate_observations import (
            read_source_observations,
        )
        from patent_sar_extractor.web.files import SafeFiles

        pdf, original_sha, metadata, bindings, observations = self.saved_source()
        files = SafeFiles(self.root)
        payloads = {
            "structures": metadata,
            "bindings": bindings,
            "smiles": observations,
        }
        self.assertTrue(read_source_observations(files, payloads, original_sha).errors)
        self.assertEqual(
            read_source_observations(
                files, payloads, original_sha, open_original=lambda: fitz.open(pdf)
            ).errors,
            [],
        )
        changed = copy.deepcopy(bindings)
        for source in [
            *changed["final_bindings"],
            *changed["compound_catalog"]["entries"],
        ]:
            packet = source["original_heading_structure_evidence"]["reaction_source"]
            packet["pages"][0]["segments"][0][0] += 1
            packet["identity"] = proof_id(
                {k: v for k, v in packet.items() if k != "identity"}
            )
        self.assertTrue(
            annotate_binding_accuracy(changed["final_bindings"][0])["accuracy_status"]
            == "confirmed"
        )
        self.assertTrue(
            candidate_coverage_errors(
                self.root, {"input_pdf": str(pdf)}, metadata, changed, observations
            )
        )
        payloads["bindings"] = changed
        self.assertTrue(
            read_source_observations(
                files, payloads, original_sha, open_original=lambda: fitz.open(pdf)
            ).errors
        )


if __name__ == "__main__":
    unittest.main()
