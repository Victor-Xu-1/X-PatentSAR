"""Small original-PDF catalogue controls for Web/recognition consumer tests."""

import json

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.core.structure_inventory import inventory_packet


def original_catalogue(root, run):
    """Produce three real source proofs, not copies with renamed crop IDs."""
    source = root / "catalog-original.pdf"
    records = []
    with fitz.open() as document:
        page = document.new_page()
        for top, title, labels, identities in (
            (
                100,
                "Table 11. Compounds",
                ("1", "8"),
                ("S0", "numbered-without-activity"),
            ),
            (300, "Table 12. Selected compounds", ("1",), ("proved-reprint",)),
        ):
            xs, ys = (
                [50 + 130 * i for i in range(len(labels) + 1)],
                [top, top + 25, top + 105],
            )
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            page.insert_text((50, top - 15), title, fontsize=10)
            for index, (label, identity) in enumerate(
                zip(labels, identities, strict=True)
            ):
                left = 70 + index * 130
                page.insert_text((left, top + 17), f"Compound {label}", fontsize=9)
                bounds = [left + 10, top + 40, left + 70, top + 75]
                page.draw_line((bounds[0], top + 52), (bounds[0] + 30, top + 40))
                page.draw_line((bounds[0] + 30, top + 40), (bounds[2], top + 52))
                image = run / "structures" / (identity + ".png")
                page.get_pixmap(clip=fitz.Rect(bounds), alpha=False).save(image)
                records.append(
                    {
                        "structure_id": identity,
                        "structure_index": len(records),
                        "page_no": 1,
                        "bbox_pdf": bounds,
                        "image_path": str(image),
                    }
                )
        document.save(source)
    metadata = run / "structures" / "metadata.json"
    envelope = json.loads(metadata.read_text())
    envelope.update(
        patent_number="CONTROLLED-CATALOG",
        structures=records,
        total_structures=len(records),
        source_inventory=inventory_packet(
            1,
            [
                {
                    "page_no": 1,
                    "status": "detected",
                    "scope": "full_page",
                    "candidates": len(records),
                }
            ],
        ),
    )
    metadata.write_text(json.dumps(envelope))
    # artifact_run supplied a declared legacy adapter cache for a different test
    # PDF. Preserve it outside the new run; the normal binder must observe this
    # new original itself. Never waive the production source/cache identity gate.
    adapter_cache = run / "page_classification" / "page_ocr_cache.json"
    if adapter_cache.exists():
        adapter_cache.rename(root / "preserved-adapter-page-cache.json")
    bind(
        str(source),
        {"structure_candidate_pages": [0]},
        str(run / "structure_bindings"),
        str(metadata),
    )
    path = run / "structure_bindings" / "bindings.json"
    payload = load_json(path, {})
    if (
        payload["source_issues"]
        or payload["compound_catalog"]["source_observations"] != 3
    ):
        raise AssertionError("Controlled original catalogue did not prove every source")
    from test_uniform_recognition import observation

    from patent_sar_extractor.smiles_artifact import build_smiles_artifact

    # One explicit controlled raw graph is used only by downstream service tests;
    # this is not an OCSR/model or chemical-accuracy claim for these line drawings.
    (run / "smiles" / "smiles_results.json").write_text(
        json.dumps(build_smiles_artifact([observation(payload["final_bindings"][0])]))
    )
    return source, path, payload
