"""Common worker/Web assertions for actual open and filled original route ink."""

import copy

import fitz


def assert_worker_checkpoint(
    test, *, filled=False, source_setup=None, terminal="S2", unassigned=("S1",)
):
    from test_candidate_stage import CandidateStageControls

    from patent_sar_extractor.artifact_io import load_json

    pdf, _, _, bindings, _ = test.saved_source(
        filled=filled,
        source_setup=source_setup,
        terminal=terminal,
    )
    test.output, test.pdf, test.bindings = test.root, pdf, bindings
    test.metadata_path = test.root / "structures/metadata.json"
    test.bind_path = test.root / "structure_bindings/bindings.json"
    test.invocations = []
    for _ in range(2):
        state = CandidateStageControls.state(test)
        state.n_bound = 1
        CandidateStageControls.execute(test, state)
        test.assertEqual(state.scientific_errors, {})
    test.assertEqual(len(test.invocations), 1)
    test.assertTrue(state.progress.checkpoint_reused)
    observed = load_json(state.smiles_json, {})
    test.assertEqual(
        [(r["cpd_id"], r["structure_id"]) for r in observed["records"]],
        [("Compound 037B", terminal)],
    )
    test.assertEqual(
        [(r["cpd_id"], r["structure_id"]) for r in observed["candidate_records"]],
        [("", identity) for identity in unassigned],
    )


def assert_web_original(
    test, *, filled=False, mutate_source=None, source_setup=None, terminal="S2"
):
    from patent_sar_extractor.core.ocsr.candidate_coverage import (
        candidate_coverage_errors,
    )
    from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
    from patent_sar_extractor.core.source_evidence_identity import proof_id
    from patent_sar_extractor.web.candidate_observations import read_source_observations
    from patent_sar_extractor.web.files import SafeFiles

    pdf, original_sha, metadata, bindings, observations = test.saved_source(
        filled=filled,
        source_setup=source_setup,
        terminal=terminal,
    )
    files = SafeFiles(test.root)
    payloads = {"structures": metadata, "bindings": bindings, "smiles": observations}
    test.assertTrue(read_source_observations(files, payloads, original_sha).errors)
    test.assertEqual(
        read_source_observations(
            files, payloads, original_sha, open_original=lambda: fitz.open(pdf)
        ).errors,
        [],
    )
    changed = copy.deepcopy(bindings)
    for source in changed["compound_catalog"]["entries"]:
        packet = source["original_heading_structure_evidence"]["reaction_source"]
        if mutate_source is not None:
            mutate_source(packet)
        elif filled:
            packet["pages"][0]["filled_heads"][0]["points"][0][0] += 1
        else:
            packet["pages"][0]["segments"][0][0] += 1
        packet["identity"] = proof_id(
            {k: v for k, v in packet.items() if k != "identity"}
        )
    # Pure packet shape validation isn't original source truth. The common
    # normal/final/Web replay must still discover a self-rehashed contradiction.
    test.assertEqual(
        annotate_binding_accuracy(changed["compound_catalog"]["entries"][0])[
            "accuracy_status"
        ],
        "confirmed",
    )
    test.assertTrue(
        candidate_coverage_errors(
            test.root, {"input_pdf": str(pdf)}, metadata, changed, observations
        )
    )
    payloads["bindings"] = changed
    test.assertTrue(
        read_source_observations(
            files, payloads, original_sha, open_original=lambda: fitz.open(pdf)
        ).errors
    )
