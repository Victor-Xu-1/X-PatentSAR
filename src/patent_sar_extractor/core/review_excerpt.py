"""Build an optional review excerpt without changing the production PDF chain.

The excerpt keeps likely examples, synthesis/preparation text, and activity
sections for operator review. Production extraction never consumes this PDF;
all formal artifacts retain original-document page coordinates.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fitz

from patent_sar_extractor.contracts import (
    REVIEW_EXCERPT_METADATA_SCHEMA,
    REVIEW_EXCERPT_METADATA_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.artifact_io import write_json_atomic

logger = logging.getLogger(__name__)


START_RE = re.compile(
    r"具体实施方式|实施例\s*1|制备例|合成例|"
    r"Detailed\s+Description|Example\s+\d+|Preparation\s+\d+|Synthesis\s+(?:of|\d+)",
    re.IGNORECASE,
)

STOP_RE = re.compile(
    r"权利要求书|"
    r"^What is claimed is|"
    r"^What is claimed:|"
    r"^The following claims\b",
    re.IGNORECASE | re.MULTILINE,
)

# ISR (International Search Report) marks the end of claims in PCT patents
ISR_RE = re.compile(
    r"INTERNATIONAL\s*SEARCH\s*REPORT|"
    r"PCT/ISA/210",
    re.IGNORECASE,
)

ACTIVITY_RE = re.compile(
    r"生物学活性|药理活性|抑制活性|抑制率|细胞活性|抗菌活性|抗病毒活性|"
    r"实验例|测试例|实验结果|生物学测定|活性测定|活性测试|"
    r"IC50|IC5[o0]|EC50|DC50|GI50|Ki|Kd|Koff|Kon|"
    r"nM|μM\b|µM\b|%抑制|抑制率|结合率|降解率|"
    r"表\s*\d+\s*[：:]\s*活性|Table\s+\d+.*activit|"
    r"binding\s+affinity|dissociation",
    re.IGNORECASE,
)

SYNTHESIS_RE = re.compile(
    r"实施例\s*\d+|合成路线|制备路线|制备例|"
    r"MS\s*m/z|LCMS|LC-MS|HPLC|NMR|收率|产率|"
    r"Example\s+\d+|Preparation\s+\d+|Synthesis\s+of",
    re.IGNORECASE,
)

EXCLUDED_SECTION_RE = re.compile(
    r"权利要求|摘要|说明书附图|国际检索报告|PCT/ISA/210|"
    r"INTERNATIONAL\s+SEARCH\s+REPORT|"
    r"通式|式\s*\(?[IVX\d]+\)?|选自|任选|取代基|定义|"
    r"药物组合物|制剂|赋形剂|载体|给药剂量|"
    r"FIELD|BACKGROUND|SUMMARY|CLAIMS|"
    r"PREPARATION\s+OF\s+WO|"
    r"国际申请|PCT申请",
    re.IGNORECASE,
)

GENERAL_MARKUSH_RE = re.compile(
    r"R[1-9]|R\^|R°|R¹|R²|R³|R⁴|X[1-9]|Y[1-9]|Z[1-9]|"
    r"任选|取代|杂芳基|烷基|卤素|选自",
    re.IGNORECASE,
)

FRONT_MATTER_RE = re.compile(
    r"技术领域|背景技术|发明内容|发明概述|具体实施方式之前|附图说明|"
    r"FIELD|BACKGROUND|SUMMARY|BRIEF\s+DESCRIPTION|DETAILED\s+SUMMARY|"
    r"摘要|Abstract",
    re.IGNORECASE,
)

BODY_START_HEADING_RE = re.compile(
    r"具体实施方式|实施方式|实施例\s*1\b|制备例\s*1\b|合成例\s*1\b|"
    r"Detailed\s+Description|Experimental\s+Section|Examples?\s*:?|"
    r"Example\s+1\b|Preparation\s+1\b|Synthesis\s+(?:Example\s+)?1\b",
    re.IGNORECASE,
)

BODY_START_SIGNAL_RE = re.compile(
    r"实施例\s*\d+|制备例\s*\d+|合成例\s*\d+|"
    r"Example\s+\d+|Preparation\s+\d+|Synthesis\s+(?:of|\d+)|"
    r"MS\s*m/z|LCMS|LC-MS|NMR|HPLC|收率|产率|mmol|mL|mg|°C|搅拌|反应|得到",
    re.IGNORECASE,
)


@dataclass
class OcrLine:
    text: str
    top: float
    bottom: float


def infer_candidate_page_window(
    page_texts: list[str],
    synthesis_pages: Optional[list[int]] = None,
    activity_pages: Optional[list[int]] = None,
    start_backoff_pages: int = 2,
) -> dict:
    """
    Infer a conservative candidate-page window in original-PDF coordinates.

    Principle:
    - Start after front matter / definitions end.
    - Stop on the page immediately before claims / ISR.
    - Allow 2-3 extra pages, but never cut relevant content short.
    """
    total = len(page_texts)
    synthesis_pages = sorted(set(synthesis_pages or []))
    activity_pages = sorted(set(activity_pages or []))
    if total == 0:
        return {
            "candidate_pages": [],
            "start_page_idx": None,
            "end_page_idx": None,
            "start_reason": "empty_pdf",
            "end_reason": "empty_pdf",
        }

    compact_pages = [re.sub(r"\s+", " ", text or "").strip() for text in page_texts]

    strong_start_idx = None
    signal_start_idx = None
    for idx in range(total):
        text = compact_pages[idx]
        if BODY_START_HEADING_RE.search(text):
            strong_start_idx = idx
            break
        if signal_start_idx is None and BODY_START_SIGNAL_RE.search(text):
            signal_start_idx = idx

    if strong_start_idx is None:
        classified_candidates = sorted(
            p for p in set(synthesis_pages + activity_pages) if 0 <= p < total
        )
        if classified_candidates:
            strong_start_idx = classified_candidates[0]
            start_reason = "first_classified_candidate_page"
        elif signal_start_idx is not None:
            strong_start_idx = signal_start_idx
            start_reason = "first_body_signal_page"
        else:
            strong_start_idx = 0
            start_reason = "fallback_document_start"
    else:
        start_reason = "body_start_heading"

    last_front_idx = None
    for idx in range(strong_start_idx):
        text = compact_pages[idx]
        has_front = bool(FRONT_MATTER_RE.search(text) or GENERAL_MARKUSH_RE.search(text) or EXCLUDED_SECTION_RE.search(text))
        has_body = bool(BODY_START_SIGNAL_RE.search(text) or ACTIVITY_RE.search(text) or SYNTHESIS_RE.search(text))
        if has_front and not has_body:
            last_front_idx = idx

    start_idx = max(0, strong_start_idx - start_backoff_pages)
    if last_front_idx is not None:
        start_idx = max(start_idx, last_front_idx + 1)
        start_reason = f"{start_reason}_after_front_matter"

    # PCT front pages often contain phrases such as "with international search
    # report (Art. 21(3))". That is not the actual ISR section and must not cut
    # a 400-page specification down to one page. Only accept claims/ISR stops
    # after the inferred body/candidate start.
    first_claim_idx = next(
        (
            idx
            for idx, text in enumerate(compact_pages)
            if idx >= start_idx and (STOP_RE.search(text) or ISR_RE.search(text))
        ),
        None,
    )

    if first_claim_idx is not None:
        end_idx = max(start_idx, first_claim_idx - 1)
        end_reason = "page_before_claims_or_isr"
    else:
        last_candidate_idx = None
        candidates = [p for p in synthesis_pages + activity_pages if start_idx <= p < total]
        if candidates:
            last_candidate_idx = max(candidates)
        if last_candidate_idx is not None:
            end_idx = min(total - 1, last_candidate_idx + 2)
            end_reason = "last_detected_candidate_page_plus_padding"
        else:
            end_idx = total - 1
            end_reason = "fallback_document_end"

    candidate_pages = list(range(start_idx, end_idx + 1)) if end_idx >= start_idx else []
    return {
        "candidate_pages": candidate_pages,
        "start_page_idx": start_idx,
        "end_page_idx": end_idx,
        "start_reason": start_reason,
        "end_reason": end_reason,
        "claim_page_idx": first_claim_idx,
    }


def _page_lines(page, dpi: int, engine) -> list[OcrLine]:
    """Return OCR lines with y coordinates in PDF points."""
    text = page.get_text("text").strip()
    if text:
        # Text PDFs: exact line coordinates are not needed for most pages.
        lines = []
        for block in page.get_text("blocks"):
            x0, y0, x1, y1, block_text, *_ = block
            for raw in str(block_text).splitlines():
                raw = raw.strip()
                if raw:
                    lines.append(OcrLine(raw, y0, y1))
        return lines

    if engine is None:
        return _page_lines_tesseract_cli(page, dpi)

    import numpy as np
    from PIL import Image
    from io import BytesIO

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
    result, _ = engine(np.array(img))
    scale = 72 / dpi
    lines = []
    for item in result or []:
        box = item[0]
        text = str(item[1]).strip()
        if not text:
            continue
        ys = [p[1] * scale for p in box]
        lines.append(OcrLine(text, min(ys), max(ys)))
    return lines


def _page_lines_tesseract_cli(page, dpi: int) -> list[OcrLine]:
    tesseract_bin = shutil.which("tesseract")
    if not tesseract_bin:
        return []
    try:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        scale = 72 / dpi
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            pix.save(tmp.name)
            proc = subprocess.run(
                [tesseract_bin, tmp.name, "stdout", "-l", "eng+chi_sim", "--psm", "6", "tsv"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        if proc.returncode != 0:
            logger.warning(f"Tesseract CLI failed: {proc.stderr[:200]}")
            return []

        grouped: dict[tuple[int, int, int], list[tuple[int, int, str]]] = {}
        for row in proc.stdout.splitlines()[1:]:
            cols = row.split("\t")
            if len(cols) < 12 or cols[0] != "5":
                continue
            text = cols[11].strip()
            if not text:
                continue
            key = (int(cols[2]), int(cols[3]), int(cols[4]))
            grouped.setdefault(key, []).append((int(cols[7]), int(cols[6]), text))

        lines: list[OcrLine] = []
        for parts in grouped.values():
            parts.sort(key=lambda p: p[1])
            top = min(p[0] for p in parts) * scale
            bottom = max(p[0] for p in parts) * scale
            text = " ".join(p[2] for p in parts)
            lines.append(OcrLine(text, top, bottom))
        lines.sort(key=lambda line: line.top)
        return lines
    except Exception as e:
        logger.warning(f"Tesseract CLI OCR failed on page: {e}")
        return []


def _load_ocr_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()
    except Exception as e:
        logger.warning(f"RapidOCR unavailable; PDF truncation will use text only: {e}")
        return None


def _classify_relevant_page(text: str) -> tuple[bool, str]:
    """Return whether a page should be kept in the review excerpt."""
    compact = re.sub(r"\s+", " ", text or "")
    if ISR_RE.search(compact) or STOP_RE.search(compact):
        return False, "excluded_claims_or_isr"

    has_activity = bool(ACTIVITY_RE.search(compact))
    has_synthesis = bool(SYNTHESIS_RE.search(compact))
    has_excluded_section = bool(EXCLUDED_SECTION_RE.search(compact))
    has_markush = bool(GENERAL_MARKUSH_RE.search(compact))
    has_analytical = bool(re.search(r"MS\s*m/z|HPLC|NMR|收率|产率|yield", compact, re.IGNORECASE))
    has_exp_heading = bool(re.search(r"实施例\s*\d+|Example\s+\d+|Preparation\s+\d+", compact, re.IGNORECASE))
    has_compound_label = bool(re.search(r"\b\d{1,2}(?:-[12]|[a-z])?\b", compact))
    has_reaction_context = bool(re.search(r"mg|mmol|mL|°C|小时|h\b|搅拌|反应|得到|制备|MS\s*m/z", compact, re.IGNORECASE))
    is_instrument_only = bool(re.search(r"测定用|分析使用|色谱仪|仪器|HPLC\s+分析|NMR\s+的测定", compact, re.IGNORECASE))

    if has_activity and not re.search(r"药物组合物|制剂|检索报告|PCT/ISA", compact, re.IGNORECASE):
        return True, "activity_page"
    if has_synthesis and (has_exp_heading or (has_analytical and has_compound_label and has_reaction_context and not is_instrument_only)):
        return True, "synthesis_experimental_page"
    if has_excluded_section and has_markush and not has_analytical:
        return False, "excluded_markush_definition"
    return False, "not_relevant"


def create_review_excerpt_pdf(
    pdf_path: str,
    output_pdf: str,
    metadata_path: Optional[str] = None,
    dpi: int = 150,
) -> dict:
    """Create a diagnostic review excerpt and return versioned metadata."""
    src = fitz.open(pdf_path)
    original_page_count = len(src)
    engine = _load_ocr_engine()

    page_infos = []
    classified_infos = []
    page_texts = []
    started = False
    stopped = False

    for page_idx in range(len(src)):
        page = src[page_idx]
        lines = _page_lines(page, dpi, engine)
        joined = " ".join(line.text for line in lines)
        page_texts.append(joined)
        page_height = float(page.rect.height)
        keep_by_class, class_reason = _classify_relevant_page(joined)
        classified_infos.append({
            "source_page_idx": page_idx,
            "source_page_no": page_idx + 1,
            "clip_pdf": [0.0, 0.0, float(page.rect.width), float(page.rect.height)],
            "reason": class_reason,
            "has_activity_marker": bool(ACTIVITY_RE.search(joined)),
            "keep": keep_by_class,
        })

        if stopped:
            # Already stopped marker-based cropping; skip to next page
            # but continue classifying remaining pages for whitelist building
            continue

        start_y = 0.0
        stop_y = page_height

        if not started:
            for line in lines:
                if START_RE.search(line.text):
                    start_y = max(0.0, line.top - 12)
                    started = True
                    break
            if not started:
                continue

        for line in lines:
            if STOP_RE.search(line.text):
                stop_y = max(start_y + 1.0, line.top - 8)
                stopped = True
                break

        # ISR marks the end of the useful section in PCT patents
        if not stopped and ISR_RE.search(joined):
            # Don't include the ISR page itself; stop before this page
            if page_infos:  # Only if we have content pages before ISR
                stopped = True
                continue  # Don't add this page
            # If ISR is before any content, just skip it
            continue

        page_infos.append({
            "source_page_idx": page_idx,
            "source_page_no": page_idx + 1,
            "clip_pdf": [0.0, start_y, float(page.rect.width), stop_y],
            "reason": "relevant_body_examples_activity",
            "has_activity_marker": bool(ACTIVITY_RE.search(joined)),
        })

    synthesis_pages = [
        info["source_page_idx"]
        for info in classified_infos
        if info["keep"] and info["reason"] == "synthesis_experimental_page"
    ]
    activity_pages = [
        info["source_page_idx"]
        for info in classified_infos
        if info["keep"] and info["reason"] == "activity_page"
    ]
    inferred_window = infer_candidate_page_window(
        page_texts,
        synthesis_pages=synthesis_pages,
        activity_pages=activity_pages,
    )
    inferred_candidates = set(inferred_window["candidate_pages"])
    whitelist_infos = []
    if inferred_candidates:
        for idx in sorted(inferred_candidates):
            page = src[idx]
            keep_by_class, class_reason = _classify_relevant_page(page_texts[idx])
            whitelist_infos.append({
                "source_page_idx": idx,
                "source_page_no": idx + 1,
                "clip_pdf": [0.0, 0.0, float(page.rect.width), float(page.rect.height)],
                "reason": class_reason if keep_by_class else "boundary_window_keep",
                "has_activity_marker": bool(ACTIVITY_RE.search(page_texts[idx])),
            })

    if whitelist_infos:
        page_infos = whitelist_infos
        strategy = "boundary_window_before_claims"
    elif page_infos:
        strategy = "marker_crop_examples_synthesis_activity"
    else:
        # Conservative fallback: do not drop data if markers fail, but make it visible.
        logger.warning("No candidate-page whitelist or markers found; copying original PDF unchanged for review")
        page_infos = [
            {
                "source_page_idx": i,
                "source_page_no": i + 1,
                "clip_pdf": [0.0, 0.0, float(src[i].rect.width), float(src[i].rect.height)],
                "reason": "fallback_full_pdf_needs_review",
                "has_activity_marker": False,
            }
            for i in range(len(src))
        ]
        strategy = "fallback_full_pdf_needs_review"

    out = fitz.open()
    for info in page_infos:
        source_page = src[info["source_page_idx"]]
        clip = fitz.Rect(info["clip_pdf"])
        new_page = out.new_page(width=clip.width, height=clip.height)
        new_page.show_pdf_page(new_page.rect, src, info["source_page_idx"], clip=clip)

    output = Path(output_pdf)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.save(str(output))
    out.close()
    src.close()

    metadata = {
        **artifact_identity(REVIEW_EXCERPT_METADATA_SCHEMA, REVIEW_EXCERPT_METADATA_SCHEMA_VERSION),
        "input_pdf": pdf_path,
        "output_pdf": output_pdf,
        "page_count_original": original_page_count,
        "page_count_excerpt": len(page_infos),
        "pages": page_infos,
        "classified_pages": classified_infos,
        "strategy": strategy,
        "boundary": inferred_window if 'inferred_window' in locals() else None,
        "needs_review": strategy == "fallback_full_pdf_needs_review",
    }

    if metadata_path:
        write_json_atomic(metadata_path, metadata)

    logger.info(
        f"Review excerpt created: {output_pdf} ({metadata['page_count_excerpt']}/"
        f"{metadata['page_count_original']} pages)"
    )
    return metadata
