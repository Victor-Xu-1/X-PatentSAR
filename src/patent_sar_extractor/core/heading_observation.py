"""One bounded native/raster heading observer using the existing text-cell SDK."""

import hashlib

from .cell_ocr_observation import observe_cell
from .heading_source_geometry import MAX_HEADING_HEIGHT, heading_bounds
from .heading_source_proof import heading_observation_status
from .page_ocr_cache import get_ocr_engine
from .source_geometry import SourceTokens, overlaps, source_layout
from .source_observations import source_cell_observation
from .source_section_roles import section_heading
from .table_cells import cell_image


def observe_heading(page, line, original_pdf_sha256, *, layout=None):
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
    status, _ = heading_observation_status(proof)
    raster = layout.raster_bounds is not None and overlaps(layout.raster_bounds, bounds)
    if status != "confirmed" and (raster or not native["text"].strip()):
        engine = get_ocr_engine()
        if engine and engine[0] == "rapidocr":
            for dpi in (400, 600):
                image = cell_image(page, bounds, dpi)
                reading = observe_cell(
                    image,
                    "heading",
                    dpi,
                    engine[1],
                    lambda raw, _kind: raw if section_heading(raw) else "",
                )
                proof["observations"].append(reading.evidence(dpi, bounds))
                proof["rendered_frames"].append(
                    {
                        "dpi": dpi,
                        "shape": list(image.shape),
                        "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                    }
                )
    proof["status"], _ = heading_observation_status(proof)
    return proof
