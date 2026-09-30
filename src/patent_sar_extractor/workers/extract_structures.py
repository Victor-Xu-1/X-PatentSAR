#!/usr/bin/env python3
"""
Extract chemical structures from patent PDF using DECIMER Image Segmentation.
Generates metadata.json for the structure binder.

Usage:
    python extract_structures.py --pdf PATH --output DIR --pages 0 1 2 3
"""

import os

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import fitz
import numpy as np

PACKAGE_IMPORT_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_IMPORT_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_IMPORT_ROOT))

from patent_sar_extractor.contracts import STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION, artifact_identity
from patent_sar_extractor.artifact_io import write_json_atomic

logger = logging.getLogger("patent_sar_extractor.structure_extraction")


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


# DECIMER uses TensorFlow. Keep structure extraction CPU-stable unless the
# pipeline explicitly marks the local TensorFlow/GPU pair as compatible.
if not _truthy(os.environ.get("PATENTSAR_DECIMER_ENABLE_GPU")):
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TF_CPP_MIN_VLOG_LEVEL", "3")
    os.environ.setdefault("ABSL_LOGGING_MIN_LOG_LEVEL", "3")

# Fix numpy 2.x compatibility for DECIMER
if not hasattr(np, 'VisibleDeprecationWarning'):
    np.VisibleDeprecationWarning = FutureWarning

try:
    # Some DECIMER builds decorate package functions with numba cache=True.
    # In this WSL plugin install numba cannot locate that package cache, so
    # force cache=False before importing DECIMER.
    import numba

    _numba_jit = numba.jit

    def _jit_no_cache(*jit_args, **jit_kwargs):
        jit_kwargs["cache"] = False
        return _numba_jit(*jit_args, **jit_kwargs)

    numba.jit = _jit_no_cache
except Exception as exc:
    logger.debug("Optional numba cache patch was not applied: %s", exc)

try:
    from decimer_segmentation import get_model, segment_chemical_structures
    DECIMER_AVAILABLE = True
except ImportError:
    DECIMER_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _load_crop_regions(crop_regions_path: str) -> dict:
    if not crop_regions_path:
        return {}
    try:
        with open(crop_regions_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load crop regions {crop_regions_path}: {e}")
        return {}


def _resolve_crop_pixels(crop: dict, page, dpi: int, img_width: int, img_height: int) -> tuple[int, int, int, int]:
    if not crop:
        return 0, 0, img_width, img_height

    x0 = crop.get("x0", 0) or 0
    y0 = crop.get("y0", 0) or 0
    x1 = crop.get("x1", img_width) or img_width
    y1 = crop.get("y1", img_height) or img_height

    if crop.get("source") == "activity_led_locator":
        scale = dpi / 72.0
        x0 = int(float(x0) * scale)
        y0 = int(float(y0) * scale)
        x1 = int(float(x1) * scale)
        y1 = int(float(y1) * scale)
    else:
        x0 = int(x0)
        y0 = int(y0)
        x1 = int(x1)
        y1 = int(y1)

    x0 = max(0, min(x0, img_width - 1))
    y0 = max(0, min(y0, img_height - 1))
    x1 = max(x0 + 1, min(x1, img_width))
    y1 = max(y0 + 1, min(y1, img_height))
    return x0, y0, x1, y1


def extract_structures_from_pdf(
    pdf_path: str,
    target_pages: list[int],
    output_dir: str,
    crop_regions_path: str = "",
) -> dict:
    """Extract chemical structures from specified pages of a PDF."""
    os.makedirs(output_dir, exist_ok=True)
    crop_regions = _load_crop_regions(crop_regions_path)

    doc = fitz.open(pdf_path)
    structures = []
    idx = 0
    failed_pages: list[tuple[int, str]] = []

    # Extract patent number from filename
    patent_id = Path(pdf_path).stem
    m = re.search(r"(WO\d{6,}|CN\d+)", patent_id)
    if m:
        patent_id = m.group(1)

    if DECIMER_AVAILABLE:
        logger.info(f"Using DECIMER segmentation for {len(target_pages)} pages")
        try:
            # Load and validate the model once.  Repeating a failed lazy load
            # for every page turns one environment error into hours of empty
            # chunks that still exit successfully.
            get_model()
        except Exception as exc:
            raise RuntimeError(f"DECIMER model initialization failed: {exc}") from exc
        for page_num in target_pages:
            if page_num >= doc.page_count:
                continue
            # Render page as image at 150dpi
            page = doc[page_num]
            dpi = 150
            mat = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat)
            img_path = os.path.join(output_dir, f"page_{page_num+1:03d}.png")
            pix.save(img_path)

            try:
                from PIL import Image
                img = Image.open(img_path).convert("RGB")
                crop = crop_regions.get(str(page_num), crop_regions.get(str(page_num + 1), {}))
                crop_x0, crop_y0, crop_x1, crop_y1 = _resolve_crop_pixels(crop, page, dpi, img.width, img.height)
                if crop_x0 or crop_y0 or crop_x1 != img.width or crop_y1 != img.height:
                    img = img.crop((crop_x0, crop_y0, crop_x1, crop_y1))
                    img_path = os.path.join(output_dir, f"page_{page_num+1:03d}_synthesis_crop.png")
                    img.save(img_path)
                    logger.info(f"  Page {page_num+1}: crop ({crop_x0},{crop_y0})-({crop_x1},{crop_y1})")
                segments, bboxes = segment_chemical_structures(
                    np.array(img),
                    return_bboxes=True,
                )
                logger.info(f"  Page {page_num+1}: found {len(segments)} structures")

                for box_idx, (y0, x0, y1, x1) in enumerate(bboxes):
                    x0_abs = x0 + crop_x0
                    y0_abs = y0 + crop_y0
                    x1_abs = x1 + crop_x0
                    y1_abs = y1 + crop_y0
                    # Convert bbox from image coords back to PDF coords
                    scale = 72 / 150  # reverse the 150dpi scaling
                    pdf_x0 = x0_abs * scale
                    pdf_y0 = y0_abs * scale
                    pdf_x1 = x1_abs * scale
                    pdf_y1 = y1_abs * scale

                    # Crop and save structure image
                    struct_img_path = os.path.join(output_dir, f"structure_{idx:04d}.png")
                    try:
                        segment = segments[box_idx]
                        if segment.ndim == 3 and segment.shape[2] == 4:
                            Image.fromarray(segment.astype(np.uint8), mode="RGBA").save(struct_img_path)
                        else:
                            Image.fromarray(segment.astype(np.uint8)).save(struct_img_path)
                    except Exception as e:
                        logger.warning(f"  Failed to crop structure {idx}: {e}")
                        struct_img_path = img_path

                    structures.append({
                        "structure_index": idx,
                        "structure_id": f"S{idx:04d}",
                        "page_no": page_num + 1,
                        "page_idx": page_num,
                        "bbox_pdf": [pdf_x0, pdf_y0, pdf_x1, pdf_y1],
                        "bbox": [int(x0_abs), int(y0_abs), int(x1_abs), int(y1_abs)],
                        "crop_region": crop,
                        "image_path": struct_img_path,
                    })
                    idx += 1
            except Exception as e:
                err = str(e).replace("\n", " ")
                if "Got a model or layer" in err:
                    err = err.split("Got a model or layer", 1)[0].strip()
                logger.warning(f"  Page {page_num+1}: DECIMER failed: {err[:500]}")
                failed_pages.append((page_num + 1, err[:500]))
    else:
        # Fallback: use image analysis to detect structure regions
        logger.warning("DECIMER not available, using basic image-based extraction")

    doc.close()
    logger.info(f"Extracted {len(structures)} structures total")

    metadata = {
        **artifact_identity(STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION),
        "patent_number": patent_id,
        "total_structures": len(structures),
        "structures": structures,
        "failed_pages": [
            {"page_no": page_no, "error": error}
            for page_no, error in failed_pages
        ],
    }

    output_path = os.path.join(output_dir, "metadata.json")
    write_json_atomic(output_path, metadata)
    logger.info(f"Saved metadata to {output_path}")

    if failed_pages:
        sample = "; ".join(f"p{page_no}: {error}" for page_no, error in failed_pages[:3])
        raise RuntimeError(
            f"DECIMER segmentation failed on {len(failed_pages)}/{len(target_pages)} pages: {sample}"
        )

    return metadata


def main():
    parser = argparse.ArgumentParser(description="Extract chemical structures from a patent PDF")
    parser.add_argument("--pdf", required=True, help="Path to patent PDF")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument(
        "--pages",
        type=int,
        nargs="+",
        required=True,
        help="Authoritative page numbers from the locator (0-indexed)",
    )
    parser.add_argument("--crop-regions", default="", help="Optional JSON page crop regions in rendered-image pixels")
    args = parser.parse_args()

    extract_structures_from_pdf(args.pdf, args.pages, args.output, args.crop_regions)


if __name__ == "__main__":
    main()
