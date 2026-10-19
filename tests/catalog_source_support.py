"""Small original-PDF catalogue controls for Web/recognition consumer tests."""

import json
from contextlib import nullcontext
from unittest.mock import patch

import fitz

from patent_sar_extractor.application.stage_cache import (
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.contracts import STRUCTURE_WORKER_VERSION
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.core.structure_inventory import inventory_packet


def original_catalogue(
    root,
    run,
    *,
    labels=("1", "8"),
    identities=("S0", "numbered-without-activity"),
    selected=True,
    source=None,
    molecule=None,
    raster=False,
    token_reader=None,
):
    """Produce original source proofs, not copies with renamed crop IDs."""
    source = source or root / "catalog-original.pdf"
    records = []
    tables = [(100, "Table 11. Compounds", labels, identities)]
    if selected:
        tables.append(
            (300, "Table 12. Selected compounds", (labels[0],), ("proved-reprint",))
        )

    def depict(identity):
        if molecule is None:
            return None
        from io import BytesIO

        from rdkit import Chem
        from rdkit.Chem import Draw

        buffer = BytesIO()
        raw = molecule[identity] if isinstance(molecule, dict) else molecule
        Draw.MolToImage(Chem.MolFromSmiles(raw), size=(300, 150)).save(
            buffer, format="PNG"
        )
        return buffer.getvalue()

    with fitz.open() as document:
        page = document.new_page()
        for top, title, row_labels, row_identities in tables:
            xs, ys = (
                [50 + 130 * i for i in range(len(row_labels) + 1)],
                [top, top + 25, top + 105],
            )
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            page.insert_text((50, top - 15), title, fontsize=10)
            for index, (label, identity) in enumerate(
                zip(row_labels, row_identities, strict=True)
            ):
                left = 70 + index * 130
                page.insert_text((left, top + 17), f"Compound {label}", fontsize=9)
                bounds = [left + 10, top + 40, left + 70, top + 75]
                depiction = depict(identity)
                if depiction is None:
                    page.draw_line((bounds[0], top + 52), (bounds[0] + 30, top + 40))
                    page.draw_line((bounds[0] + 30, top + 40), (bounds[2], top + 52))
                else:
                    page.insert_image(fitz.Rect(bounds), stream=depiction)
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
        if raster:
            pixels = document[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            with fitz.open() as flattened:
                page = flattened.new_page(
                    width=document[0].rect.width, height=document[0].rect.height
                )
                page.insert_image(page.rect, stream=pixels.tobytes("png"))
                flattened.save(source)
        else:
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
    _write_step_manifest(
        str(metadata),
        _step_fingerprint(
            "structures",
            pdf_path=str(source),
            params={
                "structure_pages": [0],
                "structure_worker_contract_version": STRUCTURE_WORKER_VERSION,
            },
        ),
    )
    # artifact_run supplied a declared legacy adapter cache for a different test
    # PDF. Preserve it outside the new run; the normal binder must observe this
    # new original itself. Never waive the production source/cache identity gate.
    adapter_cache = run / "page_classification" / "page_ocr_cache.json"
    if adapter_cache.exists():
        adapter_cache.rename(root / "preserved-adapter-page-cache.json")
    reader = (
        patch(
            "patent_sar_extractor.core.binding_spatial.page_tokens",
            side_effect=token_reader,
        )
        if token_reader
        else nullcontext()
    )
    with reader:
        bind(
            str(source),
            {"structure_candidate_pages": [0]},
            str(run / "structure_bindings"),
            str(metadata),
        )
    path = run / "structure_bindings" / "bindings.json"
    payload = load_json(path, {})
    if payload["source_issues"] or payload["compound_catalog"][
        "source_observations"
    ] != len(records):
        diagnostics = [
            {
                "reason": item.get("reason"),
                "readings": [
                    {
                        k: observation.get(k)
                        for k in ("method", "raw_text", "text", "caption_word_form")
                    }
                    for observation in item.get("proposal", {}).get("observations", [])
                ],
            }
            for item in payload.get("source_role_observations", {}).values()
            if item.get("reason") == "unread_or_conflicting_caption"
        ]
        raise AssertionError(
            "Controlled original catalogue did not prove every source: "
            + json.dumps(diagnostics, ensure_ascii=False)[:6000]
        )
    from recognition_source_support import observation

    from patent_sar_extractor.smiles_artifact import build_smiles_artifact

    # One explicit controlled raw graph is used only by downstream service tests;
    # this is not an OCSR/model or chemical-accuracy claim for these line drawings.
    write_json_atomic(
        run / "smiles" / "smiles_results.json",
        build_smiles_artifact([observation(payload["compound_catalog"]["entries"][0])]),
    )
    return source, path, payload
