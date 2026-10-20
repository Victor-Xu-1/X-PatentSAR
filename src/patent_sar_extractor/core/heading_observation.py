"""One bounded native/raster heading observer using the existing text-cell SDK."""

from dataclasses import replace

import fitz

from .cell_ocr_observation import observe_cell
from .cell_raster import render_cell_raster
from .heading_cell_source import observe_cell_source
from .heading_source_geometry import MAX_HEADING_HEIGHT, heading_bounds
from .heading_source_proof import heading_observation_status
from .page_ocr_cache import get_ocr_engine
from .source_geometry import SourceTokens, overlaps, source_layout
from .source_observations import source_cell_observation
from .source_section_roles import section_heading


def observe_heading(page, line, original_pdf_sha256, *, layout=None, grids=None):
    bounds = heading_bounds(line["bbox"], [page.rect.width, page.rect.height])
    if bounds.is_empty or bounds.height > MAX_HEADING_HEIGHT:
        raise ValueError("Original heading exceeds its physical source bounds")
    layout = layout if layout is not None else source_layout(page)
    native = source_cell_observation(
        SourceTokens(layout.native, layout), tuple(bounds), native=True
    )
    proof = {
        "version": 1,
        "original_pdf_sha256": original_pdf_sha256,
        "page_no": page.number + 1,
        "page_size": [page.rect.width, page.rect.height],
        "bbox": list(bounds),
        "nomination": {
            "text": line["text"],
            "source": line["source"],
            "bbox": list(line["bbox"]),
            "geometry_space": line.get("geometry_space", "locator"),
            **({"rows": line["heading_rows"]} if "heading_rows" in line else {}),
        },
        "native_source": native,
        "raster_bounds": list(layout.raster_bounds) if layout.raster_bounds else None,
        "observations": [],
        "rendered_frames": [],
    }
    # Resolve the physical source before OCR. Reading an arbitrary locator's
    # padded rectangle first can turn a ruling stroke into a spurious digit.
    # The original native window remains retained, never promoted by geometry.
    proof["status"], _ = heading_observation_status(proof)
    if proof["status"] != "unresolved":
        return proof
    if grids is None:
        from .table_geometry import detect_ruled_table_regions

        grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
    cell_source = observe_cell_source(page, line["bbox"], grids, MAX_HEADING_HEIGHT)
    if cell_source is None:
        _observe_window(page, proof, layout)
        return proof
    candidate = {
        **proof,
        "version": 2,
        "bbox": cell_source["cell"],
        "native_source": source_cell_observation(
            SourceTokens(layout.native, layout), tuple(cell_source["cell"]), native=True
        ),
        "original_heading": proof,
        "cell_source": cell_source,
        "observations": [],
        "rendered_frames": [],
    }
    _observe_window(page, candidate, layout)
    return candidate


def _observe_window(page, proof, layout):
    bounds = fitz.Rect(proof["bbox"])
    native = proof["native_source"]
    status, _ = heading_observation_status(proof)
    raster = layout.raster_bounds is not None and overlaps(layout.raster_bounds, bounds)
    if status != "confirmed" and (raster or not native["text"].strip()):
        engine = get_ocr_engine()
        if engine and engine[0] == "rapidocr":
            for dpi in (400, 600):
                raster = render_cell_raster(page, list(bounds), dpi, purpose="text")
                reading = observe_cell(
                    raster.image,
                    "heading",
                    dpi,
                    engine[1],
                    lambda raw, _kind: raw if section_heading(raw) else "",
                )
                reading = replace(
                    reading,
                    source_frame=raster.frame,
                    source_window=raster.source_window,
                )
                proof["observations"].append(reading.evidence(dpi, bounds))
                proof["rendered_frames"].append(raster.frame)
    proof["status"], _ = heading_observation_status(proof)
    if proof["status"] == "unresolved" and len(proof["observations"]) == 2:
        from .text_ocr.source_capture import refine_source_text

        proof["observations"] = refine_source_text(page, bounds, proof["observations"])
        proof["status"], _ = heading_observation_status(proof)
