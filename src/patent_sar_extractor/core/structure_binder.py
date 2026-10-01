"""
Structure Binder — activity-led compound-to-structure binding.

Detect compound label formats and bind structures using visible evidence,
table geometry and the authoritative activity set. Ambiguous rows fail closed.

用法:
    from patent_sar_extractor.core.structure_binder import bind
    result = bind(
        pdf_path="WO2026073080.pdf",
        profile=profile_dict,
        structures_path="step6/metadata.json",
        output_dir="data/WO2026073080/step6_5",
    )
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    VISIBLE_LABEL_CACHE_SCHEMA,
    VISIBLE_LABEL_CACHE_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
)
from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.core.numbered_structure_binding import (
    NumberedTableResult,
    bind_numbered_tables,
)
from patent_sar_extractor.core.page_ocr_cache import (
    _paddlex_ocr_url as _shared_paddlex_ocr_url,
)
from patent_sar_extractor.core.page_ocr_cache import (
    _paddlex_payload_from_image as _shared_paddlex_payload_from_image,
)
from patent_sar_extractor.core.page_ocr_cache import (
    _paddlex_pruned_result,
    _paddlex_request_payload_from_png,
)
from patent_sar_extractor.core.pipeline_rules import (
    annotate_binding_accuracy,
    summarise_binding_accuracy,
)
from patent_sar_extractor.core.series_table_binding import pair_series_table

try:
    import fitz
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

logger = logging.getLogger(__name__)

_PADDLEX_OCR_AVAILABLE: Optional[bool] = None


def _paddlex_ocr_url() -> str:
    return _shared_paddlex_ocr_url()


def _structure_cache_signature(struct: Dict) -> Dict[str, Any]:
    """Fingerprint a segmented structure for visible-label cache safety.

    Structure IDs are assigned by segmentation order, so after changing crop
    regions the same Sxxxx may point to a different drawing. The visible-label
    cache is only safe to reuse when the current page, geometry, and image bytes
    match the cached structure.
    """
    bbox = [
        round(float(struct.get(key) or 0), 2)
        for key in ("x0", "y0", "x1", "y1")
    ]
    image_path = str(struct.get("image_path") or "")
    image_sha1 = ""
    if image_path and os.path.exists(image_path):
        try:
            h = hashlib.sha1()
            with open(image_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            image_sha1 = h.hexdigest()
        except Exception:
            image_sha1 = ""
    return {
        "page_no": int(struct.get("page_no") or 0),
        "bbox": bbox,
        "image_sha1": image_sha1,
    }


def _visible_cache_item_matches_structure(cache_item: Any, struct: Dict) -> bool:
    if not isinstance(cache_item, dict):
        return False
    if not artifact_identity_matches(
        cache_item,
        VISIBLE_LABEL_CACHE_SCHEMA,
        VISIBLE_LABEL_CACHE_SCHEMA_VERSION,
    ):
        return False
    if not cache_item.get("cache_complete"):
        return False
    if int(cache_item.get("cache_version") or 0) < _VISIBLE_LABEL_CACHE_VERSION:
        return False
    cached_sig = cache_item.get("structure_signature")
    if not isinstance(cached_sig, dict):
        return False
    return cached_sig == _structure_cache_signature(struct)


def _filter_visible_label_cache_for_structures(
    cache: Optional[Dict[str, Dict]],
    processed_structures: List[Dict],
) -> Dict[str, Dict]:
    """Keep only visible-label cache entries proven to match this run's crops."""
    if not cache:
        return {}
    struct_by_id = {
        str(struct.get("id") or ""): struct
        for struct in processed_structures
        if str(struct.get("id") or "")
    }
    filtered: Dict[str, Dict] = {}
    stale = 0
    for sid, item in cache.items():
        struct = struct_by_id.get(str(sid))
        if struct and _visible_cache_item_matches_structure(item, struct):
            filtered[str(sid)] = item
        else:
            stale += 1
    if stale:
        logger.info("   👁 丢弃不匹配的结构可见编号缓存: %d stale entries", stale)
    return filtered


def _allow_tesseract_fallback() -> bool:
    return os.environ.get("WIPO_ALLOW_TESSERACT_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}


def _paddlex_ocr_texts_from_image(img, timeout: float = 12.0) -> List[str]:
    """OCR a small crop through the existing PaddleX OCR service.

    The local service is the configured GPU OCR path for this workstation. Keep
    Tesseract only as fallback so binder does not spawn CPU OCR for every label
    crop when the GPU service is available.
    """
    global _PADDLEX_OCR_AVAILABLE
    url = _paddlex_ocr_url()
    if not url or url.lower() in {"off", "none", "0"}:
        _PADDLEX_OCR_AVAILABLE = False
        return []
    if _PADDLEX_OCR_AVAILABLE is False:
        return []
    try:
        texts, _boxes = _shared_paddlex_payload_from_image(img, timeout=timeout)
    except Exception as exc:
        if _PADDLEX_OCR_AVAILABLE is not False:
            logger.warning("   PaddleX OCR服务不可用，回退到Tesseract: %s", exc)
        _PADDLEX_OCR_AVAILABLE = False
        return []

    _PADDLEX_OCR_AVAILABLE = True
    return [str(text or "").strip() for text in texts if str(text or "").strip()]


def _extract_heading_blocks_from_page(
    page_no: int,
    words: list,
    prefix: str,
    pattern: str,
    ocr_text: str = "",
    ocr_coords: Optional[List[Tuple[float, str]]] = None,
) -> List[Dict]:
    heading_pattern = re.compile(pattern, re.IGNORECASE)
    blocks = []
    seen = set()

    def add_block(cpd_label: str, y0: float, x0: float, word_index: int, line_text: str) -> None:
        label_key = _normalise_compound_label(cpd_label)
        cpd_num = _base_cpd_num(label_key)
        if not label_key or cpd_num is None:
            return
        cpd_id = f"{prefix}{label_key}"
        dedup_key = (page_no, cpd_id)
        if dedup_key in seen:
            return
        seen.add(dedup_key)
        blocks.append({
            "cpd": cpd_id,
            "cpd_num": cpd_num,
            "cpd_label": label_key,
            "prefix": prefix,
            "page_no": page_no,
            "y0": y0,
            "x0": x0,
            "word_index": word_index,
            "line_text": line_text[:120],
        })

    if words:
        lines: Dict[int, list] = {}
        for w in words:
            y_key = round(w[1] / 5) * 5
            lines.setdefault(y_key, []).append(w)

        for y_key in sorted(lines.keys()):
            line_words = sorted(lines[y_key], key=lambda w: w[0])
            line_text = " ".join([w[4] for w in line_words])
            for m in heading_pattern.finditer(line_text):
                first_word = line_words[0]
                add_block(m.group(1), first_word[1], first_word[0], 0, line_text)
        return blocks

    if ocr_text:
        if ocr_coords:
            for y0_coord, line_text in ocr_coords:
                for m in heading_pattern.finditer(line_text):
                    add_block(m.group(1), y0_coord, 0, 0, line_text.strip())
        else:
            lines = ocr_text.replace('\n', '\n').split('\n')
            if len(lines) <= 1:
                lines = re.split(r'[。；;\n]', ocr_text)
            for line_idx, line_text in enumerate(lines):
                for m in heading_pattern.finditer(line_text):
                    # OCR cache text may not include coordinates. Keep a
                    # line-order y estimate so adjacent Chinese examples
                    # on the same page do not collapse into y=0 and force
                    # unsafe cross-page/previous-page fallbacks.
                    add_block(m.group(1), float(line_idx) * 14.0, 0, 0, line_text.strip())
    return blocks


def _extract_binder_page_text(pdf_path: str, page_idx: int) -> tuple[int, str]:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_idx]
        text = page.get_text("text")
        if not text.strip():
            try:
                from patent_sar_extractor.core.patent_profiler import _ocr_page_fallback
                text = _ocr_page_fallback(page)
            except Exception:
                pass
        return page_idx, text
    finally:
        doc.close()


def _extract_binder_page_lines(pdf_path: str, page_idx: int) -> tuple[int, List[Tuple[float, str]]]:
    doc = fitz.open(pdf_path)
    try:
        return page_idx, _get_ocr_line_coords(doc[page_idx]) or []
    finally:
        doc.close()


def _scan_heading_page(
    pdf_path: str,
    page_no: int,
    prefix: str,
    pattern: str,
    ocr_text: str = "",
    ocr_coords: Optional[List[Tuple[float, str]]] = None,
) -> List[Dict]:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_no - 1]
        words = page.get_text("words")
        return _extract_heading_blocks_from_page(page_no, words, prefix, pattern, ocr_text=ocr_text, ocr_coords=ocr_coords)
    finally:
        doc.close()


# ============================================================================
# 配置
# ============================================================================

@dataclass
class BinderConfig:
    """绑定算法配置"""
    search_below_pixels: int = 300
    search_above_pixels: int = 200
    search_side_pixels: int = 300
    cluster_y_threshold: int = 50


# ============================================================================
# 化合物编号检测模式
# ============================================================================

# Cpd 前缀检测模式（与 PatentProfiler 一致，中文优先）
CPD_PREFIX_PATTERNS = [
    (r"实施例\s*(\d+)", "实施例"),
    (r"化合物\s*(\d+)", "化合物"),
    (r"Cpd[-\s]?(\d+)", "Cpd-"),
    (r"Example[-\s]+(\d+)", "Example "),
    (r"Compound[-\s]+(\d+)", "Compound "),
    (r"Cmpd\.?\s*(\d+)", "Cmpd "),
    (r"Int[-\s]?(\d+)", "Int-"),
]

CPD_DENSE_RE = re.compile(r"Cpd[-\s]?\d+", re.IGNORECASE)


# ============================================================================
# 区块查找：Cpd-N 格式（"Synthesis of Cpd-N"）
# ============================================================================

def _find_synthesis_blocks_cpd(doc, page_numbers: Optional[List[int]] = None) -> List[Dict]:
    """查找 "Synthesis of Cpd-N" 区块。
    
    用于 Cpd-N 风格专利（如 WO2026067249）。
    """
    blocks = []
    synthesis_pattern = re.compile(r"Synthesis", re.IGNORECASE)
    cpd_pattern = re.compile(r"Cpd[-\s]?(\d+)", re.IGNORECASE)
    
    for page_no in (page_numbers or list(range(1, len(doc) + 1))):
        page = doc[page_no - 1]
        words = page.get_text("words")
        
        for i, word in enumerate(words):
            word_text = word[4]
            if synthesis_pattern.search(word_text):
                has_of = False
                has_other_synthesis = False
                for j in range(i + 1, min(i + 3, len(words))):
                    if words[j][4].lower() == "of":
                        has_of = True
                    if synthesis_pattern.search(words[j][4]):
                        has_other_synthesis = True
                
                if not has_of or has_other_synthesis:
                    continue
                
                search_words = words[i:i + 50]
                search_text = " ".join([w[4] for w in search_words])
                cpd_match = cpd_pattern.search(search_text)
                if cpd_match:
                    cpd_num = int(cpd_match.group(1))
                    blocks.append({
                        "cpd": f"Cpd-{cpd_num}",
                        "cpd_num": cpd_num,
                        "prefix": "Cpd-",
                        "page_no": page_no,
                        "y0": word[1],
                        "word_index": i,
                    })
    
    blocks.sort(key=lambda x: (x["page_no"], x["y0"]))
    return blocks


# ============================================================================
# 区块查找：标题式（Example N / Intermediate N / Compound N）
# ============================================================================

def _find_heading_blocks(
    doc,
    prefix: str = "Example",
    pattern: str = r"Example\s*(\d+)",
    ocr_text_map: Optional[Dict[int, str]] = None,
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    page_numbers: Optional[List[int]] = None,
    workers: int = 1,
) -> List[Dict]:
    """查找标题式化合物区块。

    用于 Example N / Intermediate N / Compound N 风格专利。
    支持多编号合并如 "Intermediates 3 and 4"。

    Args:
        doc: fitz.Document
        prefix: 前缀名 (如 "Example", "实施例")
        pattern: 正则模式
        ocr_text_map: {page_idx: full_text} from OCR, used as fallback for scanned PDFs
    """
    blocks = []
    pages_to_scan = page_numbers or list(range(1, len(doc) + 1))
    workers = max(1, int(workers or 1))

    if workers <= 1 or len(pages_to_scan) <= 1:
        for page_no in pages_to_scan:
            page = doc[page_no - 1]
            page_idx = page_no - 1
            words = page.get_text("words")
            text = (ocr_text_map or {}).get(page_idx, "")
            coords = (ocr_line_map or {}).get(page_idx)
            if not words and not text and coords is None:
                coords = _get_ocr_line_coords(page)
            blocks.extend(
                _extract_heading_blocks_from_page(
                    page_no,
                    words,
                    prefix,
                    pattern,
                    ocr_text=text,
                    ocr_coords=coords,
                )
            )
    else:
        pdf_path = getattr(doc, "name", "")
        if not pdf_path:
            for page_no in pages_to_scan:
                page = doc[page_no - 1]
                page_idx = page_no - 1
                blocks.extend(
                    _extract_heading_blocks_from_page(
                        page_no,
                        page.get_text("words"),
                        prefix,
                        pattern,
                        ocr_text=(ocr_text_map or {}).get(page_idx, ""),
                        ocr_coords=(ocr_line_map or {}).get(page_idx),
                    )
                )
        else:
            max_workers = min(workers, len(pages_to_scan))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {
                    pool.submit(
                        _scan_heading_page,
                        pdf_path,
                        page_no,
                        prefix,
                        pattern,
                        (ocr_text_map or {}).get(page_no - 1, ""),
                        (ocr_line_map or {}).get(page_no - 1),
                    ): page_no
                    for page_no in pages_to_scan
                }
                for future in as_completed(future_map):
                    try:
                        blocks.extend(future.result())
                    except Exception as exc:
                        logger.debug("Heading scan failed on page %s: %s", future_map[future], exc)
    blocks.sort(key=lambda x: (x["page_no"], x["y0"]))
    return blocks


def _get_ocr_line_coords(page) -> Optional[List[Tuple[float, str]]]:
    """Run OCR on a fitz.Page and return [(y0, text)] lines with PDF coordinates.

    Prefer the configured PaddleX service; RapidOCR remains a local fallback.
    """
    try:
        from patent_sar_extractor.core.page_ocr_cache import (
            get_ocr_engine,
            page_ocr_lines,
        )

        engine = get_ocr_engine()
        lines = page_ocr_lines(page, ocr_engine=engine)
        if lines:
            return [(float(item.get("y0", 0)), str(item.get("text", ""))) for item in lines if str(item.get("text", "")).strip()]
    except Exception:
        pass

    try:
        import cv2
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()
        dpi = 150
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)

        result, _ = engine(img_np)
        if not result:
            return []

        scale = 72.0 / dpi
        lines = []
        for item in result:
            box = item[0]
            text = str(item[1]).strip()
            if not text:
                continue
            y0_pdf = min(p[1] for p in box) * scale
            lines.append((y0_pdf, text))

        lines.sort(key=lambda x: x[0])
        return lines
    except Exception as e:
        logger.debug(f"RapidOCR for line coords failed: {e}")

    if not _allow_tesseract_fallback():
        return []

    tesseract_bin = shutil.which("tesseract")
    if not tesseract_bin:
        return None

    try:
        dpi = 150
        scale = 72.0 / dpi
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            pix.save(tmp.name)
            proc = subprocess.run(
                [
                    tesseract_bin,
                    tmp.name,
                    "stdout",
                    "-l",
                    os.environ.get("WIPO_TESSERACT_LANG", "eng"),
                    "--psm",
                    "6",
                    "tsv",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        if proc.returncode != 0:
            logger.debug(f"Tesseract TSV failed: {proc.stderr[:200]}")
            return None

        line_parts: Dict[Tuple[int, int, int], List[Tuple[int, int, str]]] = {}
        for row in proc.stdout.splitlines()[1:]:
            cols = row.split("\t")
            if len(cols) < 12 or cols[0] != "5":
                continue
            text = cols[11].strip()
            if not text:
                continue
            block_num, par_num, line_num = int(cols[2]), int(cols[3]), int(cols[4])
            left, top = int(cols[6]), int(cols[7])
            line_parts.setdefault((block_num, par_num, line_num), []).append((top, left, text))

        lines = []
        for parts in line_parts.values():
            parts.sort(key=lambda p: p[1])
            y0_pdf = min(p[0] for p in parts) * scale
            text = " ".join(p[2] for p in parts)
            lines.append((y0_pdf, text))
        lines.sort(key=lambda x: x[0])
        return lines
    except Exception as e:
        logger.debug(f"Tesseract TSV for line coords failed: {e}")
        return None


def _get_ocr_word_coords(page, cache: Optional[Dict[int, List[Dict]]] = None) -> List[Dict]:
    """Return OCR word coordinates in PDF units using GPU OCR first."""
    page_idx = int(getattr(page, "number", -1))
    if cache is not None and page_idx in cache:
        return cache[page_idx]
    try:
        from io import BytesIO

        from PIL import Image

        dpi = 150
        scale = 72.0 / dpi
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        img = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
        words = []

        # Use the configured PaddleX service before any CPU OCR. The service
        # returns recognized boxes in rendered-image pixels.
        texts = []
        rec_boxes = []
        try:
            import requests  # type: ignore

            buf = BytesIO()
            img.save(buf, format="PNG")
            session = requests.Session()
            session.trust_env = False
            response = session.post(
                _paddlex_ocr_url(),
                json=_paddlex_request_payload_from_png(buf.getvalue()),
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            pruned = _paddlex_pruned_result(data)
            texts = pruned.get("rec_texts") or []
            rec_boxes = pruned.get("rec_boxes") or []
        except Exception as exc:
            logger.debug("PaddleX word OCR failed: %s", exc)

        if texts and rec_boxes:
            for text, box in zip(texts, rec_boxes):
                value = str(text or "").strip()
                if not value or not isinstance(box, list) or len(box) < 4:
                    continue
                left, top, right, bottom = [float(v) for v in box[:4]]
                words.append({
                    "text": value,
                    "x": ((left + right) / 2.0) * scale,
                    "y": ((top + bottom) / 2.0) * scale,
                })
            if cache is not None and page_idx >= 0:
                cache[page_idx] = words
            return words
    except Exception:
        pass

    try:
        import cv2
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR

        dpi = 150
        scale = 72.0 / dpi
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
        result, _ = RapidOCR()(img_np)
        words = []
        for item in result or []:
            text = str(item[1]).strip()
            if not text:
                continue
            box = item[0]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            words.append({
                "text": text,
                "x": (sum(xs) / len(xs)) * scale,
                "y": (sum(ys) / len(ys)) * scale,
            })
        if cache is not None and page_idx >= 0:
            cache[page_idx] = words
        return words
    except Exception:
        pass

    if not _allow_tesseract_fallback():
        if cache is not None and page_idx >= 0:
            cache[page_idx] = []
        return []

    tesseract_bin = shutil.which("tesseract")
    if not tesseract_bin:
        if cache is not None and page_idx >= 0:
            cache[page_idx] = []
        return []

    try:
        dpi = 150
        scale = 72.0 / dpi
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            pix.save(tmp.name)
            proc = subprocess.run(
                [
                    tesseract_bin,
                    tmp.name,
                    "stdout",
                    "-l",
                    os.environ.get("WIPO_TESSERACT_LANG", "eng"),
                    "--psm",
                    "6",
                    "tsv",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        if proc.returncode != 0:
            if cache is not None and page_idx >= 0:
                cache[page_idx] = []
            return []

        words = []
        for row in proc.stdout.splitlines()[1:]:
            cols = row.split("\t")
            if len(cols) < 12 or cols[0] != "5":
                continue
            text = cols[11].strip()
            if not text:
                continue
            left, top, width, height = int(cols[6]), int(cols[7]), int(cols[8]), int(cols[9])
            words.append({
                "text": text,
                "x": (left + width / 2) * scale,
                "y": (top + height / 2) * scale,
            })
        if cache is not None and page_idx >= 0:
            cache[page_idx] = words
        return words
    except Exception as e:
        logger.debug(f"OCR word coords failed: {e}")
        if cache is not None and page_idx >= 0:
            cache[page_idx] = []
        return []


# ============================================================================
# OCR 回退补漏
# ============================================================================

def _find_missing_blocks_via_ocr_text(
    doc,
    blocks: List[Dict],
    pages_text: Dict[int, str],
    prefix: str,
    pattern: str,
) -> List[Dict]:
    """OCR 文本回退补漏：fitz 文本层找不到的编号，通过 OCR 全文搜索补回。
    
    适用于嵌入在流程图图片中的文字（如 "Example7", "Intermediate 14"）。
    通过上下文锚点（段落号 [00191]、INT-xx 缩写等）在 fitz 层中定位 y0。
    """
    heading_pattern = re.compile(pattern, re.IGNORECASE)
    
    # 收集已找到的编号
    found_nums = set()
    for b in blocks:
        if b["prefix"] == prefix:
            found_nums.add(b["cpd_num"])
    
    # 在 OCR 全文中搜索
    ocr_nums = set()
    ocr_locations: List[Tuple[int, int, str]] = []
    for page_idx, text in pages_text.items():
        page_idx = int(page_idx)
        for m in heading_pattern.finditer(text):
            cpd_num = int(m.group(1))
            ocr_nums.add(cpd_num)
            start = max(0, m.start() - 200)
            end = min(len(text), m.end() + 200)
            ctx = text[start:end]
            ocr_locations.append((page_idx, cpd_num, ctx))
    
    missing_nums = ocr_nums - found_nums
    if not missing_nums:
        return []
    
    logger.info(
        f"🔍 OCR回退: {prefix}在fitz层缺{len(missing_nums)}个 → {sorted(missing_nums)}"
    )
    
    new_blocks = []
    for page_idx, cpd_num, ctx in ocr_locations:
        if cpd_num not in missing_nums:
            continue
        
        page_no = page_idx + 1  # 转为 1-indexed
        y0_estimated = None
        x0_estimated = 72.0  # 默认左边距
        
        # 策略1: 上下文锚点映射
        anchor_patterns = [
            (r"\[(\d{5,6})\]", "paragraph"),
            (r"INT[-\s]?(\d+)", "int_abbrev"),
        ]
        
        page = doc[page_idx]
        words = page.get_text("words")
        
        for anchor_pat, anchor_type in anchor_patterns:
            anchor_matches = list(re.finditer(anchor_pat, ctx, re.IGNORECASE))
            if not anchor_matches:
                continue
            for am in anchor_matches:
                anchor_text = am.group(0)
                for w in words:
                    if w[4].strip() == anchor_text.strip():
                        y0_estimated = w[1]
                        logger.info(
                            f"   {prefix}{cpd_num} p{page_no}: "
                            f"锚点'{anchor_text}' → y0={y0_estimated:.0f}"
                        )
                        break
                if y0_estimated is not None:
                    break
            if y0_estimated is not None:
                break
        
        # 策略2: 同页已有 block 做插值
        if y0_estimated is None:
            same_page_blocks = [b for b in blocks if b["page_no"] == page_no]
            if same_page_blocks:
                avg_y0 = sum(b["y0"] for b in same_page_blocks) / len(same_page_blocks)
                y0_estimated = avg_y0
                logger.info(
                    f"   {prefix}{cpd_num} p{page_no}: 无锚点，用插值y0={y0_estimated:.0f}"
                )
            else:
                y0_estimated = 400.0
                logger.info(
                    f"   {prefix}{cpd_num} p{page_no}: 无锚点无参考，用默认y0=400"
                )
        
        new_blocks.append({
            "cpd": f"{prefix}{cpd_num}",
            "cpd_num": cpd_num,
            "prefix": prefix,
            "page_no": page_no,
            "y0": y0_estimated,
            "x0": x0_estimated,
            "word_index": -1,  # 标记为 OCR 回退
            "line_text": f"[OCR回退] {ctx[:100]}",
            "source": "ocr_fallback",
        })
    
    return new_blocks


# ============================================================================
# 自动检测编号格式
# ============================================================================

def _find_blocks_auto(
    doc,
    pages_text: Dict[int, str],
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    page_numbers: Optional[List[int]] = None,
    workers: int = 1,
) -> Tuple[List[Dict], str]:
    """自动检测化合物编号格式并查找区块。
    
    Returns:
        (blocks, detected_style) — 区块列表和检测到的风格
    """
    all_text = "\n".join(pages_text.values())
    
    cpd_count = len(set(re.findall(r"Cpd[-\s]?(\d+)", all_text, re.IGNORECASE)))
    example_count = len(set(re.findall(r"Example\s*(\d+)", all_text, re.IGNORECASE)))
    intermediate_count = len(
        set(re.findall(r"Intermediate\s+(\d+)", all_text, re.IGNORECASE))
    )
    int_count = len(set(re.findall(r"INT[-\s]?(\d+)", all_text, re.IGNORECASE)))
    compound_count = len(
        set(re.findall(r"Compound\s*(\d+)", all_text, re.IGNORECASE))
    )
    # Chinese patterns
    shili_count = len(set(re.findall(r"实施例\s*(\d+)", all_text)))
    compound_cn_count = len(set(re.findall(r"化合物\s*(\d+)", all_text)))

    logger.info(
        f"📊 编号模式检测: Cpd={cpd_count}, Example={example_count}, "
        f"Intermediate={intermediate_count}, INT={int_count}, Compound={compound_count}, "
        f"实施例={shili_count}, 化合物={compound_cn_count}"
    )

    all_blocks: List[Dict] = []
    detected_style = "unknown"

    # Helper: filter out X-N pattern compounds (Compound 1-1, 化合物2-2, etc.)
    # These are synthesis intermediates, not final products.
    _X_N_RE = re.compile(r'[-]\d+$')

    def _filter_xn(blocks: List[Dict], label: str = "") -> List[Dict]:
        filtered = [b for b in blocks if not _X_N_RE.search(b.get('cpd', ''))]
        if len(filtered) < len(blocks):
            skipped = [b['cpd'] for b in blocks if b not in filtered]
            logger.info(f"  ⚠️  过滤 {len(blocks)-len(filtered)} 个中间体 ({label}): {', '.join(skipped)}")
        return filtered

    # Priority: Chinese 实施例/化合物 first, then Cpd, then Compound/Example.
    # A few biology "Example N" assay sections must not override hundreds of
    # synthesis "Compound N" final-product labels.
    if shili_count >= 2:
        logger.info(f"🧪 检测到 实施例 N 格式 ({shili_count}个)，使用 heading 模式 (中文)")
        ex_blocks = _find_heading_blocks(
            doc, prefix="实施例", pattern=r"实施例\s*(\d+)", ocr_text_map=pages_text, ocr_line_map=ocr_line_map, page_numbers=page_numbers, workers=workers
        )
        all_blocks.extend(ex_blocks)
        detected_style = "heading"
    elif compound_cn_count >= 2:
        logger.info(f"🧪 检测到 化合物 N 格式 ({compound_cn_count}个)，使用 heading 模式 (中文)")
        cp_blocks = _find_heading_blocks(
            doc, prefix="化合物", pattern=r"化合物\s*(\d+)", ocr_text_map=pages_text, ocr_line_map=ocr_line_map, page_numbers=page_numbers, workers=workers
        )
        all_blocks.extend(cp_blocks)
        detected_style = "heading_compound_cn"
    elif cpd_count >= 5:
        logger.info(f"🧪 检测到 Cpd-N 格式 ({cpd_count}个)，使用 synthesis_of 模式")
        all_blocks = _find_synthesis_blocks_cpd(doc, page_numbers=page_numbers)
        detected_style = "synthesis_of"
    elif compound_count >= 5:
        logger.info(
            f"🧪 检测到 Compound N 格式 ({compound_count}个)，使用 heading 模式"
        )
        cp_blocks = _find_heading_blocks(
            doc, prefix="Compound", pattern=r"Compound\s*(\d+)", ocr_text_map=pages_text, ocr_line_map=ocr_line_map, page_numbers=page_numbers, workers=workers
        )
        all_blocks.extend(cp_blocks)
        detected_style = "heading_compound"
    elif example_count >= 2:
        logger.info(f"🧪 检测到 Example N 格式 ({example_count}个)，使用 heading 模式")
        ex_blocks = _find_heading_blocks(
            doc, prefix="Example", pattern=r"Example\s*(\d+[A-Z]?)", ocr_text_map=pages_text, ocr_line_map=ocr_line_map, page_numbers=page_numbers, workers=workers
        )
        all_blocks.extend(ex_blocks)
        detected_style = "heading"

        if intermediate_count >= 2:
            logger.info(
                f"🧪 同时检测到 Intermediate N ({intermediate_count}个)，合并提取"
            )
            int_blocks = _find_heading_blocks(
                doc, prefix="Intermediate", pattern=r"Intermediate\s+(\d+[A-Z]?)", ocr_text_map=pages_text, ocr_line_map=ocr_line_map, page_numbers=page_numbers, workers=workers
            )
            all_blocks.extend(int_blocks)
            detected_style = "heading_mixed"
    elif intermediate_count >= 2:
        logger.info(f"🧪 仅检测到 Intermediate N ({intermediate_count}个)")
        int_blocks = _find_heading_blocks(
            doc, prefix="Intermediate", pattern=r"Intermediate\s+(\d+[A-Z]?)", ocr_text_map=pages_text, ocr_line_map=ocr_line_map, page_numbers=page_numbers, workers=workers
        )
        all_blocks.extend(int_blocks)
        detected_style = "heading_intermediate"
    else:
        logger.warning("⚠️ 未检测到任何已知化合物编号模式")

    all_blocks.sort(key=lambda x: (x["page_no"], x["y0"]))
    logger.info(f"📋 最终找到 {len(all_blocks)} 个化合物区块")
    return all_blocks, detected_style


# ============================================================================
# 结构坐标处理
# ============================================================================

def _process_structure(s: Dict) -> Dict:
    """处理结构数据，返回标准化格式"""
    # bbox_pdf 优先，fallback 到 bbox
    for key in ("bbox_pdf", "bbox"):
        bbox_raw = s.get(key, [])
        if len(bbox_raw) == 4:
            x0_pdf, y0_pdf, x1_pdf, y1_pdf = bbox_raw
            break
    else:
        x0_pdf, y0_pdf, x1_pdf, y1_pdf = 0, 0, 0, 0
    
    page_no = s.get("page_no", s.get("page_num", 0))
    image_path = s.get(
        "image_path",
        s.get("orig_path", s.get("bnw_path", s.get("norm_path", None))),
    )
    
    return {
        "struct": s,
        "x0": x0_pdf,
        "y0": y0_pdf,
        "x1": x1_pdf,
        "y1": y1_pdf,
        "page_no": page_no,
        "idx": s["structure_index"],
        "id": s["structure_id"],
        "image_path": image_path,
    }


# ============================================================================
# V4.1 选择算法
# ============================================================================

def _select_best_structure_v4(
    candidate_structs: List[Dict],
    config: BinderConfig,
    heading_page: Optional[int] = None,
) -> Optional[Dict]:
    """V4.1 选择算法 — 同页优先，避免跨页远距离误绑。
    
    Args:
        candidate_structs: 候选结构列表
        config: 绑定配置
        heading_page: 标题所在页码（1-indexed），用于同页优先策略
    """
    if not candidate_structs:
        return None

    if len(candidate_structs) > 1:
        def _area(struct: Dict) -> float:
            return max(0.0, float(struct.get("x1", 0)) - float(struct.get("x0", 0))) * max(
                0.0, float(struct.get("y1", 0)) - float(struct.get("y0", 0))
            )

        areas = [_area(p) for p in candidate_structs]
        max_area = max(areas) if areas else 0.0
        if max_area > 0:
            large_structs = [
                p for p in candidate_structs
                if _area(p) >= max(max_area * 0.45, 4500.0)
            ]
            if large_structs:
                candidate_structs = large_structs
    
    # V4.1: 同页优先策略
    if heading_page is not None and len(candidate_structs) > 1:
        same_page_structs = [
            p for p in candidate_structs if p["page_no"] == heading_page
        ]
        if len(same_page_structs) >= 2:
            candidate_structs = same_page_structs
            logger.debug(f"   V4.1同页优先: {len(same_page_structs)}个同页候选")
        elif len(same_page_structs) == 1:
            return same_page_structs[0]
    
    max_page = max(p["page_no"] for p in candidate_structs)
    last_page_structs = [p for p in candidate_structs if p["page_no"] == max_page]
    
    if not last_page_structs:
        return max(candidate_structs, key=lambda x: x["y0"])
    
    sorted_by_y0 = sorted(last_page_structs, key=lambda x: x["y0"])
    clusters: List[List[Dict]] = []
    current_cluster = [sorted_by_y0[0]]
    for p in sorted_by_y0[1:]:
        if p["y0"] - current_cluster[-1]["y0"] < config.cluster_y_threshold:
            current_cluster.append(p)
        else:
            clusters.append(current_cluster)
            current_cluster = [p]
    clusters.append(current_cluster)
    
    max_y0_cluster = max(clusters, key=lambda c: max(p["y0"] for p in c))
    
    if len(max_y0_cluster) >= 2:
        best_cluster = max_y0_cluster
    else:
        best_cluster = None
        max_count = -1
        max_y0 = -1
        
        for cluster in clusters:
            count = len(cluster)
            cluster_y0 = max(p["y0"] for p in cluster)
            if count > max_count:
                max_count = count
                max_y0 = cluster_y0
                best_cluster = cluster
            elif count == max_count:
                if cluster_y0 > max_y0:
                    max_y0 = cluster_y0
                    best_cluster = cluster
    
    best_p = max(best_cluster, key=lambda x: x["x0"])
    return best_p


# ============================================================================
# Intermediate 过滤
# ============================================================================

_INTERMEDIATE_RE = re.compile(r"^Intermediate", re.IGNORECASE)


def _is_intermediate(item: Dict) -> bool:
    """判断一个化合物条目是否为 Intermediate（中间体）"""
    for key in ("prefix", "cpd_id", "cpd"):
        val = item.get(key, "")
        if val and _INTERMEDIATE_RE.match(str(val)):
            return True
    return False


def _filter_examples_only(items: List[Dict]) -> List[Dict]:
    """过滤掉 Intermediate，只保留 Example"""
    before = len(items)
    filtered = [item for item in items if not _is_intermediate(item)]
    removed = before - len(filtered)
    if removed > 0:
        logger.info(
            f"  [filter] 去除 {removed} 个 Intermediate，保留 {len(filtered)} 个 Example "
            f"(总共 {before})"
        )
    return filtered


def _page_text_for_page_no(pages_text: Optional[Dict[int, str]], page_no: int, include_next: bool = False) -> str:
    """Return OCR text for a 1-based PDF page without crossing to the next page by accident."""
    if not pages_text:
        return ""
    try:
        page_no_int = int(page_no)
    except Exception:
        return ""
    keys = [page_no_int - 1]
    if include_next:
        keys.append(page_no_int)
    parts: List[str] = []
    for key in keys:
        text = str((pages_text or {}).get(key, "") or "")
        if text.strip():
            parts.append(text)
    return "\n".join(parts)


def _extract_chinese_compound_sequence(pages_text: Dict[int, str]) -> List[int]:
    """Extract ordered "(化合物N)" identifiers from OCR text."""
    text = "\n".join(pages_text.get(i, "") for i in sorted(pages_text))
    nums = [int(n) for n in re.findall(r"化合\s*物\s*(\d+)", text)]
    # Keep OCR order but remove adjacent duplicates from repeated headers.
    ordered: List[int] = []
    for n in nums:
        if not ordered or ordered[-1] != n:
            ordered.append(n)
    return ordered


def _product_context_distance(pages_text: Dict[int, str], page_no: int, compound_num: int) -> int:
    fuzzy = _ocr_confusable_num_pattern(compound_num)
    fuzzy_token = rf"(?<![\dA-Za-z]){fuzzy}(?![\dA-Za-z-])"
    # For comma/range style product lists, the target number must itself be a
    # listed product token. Do not let "Examples 289-293 ... Int-12" satisfy
    # product context for Compound 12.
    list_fuzzy_token = rf"(?<![\dA-Za-z-]){fuzzy}(?![\dA-Za-z-])"
    compound_ref = (
        rf"(?:Compounds?|Cmpd|Cpd|化.?[合台]物)\s*[-:]?\s*"
        rf"(?:Cmpd|Cpd|Compound)?\s*[-:]?\s*{fuzzy_token}"
    )
    # Product context must point at an example or a compound identifier. A
    # broad "得到 ... 1" match also sees IUPAC locants in procedure text and
    # makes S1/S2 route annotations look like bare Compound 1/2 labels.
    heading_context = re.compile(
        rf"(?:Examples?|实施例)\s*{fuzzy_token}(?![\dA-Za-z-])"
        rf"|{compound_ref}\s*(?:[:：]|(?:的)?(?:preparation|synthesis|制备|合成))"
        rf"|(?:preparation|synthesis|制备|合成)[^\n]{{0,48}}{compound_ref}",
        re.IGNORECASE,
    )
    obtained_context = re.compile(
        rf"(?:得到|制备得到|分离制备得到)[^\n]{{0,80}}{compound_ref}",
        re.IGNORECASE,
    )

    # Chinese patents often combine enantiomer/product pairs in one heading:
    # "实施例51，52  化合物51、52的合成". Treat each listed number as product
    # context so the second product is not incorrectly blocked.
    pair_context = re.compile(
        rf"(?:Examples?|Compounds?|实施例|化.?[合台]物)[^\n]{{0,140}}"
        rf"(?<![\dA-Za-z])\d{{1,3}}(?![\dA-Za-z-])"
        rf"(?:[、,，/和及\s]+|\s+and\s+){list_fuzzy_token}",
        re.IGNORECASE,
    )

    best = 999
    for page_no_candidate in (page_no - 2, page_no - 1, page_no, page_no + 1, page_no + 2):
        key = page_no_candidate - 1
        text = str(pages_text.get(key, "") or "")
        if not text.strip():
            continue
        if page_no_candidate != page_no and compound_num <= 20:
            # Low labels are common in NMR text and route annotations. Do not
            # let a neighboring page's unrelated Example 139/246 etc. make a
            # bare "1" look like product context.
            continue
        if heading_context.search(text) or obtained_context.search(text) or pair_context.search(text):
            best = min(best, abs(page_no_candidate - page_no))
    return best


def _page_has_product_context(pages_text: Dict[int, str], page_no: int, compound_num: int) -> bool:
    return _product_context_distance(pages_text, page_no, compound_num) < 999


def _line_estimated_y(line_idx: int) -> float:
    return float(line_idx) * 14.0


def _product_anchor_lines_from_text(text: str, active_bases: set[int]) -> List[Tuple[int, float, str]]:
    anchors: List[Tuple[int, float, str]] = []
    colon_anchors: List[Tuple[int, float, str]] = []
    if not text:
        return anchors
    seen: set[Tuple[int, int]] = set()
    for line_idx, line in enumerate(str(text).splitlines()):
        clean = re.sub(r"\s+", " ", line).strip()
        if not clean or re.search(r"中间体", clean):
            continue
        compact = re.sub(r"\s+", "", clean)
        for num in active_bases:
            # Avoid running several OCR-fuzzy regexes for every active compound
            # on every long OCR line. Keep the cheap gate permissive for common
            # leading-5 confusions (51 -> S1/$1), but only evaluate likely hits.
            num_text = str(num)
            maybe_num = num_text in compact
            if not maybe_num and num_text.startswith("5") and len(num_text) > 1:
                maybe_num = any((lead + num_text[1:]) in compact for lead in ("S", "s", "$", "＄"))
            if not maybe_num:
                continue
            fuzzy = _ocr_confusable_num_pattern(num)
            fuzzy_token = rf"(?<![\dA-Za-z]){fuzzy}(?![\dA-Za-z-])"
            colon_match = re.search(rf"化.?[合台]物\s*{fuzzy_token}\s*[:：]", clean, re.IGNORECASE)
            context_patterns = [
                rf"化.?[合台]物\s*{fuzzy_token}\s*的制备",
                rf"(?:步骤\s*[\dS$]+\s*[:：]\s*)?(?:[A-Za-z]{{1,6}}\s*)?{fuzzy_token}\s*的制备",
                rf"得到(?:目标)?化.?[合台]物\s*{fuzzy_token}",
                rf"分离制备(?:分别)?得到化.?[合台]物[^\n]{{0,60}}{fuzzy_token}",
                rf"得到(?:目标)?\s*{fuzzy_token}\s*[（(]?\s*\d+(?:\.\d+)?\s*m?s?g",
            ]
            if colon_match or any(re.search(pat, clean, re.IGNORECASE) for pat in context_patterns):
                key = (num, line_idx)
                if key in seen:
                    continue
                seen.add(key)
                anchor = (num, _line_estimated_y(line_idx), clean)
                anchors.append(anchor)
                if colon_match:
                    colon_anchors.append(anchor)

    def _dedupe_latest_per_compound(items: List[Tuple[int, float, str]]) -> List[Tuple[int, float, str]]:
        latest: Dict[int, Tuple[int, float, str]] = {}
        for item in items:
            num, y0, _line = item
            if num not in latest or y0 >= latest[num][1]:
                latest[num] = item
        return sorted(latest.values(), key=lambda item: item[1])

    # If explicit "化合物 N:" analysis/product subsections are present, use
    # those as the only anchors on the page. Broader title/obtained lines can
    # mention several compounds at once and are too imprecise for structure
    # pairing; they caused final products to be shifted or stolen by neighbors.
    return _dedupe_latest_per_compound(colon_anchors or anchors)


def _extract_product_section_bindings(
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    existing_bindings: List[Dict],
) -> List[Dict]:
    """Bind final products using explicit product subsection text.

    This rule is intentionally stricter than broad heading ranges: it only
    fires around lines that say "化合物 N:" / "化合物 N 的制备" /
    "得到化合物 N", and ignores intermediate sections.
    """
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return []

    product_used_structures: set[str] = set()

    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct["page_no"]), []).append(struct)

    bindings: List[Dict] = []
    for page_idx, text in sorted((pages_text or {}).items()):
        page_no = int(page_idx) + 1
        # Product-section evidence is stronger than broad OCR/heading fallbacks.
        # Do not suppress an anchor just because an earlier weak rule already
        # claimed that compound; final merge will choose the stricter rule.
        anchors = _product_anchor_lines_from_text(str(text or ""), active_bases)
        if not anchors:
            continue
        page_structs = list(by_page.get(page_no, []))
        if not page_structs:
            continue
        anchors.sort(key=lambda item: item[1])
        if len(anchors) >= 2:
            rows = _group_structures_by_row(page_structs, y_threshold=90.0)
            multi_rows = [
                row for row in rows
                if len(row) >= len(anchors)
                and all(str(p.get("id")) not in product_used_structures for p in row)
            ]
            if multi_rows:
                row = max(multi_rows, key=lambda r: (sum((float(p.get("x1", 0)) - float(p.get("x0", 0))) * (float(p.get("y1", 0)) - float(p.get("y0", 0))) for p in r), max(float(p.get("y0") or 0) for p in r)))
                for (compound_num, _anchor_y, _line), struct in zip(anchors, row):
                    binding = _build_binding_from_structure(struct, str(compound_num))
                    binding["binding_rule"] = "product_section_context"
                    binding["candidates"] = len(row)
                    bindings.append(binding)
                    product_used_structures.add(str(struct.get("id")))
                continue

        for idx, (compound_num, anchor_y, _line) in enumerate(anchors):
            next_y = anchors[idx + 1][1] if idx + 1 < len(anchors) else 10**9
            candidates = [
                p for p in page_structs
                if str(p.get("id")) not in product_used_structures
                and float(p.get("y0") or 0) <= anchor_y + 80.0
                and float(p.get("y1") or p.get("y0") or 0) >= max(0.0, anchor_y - 260.0)
                and float(p.get("y0") or 0) < next_y + 20.0
            ]
            if not candidates:
                continue

            def _area(struct: Dict) -> float:
                return max(0.0, float(struct.get("x1", 0)) - float(struct.get("x0", 0))) * max(
                    0.0, float(struct.get("y1", 0)) - float(struct.get("y0", 0))
                )

            best = max(candidates, key=lambda p: (_area(p), -abs(float(p.get("y0") or 0) - anchor_y)))
            binding = _build_binding_from_structure(best, str(compound_num))
            binding["binding_rule"] = "product_section_context"
            binding["candidates"] = len(candidates)
            bindings.append(binding)
            product_used_structures.add(str(best.get("id")))

    return bindings


def _product_structures_from_triplets(processed_structures: List[Dict]) -> List[Dict]:
    """For Chinese synthesis pages, DECIMER returns reagent/reagent/product triplets.

    The right-most structure in each row is the target product.
    """
    rows: List[List[Dict]] = []
    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_structs = sorted(
            [p for p in processed_structures if p["page_no"] == page_no],
            key=lambda p: (p["y0"], p["x0"]),
        )
        page_rows: List[List[Dict]] = []
        for struct in page_structs:
            if not page_rows or abs(struct["y0"] - page_rows[-1][0]["y0"]) > 90:
                page_rows.append([struct])
            else:
                page_rows[-1].append(struct)
        rows.extend(page_rows)

    products: List[Dict] = []
    for row in rows:
        if len(row) >= 3:
            products.append(max(row, key=lambda p: p["x0"]))
    return products


# Match OCR numeric labels for final compounds on Chinese synthesis pages.
# Accept: hyphenated variants (1-1, 1-2, 4-1, 12-1) — these are target compounds.
# Reject: bare single digits (1–9) — these are intermediate step numbers
# in Chinese multi-step synthesis routes (e.g. "第一步 → 化合物1a").
# Reject: lettered labels (1a, 2b) — intermediate compounds.
_FINAL_COMPOUND_LABEL_RE = re.compile(r"^[1-9]\d*(?:-[12])$")
_BARE_FINAL_LABEL_RE = re.compile(r"^[1-9]\d*$")
_SPLIT_PAIR_RE = re.compile(
    r"(?<!\d)([1-9]\d*)\s*[-—–]\s*1.{0,160}?\1\s*[-—–]\s*2(?!\d)"
)
_CPD_LETTER_PAIR_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:Cpd|Cmpd|Compound|化合物)\s*[-:]?\s*([1-9]\d{0,2})"
    r"(?![A-Za-z0-9-]).{0,120}?"
    r"(?:Cpd|Cmpd|Compound|化合物)\s*[-:]?\s*\1\s*A(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_TABLE_ROW_RE = re.compile(r"^\s*(\d{1,3})(?=\s|$)")
_PRODUCT_VISIBLE_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:examples?|cmpd|cpd|compound|实施例|化合物)\s*[-.:]?\s*([1-9]\d{0,2}[A-Z]?)(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
_DIRECT_LABEL_RE = re.compile(r"(?<![A-Za-z0-9])([1-9]\d{0,2}[A-Z]?)(?![A-Za-z0-9-])", re.IGNORECASE)
_ROUTE_STEP_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:step|s)\s*[-.:]?\s*([1-9]\d{0,2})(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
_RACEMIC_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:rac|racemic)\s*[-.:]?\s*(?:cmpd|cpd|compound)?\s*[-.:]?\s*([1-9]\d{0,2}[A-Z]?)(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
_VISIBLE_LABEL_CACHE_VERSION = 7
_VISIBLE_LABEL_SOURCE_RANK = {
    "page_strict": 0,
    "direct": 1,
    "page_wide": 2,
    "pdf_clip": 3,
}
_STRICT_VISIBLE_LABEL_SOURCES = {"page_strict", "direct", "pdf_clip"}
_VISUAL_LABEL_SOURCES = _STRICT_VISIBLE_LABEL_SOURCES | {"page_wide"}


def _int_or_default(value: Any, default: int = 999) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def _normalise_compound_label(text: str) -> str:
    text = text.strip()
    text = text.strip("()[]{}.,;:，。；：")
    text = text.replace("—", "-").replace("–", "-").replace("_", "-")
    if re.fullmatch(r"[1-9]\d*(?:-\d+)?[A-Z]?", text, re.IGNORECASE):
        text = text.upper()
    # NOTE: Do NOT auto-split "42" → "4-2". This caused many misbindings.
    # Only accept labels that already have hyphens (e.g. "1-1", "4-2").
    return text


def _cpd_sort_key(value: str):
    label = _normalise_compound_label(str(value or ""))
    parts = re.findall(r"\d+|\D+", label)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def _direct_labels_from_structure_image(struct: Dict) -> List[str]:
    """OCR labels embedded in/under a structure crop.

    Some final product labels are cropped together with the drawing, so whole
    page OCR may miss them. Keep this narrow: only bare 2-3 digit labels are
    accepted; lettered labels such as 17h/44b remain intermediates.
    """
    image_path = str(struct.get("image_path") or "")
    if not image_path or not os.path.exists(image_path):
        return []
    try:
        from PIL import Image
        if _allow_tesseract_fallback():
            import pytesseract  # type: ignore
        else:
            pytesseract = None
    except Exception:
        return []

    labels: List[str] = []
    try:
        img = Image.open(image_path).convert("L")
        width, height = img.size
        # Only inspect the bottom label band. OCR-ing the whole structure
        # catches reagent numbers, page fragments, or substituent annotations
        # and can steal a binding from the actual compound label.
        crops = [
            img.crop((0, int(height * 0.72), width, height)),
            img.crop((int(width * 0.15), int(height * 0.62), int(width * 0.85), height)),
        ]
        for crop in crops:
            ocr_texts = _paddlex_ocr_texts_from_image(crop)
            if not ocr_texts:
                if pytesseract is None:
                    continue
                text = pytesseract.image_to_string(crop, lang="eng", config="--psm 6")
                ocr_texts = [text]
            for text in ocr_texts:
                for value in _labels_from_ocr_text(str(text or "")):
                    if value not in labels:
                        labels.append(value)
    except Exception:
        return labels
    return labels


def _labels_from_ocr_texts(ocr_texts: List[str]) -> List[str]:
    labels: List[str] = []
    for text in ocr_texts or []:
        for value in _labels_from_ocr_text(str(text or "")):
            if value not in labels:
                labels.append(value)
    return labels


def _labels_from_ocr_text(text: str) -> List[str]:
    """Return visible product-label tokens while preserving route step guards."""
    raw_text = str(text or "")
    blocked_spans = [
        match.span(1)
        for pattern in (_ROUTE_STEP_LABEL_RE, _RACEMIC_LABEL_RE)
        for match in pattern.finditer(raw_text)
    ]
    protected_spans = [
        *blocked_spans,
        *[match.span(1) for match in _PRODUCT_VISIBLE_LABEL_RE.finditer(raw_text)],
    ]
    labels: List[str] = []
    for match in _PRODUCT_VISIBLE_LABEL_RE.finditer(raw_text):
        span = match.span(1)
        if any(span[0] < blocked[1] and blocked[0] < span[1] for blocked in blocked_spans):
            continue
        value = match.group(1).upper()
        if value not in labels:
            labels.append(value)
    for match in _DIRECT_LABEL_RE.finditer(raw_text):
        span = match.span(1)
        if any(span[0] < protected[1] and protected[0] < span[1] for protected in protected_spans):
            continue
        value = match.group(1).upper()
        if value not in labels:
            labels.append(value)
    return labels


def _nearby_ocr_label_kind(
    struct: Dict,
    label_key: str,
    lines_by_page: Optional[Dict[int, List[Tuple[float, str]]]],
) -> str:
    """Classify a visual module's nearest OCR label as product or precursor."""
    if not label_key or not lines_by_page:
        return ""
    page_idx = int(struct.get("page_no") or 0) - 1
    y0 = float(struct.get("y0") or 0)
    y1 = float(struct.get("y1") or y0)
    best: Tuple[float, str] | None = None
    label_pat = re.escape(label_key)
    for line_y, text in lines_by_page.get(page_idx, []):
        if not (y0 - 24 <= float(line_y) <= y1 + 28):
            continue
        compact = re.sub(r"\s+", "", str(text or ""))
        if re.search(rf"(?:Rac|Racemic)-?(?:Cmpd|Cpd|Compound)-?{label_pat}(?!\d)", compact, re.IGNORECASE):
            rank = (abs(float(line_y) - y1), "racemic")
        elif re.search(rf"(?:Cmpd|Cpd|Compound)-?{label_pat}(?!\d)", compact, re.IGNORECASE):
            rank = (abs(float(line_y) - y1), "product")
        else:
            continue
        if best is None or rank[0] < best[0]:
            best = rank
    return best[1] if best else ""


def _nearby_exact_product_label(
    struct: Dict,
    label_key: str,
    lines_by_page: Optional[Dict[int, List[Tuple[float, str]]]],
    row: Optional[List[Dict]] = None,
) -> str:
    """Return the nearest Cpd-style product label text for a structure."""
    if not label_key or not lines_by_page:
        return ""
    page_idx = int(struct.get("page_no") or 0) - 1
    y0 = float(struct.get("y0") or 0)
    y1 = float(struct.get("y1") or y0)
    labels: List[Tuple[float, float, str]] = []
    for line_y, text in lines_by_page.get(page_idx, []):
        if not (y0 - 18 <= float(line_y) <= y1 + 40):
            continue
        value = str(text or "").strip()
        if _RACEMIC_LABEL_RE.search(value):
            continue
        for match in _PRODUCT_VISIBLE_LABEL_RE.finditer(value):
            label = match.group(1).upper()
            labels.append((abs(float(line_y) - y1), float(line_y), label))
    if not labels:
        return ""
    labels.sort(key=lambda item: (item[0], item[1]))
    nearest = labels[0]
    if nearest[2] != label_key and nearest[0] <= 42.0:
        return nearest[2]
    same_base = [item for item in labels if re.match(rf"^{re.escape(label_key)}[A-Z]?$", item[2])]
    if not same_base:
        return ""
    same_base.sort(key=lambda item: (item[1], item[0]))
    if len(same_base) > 1:
        row_labels = [item[2] for item in same_base if abs(item[1] - same_base[0][1]) <= 3.0]
        if len(row_labels) > 1 and row:
            row_labels = sorted(row_labels, key=lambda label: (len(label), label))
            # The OCR cache lacks x coordinates for these label lines. In
            # Chinese paired product rows the labels are printed left-to-right.
            # If a reaction row also contains unlabeled precursors, those are
            # typically to the left of the labeled final products.
            row_sorted = sorted(row, key=lambda item: float(item.get("x0") or 0))
            if len(row_sorted) > len(row_labels):
                row_sorted = row_sorted[-len(row_labels):]
            sid = str(struct.get("id") or "")
            try:
                position = next(
                    idx for idx, item in enumerate(row_sorted)
                    if str(item.get("id") or "") == sid
                )
            except StopIteration:
                position = -1
            if 0 <= position < len(row_labels):
                return row_labels[position]
            return ""
    return same_base[0][2]


def _row_for_structure(
    struct: Dict,
    rows_by_page: Optional[Dict[int, List[List[Dict]]]],
) -> Optional[List[Dict]]:
    if not rows_by_page:
        return None
    sid = str(struct.get("id") or "")
    page_no = int(struct.get("page_no") or 0)
    for row in rows_by_page.get(page_no, []):
        if any(str(item.get("id") or "") == sid for item in row):
            return row
    return None


def _passes_exact_visual_label_guard(
    struct: Dict,
    label_key: str,
    lines_by_page: Optional[Dict[int, List[Tuple[float, str]]]],
    row: Optional[List[Dict]] = None,
) -> Tuple[bool, str]:
    """Fail closed when nearby visible Cpd labels prove a suffix mismatch."""
    exact_label = _nearby_exact_product_label(struct, label_key, lines_by_page, row=row)
    if exact_label and exact_label != label_key:
        return False, exact_label
    return True, exact_label


def _normalise_visible_cache_item(cache_item: Any) -> List[Dict[str, str]]:
    if not isinstance(cache_item, dict):
        return []
    raw_labels = cache_item.get("visible_label_candidates")
    if raw_labels is None:
        raw_labels = cache_item.get("visible_labels") or []
    candidates: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for item in raw_labels:
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            source = str(item.get("source") or cache_item.get("source") or "cache").strip() or "cache"
        else:
            label = str(item or "").strip()
            source = str(cache_item.get("source") or "cache").strip() or "cache"
        if not label:
            continue
        key = (label, source)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"label": label, "source": source})
    return candidates


def _labels_from_visible_cache_item(cache_item: Any) -> List[str]:
    labels: List[str] = []
    for item in _normalise_visible_cache_item(cache_item):
        label = str(item.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def _refine_visible_label_cache_with_page_ocr(
    processed_structures: List[Dict],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]],
    output_dir: str,
    profile: Optional[dict] = None,
) -> Dict[str, Dict]:
    """Use full-page OCR label rows to restore suffixes lost by tight crops."""
    if not visible_label_cache or not ocr_line_map:
        return visible_label_cache or {}
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    if not lines_by_page:
        return visible_label_cache
    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    rows_by_page: Dict[int, List[List[Dict]]] = {}
    for page_no in sorted({int(struct.get("page_no") or 0) for struct in processed_structures}):
        rows_by_page[page_no] = _group_structures_by_row(
            [struct for struct in processed_structures if int(struct.get("page_no") or 0) == page_no],
            y_threshold=55.0,
        )

    refined: Dict[str, Dict] = {}
    changed = 0
    for sid, cache_item in visible_label_cache.items():
        item = dict(cache_item) if isinstance(cache_item, dict) else {}
        struct = struct_by_id.get(str(sid))
        if not struct or not item:
            changed += 1
            continue
        if not _visible_cache_item_matches_structure(item, struct):
            changed += 1
            continue
        candidates: List[Dict[str, str]] = []
        for candidate in _normalise_visible_cache_item(item):
            label = _normalise_compound_label(str(candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if not key:
                continue
            base_num = _base_cpd_num(key)
            base_key = str(base_num) if base_num is not None else key
            nearby_kind = _nearby_ocr_label_kind(struct, base_key, lines_by_page)
            if nearby_kind == "racemic":
                changed += 1
                continue
            exact = _nearby_exact_product_label(
                struct,
                base_key,
                lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
            if exact and exact != key and (
                _base_cpd_num(exact) == base_num
                or _is_truncated_visible_prefix(exact, key)
                or _is_truncated_visible_prefix(key, exact)
            ):
                label = exact
                changed += 1
            updated = dict(candidate)
            updated["label"] = label
            candidates.append(updated)
        if candidates:
            item["visible_label_candidates"] = candidates
            item["visible_labels"] = []
            for candidate in candidates:
                label = str(candidate.get("label") or "").strip()
                if label and label not in item["visible_labels"]:
                    item["visible_labels"].append(label)
            item["page_ocr_refined"] = True
        refined[str(sid)] = item

    if changed:
        try:
            path = _visible_label_cache_path(output_dir, profile)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(refined, f, ensure_ascii=False, indent=2)
            logger.info("   👁 页面OCR校正可见编号缓存: %d candidates -> %s", changed, path)
        except Exception as exc:
            logger.warning("   页面OCR校正可见编号缓存写入失败: %s", exc)
    return refined


def _visible_label_candidates_for_structure(
    struct: Dict,
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict[str, str]]:
    cache_item = (visible_label_cache or {}).get(str(struct.get("id") or ""))
    if not _visible_cache_item_matches_structure(cache_item, struct):
        return []
    return _normalise_visible_cache_item(cache_item)


def _annotate_bindings_with_visible_labels(
    bindings: List[Dict],
    visible_label_cache: Optional[Dict[str, Dict]],
) -> List[Dict]:
    if not bindings or not visible_label_cache:
        return bindings
    annotated: List[Dict] = []
    for binding in bindings:
        item = dict(binding)
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        candidates = _normalise_visible_cache_item((visible_label_cache or {}).get(sid))
        if candidates:
            labels: List[str] = []
            sources: List[str] = []
            label_sources: Dict[str, List[str]] = {}
            normalized_candidates: List[Dict[str, str]] = []
            for candidate in candidates:
                label = _normalise_compound_label(str(candidate.get("label") or ""))
                if label and label not in labels:
                    labels.append(label)
                source = str(candidate.get("source") or "")
                if source and source not in sources:
                    sources.append(source)
                if label:
                    label_sources.setdefault(label, [])
                    if source and source not in label_sources[label]:
                        label_sources[label].append(source)
                    normalized_candidates.append({"label": label, "source": source})
            item["visible_labels"] = labels
            item["visible_label_candidates"] = normalized_candidates
            item["visible_label_sources"] = label_sources
            if not item.get("visible_label") and len(labels) == 1:
                item["visible_label"] = labels[0]
            if not item.get("visible_label_crop_source") and sources:
                item["visible_label_crop_source"] = sources[0]
        annotated.append(item)
    return annotated


def _contextual_visible_label_candidates(
    struct: Dict,
    candidates: List[Dict[str, str]],
    active_keys_or_bases,
    pages_text: Optional[Dict[int, str]],
    max_context_distance: int = 1,
    lines_by_page: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    row: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """Return visual label candidates proven by activity set and context.

    OCR can read multiple numbers from a wide crop. Treat the label as binding
    evidence only when it is active and the page text has nearby product context
    for that exact number. This prevents neighboring/intermediate labels from
    hijacking a final compound.
    """
    ranked: List[Tuple[int, int, int, int, int, Dict[str, Any]]] = []
    page_no = int(struct.get("page_no") or 0)
    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    route_like = 1 if (height > 0 and width / max(height, 1.0) > 5.5) else 0
    multi_label = 1 if len({str(c.get("label") or "").strip() for c in candidates if c.get("label")}) > 1 else 0
    active_keys = {str(item).upper() for item in (active_keys_or_bases or set())}
    visible_candidate_bases: List[int] = []
    for candidate in candidates:
        label_key = _cpd_label_key(_normalise_compound_label(str(candidate.get("label") or "").strip()))
        base = _base_cpd_num(label_key)
        if base is not None:
            visible_candidate_bases.append(base)
    max_visible_candidate_base = max(visible_candidate_bases) if visible_candidate_bases else 0
    for candidate in candidates:
        label = _normalise_compound_label(str(candidate.get("label") or "").strip())
        if not re.fullmatch(r"[1-9]\d{0,2}[A-Z]?", label, re.IGNORECASE):
            continue
        label_key = _cpd_label_key(label)
        if label_key not in active_keys:
            continue
        compound_num = _base_cpd_num(label) or 0
        exact_label = _nearby_exact_product_label(struct, label_key, lines_by_page, row=row)
        if exact_label and exact_label != label_key:
            continue
        if multi_label and compound_num <= 20 and exact_label != label_key:
            continue
        distance = 0
        if pages_text is not None:
            distance = _product_context_distance(pages_text, page_no, compound_num)
            if distance > max_context_distance:
                continue
        source = str(candidate.get("source") or "ocr").strip() or "ocr"
        item: Dict[str, Any] = {
            "label": label,
            "label_key": label_key,
            "source": source,
            "product_context_distance": distance,
            "multi_label_crop": bool(multi_label),
        }
        internal_low_rank = 1 if (
            multi_label
            and compound_num <= 20
            and max_visible_candidate_base >= max(50, compound_num + 30)
        ) else 0
        ranked.append((
            internal_low_rank,
            distance,
            _VISIBLE_LABEL_SOURCE_RANK.get(source, 99),
            multi_label,
            route_like,
            item,
        ))
    ranked.sort(key=lambda row: row[:4])
    if not ranked:
        return []
    # One structure crop should contribute one final compound. If a wide crop
    # sees neighbors too, keep only the context-proven best label.
    return [ranked[0][5]]


def _visible_label_cache_path(output_dir: str, profile: Optional[dict] = None) -> Path:
    explicit = (profile or {}).get("visible_labels_path") or (profile or {}).get("visible_label_cache")
    if explicit:
        return Path(str(explicit))
    return Path(output_dir).parent / "visible_labels" / "visible_labels.json"


def _paddlex_ocr_texts_batch(images: List[Any], workers: int = 4, timeout: float = 12.0) -> List[List[str]]:
    """Run PaddleX OCR for many crops concurrently while preserving order.

    The deployed PaddleX endpoint accepts one image per request. This wrapper is
    the batch boundary for binder: all label crops are scheduled here once, then
    cached, so strict/wide/direct passes do not repeatedly OCR the same module.
    """
    if not images:
        return []
    max_workers = max(1, min(int(workers or 1), len(images)))
    if max_workers <= 1:
        return [_paddlex_ocr_texts_from_image(img, timeout=timeout) for img in images]

    results: List[List[str]] = [[] for _ in images]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_paddlex_ocr_texts_from_image, img, timeout): idx
            for idx, img in enumerate(images)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = []
    return results


def _visible_label_crop_tasks_from_page_image(struct: Dict, include_wide: bool = True) -> List[Tuple[str, Any]]:
    raw = struct.get("struct") or {}
    bbox = raw.get("bbox") or []
    if len(bbox) != 4:
        return []

    image_path = str(struct.get("image_path") or "")
    if not image_path:
        return []
    page_no = int(struct.get("page_no") or 0)
    page_image = Path(image_path).with_name(f"page_{page_no:03d}.png")
    if not page_image.is_file():
        return []

    try:
        from PIL import Image, ImageEnhance, ImageOps
    except Exception:
        return []

    try:
        img = Image.open(page_image).convert("L")
        x0, y0, x1, y1 = [int(round(float(v))) for v in bbox]
    except Exception:
        return []

    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    strict_boxes = [
        (x0 + int(0.25 * width), y1 - int(0.05 * height), x1 - int(0.25 * width), y1 + max(16, int(0.16 * height))),
        (x0 + int(0.25 * width), y0 + int(0.70 * height), x1 - int(0.25 * width), y1),
        (x0 + int(0.35 * width), y1 - int(0.02 * height), x1 - int(0.35 * width), y1 + max(20, int(0.18 * height))),
    ]
    normal_boxes = [
        (x0 + int(0.18 * width), y0 + int(0.58 * height), x1 - int(0.18 * width), y1 + max(8, int(0.10 * height))),
        (x0 + int(0.05 * width), y0 + int(0.52 * height), x1 - int(0.05 * width), y1 + max(18, int(0.22 * height))),
    ]
    wide_boxes = [
        (x0, y0 + int(0.45 * height), x1, y1 + max(28, int(0.32 * height))),
        (x0 + int(0.10 * width), y0 + int(0.35 * height), x1 - int(0.10 * width), y1 + max(36, int(0.38 * height))),
    ] if include_wide else []

    tasks: List[Tuple[str, Any]] = []
    source_boxes = [("page_strict", strict_boxes)]
    if include_wide:
        source_boxes.append(("page_wide", normal_boxes + wide_boxes))
    for source, boxes in source_boxes:
        for box in boxes:
            left = max(0, box[0])
            top = max(0, box[1])
            right = min(img.width, box[2])
            bottom = min(img.height, box[3])
            if right - left <= 5 or bottom - top <= 5:
                continue
            try:
                crop = img.crop((left, top, right, bottom))
                crop = ImageOps.autocontrast(crop)
                crop = crop.resize((crop.width * 3, crop.height * 3))
                crop = ImageEnhance.Sharpness(crop).enhance(2.0)
            except Exception:
                continue
            tasks.append((source, crop))
    return tasks


def _visible_label_crop_tasks_from_structure_image(struct: Dict) -> List[Tuple[str, Any]]:
    image_path = str(struct.get("image_path") or "")
    if not image_path or not os.path.exists(image_path):
        return []
    try:
        from PIL import Image
    except Exception:
        return []
    try:
        img = Image.open(image_path).convert("L")
        width, height = img.size
        return [
            ("direct", img.crop((0, int(height * 0.72), width, height))),
            ("direct", img.crop((int(width * 0.15), int(height * 0.62), int(width * 0.85), height))),
        ]
    except Exception:
        return []


def _precompute_visible_label_cache(
    processed_structures: List[Dict],
    output_dir: str,
    profile: Optional[dict],
    existing_cache: Optional[Dict[str, Dict]],
    workers: int = 4,
) -> Dict[str, Dict]:
    """Precompute visible structure labels once and persist them for reuse."""
    cache = _filter_visible_label_cache_for_structures(existing_cache, processed_structures)
    path = _visible_label_cache_path(output_dir, profile)
    pending = [
        struct for struct in processed_structures
        if str(struct.get("id") or "")
        and not _visible_cache_item_matches_structure(cache.get(str(struct.get("id") or "")), struct)
    ]
    if not pending:
        logger.info("   👁 结构可见编号缓存已完整: %s (%d structures)", path, len(cache))
        return cache

    logger.info("   👁 批量PaddleX识别结构可见编号: %d structures, workers=%d", len(pending), max(1, int(workers or 1)))

    def _run_stage(stage_name: str, task_builder) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
        flat_images: List[Any] = []
        flat_meta: List[Tuple[str, str]] = []
        attempts: Dict[str, int] = {}
        for struct in pending:
            sid = str(struct.get("id") or "")
            if not sid:
                continue
            tasks = task_builder(struct)
            attempts[sid] = attempts.get(sid, 0) + len(tasks)
            for source, crop in tasks:
                flat_meta.append((sid, source))
                flat_images.append(crop)
        if not flat_images:
            return {}, attempts
        ocr_results = _paddlex_ocr_texts_batch(flat_images, workers=workers, timeout=12.0)
        labels_by_sid: Dict[str, List[str]] = {}
        for (sid, source), ocr_texts in zip(flat_meta, ocr_results):
            for label in _labels_from_ocr_texts(ocr_texts):
                entry = f"{label}|{source}"
                if entry not in labels_by_sid.setdefault(sid, []):
                    labels_by_sid[sid].append(entry)
        logger.info(
            "   👁 %s OCR: %d crops, %d structures with labels",
            stage_name,
            len(flat_images),
            len(labels_by_sid),
        )
        return labels_by_sid, attempts

    strict_by_sid, strict_attempts = _run_stage(
        "strict",
        lambda struct: [
            task for task in _visible_label_crop_tasks_from_page_image(struct, include_wide=False)
            if task[0] == "page_strict"
        ],
    )
    unresolved_after_strict = {
        str(struct.get("id") or "")
        for struct in pending
        if str(struct.get("id") or "") and str(struct.get("id") or "") not in strict_by_sid
    }

    def _wide_direct_tasks(struct: Dict) -> List[Tuple[str, Any]]:
        sid = str(struct.get("id") or "")
        if sid not in unresolved_after_strict:
            return []
        page_tasks = [
            task for task in _visible_label_crop_tasks_from_page_image(struct, include_wide=True)
            if task[0] == "page_wide"
        ]
        return page_tasks + _visible_label_crop_tasks_from_structure_image(struct)

    wide_by_sid, wide_attempts = _run_stage("wide/direct", _wide_direct_tasks)

    if _PADDLEX_OCR_AVAILABLE is False:
        logger.warning("   PaddleX OCR不可用，跳过可见编号缓存写入，避免缓存空结果")
        return cache

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    for struct in pending:
        sid = str(struct.get("id") or "")
        if not sid:
            continue
        candidates: List[Dict[str, str]] = []
        seen_labels: set[str] = set()
        for packed in (strict_by_sid.get(sid) or []) + (wide_by_sid.get(sid) or []):
            label, source = packed.split("|", 1)
            if label in seen_labels:
                continue
            seen_labels.add(label)
            candidates.append({"label": label, "source": source})
        candidates.sort(key=lambda item: (
            _VISIBLE_LABEL_SOURCE_RANK.get(str(item.get("source") or ""), 99),
            _cpd_sort_key(str(item.get("label") or "")),
        ))
        cache[sid] = {
            **artifact_identity(VISIBLE_LABEL_CACHE_SCHEMA, VISIBLE_LABEL_CACHE_SCHEMA_VERSION),
            "structure_id": sid,
            "page_no": int(struct.get("page_no") or 0),
            "structure_signature": _structure_cache_signature(struct),
            "visible_labels": [item["label"] for item in candidates],
            "visible_label_candidates": candidates,
            "ocr_backend": "paddlex",
            "cache_version": _VISIBLE_LABEL_CACHE_VERSION,
            "cache_complete": True,
            "ocr_attempts": int(strict_attempts.get(sid, 0) + wide_attempts.get(sid, 0)),
            "updated_at": now,
        }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        label_count = sum(1 for item in cache.values() if _labels_from_visible_cache_item(item))
        logger.info("   👁 写入结构可见编号缓存: %s (%d/%d with labels)", path, label_count, len(cache))
    except Exception as exc:
        logger.warning("   可见编号缓存写入失败 %s: %s", path, exc)
    return cache


def _ocr_visible_label_band(doc, struct: Dict, dpi: int = 450) -> List[str]:
    """OCR the visual label band around a structure on the original PDF page.

    This deliberately uses the page image, not surrounding text blocks. It
    expands slightly below the structure because final labels are often printed
    just outside the structure crop.
    """
    page_no = int(struct.get("page_no") or 0)
    if page_no < 1 or page_no > len(doc):
        return []
    try:
        if _allow_tesseract_fallback():
            import pytesseract  # type: ignore
        else:
            pytesseract = None
        from io import BytesIO

        from PIL import Image
    except Exception:
        return []

    x0 = float(struct.get("x0") or 0)
    y0 = float(struct.get("y0") or 0)
    x1 = float(struct.get("x1") or x0)
    y1 = float(struct.get("y1") or y0)
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)
    page = doc[page_no - 1]
    labels: List[str] = []

    clips = [
        # Bottom-center strip, often where the compound number is printed.
        fitz.Rect(
            max(0, x0 + 0.18 * width),
            max(0, y1 - max(18.0, 0.22 * height)),
            min(page.rect.width, x1 - 0.18 * width),
            min(page.rect.height, y1 + max(32.0, 0.28 * height)),
        ),
        # A slightly wider lower band catches labels just below the crop while
        # still avoiding prose text and reaction annotations elsewhere.
        fitz.Rect(
            max(0, x0 + 0.08 * width),
            max(0, y1 - max(12.0, 0.12 * height)),
            min(page.rect.width, x1 - 0.08 * width),
            min(page.rect.height, y1 + max(42.0, 0.34 * height)),
        ),
    ]
    for clip in clips:
        if clip.width <= 3 or clip.height <= 3:
            continue
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=clip)
            img = Image.open(BytesIO(pix.tobytes("png"))).convert("L")
            ocr_texts = _paddlex_ocr_texts_from_image(img)
            if not ocr_texts:
                if pytesseract is None:
                    continue
                text = pytesseract.image_to_string(
                    img,
                    lang="eng",
                    config="--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-",
                )
                ocr_texts = [text]
        except Exception:
            continue
        for text in ocr_texts:
            for value in _labels_from_ocr_text(str(text or "")):
                if value not in labels:
                    labels.append(value)
    return labels


def _ocr_visible_label_band_from_page_image(struct: Dict, wide: bool = False) -> List[str]:
    """OCR the label band using the rendered page image and image-coordinate bbox.

    Step 6 stores both PDF coordinates and rendered-page pixel coordinates. The
    small bold labels under Chinese patent structures are often much more
    readable on the rendered page image than through PDF text extraction or a
    PDF-coordinate clip. This intentionally inspects only the lower part of the
    structure crop, where the visual compound label is printed.
    """
    raw = struct.get("struct") or {}
    bbox = raw.get("bbox") or []
    if len(bbox) != 4:
        return []

    image_path = str(struct.get("image_path") or "")
    if not image_path:
        return []
    page_no = int(struct.get("page_no") or 0)
    page_image = Path(image_path).with_name(f"page_{page_no:03d}.png")
    if not page_image.is_file():
        return []

    try:
        if _allow_tesseract_fallback():
            import pytesseract  # type: ignore
        else:
            pytesseract = None
        from PIL import Image, ImageEnhance, ImageOps
    except Exception:
        return []

    try:
        img = Image.open(page_image).convert("L")
    except Exception:
        return []

    try:
        x0, y0, x1, y1 = [int(round(float(v))) for v in bbox]
    except Exception:
        return []
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    def _read_boxes(crop_boxes: List[Tuple[int, int, int, int]]) -> List[str]:
        labels: List[str] = []
        for box in crop_boxes:
            left = max(0, box[0])
            top = max(0, box[1])
            right = min(img.width, box[2])
            bottom = min(img.height, box[3])
            if right - left <= 5 or bottom - top <= 5:
                continue
            try:
                crop = img.crop((left, top, right, bottom))
                crop = ImageOps.autocontrast(crop)
                crop = crop.resize((crop.width * 3, crop.height * 3))
                crop = ImageEnhance.Sharpness(crop).enhance(2.0)
            except Exception:
                continue
            ocr_texts = _paddlex_ocr_texts_from_image(crop)
            if not ocr_texts:
                if pytesseract is None:
                    continue
                try:
                    text = pytesseract.image_to_string(
                        crop,
                        lang="eng",
                        config="--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-",
                    )
                    ocr_texts = [text]
                except Exception:
                    continue
            for text in ocr_texts:
                for value in _labels_from_ocr_text(str(text or "")):
                    if value not in labels:
                        labels.append(value)
        return labels

    strict_boxes = [
        # Read the printed label itself, not surrounding chemistry/prose. This
        # prevents 101-style labels from being misread as another active number.
        (x0 + int(0.25 * width), y1 - int(0.05 * height), x1 - int(0.25 * width), y1 + max(16, int(0.16 * height))),
        (x0 + int(0.25 * width), y0 + int(0.70 * height), x1 - int(0.25 * width), y1),
        (x0 + int(0.35 * width), y1 - int(0.02 * height), x1 - int(0.35 * width), y1 + max(20, int(0.18 * height))),
    ]
    strict_labels = _read_boxes(strict_boxes)
    if strict_labels:
        return strict_labels

    crop_boxes = [
        # Most labels sit inside the lower third of the structure crop.
        (x0 + int(0.18 * width), y0 + int(0.58 * height), x1 - int(0.18 * width), y1 + max(8, int(0.10 * height))),
        # Wider lower band catches labels below long horizontal structures, but
        # only after strict label boxes fail.
        (x0 + int(0.05 * width), y0 + int(0.52 * height), x1 - int(0.05 * width), y1 + max(18, int(0.22 * height))),
    ]
    if wide:
        crop_boxes.extend([
            (x0, y0 + int(0.45 * height), x1, y1 + max(28, int(0.32 * height))),
            (x0 + int(0.10 * width), y0 + int(0.35 * height), x1 - int(0.10 * width), y1 + max(36, int(0.38 * height))),
        ])
    return _read_boxes(crop_boxes)


def _load_visible_label_cache(output_dir: str, profile: Optional[dict] = None) -> Dict[str, Dict]:
    """Load precomputed structure-label OCR cache when available.

    The cache is intentionally optional: if a run has not generated it yet,
    binder falls back to per-structure visual OCR. When present, however, these
    labels are the highest-priority binding evidence because they come from the
    drawing/label region itself rather than prose text.
    """
    candidates: List[Path] = []
    explicit = (profile or {}).get("visible_labels_path") or (profile or {}).get("visible_label_cache")
    if explicit:
        candidates.append(Path(str(explicit)))

    out = Path(output_dir)
    candidates.extend([
        out / "visible_labels" / "visible_labels.json",
        out.parent / "visible_labels" / "visible_labels.json",
        out.parent.parent / "visible_labels" / "visible_labels.json",
    ])

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            logger.warning("   可见编号缓存读取失败 %s: %s", path, exc)
            continue
        if isinstance(payload, dict):
            logger.info("   👁 加载结构可见编号缓存: %s (%d structures)", path, len(payload))
            return payload
        logger.warning("   可见编号缓存格式不是 dict，忽略: %s", path)
    return {}


def _visible_labels_for_structure(
    doc,
    struct: Dict,
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    fast_only: bool = True,
) -> List[str]:
    labels: List[str] = []
    cache_item = (visible_label_cache or {}).get(str(struct.get("id") or ""))
    if _visible_cache_item_matches_structure(cache_item, struct):
        return _labels_from_visible_cache_item(cache_item)
    sources = [
        _ocr_visible_label_band_from_page_image(struct),
        _direct_labels_from_structure_image(struct),
    ]
    if not fast_only:
        sources.append(_ocr_visible_label_band(doc, struct))
    for source in sources:
        for label in source:
            if label not in labels:
                labels.append(label)
    return labels


def _group_structures_by_row(page_structs: List[Dict], y_threshold: float = 65.0) -> List[List[Dict]]:
    rows: List[List[Dict]] = []
    for struct in sorted(page_structs, key=lambda p: (p["y0"], p["x0"])):
        if not rows or abs(struct["y0"] - rows[-1][0]["y0"]) > y_threshold:
            rows.append([struct])
        else:
            rows[-1].append(struct)
    return [sorted(row, key=lambda p: p["x0"]) for row in rows]


def _structure_row_bounds(row: List[Dict]) -> Tuple[float, float, float]:
    y0 = min(float(s.get("y0") or 0) for s in row)
    y1 = max(float(s.get("y1") or s.get("y0") or 0) for s in row)
    return y0, y1, (y0 + y1) / 2.0


def _is_probable_table_structure(struct: Dict, page_structs: Optional[List[Dict]] = None) -> bool:
    """Keep table row binding focused on the left structure column."""
    geom = _structure_geometry(struct)
    area = geom["struct_area"]
    width = geom["struct_width"]
    height = geom["struct_height"]
    aspect = geom["struct_aspect"]
    x0 = float(struct.get("x0") or 0)
    if area < 5000 or width < 70 or height < 55 or aspect > 4.6:
        return False
    if x0 > 330:
        return False

    if page_structs:
        table_like = [
            p for p in page_structs
            if _structure_geometry(p)["struct_area"] >= 5000
            and 70 <= _structure_geometry(p)["struct_width"] <= 190
            and _structure_geometry(p)["struct_height"] >= 55
            and float(p.get("x0") or 0) <= 330
        ]
        if len(table_like) >= 2:
            xs = sorted(float(p.get("x0") or 0) for p in table_like)
            median_x = xs[len(xs) // 2]
            if abs(x0 - median_x) > 95:
                return False
    return True


def _is_complete_visible_product_module(struct: Dict) -> bool:
    geom = _structure_geometry(struct)
    return (
        geom["struct_area"] >= 6500
        and geom["struct_width"] >= 80
        and geom["struct_height"] >= 65
        and geom["struct_aspect"] <= 4.6
    )


def _has_strong_structure_table_row_evidence(binding: Dict) -> bool:
    """Return True when the binding is anchored by a real structure-table row.

    In Ex#/Structure/LCMS/NMR tables the authoritative product ID is often the
    left text column, not a label printed under the drawing. Internal structure
    annotations can be OCR'd as active-looking numbers, so table rows need their
    own confidence gate instead of being treated like direct visual labels.
    """
    rule = str(binding.get("binding_rule") or "")
    if rule not in {
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "cmpd_overview_table_order",
    }:
        return False
    try:
        return float(binding.get("struct_area") or 0) >= 6500
    except Exception:
        return False


def _best_table_structure_from_row(row: List[Dict], page_structs: Optional[List[Dict]] = None) -> Optional[Dict]:
    candidates = [s for s in row if _is_probable_table_structure(s, page_structs)]
    if not candidates:
        candidates = [
            s for s in row
            if _structure_geometry(s)["struct_area"] >= 4500
            and float(s.get("x0") or 0) <= 330
        ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda p: (
            abs(float(p.get("x0") or 0) - 150.0),
            -int(_structure_geometry(p)["struct_area"]),
        ),
    )


def _best_table_structure_for_row_label(
    row: List[Dict],
    label_y0: float,
    page_structs: Optional[List[Dict]] = None,
) -> Optional[Dict]:
    """Choose the product drawing on the same table row as a left ID label."""
    if not row:
        return None
    try:
        label_y = float(label_y0)
    except Exception:
        return _best_table_structure_from_row(row, page_structs)

    candidates = []
    for struct in row:
        geom = _structure_geometry(struct)
        center = (float(struct.get("y0") or 0) + float(struct.get("y1") or struct.get("y0") or 0)) / 2.0
        if abs(center - label_y) > 105.0:
            continue
        if geom["struct_area"] < 5000 or geom["struct_width"] < 70 or geom["struct_height"] < 55:
            continue
        candidates.append(struct)
    if not candidates:
        return _best_table_structure_from_row(row, page_structs)

    # In OCR line coordinates the left-column ID is vertically aligned with the
    # row. A row may also contain reagents/intermediates on the left or small
    # fragments near the ID. The final product is usually the largest complete
    # module to the right side of that row.
    return max(
        candidates,
        key=lambda struct: (
            float(struct.get("x0") or 0),
            _structure_geometry(struct)["struct_area"],
        ),
    )


def _right_complete_product_on_same_row(
    struct: Dict,
    rows_by_page: Dict[int, List[List[Dict]]],
    min_area_ratio: float = 1.05,
) -> Optional[Dict]:
    """Return a larger/right-side complete product module from the same visual row."""
    sid = str(struct.get("id") or "")
    if not sid:
        return None
    page_no = int(struct.get("page_no") or 0)
    struct_x0 = float(struct.get("x0") or 0)
    struct_area = _structure_geometry(struct)["struct_area"]
    for row in rows_by_page.get(page_no, []):
        if not any(str(item.get("id") or "") == sid for item in row):
            continue
        right_complete = [
            item for item in row
            if float(item.get("x0") or 0) > struct_x0 + 25
            and _is_complete_visible_product_module(item)
            and _structure_geometry(item)["struct_area"] >= max(struct_area * min_area_ratio, 6500)
        ]
        if not right_complete:
            return None
        return max(
            right_complete,
            key=lambda item: (
                _structure_geometry(item)["struct_area"],
                float(item.get("x0") or 0),
            ),
        )
    return None


def _has_other_active_strict_label(struct: Dict, target_key: str, visible_label_cache: Optional[Dict[str, Dict]]) -> bool:
    sid = str(struct.get("id") or "")
    for candidate in _normalise_visible_cache_item((visible_label_cache or {}).get(sid)):
        source = str(candidate.get("source") or "")
        if source not in _STRICT_VISIBLE_LABEL_SOURCES:
            continue
        key = _cpd_label_key(str(candidate.get("label") or ""))
        if key and key != target_key:
            return True
    return False


def _is_mergeable_fragment_neighbor(current: Dict, neighbor: Dict, target_key: str, visible_label_cache: Optional[Dict[str, Dict]]) -> bool:
    """Return True when adjacent DECIMER boxes look like one split molecule."""
    if int(current.get("page_no") or 0) != int(neighbor.get("page_no") or 0):
        return False
    if _has_other_active_strict_label(neighbor, target_key, visible_label_cache):
        return False

    cy0, cy1 = float(current.get("y0") or 0), float(current.get("y1") or 0)
    ny0, ny1 = float(neighbor.get("y0") or 0), float(neighbor.get("y1") or 0)
    overlap = max(0.0, min(cy1, ny1) - max(cy0, ny0))
    min_height = max(1.0, min(cy1 - cy0, ny1 - ny0))
    if overlap / min_height < 0.55:
        return False

    gap = max(float(neighbor.get("x0") or 0), float(current.get("x0") or 0)) - min(
        float(neighbor.get("x1") or 0),
        float(current.get("x1") or 0),
    )
    if gap < -8 or gap > 90:
        return False
    return True


def _save_merged_structure_crop(parts: List[Dict], output_dir: str, target_key: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Save a page-image crop covering split structure parts and return geometry."""
    if not parts:
        return None
    raw_boxes = []
    for part in parts:
        raw = part.get("struct") or {}
        bbox = raw.get("bbox") or []
        if len(bbox) != 4:
            return None
        raw_boxes.append([int(round(float(v))) for v in bbox])
    image_path = str(parts[0].get("image_path") or "")
    page_no = int(parts[0].get("page_no") or 0)
    page_image = Path(image_path).with_name(f"page_{page_no:03d}.png")
    if not page_image.is_file():
        return None
    try:
        from PIL import Image

        img = Image.open(page_image).convert("RGB")
        left = max(0, min(box[0] for box in raw_boxes) - 8)
        top = max(0, min(box[1] for box in raw_boxes) - 10)
        right = min(img.width, max(box[2] for box in raw_boxes) + 8)
        bottom = min(img.height, max(box[3] for box in raw_boxes) + 24)
        if right - left <= 10 or bottom - top <= 10:
            return None
        crop = img.crop((left, top, right, bottom))
        merged_dir = Path(output_dir) / "merged_fragments"
        merged_dir.mkdir(parents=True, exist_ok=True)
        part_ids = "_".join(str(part.get("id") or "") for part in parts)
        path = merged_dir / f"{part_ids}_compound_{target_key}.png"
        crop.save(path)
    except Exception as exc:
        logger.debug("Split-fragment crop save failed: %s", exc)
        return None

    scale = 72 / 150
    geom = {
        "struct_x0": left * scale,
        "struct_y0": top * scale,
        "struct_x1": right * scale,
        "struct_y1": bottom * scale,
        "struct_width": (right - left) * scale,
        "struct_height": (bottom - top) * scale,
        "struct_area": ((right - left) * scale) * ((bottom - top) * scale),
        "struct_aspect": (right - left) / max((bottom - top), 1),
    }
    return str(path), geom


def _merge_split_visible_label_fragments(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]],
    output_dir: str,
) -> List[Dict]:
    """Merge adjacent DECIMER fragments when the label-bearing crop is incomplete."""
    if not final_bindings or not processed_structures:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    rows_by_page: Dict[int, List[List[Dict]]] = {}
    for page_no in sorted({int(struct.get("page_no") or 0) for struct in processed_structures}):
        rows_by_page[page_no] = _group_structures_by_row(
            [struct for struct in processed_structures if int(struct.get("page_no") or 0) == page_no],
            y_threshold=55.0,
        )

    merged: List[Dict] = []
    replacements = 0
    for binding in _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache):
        item = dict(binding)
        key = _binding_label_key(item)
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        struct = struct_by_id.get(sid)
        if (
            not key
            or key not in active_keys
            or not struct
            or key not in _strict_visible_label_keys_for_binding(item)
            or _is_complete_product_like_structure(item)
        ):
            merged.append(item)
            continue

        geom = _structure_geometry(item)
        if geom["struct_area"] >= 4200 and geom["struct_width"] >= 60 and geom["struct_height"] >= 55:
            merged.append(item)
            continue

        row = next(
            (
                row
                for row in rows_by_page.get(int(struct.get("page_no") or 0), [])
                if any(str(part.get("id") or "") == sid for part in row)
            ),
            [],
        )
        if not row:
            merged.append(item)
            continue

        parts = [struct]
        current_left = float(struct.get("x0") or 0)
        current_right = float(struct.get("x1") or 0)
        for neighbor in row:
            nsid = str(neighbor.get("id") or "")
            if nsid == sid:
                continue
            if not _is_mergeable_fragment_neighbor(struct, neighbor, key, visible_label_cache):
                continue
            nx0, nx1 = float(neighbor.get("x0") or 0), float(neighbor.get("x1") or 0)
            if nx1 <= current_left + 6 or nx0 >= current_right - 6:
                parts.append(neighbor)
        parts = sorted(parts, key=lambda part: float(part.get("x0") or 0))
        if len(parts) <= 1:
            merged.append(item)
            continue

        saved = _save_merged_structure_crop(parts, output_dir, key)
        if not saved:
            merged.append(item)
            continue
        path, merged_geom = saved
        item["image_path"] = path
        item["source_image_path"] = str(item.get("source_image_path") or struct.get("image_path") or "")
        item["ocsr_image_path"] = str(path)
        item["structure_id"] = f"{sid}_merged"
        item["source_structure_id"] = sid
        item["binding_rule"] = "direct_structure_label_merged_fragment"
        item["merged_fragment_sources"] = [str(part.get("id") or "") for part in parts]
        item.update(merged_geom)
        merged.append(item)
        replacements += 1

    if replacements:
        logger.info("   🧩 合并严格可见标签的拆分结构图块: %d rows", replacements)
    return _active_ordered_bindings(merged, active_cpds)


def _save_expanded_strict_label_crop(
    struct: Dict,
    row: List[Dict],
    output_dir: str,
    target_key: str,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Expand a strict label-bearing fragment to its visual row cell.

    DECIMER can split a labelled final product into a lower fragment that still
    carries the printed compound number.  The repair crop must recover the full
    molecule, but it must not swallow neighboring reaction arrows, plus signs, or
    the prose below the drawing.  Use the nearest same-row structure gaps as
    visual cell boundaries, then expand mostly upward from the label fragment.
    """
    raw = struct.get("struct") or {}
    bbox = raw.get("bbox") or []
    if len(bbox) != 4:
        return None
    image_path = str(struct.get("image_path") or "")
    page_no = int(struct.get("page_no") or 0)
    page_image = Path(image_path).with_name(f"page_{page_no:03d}.png")
    if not page_image.is_file():
        return None

    try:
        from PIL import Image

        img = Image.open(page_image).convert("RGB")
        x0, y0, x1, y1 = [int(round(float(v))) for v in bbox]
        row_sorted = sorted(row or [struct], key=lambda item: float(item.get("x0") or 0))
        idx = next(
            (
                i for i, item in enumerate(row_sorted)
                if str(item.get("id") or "") == str(struct.get("id") or "")
            ),
            -1,
        )
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        left = x0 - max(42, int(width * 0.62))
        right = x1 + max(18, int(width * 0.26))
        if width < 170 and height < 230:
            # A strict label can be attached to a DECIMER half-module when the
            # left heterocycle or right substituent is segmented separately.
            # Recover the full visual cell, not only the label-bearing half.
            left = min(left, x0 - max(56, int(width * 0.86)))
            right = max(right, x1 + max(34, int(width * 0.42)))
        if idx > 0:
            prev_raw = (row_sorted[idx - 1].get("struct") or {}).get("bbox") or []
            if len(prev_raw) == 4:
                px1 = int(round(float(prev_raw[2])))
                gap = x0 - px1
                if gap > 20:
                    # Stay inside the product's visual cell; the left side of a
                    # split product often borders a reaction arrow.
                    left = max(left, px1 + int(gap * 0.68))
        if idx >= 0 and idx + 1 < len(row_sorted):
            next_raw = (row_sorted[idx + 1].get("struct") or {}).get("bbox") or []
            if len(next_raw) == 4:
                nx0 = int(round(float(next_raw[0])))
                gap = nx0 - x1
                if gap > 20:
                    # Keep away from neighboring products/plus signs while
                    # retaining terminal substituents near the label fragment.
                    right = min(right, x1 + int(gap * 0.28))

        top = y0 - max(58, int(height * 1.08))
        if width < 170 and height < 230:
            top = min(top, y0 - max(70, int(height * 1.22)))
        bottom = y1 + max(18, int(height * 0.24))
        left = max(0, left)
        top = max(0, top)
        right = min(img.width, right)
        bottom = min(img.height, bottom)
        expanded_enough = (
            right - left > width * 1.35
            or bottom - top > height * 1.35
            or (
                width < 170
                and height < 230
                and right - left > width * 1.18
                and bottom - top > height * 1.18
            )
        )
        if not expanded_enough:
            return None
        crop = img.crop((left, top, right, bottom))
        expanded_dir = Path(output_dir) / "expanded_strict_labels"
        expanded_dir.mkdir(parents=True, exist_ok=True)
        path = expanded_dir / f"{struct.get('id')}_compound_{target_key}_expanded.png"
        crop.save(path)
    except Exception as exc:
        logger.debug("Strict-label expanded crop save failed: %s", exc)
        return None

    scale = 72 / 150
    geom = {
        "struct_x0": left * scale,
        "struct_y0": top * scale,
        "struct_x1": right * scale,
        "struct_y1": bottom * scale,
        "struct_width": (right - left) * scale,
        "struct_height": (bottom - top) * scale,
        "struct_area": ((right - left) * scale) * ((bottom - top) * scale),
        "struct_aspect": (right - left) / max((bottom - top), 1),
    }
    return str(path), geom


def _repair_weak_bindings_with_expanded_strict_fragments(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    output_dir: str,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Use strict visible labels to recover complete crops for split fragments."""
    if not final_bindings or not active_cpds or not visible_label_cache:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    annotated = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    by_key = {_binding_label_key(binding): dict(binding) for binding in annotated if _binding_label_key(binding)}
    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    rows_by_page: Dict[int, List[List[Dict]]] = {}
    for page_no in sorted({int(struct.get("page_no") or 0) for struct in processed_structures}):
        rows_by_page[page_no] = _group_structures_by_row(
            [struct for struct in processed_structures if int(struct.get("page_no") or 0) == page_no],
            y_threshold=55.0,
        )
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    weak_rules = {
        "heading_range_fallback",
        "product_section_context",
        "paired_route_product_row_order",
        "triplet_split_row_structure_order",
        "split_reaction_product_label",
        "ocr_numeric_structure_label",
        "ocr_bare_numeric_product_label",
        "dense_scheme_final_product",
        "same_row_right_product_repair",
        "route_title_row_right_product",
    }
    target_keys = set()
    for key in active_keys:
        current = by_key.get(key)
        if not current:
            target_keys.add(key)
            continue
        rule = str(current.get("binding_rule") or "")
        geom = _structure_geometry(current)
        strict_exact = key in _strict_visible_label_keys_for_binding(current)
        current_visible_keys = _visible_label_keys_for_binding(current)
        current_is_clean_standalone = (
            rule == "direct_structure_label"
            and key in current_visible_keys
            and current_visible_keys <= {key}
            and _is_ocsr_single_molecule_source(current)
            and not _is_low_internal_label_in_multi_visible_crop(current)
            and _visible_label_conflict_rank(current, active_keys) < 3
        )
        if current_is_clean_standalone:
            # A wide/weak OCR label on a complete standalone product is safer
            # than a strict label attached to a later reaction intermediate.
            continue
        if (
            rule in weak_rules
            or not strict_exact
            or geom["struct_area"] < 4200
            or (
                key in {"1", "2", "3", "4", "5", "6", "7", "8", "9"}
                and geom["struct_area"] < 6400
                and geom["struct_height"] < 95
            )
        ):
            target_keys.add(key)
    if not target_keys:
        return final_bindings

    candidates_by_key: Dict[str, List[Tuple[Tuple[int, int, int, int], Dict]]] = {}
    for sid, cache_item in (visible_label_cache or {}).items():
        struct = struct_by_id.get(str(sid))
        if not struct:
            continue
        strict_candidates = [
            candidate for candidate in _normalise_visible_cache_item(cache_item)
            if str(candidate.get("source") or "") in _STRICT_VISIBLE_LABEL_SOURCES
            and _cpd_label_key(str(candidate.get("label") or "")) in target_keys
        ]
        if not strict_candidates:
            continue
        page_no = int(struct.get("page_no") or 0)
        row = next(
            (
                row for row in rows_by_page.get(page_no, [])
                if any(str(item.get("id") or "") == str(sid) for item in row)
            ),
            [struct],
        )
        for candidate in strict_candidates:
            label = _normalise_compound_label(str(candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if key not in target_keys:
                continue
            ok_exact, exact_label = _passes_exact_visual_label_guard(
                struct,
                key,
                lines_by_page,
                row=row,
            )
            if not ok_exact:
                continue
            context_distance = _product_context_distance(pages_text, page_no, _base_cpd_num(key) or 0)
            if context_distance > 1:
                continue
            saved = _save_expanded_strict_label_crop(struct, row, output_dir, key)
            if not saved:
                continue
            path, expanded_geom = saved
            binding = _build_binding_from_structure(struct, key)
            binding["binding_rule"] = "direct_structure_label_merged_fragment"
            binding["visible_label"] = label
            binding["visual_label_source"] = "expanded_strict_label"
            binding["visible_label_crop_source"] = str(candidate.get("source") or "")
            binding["visible_label_multi_candidate"] = False
            binding["product_context_nearby"] = True
            binding["product_context_distance"] = int(context_distance)
            binding["source_structure_id"] = str(sid)
            binding["structure_id"] = f"{sid}_expanded"
            binding["image_path"] = path
            binding["source_image_path"] = str(struct.get("image_path") or "")
            source_is_clean = _is_ocsr_single_molecule_source(struct)
            binding["ocsr_source_clean_single_molecule"] = source_is_clean
            binding["ocsr_image_path"] = str(struct.get("image_path") if source_is_clean else path)
            binding["expanded_from_fragment"] = str(sid)
            binding["visible_labels"] = _labels_from_visible_cache_item(cache_item)
            binding["visible_label_candidates"] = _normalise_visible_cache_item(cache_item)
            if exact_label:
                binding["nearby_exact_product_label"] = exact_label
            binding.update(expanded_geom)
            score = (
                _VISIBLE_LABEL_SOURCE_RANK.get(str(candidate.get("source") or ""), 99),
                int(context_distance),
                _visual_module_score({**struct, **{
                    "x0": expanded_geom["struct_x0"],
                    "y0": expanded_geom["struct_y0"],
                    "x1": expanded_geom["struct_x1"],
                    "y1": expanded_geom["struct_y1"],
                }})[0],
                -int(expanded_geom["struct_area"]),
            )
            candidates_by_key.setdefault(key, []).append((score, binding))

    replacements = 0
    for key, candidates in candidates_by_key.items():
        candidates.sort(key=lambda item: item[0])
        candidate = candidates[0][1]
        current = by_key.get(key)
        if current is None or _visual_binding_priority(candidate, active_keys) < _visual_binding_priority(current, active_keys):
            by_key[key] = candidate
            replacements += 1
    if replacements:
        logger.info("   🧩 严格可见标签扩展修复弱/片段绑定: %d rows", replacements)
    return _active_ordered_bindings(list(by_key.values()), active_cpds)


def _split_pair_bases_from_text(text: str) -> List[int]:
    """Return split-product bases visible in OCR text, e.g. 7 from 7-1 ... 7-2."""
    bases: List[int] = []
    for m in _SPLIT_PAIR_RE.finditer(text.replace("\n", " ")):
        base = int(m.group(1))
        if base not in bases:
            bases.append(base)
    return bases


def _split_pair_base_lines(doc, page_no: int, page_text: str, ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None) -> List[Tuple[int, Optional[float]]]:
    """Return split-product bases with approximate heading y coordinates."""
    lines = (ocr_line_map or {}).get(page_no - 1) or _get_ocr_line_coords(doc[page_no - 1]) or []
    found: List[Tuple[int, Optional[float]]] = []

    for idx, (y0, _text) in enumerate(lines):
        window = " ".join(text for _, text in lines[idx:idx + 3])
        for base in _split_pair_bases_from_text(window):
            if base not in [b for b, _ in found]:
                found.append((base, y0))

    if found:
        return found

    return [(base, None) for base in _split_pair_bases_from_text(page_text)]


def _cpd_letter_pair_bases_from_text(text: str) -> List[int]:
    """Return bases from Cpd-N/Cpd-NA paired-product text."""
    bases: List[int] = []
    compact = re.sub(r"\s+", " ", str(text or ""))
    for match in _CPD_LETTER_PAIR_RE.finditer(compact):
        base = int(match.group(1))
        if base not in bases:
            bases.append(base)
    return bases


def _cpd_letter_pair_base_lines(
    page_no: int,
    page_text: str,
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
) -> List[Tuple[int, Optional[float]]]:
    """Return Cpd-N/Cpd-NA pair bases with approximate heading y coordinates."""
    lines = (ocr_line_map or {}).get(page_no - 1) or []
    found: List[Tuple[int, Optional[float]]] = []
    for idx, (y0, _text) in enumerate(lines):
        window = " ".join(text for _, text in lines[idx:idx + 3])
        if re.search(r"备注|相同|采用|参考|参照|same\s+route|same\s+procedure", window, re.IGNORECASE):
            continue
        for base in _cpd_letter_pair_bases_from_text(window):
            if base not in [item[0] for item in found]:
                found.append((base, y0))
    if found:
        return found
    return [(base, None) for base in _cpd_letter_pair_bases_from_text(page_text)]


def _is_cpd_letter_pair_product_candidate(struct: Dict) -> bool:
    """Accept compact final-product drawings in Cpd-N/Cpd-NA paired schemes."""
    geom = _structure_geometry(struct)
    return (
        geom["struct_area"] >= 5000
        and geom["struct_width"] >= 60
        and geom["struct_height"] >= 55
        and geom["struct_aspect"] <= 3.2
    )


def _cpd_letter_pair_label_y(
    base: int,
    page_no: int,
    lines_by_page: Optional[Dict[int, List[Tuple[float, str]]]],
) -> Optional[float]:
    """Return y for the printed Cpd-N/Cpd-NA product-label row."""
    if not lines_by_page:
        return None
    base_text = str(base)
    left_label = rf"(?:Cpd|Cmpd|Compound)\s*[-:]?\s*{re.escape(base_text)}(?:NH)?(?![A-Za-z0-9-])"
    right_label = rf"(?:Cpd|Cmpd|Compound)\s*[-:]?\s*{re.escape(base_text)}\s*A(?![A-Za-z0-9])"
    label_re = re.compile(
        rf"{left_label}.{{0,80}}?"
        rf"(?:Cpd|Cmpd|Compound)\s*[-:]?\s*{re.escape(base_text)}\s*A(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    single_left_re = re.compile(left_label, re.IGNORECASE)
    single_right_re = re.compile(right_label, re.IGNORECASE)
    lines = lines_by_page.get(page_no - 1) or []
    for idx, (y0, text) in enumerate(lines):
        window = " ".join(str(item[1] or "") for item in lines[idx:idx + 2])
        if re.search(r"实施例|Example|制备|备注|相同|采用|参考|参照|same\s+route|same\s+procedure", window, re.IGNORECASE):
            continue
        if len(window) > 140:
            continue
        if label_re.search(window) or (single_left_re.search(window) and single_right_re.search(window)):
            return float(y0)
        line_text = str(text or "")
        if not single_left_re.search(line_text):
            continue
        nearby_texts: List[str] = []
        for other_y, other_text in lines[idx:idx + 6]:
            if abs(float(other_y) - float(y0)) > 24.0:
                break
            value = str(other_text or "")
            if re.search(r"实施例|Example|制备|备注|相同|采用|参考|参照|same\s+route|same\s+procedure", value, re.IGNORECASE):
                continue
            nearby_texts.append(value)
        nearby_window = " ".join(nearby_texts)
        if len(nearby_window) <= 160 and single_right_re.search(nearby_window):
            return float(y0)
    return None


def _has_cpd_letter_pair_product_text(base: int, page_text: str) -> bool:
    """Return True for result/prose rows mentioning Cpd-N and Cpd-NA."""
    text = re.sub(r"\s+", " ", str(page_text or ""))
    if not text or re.search(r"实施例|Example|制备", text[:160], re.IGNORECASE):
        return False
    if re.search(r"备注|相同|采用|参考|参照|same\s+route|same\s+procedure", text, re.IGNORECASE):
        return False
    return base in _cpd_letter_pair_bases_from_text(text)


def _structure_geometry(struct: Dict) -> Dict[str, float]:
    """Return normalized geometry for a processed structure or saved binding."""
    x0 = float(struct.get("x0", struct.get("struct_x0", 0)) or 0)
    y0 = float(struct.get("y0", struct.get("struct_y0", 0)) or 0)
    x1 = float(struct.get("x1", struct.get("struct_x1", x0)) or x0)
    y1 = float(struct.get("y1", struct.get("struct_y1", y0)) or y0)
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    area = width * height
    aspect = width / max(height, 1.0)
    return {
        "struct_x1": x1,
        "struct_y1": y1,
        "struct_width": width,
        "struct_height": height,
        "struct_area": area,
        "struct_aspect": aspect,
    }


def _attach_structure_geometry(binding: Dict, struct: Dict) -> Dict:
    binding.update(_structure_geometry(struct))
    return binding


def _build_binding_from_structure(struct: Dict, label: str) -> Dict:
    label_key = _normalise_compound_label(str(label))
    cpd = f"Compound {label_key}"
    label_num = _base_cpd_num(label_key) or 0
    binding = {
        "cpd": cpd,
        "example_id": cpd,
        "example_num": label_num,
        "compound_id": cpd,
        "compound_num": label_num,
        "cpd_num": label_num,
        "prefix": "Compound",
        "structure_id": struct["id"],
        "page_no": struct["page_no"],
        "structure_index": struct["idx"],
        "struct_x0": struct["x0"],
        "struct_y0": struct["y0"],
        "image_path": struct["image_path"],
        "source_image_path": struct["image_path"],
        "ocsr_image_path": struct["image_path"],
        "candidates": 1,
        "binding_rule": "ocr_pair_heading_structure_order",
    }
    return _attach_structure_geometry(binding, struct)


def _normalise_binding_to_compound(binding: Dict, compound_label) -> Dict:
    raw_label = str(compound_label or "").strip()
    label_key = "CLAIM1" if raw_label.upper() == "CLAIM1" else (_cpd_label_key(compound_label) or raw_label)
    if label_key == "CLAIM1":
        cpd = "Claim 1 compound"
        binding["cpd"] = cpd
        binding["cpd_id"] = cpd
        binding["example_id"] = cpd
        binding["example_num"] = 1
        binding["compound_id"] = cpd
        binding["compound_num"] = 1
        binding["cpd_num"] = 1
        binding["prefix"] = "Claim"
        return binding
    cpd = f"Compound {label_key}"
    compound_num = _base_cpd_num(label_key) or 0
    binding["cpd"] = cpd
    binding["example_id"] = cpd
    binding["example_num"] = compound_num
    binding["compound_id"] = cpd
    binding["compound_num"] = compound_num
    binding["cpd_num"] = compound_num
    binding["prefix"] = "Compound"
    return binding


def _binding_sort_key(binding: Dict) -> Tuple[int, int, int, float, float]:
    m = re.match(r"^Compound\s+([1-9]\d*)(?:-([12]))?([A-Z])?$", str(binding.get("cpd", "")), re.IGNORECASE)
    if m:
        suffix_rank = int(m.group(2) or 0)
        letter_rank = ord(m.group(3).upper()) - 64 if m.group(3) else 0
        return (
            int(m.group(1)),
            suffix_rank * 100 + letter_rank,
            int(binding.get("page_no") or 0),
            float(binding.get("struct_y0") or 0),
            float(binding.get("struct_x0") or 0),
        )
    return (
        10**9,
        10**9,
        int(binding.get("page_no") or 0),
        float(binding.get("struct_y0") or 0),
        float(binding.get("struct_x0") or 0),
    )


def _binding_base_num(binding: Dict) -> Optional[int]:
    """Return the parent compound number for de-duplicating mixed bind rules."""
    return _base_cpd_num(binding.get("compound_id") or binding.get("cpd") or "")


def _cpd_label_key(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if text.upper() == "CLAIM1":
        return "CLAIM1"
    if re.fullmatch(
        r"(?:claim\s*1\s+compound|claimed\s+compound|main\s+compound|single(?:ton)?\s+compound)",
        text,
        re.IGNORECASE,
    ):
        return "CLAIM1"
    match = re.search(
        r"(?:compound|cpd|example|实施例|化合物)?\s*[-:]?\s*([1-9]\d*(?:-\d+)?[A-Z]?)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()
    return ""


def _binding_label_key(binding: Dict) -> str:
    return _cpd_label_key(binding.get("compound_id") or binding.get("cpd") or binding.get("visible_label") or "")


def _active_label_keys(active_cpds: Optional[List[str]]) -> set[str]:
    return {key for key in (_cpd_label_key(cpd) for cpd in (active_cpds or [])) if key}


def _enforce_authoritative_structure_table_source(final_bindings: List[Dict], profile: Optional[Dict]) -> List[Dict]:
    """Reject synthesis-page competitors for compound IDs present in a structure table."""
    raw_pages = (profile or {}).get("authoritative_structure_table_pages", []) or []
    raw_cpds = (profile or {}).get("authoritative_structure_table_cpds", []) or []
    table_page_nos = set()
    for page_idx in raw_pages:
        try:
            table_page_nos.add(int(page_idx) + 1)
        except Exception:
            continue
    covered_keys = _active_label_keys([str(cpd) for cpd in raw_cpds])
    if not table_page_nos or not covered_keys:
        return final_bindings
    active_keys = _active_label_keys((profile or {}).get("active_cpds", []) or [])
    if active_keys and not active_keys.issubset(covered_keys):
        # A partial structure table is useful evidence, but it is not a global
        # authority. Do not delete clear visual bindings for active compounds
        # merely because one incomplete table mentions the same number.
        return final_bindings

    kept: List[Dict] = []
    dropped: List[str] = []
    for binding in final_bindings:
        key = _binding_label_key(binding)
        try:
            page_no = int(binding.get("page_no") or 0)
        except Exception:
            page_no = 0
        if key in covered_keys and page_no not in table_page_nos:
            dropped.append(key)
            continue
        kept.append(binding)
    if dropped:
        logger.info(
            "   结构表权威来源保护: 删除 %d 个表外竞争绑定 (%s)",
            len(dropped),
            ", ".join(sorted(set(dropped), key=lambda value: (len(value), value))[:12]),
        )
    return kept


def _extract_authoritative_structure_table_sequence_bindings(
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    profile: Optional[Dict],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
    *,
    numbered_result: Optional[NumberedTableResult] = None,
) -> List[Dict]:
    """Resolve authoritative cells before series or legacy sequence evidence.

    Recognized numbered grids never enter global sequence inference. Existing
    I-series geometry remains independent; the older complete-sequence rule is
    restricted to tables not recognized by either spatial authority.
    """
    raw_pages = (profile or {}).get("authoritative_structure_table_pages", []) or []
    try:
        page_indices = sorted({int(page) for page in raw_pages})
    except Exception:
        return []
    if not page_indices or page_indices[0] < 0:
        return []

    if numbered_result is not None and numbered_result.recognized:
        bindings = []
        for pair in numbered_result.bindings:
            binding = _build_binding_from_structure(pair.structure, pair.label)
            binding["binding_rule"] = "numbered_structure_table_cell"
            binding["numbered_table_cell_evidence"] = pair.evidence()
            binding["authoritative_table_source_label"] = pair.label
            binding["authoritative_table_pages"] = list(numbered_result.recognized_pages)
            bindings.append(binding)
        if numbered_result.issues:
            logger.warning(
                "   编号结构表保留未确认单元格: %d (%s)",
                len(numbered_result.issues),
                ", ".join(sorted({issue.reason for issue in numbered_result.issues})),
            )
        # Recognition is authoritative even when every cell is unresolved.
        # A numeric global zip cannot resolve missing/ambiguous cell evidence.
        return bindings

    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    active_keys = _active_label_keys(active_cpds)
    series = pair_series_table(processed_structures, page_indices, lines_by_page, active_keys)
    if series.rejected_geometry or series.ambiguous_pairings:
        logger.warning(
            "   权威 I-NNN 表拒绝无效坐标=%d, 歧义配对=%d",
            series.rejected_geometry,
            series.ambiguous_pairings,
        )
    if series.recognized:
        bindings: List[Dict] = []
        for pair in series.bindings:
            binding = _build_binding_from_structure(pair.structure, str(pair.label))
            binding["binding_rule"] = "authoritative_structure_table_sequence"
            binding["authoritative_table_sequence_confirmed"] = True
            binding["authoritative_table_sequence_position"] = pair.evidence_position + 1
            binding["authoritative_table_label_count"] = series.label_count
            binding["authoritative_table_structure_count"] = len(processed_structures)
            binding["authoritative_table_pages"] = page_indices
            binding["authoritative_table_visible_label"] = f"I-{pair.label}"
            binding["authoritative_table_label_y0"] = round(pair.label_y, 2)
            binding["authoritative_table_pair_distance"] = round(pair.center_distance, 2)
            binding["authoritative_table_source_label"] = f"I-{pair.source_label}"
            if pair.correction_reason:
                binding["authoritative_table_label_corrected"] = True
                binding["authoritative_table_label_correction_reason"] = pair.correction_reason
            bindings.append(binding)
        logger.info(
            "   权威 I-NNN 结构表坐标绑定: %d active rows, labels=%d, structures=%d",
            len(bindings),
            series.label_count,
            len(processed_structures),
        )
        # A recognized but ambiguous series table must not enter the numeric
        # global-sequence rule, which cannot resolve its spatial uncertainty.
        return bindings

    # Only the numeric global zip requires a complete contiguous table. The
    # I-series rule above pairs within each observed original-PDF page.
    if any(b != a + 1 for a, b in zip(page_indices, page_indices[1:])):
        return []
    label_re = re.compile(
        r"(?:Compound|Cpd|化合物|实施例)\s*[-:]?\s*([1-9]\d{0,3})(?![\dA-Za-z-])",
        re.IGNORECASE,
    )
    labels = {
        int(match.group(1))
        for page_idx in page_indices
        for match in label_re.finditer(str(pages_text.get(page_idx, "") or ""))
    }
    if len(labels) < 6:
        return []
    ordered_labels = sorted(labels)
    if ordered_labels != list(range(ordered_labels[0], ordered_labels[-1] + 1)):
        return []

    table_structures: List[Dict] = []
    for page_idx in page_indices:
        page_structs = [
            struct for struct in processed_structures
            if int(struct.get("page_no") or 0) == page_idx + 1
        ]
        rows = _group_structures_by_row(page_structs, y_threshold=42.0)
        table_structures.extend(
            struct for row in rows
            for struct in sorted(row, key=lambda item: float(item.get("x0") or 0))
        )
    if len(table_structures) != len(ordered_labels):
        logger.warning(
            "   权威结构表全局序列未启用: labels=%d, structures=%d",
            len(ordered_labels),
            len(table_structures),
        )
        return []

    bindings: List[Dict] = []
    for position, (compound_num, struct) in enumerate(zip(ordered_labels, table_structures), start=1):
        key = str(compound_num)
        if key not in active_keys:
            continue
        binding = _build_binding_from_structure(struct, key)
        binding["binding_rule"] = "authoritative_structure_table_sequence"
        binding["authoritative_table_sequence_confirmed"] = True
        binding["authoritative_table_sequence_position"] = position
        binding["authoritative_table_label_count"] = len(ordered_labels)
        binding["authoritative_table_structure_count"] = len(table_structures)
        binding["authoritative_table_pages"] = page_indices
        bindings.append(binding)
    if bindings:
        logger.info(
            "   📋 权威结构表跨页全局顺序绑定: %d/%d active rows, pages=%s",
            len(bindings),
            len(ordered_labels),
            page_indices,
        )
    return bindings


def _visible_label_keys_for_binding(binding: Dict) -> set[str]:
    keys: set[str] = set()
    if binding.get("visible_label"):
        key = _cpd_label_key(str(binding.get("visible_label") or ""))
        if key:
            keys.add(key)
    for label in binding.get("visible_labels") or []:
        key = _cpd_label_key(str(label or ""))
        if key:
            keys.add(key)
    return keys


def _strict_visible_label_keys_for_binding(binding: Dict) -> set[str]:
    keys: set[str] = set()
    for candidate in binding.get("visible_label_candidates") or []:
        source = str(candidate.get("source") or "")
        if source not in _STRICT_VISIBLE_LABEL_SOURCES:
            continue
        key = _cpd_label_key(str(candidate.get("label") or ""))
        if key:
            keys.add(key)
    if not keys and binding.get("visible_label_crop_source") in _STRICT_VISIBLE_LABEL_SOURCES:
        key = _cpd_label_key(str(binding.get("visible_label") or ""))
        if key:
            keys.add(key)
    return keys


def _visual_label_keys_for_binding(
    binding: Dict,
    *,
    include_wide: bool = True,
) -> set[str]:
    allowed_sources = _VISUAL_LABEL_SOURCES if include_wide else _STRICT_VISIBLE_LABEL_SOURCES
    keys: set[str] = set()
    for candidate in binding.get("visible_label_candidates") or []:
        source = str(candidate.get("source") or "")
        if source not in allowed_sources:
            continue
        key = _cpd_label_key(str(candidate.get("label") or ""))
        if key:
            keys.add(key)
    source = str(binding.get("visible_label_crop_source") or "")
    if source in allowed_sources:
        key = _cpd_label_key(str(binding.get("visible_label") or ""))
        if key:
            keys.add(key)
    return keys


def _has_exact_visual_product_evidence(binding: Dict, active_keys: Optional[set[str]] = None) -> bool:
    key = _binding_label_key(binding)
    if not key:
        return False
    visual_keys = _visual_label_keys_for_binding(binding)
    if key not in visual_keys:
        return False
    competing = visual_keys - {key}
    if active_keys:
        competing = {item for item in competing if item in active_keys}
    if competing:
        return False
    if bool(binding.get("visible_label_multi_candidate")) and key not in _strict_visible_label_keys_for_binding(binding):
        return False
    distance = _int_or_default(binding.get("product_context_distance"), 999)
    if binding.get("product_context_nearby") is True and distance <= 1:
        return True
    nearby_exact = _cpd_label_key(str(binding.get("nearby_exact_product_label") or ""))
    return nearby_exact == key


def _is_truncated_visible_prefix(target_key: str, visible_key: str) -> bool:
    if not target_key or not visible_key:
        return False
    if not re.fullmatch(r"\d{3}[A-Z]?", target_key) or not re.fullmatch(r"\d{1,2}[A-Z]?", visible_key):
        return False
    return target_key.startswith(visible_key)


def _is_short_internal_visible_key(target_key: str, visible_key: str) -> bool:
    """Return True for atom/reagent/NMR-like labels inside a stronger binding."""
    if not target_key or not visible_key or target_key == visible_key:
        return False
    if not re.fullmatch(r"\d{2,3}[A-Z]?", target_key):
        return False
    if not re.fullmatch(r"\d{1,2}[A-Z]?", visible_key):
        return False
    match = re.match(r"\d+", visible_key)
    if not match:
        return False
    value = int(match.group(0))
    # Only a lone "1" is routinely an internal stereochemical/route annotation.
    # Larger visible numbers such as 2/4/10 may be real competing products or
    # intermediates, so derived crops must fail closed instead of auto-confirming.
    return value == 1 or _is_truncated_visible_prefix(target_key, visible_key)


def _visible_label_conflict_rank(binding: Dict, active_keys: Optional[set[str]] = None) -> int:
    """Penalize candidates whose own visual label proves another active ID."""
    key = _binding_label_key(binding)
    strict_keys = _strict_visible_label_keys_for_binding(binding)
    visible_keys = strict_keys or _visible_label_keys_for_binding(binding)
    if not key or not visible_keys:
        return 1
    if str(binding.get("binding_rule") or "") == "visual_grid_label":
        all_visible_keys = _visible_label_keys_for_binding(binding)
        base = _base_cpd_num(key)
        try:
            page_min = int(binding.get("visual_grid_page_min") or 0)
            page_max = int(binding.get("visual_grid_page_max") or 0)
        except Exception:
            page_min = page_max = 0
        if key in all_visible_keys and base is not None and page_min <= base <= page_max:
            competing_in_grid = {
                vkey for vkey in all_visible_keys
                if vkey != key
                and (vbase := _base_cpd_num(vkey)) is not None
                and page_min <= vbase <= page_max
            }
            if not competing_in_grid:
                return 0
    if key in visible_keys:
        return 0
    if (
        str(binding.get("binding_rule") or "") in {"structure_table_row_order", "structure_table_row_order_inferred", "structure_table_row_order_corrected"}
        and all(_is_short_internal_visible_key(key, vkey or "") for vkey in visible_keys)
    ):
        return 1
    if (
        str(binding.get("binding_rule") or "") in {"structure_table_row_order", "structure_table_row_order_inferred", "structure_table_row_order_corrected"}
        and re.fullmatch(r"\d{3}[A-Z]?", key)
        and all(re.fullmatch(r"\d{1,2}[A-Z]?", vkey or "") for vkey in visible_keys)
    ):
        # Table-row bindings are often correct even when OCR sees small atom,
        # reagent, or route annotations inside the drawing. Do not let "1" or
        # "11" override a three-digit left-column row number without an exact
        # competing visual label for that target.
        return 1
    if visible_keys and all(_is_truncated_visible_prefix(key, vkey) for vkey in visible_keys):
        # PaddleX sometimes clips the final digit from a tight label crop
        # (Example 134 -> "13"). Treat that as weak evidence unless another
        # exact candidate exists for the shorter active number.
        return 1
    if _has_strong_structure_table_row_evidence(binding):
        # In a structure table the row ID is outside the molecule crop. A small
        # strict digit inside the drawing is usually an atom, stereochemistry,
        # or procedure annotation, not a competing final compound ID.
        return 1
    if key in strict_keys and key != "1" and (strict_keys - {key}) <= {"1"}:
        # Stereochemical annotations such as "or1" are often OCR'd as an
        # additional strict "1" inside the same crop. If the target label is
        # also present, do not turn that annotation into an active-label conflict.
        return 0
    if key in strict_keys and all(
        vkey == key or _is_short_internal_visible_key(key, vkey or "")
        for vkey in strict_keys
    ):
        return 0
    if key in strict_keys and strict_keys - {key}:
        return 5
    if strict_keys and active_keys and any(vkey in active_keys for vkey in strict_keys):
        return 5
    if active_keys and any(vkey in active_keys for vkey in visible_keys):
        return 3
    return 2


def _is_low_internal_label_in_multi_visible_crop(binding: Dict) -> bool:
    """Detect low route/intermediate numbers inside a crop labelled as a later product."""
    if str(binding.get("binding_rule") or "") == "visual_grid_label":
        return False
    key = _binding_label_key(binding)
    base = _base_cpd_num(key)
    if base is None or base > 20:
        return False
    visible_bases = [
        n for n in (_base_cpd_num(label) for label in _visible_label_keys_for_binding(binding))
        if n is not None
    ]
    if len(set(visible_bases)) < 2:
        return False
    return max(visible_bases) >= max(50, base + 30)


def _visible_label_exactness_rank(binding: Dict, active_keys: Optional[set[str]] = None) -> int:
    key = _binding_label_key(binding)
    strict_keys = _strict_visible_label_keys_for_binding(binding)
    visible_keys = _visible_label_keys_for_binding(binding)
    if key and key in strict_keys and not _is_low_internal_label_in_multi_visible_crop(binding):
        return 0
    if key and key in strict_keys:
        return 3
    if key and key in visible_keys and not _is_low_internal_label_in_multi_visible_crop(binding):
        return 1
    if visible_keys and active_keys and any(vkey in active_keys for vkey in visible_keys):
        return 4
    return 2


def _strict_visible_source_rank(binding: Dict) -> int:
    """Return best strict visual-label source rank for the binding target."""
    key = _binding_label_key(binding)
    if not key:
        return 99
    best = 99
    for candidate in binding.get("visible_label_candidates") or []:
        source = str(candidate.get("source") or "")
        if source not in _STRICT_VISIBLE_LABEL_SOURCES:
            continue
        if _cpd_label_key(str(candidate.get("label") or "")) != key:
            continue
        best = min(best, _VISIBLE_LABEL_SOURCE_RANK.get(source, 99))
    if best == 99 and binding.get("visible_label_crop_source") in _STRICT_VISIBLE_LABEL_SOURCES:
        if _cpd_label_key(str(binding.get("visible_label") or "")) == key:
            best = min(best, _VISIBLE_LABEL_SOURCE_RANK.get(str(binding.get("visible_label_crop_source") or ""), 99))
    return best


def _binding_priority(binding: Dict, active_keys: Optional[set[str]] = None) -> Tuple[int, int, int, int]:
    """Prefer explicit OCR/table labels over broad heading-window fallbacks."""
    rule = str(binding.get("binding_rule") or "")
    key = _binding_label_key(binding)
    active_rank = 0 if active_keys and key in active_keys else 1
    rule_rank = {
        "authoritative_structure_table_sequence": -1,
        "direct_structure_label": 1,
        "direct_structure_label_right_product_crop": 1,
        "visual_grid_label": 0,
        "product_section_context": 1,
        "structure_table_row_order": 0,
        "structure_table_row_order_corrected": 0,
        "structure_table_row_order_inferred": 0,
        "ocr_pair_heading_structure_order": 3,
        "paired_route_product_row_order": 4,
        "triplet_split_row_structure_order": 5,
        "split_reaction_product_label": 6,
        "ocr_numeric_structure_label": 7,
        "ocr_bare_numeric_product_label": 8,
        "heading_row_right_product_recovery": 2,
        "same_row_right_product_repair": 2,
        "route_title_row_right_product": 2,
    }
    rank = rule_rank.get(rule, 20 if rule else 30)
    return (
        active_rank,
        rank,
        int(binding.get("candidates") or 9999),
        int(binding.get("structure_index") or 999999),
    )


def _direct_visual_shape_rank(binding: Dict) -> int:
    """Rank visually-labeled crops by whether they look like final products."""
    area = float(binding.get("struct_area") or 0)
    width = float(binding.get("struct_width") or 0)
    height = float(binding.get("struct_height") or 0)
    if area and area < 5000:
        return 5
    if width and height and width / max(height, 1.0) > 5.5:
        return 4
    if area >= 18000 and width >= 250 and height >= 85:
        return 0
    return 1


def _is_weak_direct_visual_binding(binding: Optional[Dict]) -> bool:
    """Return True when direct OCR evidence should be rechecked visually.

    A visible numeric label is strong evidence only when the crop is plausibly a
    final product module. Tiny fragments, whole reaction routes, and labels far
    from the product heading must not lock the binding before module repair.
    """
    if not binding:
        return False
    if str(binding.get("binding_rule") or "") != "direct_structure_label":
        return False
    shape_rank = _direct_visual_shape_rank(binding)
    if shape_rank >= 4:
        return True
    key = _binding_label_key(binding)
    if (
        re.fullmatch(r"[1-9]", key or "")
        and float(binding.get("struct_area") or 0) < 6400
        and float(binding.get("struct_height") or 0) < 95
    ):
        # Route step numbers are overwhelmingly single-digit. If one still
        # lands on a compact crop, force the later strict-label repair pass to
        # compare it against complete Cpd-labelled product modules.
        return True
    if str(binding.get("visual_label_source") or "") not in {"module", "route_right_product"}:
        return True
    distance = binding.get("product_context_distance")
    if distance is not None:
        try:
            if int(distance) > 1:
                return True
        except Exception:
            pass
    return False


def _visual_binding_priority(binding: Dict, active_keys: Optional[set[str]] = None) -> Tuple[int, ...]:
    """Tie-break visual label candidates without favoring route fragments.

    The same compound number can appear both under a standalone final-product
    drawing and inside a reaction scheme. Prefer candidates with product
    context, then larger standalone-looking crops, while still keeping visual
    labels ahead of prose-derived fallbacks.
    """
    base_priority = _binding_priority(binding, active_keys)
    rule = str(binding.get("binding_rule") or "")
    context_distance = binding.get("product_context_distance")
    if context_distance is None:
        context_distance = 0 if binding.get("product_context_nearby") is True else 999
    try:
        context_rank = int(context_distance)
    except Exception:
        context_rank = 999
    area = float(binding.get("struct_area") or 0)
    shape_rank = _direct_visual_shape_rank(binding)
    source = str(binding.get("visual_label_source") or "")
    if rule in {"authoritative_structure_table_sequence", "structure_table_row_order", "structure_table_row_order_inferred", "structure_table_row_order_corrected"} and area >= 6500:
        shape_rank = 0
    source_rank = {
        "module": 0,
        "cache_fill": 0,
        "cache_confirmed": 0,
        "route_right_product": 1,
    }.get(source, 2)
    if rule in {"direct_structure_label", "direct_structure_label_right_product_crop"}:
        try:
            row_rank = int(float(binding.get("struct_y0") or 999999))
        except Exception:
            row_rank = 999999
        try:
            column_rank = int(float(binding.get("struct_x0") or 999999))
        except Exception:
            column_rank = 999999
    else:
        row_rank = 999999
        column_rank = 999999
    # Negative values sort larger standalone crops first.
    return (
        base_priority[0],
        _visible_label_conflict_rank(binding, active_keys),
        _strict_visible_source_rank(binding),
        base_priority[1],
        context_rank if rule in {"direct_structure_label", "direct_structure_label_right_product_crop"} else 999,
        source_rank,
        shape_rank,
        base_priority[2],
        row_rank,
        column_rank,
        -int(area),
        base_priority[3],
    )


def _merge_binding_candidates(primary: List[Dict], fallback: List[Dict], active_cpds: Optional[List[str]] = None) -> List[Dict]:
    """Merge binding candidates, keeping one best structure per exact compound label."""
    active_keys = _active_label_keys(active_cpds)
    all_candidates = [*primary, *fallback]
    table_structures: set[str] = set()
    for binding in all_candidates:
        rule = str(binding.get("binding_rule") or "")
        struct_id = str(binding.get("structure_id") or "")
        if struct_id and rule == "authoritative_structure_table_sequence":
            table_structures.add(struct_id)
            continue
        if (
            struct_id
            and rule in {"authoritative_structure_table_sequence", "structure_table_row_order", "structure_table_row_order_inferred", "structure_table_row_order_corrected"}
            and float(binding.get("struct_area") or 0) >= 6500
        ):
            table_structures.add(struct_id)

    by_key: Dict[str, Dict] = {}
    used_structures: set[str] = set()
    def _merge_priority(binding: Dict) -> Tuple[int, int, int, int, int, int, int, int, int]:
        rule = str(binding.get("binding_rule") or "")
        struct_id = str(binding.get("structure_id") or "")
        table_guard = 0 if (
            rule in {"authoritative_structure_table_sequence", "structure_table_row_order", "structure_table_row_order_inferred", "structure_table_row_order_corrected"}
            and struct_id in table_structures
        ) else 1
        internal_label_penalty = 1 if (
            rule == "direct_structure_label"
            and struct_id in table_structures
            and len(_visible_label_keys_for_binding(binding)) <= 1
        ) else 0
        return (table_guard, internal_label_penalty, *_visual_binding_priority(binding, active_keys))

    for binding in sorted(all_candidates, key=_merge_priority):
        key = _binding_label_key(binding)
        struct_id = str(binding.get("structure_id") or "")
        if not key or not struct_id:
            continue
        if key in by_key or struct_id in used_structures:
            continue
        by_key[key] = binding
        used_structures.add(struct_id)
    return sorted(by_key.values(), key=_binding_sort_key)


def _visual_module_score(struct: Dict) -> Tuple[int, int, int]:
    """Score whether a crop looks like a standalone final-product module."""
    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    area = width * height
    # Big complete modules should beat small intermediates/fragments. Keep the
    # threshold permissive because long flat products can have modest height.
    route_rank = 2 if (height > 0 and width / max(height, 1.0) > 5.5) else 0
    complete_rank = 0 if (area >= 6000 and width >= 70 and height >= 35) else 1
    page_y = float(struct.get("y0") or 0)
    # Prefer standalone modules printed before the reaction/prose block when
    # the same label appears twice on the page.
    return (route_rank, complete_rank, int(page_y), -int(area), int(struct.get("idx") or 999999))


def _is_complete_product_like_structure(struct: Dict) -> bool:
    """Reject route fragments when visual labels are used without text context."""
    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    area = width * height
    aspect = width / max(height, 1.0)
    if area < 5600 or width < 65 or height < 55:
        return False
    if aspect > 4.2:
        return False
    return True


def _is_ocsr_single_molecule_source(struct: Dict) -> bool:
    """Return whether a segmented crop is large enough for standalone OCSR.

    Final products can be long and flat, so this is more permissive than the
    binding module check. It still rejects compact route fragments such as
    protected intermediates that carry an incidental visible number.
    """
    geom = _structure_geometry(struct)
    width = geom["struct_width"]
    height = geom["struct_height"]
    area = geom["struct_area"]
    aspect = geom["struct_aspect"]
    return area >= 4200 and width >= 100 and height >= 28 and aspect <= 5.5


def _is_final_label_band_product_like(struct: Dict, visual_candidate: Optional[Dict[str, Any]] = None) -> bool:
    """Allow compact final products when a strict label is printed under them."""
    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    area = width * height
    aspect = width / max(height, 1.0)
    source = str((visual_candidate or {}).get("source") or "")
    if source not in _STRICT_VISIBLE_LABEL_SOURCES:
        return False
    return area >= 4200 and width >= 60 and height >= 55 and aspect <= 2.4


def _is_contextual_final_visual_candidate(struct: Dict, visual_candidate: Dict[str, Any]) -> bool:
    """Accept visually labelled structures only when they are not route fragments.

    Some synthesis schemes contain labels like ``6.1``; OCR can split those into
    active-looking labels (``6`` and ``1``).  A small or multi-label crop must not
    become a final product unless it has very tight product context.
    """
    if _is_complete_product_like_structure(struct):
        return True
    source = str(visual_candidate.get("source") or "")
    if (
        source == "page_wide"
        and not bool(visual_candidate.get("multi_label_crop"))
    ):
        width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
        height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
        area = width * height
        aspect = width / max(height, 1.0)
        if area >= 5000 and width >= 90 and height >= 48 and aspect <= 3.2:
            return True
    if _is_final_label_band_product_like(struct, visual_candidate):
        return True

    try:
        distance = _int_or_default(visual_candidate.get("product_context_distance"), 999)
    except Exception:
        distance = 999
    if distance != 0 or bool(visual_candidate.get("multi_label_crop")):
        return False

    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    area = width * height
    aspect = width / max(height, 1.0)
    return area >= 4500 and width >= 65 and height >= 45 and aspect <= 4.8


def _strict_single_visible_candidate_for_missing(
    struct: Dict,
    candidates: List[Dict[str, str]],
    missing_keys: set[str],
    active_keys: set[str],
    pages_text: Optional[Dict[int, str]] = None,
    lines_by_page: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    row: Optional[List[Dict]] = None,
) -> Optional[Dict[str, Any]]:
    """Allow activity-only backfill from visual OCR when the crop is unambiguous.

    This is deliberately narrower than normal direct-label binding. It fires only
    for missing active compounds, only when a strict crop sees one active label,
    and only when the structure looks like a complete product rather than a
    reagent/intermediate fragment or reaction arrow.
    """
    strict_matches: List[Dict[str, Any]] = []
    active_labels_seen: set[str] = set()
    for candidate in candidates:
        source = str(candidate.get("source") or "")
        label = _normalise_compound_label(str(candidate.get("label") or ""))
        key = _cpd_label_key(label)
        if not key:
            continue
        if key in active_keys:
            active_labels_seen.add(key)
        if source not in _STRICT_VISIBLE_LABEL_SOURCES or key not in missing_keys:
            continue
        strict_matches.append({"label": label, "label_key": key, "source": source})

    match_keys = {str(item.get("label_key") or "") for item in strict_matches}
    if len(match_keys) != 1:
        return None
    key = next(iter(match_keys))
    if active_labels_seen - {key}:
        return None
    best_source = sorted(strict_matches, key=lambda item: _VISIBLE_LABEL_SOURCE_RANK.get(str(item.get("source") or ""), 99))[0]
    if not (
        _is_complete_product_like_structure(struct)
        or _is_final_label_band_product_like(struct, best_source)
    ):
        return None

    exact_label = _nearby_exact_product_label(struct, key, lines_by_page, row=row)
    if exact_label and exact_label != key:
        return None
    product_context_distance = 999
    if pages_text is not None:
        product_context_distance = _product_context_distance(
            pages_text,
            int(struct.get("page_no") or 0),
            _base_cpd_num(key) or 0,
        )
    strict_matches.sort(key=lambda item: _VISIBLE_LABEL_SOURCE_RANK.get(str(item.get("source") or ""), 99))
    best = strict_matches[0]

    # A strict/direct/PDF visual label on a complete product-like structure is
    # authoritative. Nearby text context is helpful but not required; otherwise
    # patents with dense structure grids and sparse prose bind only a handful of
    # compounds despite clear visual labels.
    source_rank = _VISIBLE_LABEL_SOURCE_RANK.get(str(best.get("source") or ""), 99)
    if source_rank > _VISIBLE_LABEL_SOURCE_RANK.get("pdf_clip", 3) and exact_label != key and product_context_distance > 1:
        return None

    return {
        "label": str(best.get("label") or key),
        "label_key": key,
        "source": str(best.get("source") or ""),
        "product_context_distance": product_context_distance,
        "multi_label_crop": False,
        "strict_visual_missing_backfill": True,
    }


def _extract_visual_module_bindings(
    doc,
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    target_bases: Optional[set[int]] = None,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Build high-confidence bindings from complete visual modules.

    This pass is intentionally separate from heading/prose fallbacks: it scans
    every structure module for a visible active compound number and only keeps
    candidates that also sit on a page with product context for that compound.
    It is used to repair missing/fallback bindings without disturbing existing
    strong direct-label bindings.
    """
    active_keys = _active_label_keys(active_cpds)
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if target_bases is not None:
        active_bases &= set(target_bases)
        active_keys = {key for key in active_keys if (_base_cpd_num(key) in active_bases)}
    if not active_keys:
        return []

    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    page_structs_by_no: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        page_structs_by_no.setdefault(int(struct.get("page_no") or 0), []).append(struct)
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in page_structs_by_no.items()
    }
    by_key: Dict[str, List[Dict]] = {}
    for struct in processed_structures:
        sid = str(struct.get("id") or "")
        cache_item = (visible_label_cache or {}).get(sid)
        if isinstance(cache_item, dict):
            visual_candidates = _contextual_visible_label_candidates(
                struct,
                _normalise_visible_cache_item(cache_item),
                active_keys,
                pages_text,
                max_context_distance=1,
                lines_by_page=lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
        else:
            labels = _ocr_visible_label_band_from_page_image(struct)
            if not any(_cpd_label_key(str(label)) in active_keys for label in labels):
                labels = [*labels, *_ocr_visible_label_band_from_page_image(struct, wide=True)]
            visual_candidates = [
                {
                    "label": _normalise_compound_label(str(label)),
                    "source": "ocr",
                    "product_context_distance": _product_context_distance(pages_text, int(struct.get("page_no") or 0), _base_cpd_num(str(label)) or 0) if _cpd_label_key(str(label)) in active_keys else 999,
                    "multi_label_crop": len(labels) > 1,
                }
                for label in labels
            ]
        for visual_candidate in visual_candidates:
            label = _normalise_compound_label(str(visual_candidate.get("label") or ""))
            label_key = _cpd_label_key(label)
            if not label_key or not re.fullmatch(r"[1-9]\d{0,2}[A-Z]?", label, re.IGNORECASE):
                continue
            if label_key not in active_keys:
                continue
            nearby_label_kind = _nearby_ocr_label_kind(struct, label_key, lines_by_page)
            if nearby_label_kind == "racemic":
                continue
            ok_exact, exact_label = _passes_exact_visual_label_guard(
                struct,
                label_key,
                lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
            if not ok_exact:
                continue
            product_context_distance = _int_or_default(visual_candidate.get("product_context_distance"), 999)
            if product_context_distance > 1:
                continue
            if not _is_contextual_final_visual_candidate(struct, visual_candidate):
                continue
            width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
            height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
            if width * height < 2500:
                continue
            binding = _build_binding_from_structure(struct, label_key)
            binding["binding_rule"] = "direct_structure_label"
            binding["visible_label"] = str(label)
            binding["visual_label_source"] = "module"
            binding["visible_label_crop_source"] = str(visual_candidate.get("source") or "")
            binding["visible_label_multi_candidate"] = bool(visual_candidate.get("multi_label_crop"))
            binding["product_context_nearby"] = True
            binding["product_context_distance"] = product_context_distance
            if nearby_label_kind:
                binding["nearby_ocr_label_kind"] = nearby_label_kind
            if exact_label:
                binding["nearby_exact_product_label"] = exact_label
            binding["struct_width"] = width
            binding["struct_height"] = height
            binding["struct_area"] = width * height
            by_key.setdefault(label_key, []).append(binding)

    selected: List[Dict] = []
    for _key, candidates in by_key.items():
        selected.append(min(
            candidates,
            key=lambda b: (
                _int_or_default(b.get("product_context_distance"), 999),
                _visual_module_score({
                    "x0": b.get("struct_x0"),
                    "x1": float(b.get("struct_x0") or 0) + float(b.get("struct_width") or 0),
                    "y0": b.get("struct_y0"),
                    "y1": float(b.get("struct_y0") or 0) + float(b.get("struct_height") or 0),
                    "idx": b.get("structure_index"),
                }),
            )
        ))
    return selected


def _active_visible_keys_for_struct(
    struct: Dict,
    visible_label_cache: Optional[Dict[str, Dict]],
    active_keys: set[str],
) -> List[Tuple[str, str]]:
    labels: List[Tuple[str, str]] = []
    for candidate in _normalise_visible_cache_item((visible_label_cache or {}).get(str(struct.get("id") or ""))):
        label = _normalise_compound_label(str(candidate.get("label") or ""))
        key = _cpd_label_key(label)
        source = str(candidate.get("source") or "")
        if key in active_keys and source in _VISUAL_LABEL_SOURCES:
            labels.append((key, source))
    return labels


def _visual_grid_primary_key(labels: List[Tuple[str, str]], page_min: int, page_max: int) -> Optional[Tuple[str, str, bool]]:
    """Choose the printed product ID on dense structure-grid pages."""
    if not labels:
        return None
    ranked: List[Tuple[int, int, int, str, str]] = []
    for key, source in labels:
        base = _base_cpd_num(key)
        if base is None:
            continue
        in_page_sequence = page_min <= base <= page_max
        low_internal = base < page_min and base <= 30
        if not in_page_sequence and not low_internal:
            continue
        ranked.append((
            0 if in_page_sequence else 3,
            0 if source == "page_wide" else _VISIBLE_LABEL_SOURCE_RANK.get(source, 9),
            -base,
            key,
            source,
        ))
    if not ranked:
        return None
    ranked.sort()
    rank, _source_rank, _neg_base, key, source = ranked[0]
    if rank != 0:
        return None
    competing = [
        other_key for other_key, _source in labels
        if other_key != key
        and (other_base := _base_cpd_num(other_key)) is not None
        and page_min <= other_base <= page_max
    ]
    if competing:
        return None
    return key, source, len({label for label, _source in labels}) > 1


def _dominant_visual_grid_base_range(page_bases: List[int], structure_count: int) -> Optional[Tuple[int, int, int]]:
    """Return the dense product-number run on a structure-grid page.

    Structure drawings often contain small substituent, reagent, or assay
    numbers. Dense grid pages, however, present final products as a compact
    sequence. Use the densest high-number window as the authoritative page
    range instead of letting a few internal labels stretch min/max.
    """
    bases = sorted({int(base) for base in page_bases if int(base) > 30})
    if len(bases) < 6:
        return None
    max_span = max(40, int(structure_count) * 2)
    best: Optional[Tuple[int, int, int, int, int]] = None
    for idx, start in enumerate(bases):
        window = [base for base in bases[idx:] if base - start <= max_span]
        if len(window) < 6:
            continue
        end = window[-1]
        count = len(window)
        span = max(1, end - start + 1)
        density = count / span
        high_count = sum(1 for base in window if base >= 100)
        score = (
            -count,
            -int(density * 1000),
            -high_count,
            span,
            start,
        )
        if best is None or score < best:
            best = score
    if best is None:
        return None
    _neg_count, _neg_density, _neg_high_count, _span, start = best
    count = -_neg_count
    end = max(base for base in bases if start <= base <= start + max_span)
    return start, end, count


def _visual_grid_sequence_order_bindings(
    page_structs: List[Dict],
    visible_items: List[Tuple[Dict, List[Tuple[str, str]]]],
    active_keys: set[str],
    page_min: int,
    page_max: int,
    page_label_count: int,
) -> List[Dict]:
    """Fill dense grid-page gaps from row/column order when visual anchors agree."""
    rows = _group_structures_by_row(page_structs, y_threshold=42.0)
    ordered_structs = [struct for row in rows for struct in sorted(row, key=lambda item: float(item.get("x0") or 0))]
    if len(ordered_structs) < 6:
        return []

    label_map: Dict[str, List[Tuple[str, str]]] = {
        str(struct.get("id") or ""): labels
        for struct, labels in visible_items
    }
    direct_anchors: List[Tuple[int, int, Tuple[str, str, bool]]] = []
    for idx, struct in enumerate(ordered_structs):
        selected = _visual_grid_primary_key(
            label_map.get(str(struct.get("id") or ""), []),
            page_min,
            page_max,
        )
        if not selected:
            continue
        key, _source, _multi = selected
        base = _base_cpd_num(key)
        if base is not None:
            direct_anchors.append((idx, base, selected))
    if len(direct_anchors) < 6:
        return []

    offset_counts: Dict[int, int] = {}
    for position, base, _selected in direct_anchors:
        offset = base - position
        offset_counts[offset] = offset_counts.get(offset, 0) + 1
    sequence_start, anchor_count = sorted(
        offset_counts.items(),
        key=lambda item: (-item[1], abs(item[0] - page_min), item[0]),
    )[0]
    if anchor_count < max(6, int(len(direct_anchors) * 0.65)):
        return []
    selected_by_position = {
        position: selected
        for position, base, selected in direct_anchors
        if base - position == sequence_start
    }
    sequence_positions = [
        (idx, sequence_start + idx)
        for idx in range(len(ordered_structs))
        if page_min - 3 <= sequence_start + idx <= page_max + 3
        and str(sequence_start + idx) in active_keys
    ]
    if len(sequence_positions) < 6:
        return []

    additions: List[Dict] = []
    for idx, base in sequence_positions:
        key = str(base)
        struct = ordered_structs[idx]
        labels = label_map.get(str(struct.get("id") or ""), [])
        selected = selected_by_position.get(idx)
        if selected:
            label, source, multi_label = selected
            binding_rule = "visual_grid_label"
        else:
            label = key
            source = "visual_grid_sequence"
            multi_label = len({label_key for label_key, _source in labels}) > 1
            binding_rule = "visual_grid_sequence_order"
        binding = _build_binding_from_structure(struct, key)
        binding["binding_rule"] = binding_rule
        binding["visible_label"] = label
        binding["visual_label_source"] = "visual_grid" if binding_rule == "visual_grid_label" else "visual_grid_sequence"
        binding["visible_label_crop_source"] = source
        binding["visible_label_multi_candidate"] = False if binding_rule == "visual_grid_label" else bool(multi_label)
        if multi_label:
            binding["visual_grid_internal_labels"] = [
                label_key for label_key, _source in labels if label_key != key
            ]
        binding["product_context_nearby"] = True
        binding["product_context_distance"] = 0
        binding["visible_labels"] = [label_key for label_key, _source in labels]
        binding["visible_label_candidates"] = [
            {"label": label_key, "source": source_name}
            for label_key, source_name in labels
        ]
        binding["visual_grid_page_min"] = int(page_min)
        binding["visual_grid_page_max"] = int(page_max)
        binding["visual_grid_page_label_count"] = int(page_label_count)
        binding["visual_grid_sequence_confirmed"] = binding_rule == "visual_grid_sequence_order"
        binding["visual_grid_anchor_count"] = int(anchor_count)
        binding["visual_grid_sequence_position"] = int(idx + 1)
        binding["visual_grid_sequence_start"] = int(sequence_start)
        additions.append(binding)
    return additions


def _extract_visual_grid_label_bindings(
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]],
) -> List[Dict]:
    """Bind dense structure-grid pages by the visible label printed under each drawing.

    This targets pages where the patent itself presents a regular grid of final
    product structures. In that layout prose context is sparse, but the visual
    label below the structure is the authoritative compound ID. The rule is
    intentionally page-level: it fires only when many structures and visible
    active labels form a coherent sequence on the same page.
    """
    if not active_cpds or not visible_label_cache:
        return []
    active_keys = _active_label_keys(active_cpds)
    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)

    bindings: List[Dict] = []
    for page_no, page_structs in sorted(by_page.items()):
        shaped_structs = [
            struct for struct in page_structs
            if _is_contextual_final_visual_candidate(
                struct,
                {"source": "page_wide", "product_context_distance": 0, "multi_label_crop": False},
            )
        ]
        if len(shaped_structs) < 8:
            continue
        visible_items: List[Tuple[Dict, List[Tuple[str, str]]]] = []
        page_bases: List[int] = []
        for struct in shaped_structs:
            labels = _active_visible_keys_for_struct(struct, visible_label_cache, active_keys)
            if not labels:
                continue
            bases = [
                base for key, _source in labels
                for base in [_base_cpd_num(key)]
                if base is not None and base > 30
            ]
            if bases:
                visible_items.append((struct, labels))
                page_bases.extend(bases)
        if len(visible_items) < 6 or len(set(page_bases)) < 6:
            continue
        page_range = _dominant_visual_grid_base_range(page_bases, len(shaped_structs))
        if not page_range:
            continue
        page_min, page_max, page_label_count = page_range

        page_bindings = _visual_grid_sequence_order_bindings(
            page_structs,
            visible_items,
            active_keys,
            page_min,
            page_max,
            page_label_count,
        )
        if not page_bindings:
            page_bindings = []
            used_keys: set[str] = set()
            for struct, labels in sorted(visible_items, key=lambda item: (float(item[0].get("y0") or 0), float(item[0].get("x0") or 0))):
                selected = _visual_grid_primary_key(labels, page_min, page_max)
                if not selected:
                    continue
                key, source, multi_label = selected
                if key in used_keys:
                    continue
                binding = _build_binding_from_structure(struct, key)
                binding["binding_rule"] = "visual_grid_label"
                binding["visible_label"] = key
                binding["visual_label_source"] = "visual_grid"
                binding["visible_label_crop_source"] = source
                binding["visible_label_multi_candidate"] = False
                if multi_label:
                    binding["visual_grid_internal_labels"] = [
                        label for label, _source in labels if label != key
                    ]
                binding["product_context_nearby"] = True
                binding["product_context_distance"] = 0
                binding["visible_labels"] = [label for label, _source in labels]
                binding["visible_label_candidates"] = [
                    {"label": label, "source": source_name}
                    for label, source_name in labels
                ]
                binding["visual_grid_page_min"] = int(page_min)
                binding["visual_grid_page_max"] = int(page_max)
                binding["visual_grid_page_label_count"] = int(page_label_count)
                page_bindings.append(binding)
                used_keys.add(key)
        if page_bindings:
            bindings.extend(page_bindings)

    if bindings:
        logger.info(
            "   👁 结构网格可见编号绑定: %d rows",
            len(bindings),
        )
    return _active_ordered_bindings(bindings, active_cpds)


def _derive_right_product_binding(binding: Dict, output_dir: str) -> Optional[Dict]:
    """For a wide reaction-route crop, derive a right-end product crop.

    Some pages are segmented as a whole reaction route with the final label
    printed under the right-end product. OCSR should see the product module, not
    the full route. This deterministic crop is only used for unusually wide
    direct-label bindings.
    """
    image_path = str(binding.get("image_path") or "")
    if not image_path or not os.path.exists(image_path):
        return None
    width = float(binding.get("struct_width") or 0)
    height = float(binding.get("struct_height") or 0)
    aspect = width / max(height, 1.0) if width and height else 0.0
    if width <= 0 or height <= 0 or aspect <= 5.5:
        return None
    if width * height < 6500:
        return None
    labels = _visible_label_keys_for_binding(binding)
    target_key = _binding_label_key(binding)
    if labels - {target_key}:
        return None
    if (
        str(binding.get("binding_rule") or "") == "direct_structure_label"
        and str(binding.get("visual_label_source") or "") in {"module", "clean_standalone_arbitration", "cache_confirmed"}
    ):
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return None

    crop_left = int(img.width * 0.58)
    crop = img.crop((crop_left, 0, img.width, img.height))
    derived_width = float(binding.get("struct_width") or 0) * 0.42
    derived_height = float(binding.get("struct_height") or 0)
    derived_area = derived_width * derived_height
    derived_aspect = derived_width / max(derived_height, 1.0) if derived_width and derived_height else 0.0
    if derived_area < 6500 or derived_aspect > 5.0:
        return None
    derived_dir = Path(output_dir) / "derived_structures"
    derived_dir.mkdir(parents=True, exist_ok=True)
    base = _binding_base_num(binding) or binding.get("compound_num") or "unknown"
    src_id = str(binding.get("structure_id") or "structure")
    derived_path = derived_dir / f"{src_id}_compound_{base}_right_product.png"
    crop.save(derived_path)

    derived = dict(binding)
    derived["source_structure_id"] = binding.get("structure_id")
    derived["structure_id"] = f"{src_id}_right_product"
    derived["image_path"] = str(binding.get("image_path") or "")
    derived["display_image_path"] = str(binding.get("image_path") or "")
    derived["source_image_path"] = str(binding.get("image_path") or "")
    derived["ocsr_image_path"] = str(derived_path)
    derived["binding_rule"] = "direct_structure_label_right_product_crop"
    derived["visual_label_source"] = "route_right_product"
    derived["struct_width"] = derived_width
    derived["struct_area"] = derived_area
    derived["struct_aspect"] = derived_aspect
    return derived


def _repair_fallback_bindings_with_visual_modules(
    final_bindings: List[Dict],
    visual_bindings: List[Dict],
    active_cpds: List[str],
    output_dir: str = "",
) -> List[Dict]:
    """Replace only missing/prose fallback bindings with visual module matches."""
    if not active_cpds or not visual_bindings:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    visual_by_key = {
        _binding_label_key(binding): binding
        for binding in sorted(visual_bindings, key=lambda b: _visual_binding_priority(b, active_keys))
        if _binding_label_key(binding)
    }
    by_key = {
        _binding_label_key(binding): binding
        for binding in final_bindings
        if _binding_label_key(binding)
    }
    fallback_rules = {
        "product_section_context",
        "heading_range_fallback",
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "paired_route_product_row_order",
        "triplet_split_row_structure_order",
        "split_reaction_product_label",
        "ocr_numeric_structure_label",
        "ocr_bare_numeric_product_label",
    }
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if not key or key not in visual_by_key:
            continue
        current = by_key.get(key)
        current_rule = str(current.get("binding_rule") or "") if current else ""
        current_area = float((current or {}).get("struct_area") or 0)
        current_w = float((current or {}).get("struct_width") or 0)
        current_h = float((current or {}).get("struct_height") or 0)
        current_is_weak_direct = (
            current_rule == "direct_structure_label"
            and (
                current_area < 5000
                or (current_w > 0 and current_h > 0 and current_w / max(current_h, 1.0) > 5.5)
            )
        )
        if current is None or current_rule in fallback_rules or current_is_weak_direct:
            by_key[key] = visual_by_key[key]

    if output_dir:
        for key, current in list(by_key.items()):
            if current is None:
                continue
            derived = _derive_right_product_binding(current, output_dir)
            if derived:
                by_key[key] = derived

    ordered = []
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if key in by_key:
            ordered.append(by_key[key])
    # Keep any non-active leftovers for callers that do not use active gating.
    ordered.extend(b for b in final_bindings if _binding_label_key(b) not in active_keys)
    return ordered


def _replace_with_expanded_strict_crops(
    final_bindings: List[Dict],
    output_dir: str,
) -> List[Dict]:
    """Use saved strict-label expanded crops for SMILES/final output."""
    if not final_bindings:
        return final_bindings
    expanded_dir = Path(output_dir) / "expanded_strict_labels"
    if not expanded_dir.is_dir():
        return final_bindings
    replaced = 0
    updated: List[Dict] = []
    for binding in final_bindings:
        item = dict(binding)
        key = _binding_label_key(item)
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        if not key or not sid:
            updated.append(item)
            continue
        path = expanded_dir / f"{sid}_compound_{key}_expanded.png"
        if not path.is_file():
            updated.append(item)
            continue
        if (
            _is_complete_product_like_structure({
                "x0": item.get("struct_x0"),
                "x1": item.get("struct_x1"),
                "y0": item.get("struct_y0"),
                "y1": item.get("struct_y1"),
            })
            and str(item.get("binding_rule") or "") in {"direct_structure_label", "route_title_row_right_product"}
        ):
            updated.append(item)
            continue
        try:
            from PIL import Image

            img = Image.open(path)
            width_px, height_px = img.size
            scale = 72 / 150
            item["struct_width"] = width_px * scale
            item["struct_height"] = height_px * scale
            item["struct_area"] = item["struct_width"] * item["struct_height"]
            item["struct_aspect"] = width_px / max(height_px, 1)
        except Exception:
            pass
        item["display_image_path"] = str(item.get("display_image_path") or item.get("source_image_path") or item.get("image_path") or path)
        item["image_path"] = str(item.get("source_image_path") or item.get("image_path") or path)
        item["source_structure_id"] = sid
        item["structure_id"] = f"{sid}_expanded"
        item["expanded_from_fragment"] = sid
        item["source_image_path"] = str(item.get("source_image_path") or "")
        item["ocsr_image_path"] = str(item.get("ocsr_image_path") or item.get("source_image_path") or path)
        if str(item.get("binding_rule") or "") == "direct_structure_label":
            item["binding_rule"] = "direct_structure_label_merged_fragment"
        replaced += 1
        updated.append(item)
    if replaced:
        logger.info("   🧩 使用严格可见标签扩展图作为最终结构: %d rows", replaced)
    return updated


def _arbitrate_with_clean_standalone_visual_products(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Replace route/intermediate winners with clean standalone product drawings.

    A strict OCR crop proves that a number is visible, but an intermediate such
    as ``80A`` may contain the parent ``80`` text as well. When another complete
    standalone crop has only the exact active label, that clean visual evidence
    is authoritative even if its label came from a wider OCR band.
    """
    if not final_bindings or not active_cpds or not visible_label_cache:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    annotated = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    by_key = {
        _binding_label_key(binding): dict(binding)
        for binding in annotated
        if _binding_label_key(binding)
    }
    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    rows_by_page: Dict[int, List[List[Dict]]] = {}
    for page_no in sorted({int(struct.get("page_no") or 0) for struct in processed_structures}):
        rows_by_page[page_no] = _group_structures_by_row(
            [struct for struct in processed_structures if int(struct.get("page_no") or 0) == page_no],
            y_threshold=55.0,
        )
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    candidate_by_key: Dict[str, List[Tuple[Tuple[int, int, int, int, int, int], Dict]]] = {}
    for sid, cache_item in (visible_label_cache or {}).items():
        struct = struct_by_id.get(str(sid))
        if not struct:
            continue
        candidates = _normalise_visible_cache_item(cache_item)
        label_keys = {
            _cpd_label_key(str(candidate.get("label") or ""))
            for candidate in candidates
            if _cpd_label_key(str(candidate.get("label") or ""))
        }
        if len(label_keys) != 1:
            continue
        key = next(iter(label_keys))
        if key not in active_keys or not _is_ocsr_single_molecule_source(struct):
            continue
        exact_candidates = [
            candidate for candidate in candidates
            if _cpd_label_key(str(candidate.get("label") or "")) == key
        ]
        if not exact_candidates:
            continue
        row = _row_for_structure(struct, rows_by_page)
        ok_exact, exact_label = _passes_exact_visual_label_guard(
            struct,
            key,
            lines_by_page,
            row=row,
        )
        if not ok_exact:
            continue
        source_candidate = min(
            exact_candidates,
            key=lambda candidate: _VISIBLE_LABEL_SOURCE_RANK.get(str(candidate.get("source") or ""), 99),
        )
        context_distance = _product_context_distance(
            pages_text,
            int(struct.get("page_no") or 0),
            _base_cpd_num(key) or 0,
        )
        if context_distance > 1:
            continue
        binding = _build_binding_from_structure(struct, key)
        binding["binding_rule"] = "direct_structure_label"
        binding["visible_label"] = _normalise_compound_label(str(source_candidate.get("label") or key))
        binding["visible_labels"] = _labels_from_visible_cache_item(cache_item)
        binding["visible_label_candidates"] = candidates
        binding["visual_label_source"] = "clean_standalone_arbitration"
        binding["visible_label_crop_source"] = str(source_candidate.get("source") or "")
        binding["visible_label_multi_candidate"] = False
        binding["product_context_nearby"] = context_distance <= 1
        binding["product_context_distance"] = int(context_distance)
        binding["ocsr_source_clean_single_molecule"] = True
        if exact_label:
            binding["nearby_exact_product_label"] = exact_label
        geom = _structure_geometry(struct)
        module_score = _visual_module_score(struct)
        score = (
            0 if context_distance <= 1 else 1,
            int(context_distance),
            module_score[0],
            module_score[1],
            _VISIBLE_LABEL_SOURCE_RANK.get(str(source_candidate.get("source") or ""), 99),
            -int(geom["struct_area"]),
        )
        candidate_by_key.setdefault(key, []).append((score, binding))

    replacements = []
    for key, current in by_key.items():
        if key not in active_keys or key not in candidate_by_key:
            continue
        current_sid = str(current.get("source_structure_id") or current.get("structure_id") or "")
        current_struct = struct_by_id.get(current_sid)
        current_labels = _visible_label_keys_for_binding(current)
        current_is_clean_complete = bool(
            current_struct
            and current_labels == {key}
            and _is_ocsr_single_molecule_source(current_struct)
            and not current.get("expanded_from_fragment")
        )
        if current_is_clean_complete:
            continue
        rule = str(current.get("binding_rule") or "")
        should_arbitrate = bool(
            current_labels - {key}
            or current.get("expanded_from_fragment")
            or rule == "direct_structure_label_merged_fragment"
            or (
                rule == "direct_structure_label"
                and current_struct
                and not _is_ocsr_single_molecule_source(current_struct)
            )
        )
        if not should_arbitrate:
            continue
        candidates = sorted(candidate_by_key[key], key=lambda item: item[0])
        candidate = next(
            (binding for _score, binding in candidates
             if str(binding.get("structure_id") or "") != current_sid),
            None,
        )
        if not candidate:
            continue
        by_key[key] = candidate
        replacements.append((key, current_sid, str(candidate.get("structure_id") or "")))

    if replacements:
        logger.info(
            "   👁 干净独立终产物视觉仲裁: %d rows (%s)",
            len(replacements),
            ", ".join(f"{key}:{old}->{new}" for key, old, new in replacements),
        )
    return _active_ordered_bindings(list(by_key.values()), active_cpds)


def _active_ordered_bindings(final_bindings: List[Dict], active_cpds: List[str]) -> List[Dict]:
    """Use activity compounds as the canonical output set and order.

    Binder candidates are still useful for finding images, but downstream final
    tables must not be driven by non-active synthesis/intermediate headings.
    """
    if not active_cpds:
        return sorted(final_bindings, key=_binding_sort_key)

    by_key: Dict[str, Dict] = {}
    active_keys = _active_label_keys(active_cpds)
    for binding in sorted(final_bindings, key=lambda b: _visual_binding_priority(b, active_keys)):
        key = _binding_label_key(binding)
        if not key or key not in active_keys or key in by_key:
            continue
        by_key[key] = _normalise_binding_to_compound(dict(binding), key)

    ordered: List[Dict] = []
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if key in by_key:
            ordered.append(by_key[key])
    return ordered


def _seed_singleton_active_compound_binding(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
) -> List[Dict]:
    """Bind a non-numbered singleton active compound to the claim/formula image.

    Numbered SAR patents are handled by visible labels. Single-compound use or
    formulation patents often show the only structure in a claim/formula page
    and refer to it as "claim 1" rather than "Compound 1".
    """
    if "CLAIM1" not in _active_label_keys(active_cpds):
        return final_bindings
    if any(_binding_label_key(binding) == "CLAIM1" for binding in final_bindings):
        return final_bindings
    if not processed_structures:
        return final_bindings

    singleton_re = re.compile(
        r"claim\s*1.{0,220}(?:formula\s+shown\s+here|shown\s+here|new\s+compound)|"
        r"(?:formula\s+shown\s+here|shown\s+here).{0,220}claim\s*1|"
        r"formula\s+of\s+the\s+new\s+compound|chemical\s+formula.{0,180}Figure\s*[12]",
        re.IGNORECASE | re.DOTALL,
    )
    candidate_pages = {
        page_idx + 1
        for page_idx, text in (pages_text or {}).items()
        if singleton_re.search(str(text or ""))
    }
    candidates = [
        struct for struct in processed_structures
        if not candidate_pages or int(struct.get("page_no", 0) or 0) in candidate_pages
    ]
    if not candidates:
        candidates = list(processed_structures)
    best = sorted(
        candidates,
        key=lambda s: (
            0 if int(s.get("page_no", 0) or 0) in candidate_pages else 1,
            int(s.get("page_no", 0) or 0),
            float(s.get("y0", 0) or 0),
            float(s.get("x0", 0) or 0),
        ),
    )[0]
    singleton_name = ""
    name_match = re.search(
        r"(?:chemical\s+Name|chemical\s+name|compound\s+with\s+the\s+Name)\s*[\"“'']\s*([^\"”''\n]{30,360})[\"”'']",
        "\n".join(str(text or "") for text in (pages_text or {}).values()),
        re.IGNORECASE,
    )
    if name_match:
        singleton_name = re.sub(r"\s+", " ", name_match.group(1)).strip()
    binding = _attach_structure_geometry({
        "cpd": "Claim 1 compound",
        "cpd_id": "Claim 1 compound",
        "compound_id": "Claim 1 compound",
        "example_id": "Claim 1 compound",
        "prefix": "Claim",
        "structure_id": best["id"],
        "page_no": best["page_no"],
        "structure_index": best["idx"],
        "struct_x0": best["x0"],
        "struct_y0": best["y0"],
        "image_path": best["image_path"],
        "candidates": len(candidates),
        "binding_rule": "singleton_claim_formula_structure",
        "accuracy_status": "confirmed",
        "evidence_tier": "claim_formula_singleton",
        "singleton_chemical_name": singleton_name,
    }, best)
    return _active_ordered_bindings([*final_bindings, binding], active_cpds)


def _replace_with_exact_visible_table_labels(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Prefer exact visible labels over row-order on mixed table/route pages."""
    if not final_bindings or not active_cpds or not visible_label_cache:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    by_key = {
        _binding_label_key(binding): dict(binding)
        for binding in final_bindings
        if _binding_label_key(binding)
    }
    current_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    page_structs_by_no: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        page_structs_by_no.setdefault(int(struct.get("page_no") or 0), []).append(struct)
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in page_structs_by_no.items()
    }
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    replacements = 0
    for sid, cache_item in (visible_label_cache or {}).items():
        sid = str(sid)
        struct = struct_by_id.get(sid)
        if not struct:
            continue
        page_no = int(struct.get("page_no") or 0)
        if not (
            _is_probable_table_structure(struct, page_structs_by_no.get(page_no))
            or _is_complete_visible_product_module(struct)
        ):
            continue
        labels = []
        for candidate in _normalise_visible_cache_item(cache_item):
            source = str(candidate.get("source") or "")
            if source not in _STRICT_VISIBLE_LABEL_SOURCES:
                continue
            label = _normalise_compound_label(str(candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if key in active_keys:
                labels.append((key, label, source))
        exact_keys = {key for key, _label, _source in labels}
        if len(exact_keys) != 1:
            continue
        key, label, source = sorted(labels, key=lambda item: _VISIBLE_LABEL_SOURCE_RANK.get(item[2], 99))[0]
        ok_exact, exact_label = _passes_exact_visual_label_guard(
            struct,
            key,
            lines_by_page,
            row=_row_for_structure(struct, rows_by_page),
        )
        if not ok_exact:
            continue
        current = by_key.get(key)
        if not current:
            continue
        current_rule = str(current.get("binding_rule") or "")
        current_sid = str(current.get("source_structure_id") or current.get("structure_id") or "")
        current_area = float(current.get("struct_area") or 0)
        new_area = _structure_geometry(struct)["struct_area"]
        same_page = int(current.get("page_no") or 0) == page_no
        current_conflicts = key not in _visible_label_keys_for_binding(current) and bool(_visible_label_keys_for_binding(current))
        should_replace = (
            current_rule in {"structure_table_row_order", "structure_table_row_order_inferred", "structure_table_row_order_corrected"}
            and same_page
            and sid != current_sid
            and (
                current_conflicts
                or new_area >= current_area * 0.80
                or (
                    _is_complete_visible_product_module(struct)
                    and key in exact_keys
                    and key not in _visible_label_keys_for_binding(current)
                )
            )
        )
        if not should_replace or sid in current_structures:
            continue
        binding = _build_binding_from_structure(struct, key)
        binding["binding_rule"] = "direct_structure_label"
        binding["visible_label"] = label
        binding["visual_label_source"] = "table_exact_visible"
        binding["visible_label_crop_source"] = source
        binding["visible_label_multi_candidate"] = False
        binding["visible_labels"] = _labels_from_visible_cache_item(cache_item)
        if exact_label:
            binding["nearby_exact_product_label"] = exact_label
        by_key[key] = binding
        current_structures.discard(current_sid)
        current_structures.add(sid)
        replacements += 1

    if replacements:
        logger.info("   👁 表格精确可见编号替换行序绑定: %d rows", replacements)

    ordered: List[Dict] = []
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if key in by_key:
            ordered.append(by_key[key])
    return ordered


def _restore_safe_missing_active_bindings(
    final_bindings: List[Dict],
    candidate_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Restore missing active rows only from product-like table/heading candidates."""
    if not active_cpds or not candidate_bindings:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    present_keys = {_binding_label_key(binding) for binding in final_bindings}
    missing_keys = active_keys - present_keys
    if not missing_keys:
        return final_bindings

    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    page_structs_by_no: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        page_structs_by_no.setdefault(int(struct.get("page_no") or 0), []).append(struct)
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in page_structs_by_no.items()
    }

    restore_rules = {
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "heading_range_fallback",
    }
    additions: List[Dict] = []
    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    for binding in candidate_bindings:
        key = _binding_label_key(binding)
        if key not in missing_keys:
            continue
        rule = str(binding.get("binding_rule") or "")
        if rule not in restore_rules:
            continue
        sid = str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        if not sid or sid in used_structures:
            continue
        struct = struct_by_id.get(sid)
        if not struct:
            continue
        geom = _structure_geometry(struct)
        page_no = int(struct.get("page_no") or 0)
        table_like = _is_probable_table_structure(struct, page_structs_by_no.get(page_no))
        heading_like = rule == "heading_range_fallback" and _is_complete_visible_product_module(struct)
        if not table_like and not heading_like:
            continue
        if geom["struct_area"] < 6500:
            continue

        replacement_struct = _right_complete_product_on_same_row(struct, rows_by_page)
        if replacement_struct and str(replacement_struct.get("id") or "") not in used_structures:
            struct = replacement_struct
            sid = str(struct.get("id") or "")
            rule = "heading_row_right_product_recovery"
            geom = _structure_geometry(struct)

        item = _normalise_binding_to_compound(dict(binding), key)
        item["structure_id"] = sid
        item["source_structure_id"] = sid
        item["page_no"] = struct["page_no"]
        item["structure_index"] = struct["idx"]
        item["struct_x0"] = struct["x0"]
        item["struct_y0"] = struct["y0"]
        item["image_path"] = struct["image_path"]
        _attach_structure_geometry(item, struct)
        item["binding_rule"] = rule
        item = _annotate_bindings_with_visible_labels([item], visible_label_cache)[0]
        right_product_recovery = rule == "heading_row_right_product_recovery"
        if (
            _visible_label_conflict_rank(item, active_keys) >= 5
            and key not in _strict_visible_label_keys_for_binding(item)
            and not right_product_recovery
        ):
            continue
        if _is_low_internal_label_in_multi_visible_crop(item):
            continue
        item["restored_missing_active"] = True
        additions.append(item)
        used_structures.add(sid)
        missing_keys.discard(key)

    if additions:
        logger.info(
            "   表格/标题完整结构安全回填缺失活性编号: +%d (%s)",
            len(additions),
            ", ".join(_binding_label_key(item) for item in additions),
        )
    return _active_ordered_bindings([*final_bindings, *additions], active_cpds)


def _fill_missing_from_cmpd_overview_tables(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Recover active structures from Cmpd No./Structure overview grids."""
    if not active_cpds:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    present_keys = {_binding_label_key(binding) for binding in final_bindings}
    missing_keys = active_keys - present_keys
    if not missing_keys:
        return final_bindings

    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    additions: List[Dict] = []
    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    for page_idx, text in sorted((pages_text or {}).items()):
        page_text = str(text or "")
        overview_like = bool(re.search(r"Cmpd\s*No\.?\s+Structure", page_text, re.IGNORECASE))
        similar_like = bool(re.search(r"(?:Examples?|Compounds?)\s+\d{1,3}[^\n]{0,120}(?:prepared|following|similar procedure)", page_text, re.IGNORECASE))
        if not overview_like and not similar_like:
            continue
        page_no = int(page_idx) + 1
        page_structs = sorted(
            by_page.get(page_no, []),
            key=lambda item: (float(item.get("y0") or 0), float(item.get("x0") or 0)),
        )
        page_lines = lines_by_page.get(page_no - 1) or []
        active_bases = {_base_cpd_num(key) for key in missing_keys}
        active_bases.discard(None)
        row_entries = _extract_table_row_numbers_from_lines(page_lines, active_bases, page_structs)
        if not row_entries:
            # Do not recover from flat prose order. Overview/table recovery is
            # only safe when OCR gives the left compound-number column.
            continue
        struct_rows = _group_structures_by_row(
            [s for s in page_structs if str(s.get("id") or "") not in used_structures],
            y_threshold=55.0,
        )
        if not struct_rows:
            continue
        row_available = list(enumerate(struct_rows))
        for num, y0, _text in row_entries:
            key = _cpd_label_key(str(num))
            if key not in missing_keys:
                continue
            if not row_available:
                break
            best_idx, best_row = min(
                row_available,
                key=lambda pair: abs(float(y0) - _structure_row_bounds(pair[1])[2]),
            )
            if abs(float(y0) - _structure_row_bounds(best_row)[2]) > 95.0:
                continue
            struct = _best_table_structure_for_row_label(best_row, y0, page_structs)
            if not struct or not _is_complete_visible_product_module(struct):
                row_available = [item for item in row_available if item[0] != best_idx]
                continue
            sid = str(struct.get("id") or "")
            if sid in used_structures:
                row_available = [item for item in row_available if item[0] != best_idx]
                continue
            binding = _build_binding_from_structure(struct, key)
            binding["binding_rule"] = "cmpd_overview_table_order"
            binding["overview_table_recovery"] = True
            additions.append(binding)
            used_structures.add(sid)
            missing_keys.discard(key)
            row_available = [item for item in row_available if item[0] != best_idx]
        if not missing_keys:
            break

    if additions:
        logger.info(
            "   Cmpd No./Structure总览表补齐缺失活性结构: +%d (%s)",
            len(additions),
            ", ".join(_binding_label_key(item) for item in additions),
        )
    return _active_ordered_bindings([*final_bindings, *additions], active_cpds)


_ROUTE_TITLE_RE = re.compile(
    r"(?:^|[\s\]\).;。；])(?:Examples?|Compounds?|实施例|化合物)\s*([1-9]\d{0,2}[A-Z]?)\s*[:：]",
    re.IGNORECASE,
)


def _route_title_numbers_from_text(page_text: str, active_keys: Optional[set[str]] = None) -> List[str]:
    labels: List[str] = []
    for match in _ROUTE_TITLE_RE.finditer(str(page_text or "")):
        key = _cpd_label_key(match.group(1))
        if not key:
            continue
        if active_keys and key not in active_keys:
            continue
        if key not in labels:
            labels.append(key)
    return labels


def _route_product_structures_from_page(page_structs: List[Dict]) -> List[Dict]:
    products: List[Dict] = []
    rows = _group_structures_by_row(page_structs, y_threshold=65.0)
    for row in rows:
        if len(row) < 2:
            continue
        candidates = [
            struct for struct in row
            if _is_complete_visible_product_module(struct)
        ]
        if not candidates:
            continue
        product = max(
            candidates,
            key=lambda struct: (
                float(struct.get("x0") or 0),
                _structure_geometry(struct)["struct_area"],
            ),
        )
        products.append(product)
    return products


def _fill_missing_from_route_title_rows(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Recover missing active examples from route-title rows.

    Some OCR PDFs flatten heading coordinates to y=0, but the visual page remains
    regular: "Example N:" titles appear in text order and each reaction row ends
    with the final product on the right. Use that layout only for missing active
    rows and never on true structure-table pages.
    """
    if not active_cpds:
        return final_bindings
    active_keys = _active_label_keys(active_cpds)
    present_keys = {_binding_label_key(binding) for binding in final_bindings}
    missing_keys = active_keys - present_keys
    if not missing_keys:
        return final_bindings

    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    additions: List[Dict] = []
    for page_idx, text in sorted((pages_text or {}).items()):
        page_no = int(page_idx) + 1
        page_text = str(text or "")
        title_keys = _route_title_numbers_from_text(page_text)
        if not any(key in missing_keys for key in title_keys):
            continue
        page_structs = sorted(
            by_page.get(page_no, []),
            key=lambda item: (float(item.get("y0") or 0), float(item.get("x0") or 0)),
        )
        if not page_structs:
            continue
        page_lines = lines_by_page.get(page_no - 1) or []
        active_bases = {_base_cpd_num(key) for key in active_keys}
        active_bases.discard(None)
        if _is_structure_table_layout(page_structs, page_text, ocr_lines=page_lines, active_bases=active_bases):
            continue
        products = [
            struct for struct in _route_product_structures_from_page(page_structs)
            if str(struct.get("id") or "") not in used_structures
        ]
        if not products:
            continue
        # A page can begin with the previous example's scheme and only later show
        # the current "Example N:" title. If OCR sees fewer titles than route
        # rows, align the visible titles to the trailing product rows.
        product_offset = max(0, len(products) - len(title_keys))
        for idx, key in enumerate(title_keys):
            product_idx = product_offset + idx
            if key not in missing_keys or product_idx >= len(products):
                continue
            struct = products[product_idx]
            sid = str(struct.get("id") or "")
            if sid in used_structures:
                continue
            binding = _build_binding_from_structure(struct, key)
            binding["binding_rule"] = "route_title_row_right_product"
            binding["route_title_recovery"] = True
            binding = _annotate_bindings_with_visible_labels([binding], visible_label_cache)[0]
            additions.append(binding)
            used_structures.add(sid)
            missing_keys.discard(key)
        if not missing_keys:
            break

    if additions:
        logger.info(
            "   反应路线标题行右侧产物补齐缺失活性结构: +%d (%s)",
            len(additions),
            ", ".join(_binding_label_key(item) for item in additions),
        )
    return _active_ordered_bindings([*final_bindings, *additions], active_cpds)


def _fill_missing_active_from_visible_cache(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Recover missing active compounds from strict visual labels.

    This runs after normal binding/repair. It does not invent non-active rows:
    a structure can be used only when its cached visible label is an active
    compound number and nearby product context confirms that same number.
    """
    if not active_cpds or not visible_label_cache:
        return final_bindings
    active_keys = _active_label_keys(active_cpds)
    used_keys = {_binding_label_key(binding) for binding in final_bindings}
    used_keys.discard("")
    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    missing_keys = active_keys - used_keys
    if not missing_keys:
        return final_bindings

    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    page_structs_by_no: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        page_structs_by_no.setdefault(int(struct.get("page_no") or 0), []).append(struct)
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in page_structs_by_no.items()
    }
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    candidates_by_key: Dict[str, List[Tuple[Tuple[int, int, int, int, int], Dict]]] = {}
    for sid, cache_item in (visible_label_cache or {}).items():
        sid = str(sid)
        if sid in used_structures:
            continue
        struct = struct_by_id.get(sid)
        if not struct:
            continue
        visual_candidates = _contextual_visible_label_candidates(
            struct,
            _normalise_visible_cache_item(cache_item),
            missing_keys,
            pages_text,
            max_context_distance=1,
            lines_by_page=lines_by_page,
            row=_row_for_structure(struct, rows_by_page),
        )
        if not visual_candidates:
            visual_candidate = _strict_single_visible_candidate_for_missing(
                struct,
                _normalise_visible_cache_item(cache_item),
                missing_keys,
                active_keys,
                pages_text=pages_text,
                lines_by_page=lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
            if visual_candidate:
                visual_candidates = [visual_candidate]
        if not visual_candidates:
            continue
        width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
        height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
        area = int(width * height)
        for visual_candidate in visual_candidates:
            label = _normalise_compound_label(str(visual_candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if not key or key not in missing_keys:
                continue
            ok_exact, exact_label = _passes_exact_visual_label_guard(
                struct,
                key,
                lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
            if not ok_exact:
                continue
            if not _is_contextual_final_visual_candidate(struct, visual_candidate):
                continue
            binding = _build_binding_from_structure(struct, key)
            binding["binding_rule"] = "direct_structure_label"
            binding["visible_label"] = label
            binding["visual_label_source"] = "cache_fill"
            binding["visible_label_crop_source"] = str(visual_candidate.get("source") or "")
            binding["visible_label_multi_candidate"] = bool(visual_candidate.get("multi_label_crop"))
            binding["product_context_nearby"] = True
            binding["product_context_distance"] = int(visual_candidate.get("product_context_distance") or 0)
            if exact_label:
                binding["nearby_exact_product_label"] = exact_label
            binding["struct_width"] = width
            binding["struct_height"] = height
            binding["struct_area"] = width * height
            source_rank = _VISIBLE_LABEL_SOURCE_RANK.get(str(visual_candidate.get("source") or ""), 99)
            score = (
                int(binding["product_context_distance"]),
                source_rank,
                1 if bool(visual_candidate.get("multi_label_crop")) else 0,
                _visual_module_score(struct)[0],
                -area,
            )
            candidates_by_key.setdefault(key, []).append((score, binding))

    additions: List[Dict] = []
    for key, candidates in candidates_by_key.items():
        candidates.sort(key=lambda item: item[0])
        additions.append(candidates[0][1])

    if additions:
        logger.info(
            "   👁 可见编号缓存补齐活性结构: +%d (%s)",
            len(additions),
            ", ".join(str(_binding_label_key(item)) for item in sorted(additions, key=_binding_sort_key)),
        )
    return _active_ordered_bindings([*final_bindings, *additions], active_cpds)


def _repair_conflicting_bindings_from_visible_cache(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Replace weak/conflicting winners with strict visual-label matches."""
    if not active_cpds or not visible_label_cache:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    by_key = {
        _binding_label_key(binding): binding
        for binding in _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
        if _binding_label_key(binding)
    }
    target_keys: set[str] = set()
    weak_rules = {
        "heading_range_fallback",
        "product_section_context",
        "ocr_numeric_structure_label",
        "ocr_bare_numeric_product_label",
        "paired_route_product_row_order",
        "triplet_split_row_structure_order",
        "split_reaction_product_label",
        "dense_scheme_final_product",
    }
    for key, binding in by_key.items():
        if key not in active_keys:
            continue
        rule = str(binding.get("binding_rule") or "")
        if rule in {"structure_table_row_order", "structure_table_row_order_inferred", "structure_table_row_order_corrected"}:
            # Table row IDs are usually in the left text column, not in the
            # drawing crop. Internal atom/reagent labels such as "1", "2",
            # "7", or "11" must not cause an otherwise valid table row to be
            # replaced by a different active compound.
            geom = _structure_geometry(binding)
            if geom["struct_area"] >= 6500:
                continue
        if _visible_label_conflict_rank(binding, active_keys) >= 5 or rule in weak_rules or _is_weak_direct_visual_binding(binding):
            target_keys.add(key)
        elif (
            rule == "direct_structure_label"
            and key in _visible_label_keys_for_binding(binding)
            and key not in _strict_visible_label_keys_for_binding(binding)
        ):
            target_keys.add(key)
    if not target_keys:
        return final_bindings

    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    page_structs_by_no: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        page_structs_by_no.setdefault(int(struct.get("page_no") or 0), []).append(struct)
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in page_structs_by_no.items()
    }
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    candidates_by_key: Dict[str, List[Tuple[Tuple[int, int, int, int, int], Dict]]] = {}
    for sid, cache_item in (visible_label_cache or {}).items():
        struct = struct_by_id.get(str(sid))
        if not struct:
            continue
        raw_candidates = _normalise_visible_cache_item(cache_item)
        visual_candidates = []
        for candidate in raw_candidates:
            source = str(candidate.get("source") or "")
            if source not in _STRICT_VISIBLE_LABEL_SOURCES:
                continue
            label = _normalise_compound_label(str(candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if key not in target_keys:
                continue
            visual_candidates.append({
                "label": label,
                "label_key": key,
                "source": source,
                "product_context_distance": _product_context_distance(
                    pages_text,
                    int(struct.get("page_no") or 0),
                    _base_cpd_num(label) or 0,
                ),
                "multi_label_crop": len({str(c.get("label") or "").strip() for c in raw_candidates if c.get("label")}) > 1,
            })
        if not visual_candidates:
            continue
        geometry = _structure_geometry(struct)
        if geometry["struct_area"] < 1800:
            continue
        for visual_candidate in visual_candidates:
            key = _cpd_label_key(str(visual_candidate.get("label") or ""))
            if key not in target_keys:
                continue
            nearby_label_kind = _nearby_ocr_label_kind(struct, key, lines_by_page)
            if nearby_label_kind == "racemic":
                continue
            ok_exact, exact_label = _passes_exact_visual_label_guard(
                struct,
                key,
                lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
            if not ok_exact:
                continue
            if not _is_contextual_final_visual_candidate(struct, visual_candidate):
                continue
            binding = _build_binding_from_structure(struct, key)
            binding["binding_rule"] = "direct_structure_label"
            binding["visible_label"] = str(visual_candidate.get("label") or key)
            binding["visual_label_source"] = "cache_repair"
            binding["visible_label_crop_source"] = str(visual_candidate.get("source") or "")
            binding["visible_label_multi_candidate"] = bool(visual_candidate.get("multi_label_crop"))
            binding["product_context_nearby"] = True
            binding["product_context_distance"] = int(visual_candidate.get("product_context_distance") or 0)
            if nearby_label_kind:
                binding["nearby_ocr_label_kind"] = nearby_label_kind
            if exact_label:
                binding["nearby_exact_product_label"] = exact_label
            binding["visible_labels"] = _labels_from_visible_cache_item(cache_item)
            source_rank = _VISIBLE_LABEL_SOURCE_RANK.get(str(visual_candidate.get("source") or ""), 99)
            current = by_key.get(key, {})
            current_page = int((current or {}).get("page_no") or 0)
            page_delta = abs(int(struct.get("page_no") or 0) - current_page) if current_page else 999
            score = (
                source_rank,
                page_delta,
                int(binding["product_context_distance"]),
                1 if bool(visual_candidate.get("multi_label_crop")) else 0,
                _visual_module_score(struct)[0],
                -int(binding.get("struct_area") or 0),
            )
            candidates_by_key.setdefault(key, []).append((score, binding))

    replacements = 0
    for key, candidates in candidates_by_key.items():
        candidates.sort(key=lambda item: item[0])
        candidate = candidates[0][1]
        current = by_key.get(key)
        if current is None or _visual_binding_priority(candidate, active_keys) < _visual_binding_priority(current, active_keys):
            by_key[key] = candidate
            replacements += 1
    if replacements:
        logger.info("   👁 可见编号冲突/弱绑定替换: %d rows", replacements)

    ordered: List[Dict] = []
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if key in by_key:
            ordered.append(by_key[key])
    return ordered


def _confirm_final_bindings_with_visible_cache(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Annotate final active bindings with exact visual-label evidence.

    Heading/order fallbacks may still be correct, but when the chosen structure
    crop has a cached visible label matching the active compound, upgrade the
    row so downstream QA sees it as visually confirmed rather than prose-only.
    """
    if not final_bindings or not visible_label_cache:
        return final_bindings
    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in {
            page_no: [struct for struct in processed_structures if int(struct.get("page_no") or 0) == page_no]
            for page_no in sorted({int(struct.get("page_no") or 0) for struct in processed_structures})
        }.items()
    }
    confirmed: List[Dict] = []
    upgraded = 0
    for binding in final_bindings:
        item = dict(binding)
        key = _binding_label_key(item)
        if not key:
            confirmed.append(item)
            continue
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        struct = struct_by_id.get(sid)
        if not struct:
            confirmed.append(item)
            continue
        visual_candidates = _contextual_visible_label_candidates(
            struct,
            _normalise_visible_cache_item((visible_label_cache or {}).get(sid)),
            {key},
            pages_text,
            max_context_distance=1,
            lines_by_page=lines_by_page,
            row=_row_for_structure(struct, rows_by_page),
        )
        if not visual_candidates:
            confirmed.append(item)
            continue
        visual_candidate = visual_candidates[0]
        if not _is_contextual_final_visual_candidate(struct, visual_candidate):
            confirmed.append(item)
            continue
        width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
        height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
        item["visible_labels"] = _labels_from_visible_cache_item((visible_label_cache or {}).get(sid))
        item["visible_label"] = str(visual_candidate.get("label") or key)
        item["visible_label_crop_source"] = str(visual_candidate.get("source") or "")
        item["visible_label_multi_candidate"] = bool(visual_candidate.get("multi_label_crop"))
        item["product_context_nearby"] = True
        item["product_context_distance"] = int(visual_candidate.get("product_context_distance") or 0)
        item["struct_width"] = width
        item["struct_height"] = height
        item["struct_area"] = width * height
        if str(item.get("binding_rule") or "") in {
            "heading_range_fallback",
            "product_section_context",
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
            "ocr_pair_heading_structure_order",
            "paired_route_product_row_order",
            "triplet_split_row_structure_order",
        "split_reaction_product_label",
        "ocr_numeric_structure_label",
        "ocr_bare_numeric_product_label",
        "heading_row_right_product_recovery",
        "same_row_right_product_repair",
        "route_title_row_right_product",
        "visual_grid_label",
    }:
            item["binding_rule"] = "direct_structure_label"
            item["visual_label_source"] = "cache_confirmed"
            upgraded += 1
        elif not item.get("visual_label_source"):
            item["visual_label_source"] = "cache_confirmed"
        confirmed.append(item)
    if upgraded:
        logger.info("   👁 最终绑定视觉确认升级: %d rows", upgraded)
    return confirmed


def _final_structure_binding_quality(binding: Dict, active_keys: Optional[set[str]] = None) -> Tuple[int, int, int, int, int, int, int]:
    """Final arbitration score: one active compound per actual structure crop."""
    rule = str(binding.get("binding_rule") or "")
    area = float(binding.get("struct_area") or 0)
    width = float(binding.get("struct_width") or 0)
    height = float(binding.get("struct_height") or 0)
    aspect = width / max(height, 1.0) if width and height else 999.0
    weak_shape = 1 if (
        area < 6000
        or (width > 0 and height > 0 and aspect > 5.5)
    ) else 0
    if rule in {"structure_table_row_order", "structure_table_row_order_inferred", "structure_table_row_order_corrected"} and area >= 6500:
        weak_shape = 0
    fallback_rank = 1 if rule in {
        "heading_range_fallback",
        "product_section_context",
        "paired_route_product_row_order",
        "triplet_split_row_structure_order",
        "split_reaction_product_label",
        "ocr_numeric_structure_label",
        "ocr_bare_numeric_product_label",
        "dense_scheme_final_product",
        "heading_row_right_product_recovery",
        "same_row_right_product_repair",
        "route_title_row_right_product",
    } else 0
    direct_rank = 0 if rule in {"direct_structure_label", "direct_structure_label_right_product_crop"} else 1
    context_distance = binding.get("product_context_distance")
    try:
        context_rank = int(context_distance)
    except Exception:
        context_rank = 999
    return (
        fallback_rank,
        weak_shape,
        _visible_label_exactness_rank(binding, active_keys),
        _visible_label_conflict_rank(binding, active_keys),
        direct_rank,
        context_rank,
        -int(area),
    )


def _dedupe_final_bindings_by_structure(
    final_bindings: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Prevent one structure image from being emitted for multiple active IDs."""
    if not final_bindings:
        return final_bindings
    active_keys = _active_label_keys(active_cpds)
    annotated = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    best_by_structure: Dict[str, Dict] = {}
    duplicates = 0
    for binding in sorted(annotated, key=lambda b: _final_structure_binding_quality(b, active_keys)):
        sid = str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        if not sid:
            continue
        if sid in best_by_structure:
            duplicates += 1
            continue
        best_by_structure[sid] = binding

    if not duplicates:
        return annotated

    winners = list(best_by_structure.values())
    logger.info("   🧯 最终结构去重: 移除 %d 个共享同一结构的低置信绑定", duplicates)
    return _active_ordered_bindings(winners, active_cpds)


def _drop_unsafe_final_fragment_bindings(
    final_bindings: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    processed_structures: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Drop final rows that still look like small route fragments/intermediates."""
    if not final_bindings:
        return final_bindings
    active_keys = _active_label_keys(active_cpds)
    struct_by_id = {str(struct.get("id") or ""): struct for struct in (processed_structures or [])}
    rows_by_page: Dict[int, List[List[Dict]]] = {}
    if processed_structures:
        for page_no in sorted({int(struct.get("page_no") or 0) for struct in processed_structures}):
            rows_by_page[page_no] = _group_structures_by_row(
                [struct for struct in processed_structures if int(struct.get("page_no") or 0) == page_no],
                y_threshold=55.0,
            )
    kept: List[Dict] = []
    dropped: List[str] = []
    for binding in _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache):
        key = _binding_label_key(binding)
        strict_exact_visual = bool(key and key in _strict_visible_label_keys_for_binding(binding))
        exact_visual_product = _has_exact_visual_product_evidence(binding, active_keys)
        rule = str(binding.get("binding_rule") or "")
        area = float(binding.get("struct_area") or 0)
        conflict_rank = _visible_label_conflict_rank(binding, active_keys)
        unsafe_small_fallback = rule == "heading_range_fallback" and area < 6500 and not exact_visual_product
        unsafe_visible_conflict = conflict_rank >= 5 and key not in _strict_visible_label_keys_for_binding(binding)
        unsafe_low_multi = _is_low_internal_label_in_multi_visible_crop(binding)
        table_row_rules = {
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
            "cmpd_overview_table_order",
        }
        strong_layout_product_rules = {
            "route_title_row_right_product",
            "heading_row_right_product_recovery",
            "same_row_right_product_repair",
            "cpd_letter_pair_row_order",
        }
        unsafe_table_visible_mismatch = False
        if rule in table_row_rules:
            visible_keys = _visible_label_keys_for_binding(binding)
            if visible_keys and key not in visible_keys and not all(
                re.fullmatch(r"\d{1,2}[A-Z]?", vkey or "") for vkey in visible_keys
            ):
                unsafe_table_visible_mismatch = True

        unsafe_not_row_product = False
        if rule in (table_row_rules | {"heading_range_fallback"}) and processed_structures:
            sid = str(binding.get("source_structure_id") or binding.get("structure_id") or "")
            struct = struct_by_id.get(sid)
            if struct:
                if not (strict_exact_visual or exact_visual_product):
                    unsafe_not_row_product = _right_complete_product_on_same_row(
                        struct,
                        rows_by_page,
                        min_area_ratio=1.05,
                    ) is not None

        if (
            (unsafe_small_fallback and not strict_exact_visual)
            or (
                unsafe_visible_conflict
                and not (
                    rule in strong_layout_product_rules
                    and _is_complete_visible_product_module(binding)
                )
            )
            or (
                unsafe_low_multi
                and not (
                    rule in strong_layout_product_rules
                    and _is_complete_visible_product_module(binding)
                )
            )
            or (unsafe_table_visible_mismatch and not (strict_exact_visual or exact_visual_product))
            or unsafe_not_row_product
        ):
            dropped.append(key or str(binding.get("cpd") or ""))
            continue
        kept.append(binding)
    if dropped:
        logger.info("   🧯 剔除疑似中间体/反应片段终态绑定: %d (%s)", len(dropped), ", ".join(dropped[:20]))
    return _active_ordered_bindings(kept, active_cpds)


def _drop_fail_closed_bindings(
    final_bindings: List[Dict],
    active_cpds: List[str],
    keep_review_bindings: bool = False,
) -> List[Dict]:
    """Hard gate: review-required/conflicting bindings must not enter OCSR."""
    if not final_bindings:
        return final_bindings
    kept: List[Dict] = []
    dropped: List[str] = []
    for binding in final_bindings:
        key = _binding_label_key(binding)
        if bool(binding.get("fail_closed")) or str(binding.get("accuracy_status") or "") not in {"", "confirmed"}:
            if keep_review_bindings:
                row = dict(binding)
                row["partial_review_candidate"] = True
                row.setdefault("review_reason", "Retained for bootstrap partial export; strict acceptance still fails.")
                kept.append(row)
                continue
            dropped.append(key or str(binding.get("cpd") or ""))
            continue
        kept.append(binding)
    if dropped:
        logger.info(
            "   🛑 fail-closed最终闸门: 移除 %d 个不可靠绑定 (%s)",
            len(dropped),
            ", ".join(dropped[:20]),
        )
    return _active_ordered_bindings(kept, active_cpds)


def _repair_same_row_fragment_bindings_to_right_product(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Move fallback/table bindings from route fragments to the right-side product."""
    if not final_bindings or not processed_structures:
        return final_bindings
    repair_rules = {
        "heading_range_fallback",
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "cmpd_overview_table_order",
        "heading_row_right_product_recovery",
    }
    struct_by_id = {str(struct.get("id") or ""): struct for struct in processed_structures}
    rows_by_page: Dict[int, List[List[Dict]]] = {}
    for page_no in sorted({int(struct.get("page_no") or 0) for struct in processed_structures}):
        rows_by_page[page_no] = _group_structures_by_row(
            [struct for struct in processed_structures if int(struct.get("page_no") or 0) == page_no],
            y_threshold=55.0,
        )
    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    repaired: List[Dict] = []
    replacements = 0
    for binding in final_bindings:
        item = dict(binding)
        if str(item.get("binding_rule") or "") not in repair_rules:
            repaired.append(item)
            continue
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        struct = struct_by_id.get(sid)
        if not struct:
            repaired.append(item)
            continue
        replacement = _right_complete_product_on_same_row(struct, rows_by_page, min_area_ratio=1.05)
        if not replacement:
            repaired.append(item)
            continue
        replacement_sid = str(replacement.get("id") or "")
        if replacement_sid in used_structures and replacement_sid != sid:
            repaired.append(item)
            continue
        item["structure_id"] = replacement_sid
        item["source_structure_id"] = replacement_sid
        item["page_no"] = replacement["page_no"]
        item["structure_index"] = replacement["idx"]
        item["struct_x0"] = replacement["x0"]
        item["struct_y0"] = replacement["y0"]
        item["image_path"] = replacement["image_path"]
        item["source_image_path"] = str(replacement.get("image_path") or item.get("source_image_path") or "")
        item["ocsr_image_path"] = str(replacement.get("image_path") or item.get("ocsr_image_path") or "")
        item["binding_rule"] = "same_row_right_product_repair"
        item["same_row_fragment_repaired_from"] = sid
        _attach_structure_geometry(item, replacement)
        repaired.append(item)
        used_structures.discard(sid)
        used_structures.add(replacement_sid)
        replacements += 1
    if replacements:
        logger.info("   🧭 同行右侧完整产物替换中间体/片段绑定: %d rows", replacements)
    return _active_ordered_bindings(
        _annotate_bindings_with_visible_labels(repaired, visible_label_cache),
        active_cpds,
    )


def _extract_pair_heading_product_bindings(
    doc,
    pages_text: Dict[int, str],
    processed_structures: List[Dict],
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
) -> List[Dict]:
    """Bind split enantiomer pairs from page text plus left/right structure order.

    Tesseract often misreads the tiny label directly under a structure (for
    example 1-2 as 4-2). The nearby heading/title text usually still contains
    the pair as N-1 ... N-2, so use that as the primary source for split pairs.
    """
    bindings: List[Dict] = []
    used_bases: set[int] = set()
    used_structures: set[str] = set()

    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_text = _page_text_for_page_no(pages_text, page_no)
        base_lines = [
            (base, y0)
            for base, y0 in _split_pair_base_lines(doc, page_no, page_text, ocr_line_map=ocr_line_map)
            if base not in used_bases
        ]
        if not base_lines:
            continue

        page_structs = [
            p for p in processed_structures
            if p["page_no"] == page_no and p["id"] not in used_structures
        ]
        rows = _group_structures_by_row(page_structs)
        two_structure_rows = [row for row in rows if len(row) == 2]

        for base, heading_y0 in base_lines:
            available_rows = [
                row for row in two_structure_rows
                if all(p["id"] not in used_structures for p in row)
            ]
            if heading_y0 is not None:
                available_rows = [
                    row for row in available_rows
                    if min(float(p["y0"]) for p in row) > heading_y0 + 20
                ]
            if not available_rows:
                continue
            row = min(available_rows, key=lambda r: min(float(p["y0"]) for p in r))
            for suffix, struct in zip(("1", "2"), row):
                binding = _build_binding_from_structure(struct, f"{base}-{suffix}")
                binding["binding_rule"] = "ocr_pair_heading_structure_order"
                binding["pair_heading_sequence_confirmed"] = True
                binding["pair_heading_base"] = int(base)
                binding["pair_heading_suffix"] = suffix
                if heading_y0 is not None:
                    binding["pair_heading_y0"] = float(heading_y0)
                bindings.append(binding)
                used_structures.add(struct["id"])
            used_bases.add(base)

    return bindings


def _extract_cpd_letter_pair_product_bindings(
    pages_text: Dict[int, str],
    processed_structures: List[Dict],
    active_cpds: Optional[List[str]] = None,
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
) -> List[Dict]:
    """Bind Cpd-N/Cpd-NA stereoisomer pairs from title text plus row order.

    In Chinese PAMPH-style examples the final scheme often ends with
    precursor -> Cpd-N + Cpd-NA.  The full-page OCR text has the paired title
    reliably, while tight visual OCR can bleed the right label (N-A) onto the
    left product.  For activity-led output we only recover the non-A active row.
    """
    active_keys = _active_label_keys(active_cpds or [])
    if active_cpds and not active_keys:
        return []

    candidates_by_key: Dict[str, List[Tuple[Tuple[int, int, int, int], Dict]]] = {}
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)

    for page_no in sorted(by_page):
        page_text = _page_text_for_page_no(pages_text, page_no)
        base_lines = _cpd_letter_pair_base_lines(page_no, page_text, lines_by_page)
        if not base_lines:
            continue

        for base, heading_y0 in base_lines:
            key = str(base)
            if active_keys and key not in active_keys:
                continue
            for search_page in (page_no, page_no + 1):
                page_structs = by_page.get(search_page, [])
                if not page_structs:
                    continue
                rows = _group_structures_by_row(page_structs, y_threshold=70.0)
                label_y = _cpd_letter_pair_label_y(base, search_page, lines_by_page)
                has_product_text = _has_cpd_letter_pair_product_text(
                    base,
                    _page_text_for_page_no(pages_text, search_page),
                )
                for row in rows:
                    row_y = min(float(item.get("y0") or 0) for item in row)
                    row_bottom = max(float(item.get("y1") or item.get("y0") or 0) for item in row)
                    if label_y is not None:
                        if row_y > label_y + 12:
                            continue
                        label_distance = abs(float(label_y) - row_bottom)
                    else:
                        if search_page != page_no:
                            continue
                        if heading_y0 is not None and row_y <= float(heading_y0) + 20:
                            continue
                        label_distance = 9999.0
                    complete = [
                        item for item in sorted(row, key=lambda struct: float(struct.get("x0") or 0))
                        if _is_cpd_letter_pair_product_candidate(item)
                    ]
                    if len(complete) < 2:
                        continue
                    target_struct = complete[-2]
                    binding = _build_binding_from_structure(target_struct, key)
                    binding["binding_rule"] = "cpd_letter_pair_row_order"
                    binding["cpd_letter_pair_sequence_confirmed"] = True
                    binding["cpd_letter_pair_base"] = int(base)
                    binding["cpd_letter_pair_partner"] = f"{base}A"
                    binding["cpd_letter_pair_role"] = "left_non_a_product"
                    if heading_y0 is not None:
                        binding["cpd_letter_pair_heading_y0"] = float(heading_y0)
                    if label_y is not None:
                        binding["cpd_letter_pair_label_y0"] = float(label_y)
                    score = (
                        0 if (label_y is not None or has_product_text) else 1,
                        int(label_distance),
                        abs(search_page - page_no),
                        -int(row_y),
                    )
                    candidates_by_key.setdefault(key, []).append((score, binding))

    bindings: List[Dict] = []
    used_structures: set[str] = set()
    for key in sorted(candidates_by_key, key=_cpd_sort_key):
        for _score, binding in sorted(candidates_by_key[key], key=lambda item: item[0]):
            sid = str(binding.get("structure_id") or "")
            if sid in used_structures:
                continue
            bindings.append(binding)
            used_structures.add(sid)
            break
    return bindings


def _extract_split_reaction_bare_bindings(
    processed_structures: List[Dict],
    existing_bindings: List[Dict],
    used_structures: set[str],
    used_labels: set[str],
) -> List[Dict]:
    """For split pages, bind the starting material N in a later reaction row."""
    bindings: List[Dict] = []
    split_pages: Dict[int, List[int]] = {}
    for binding in existing_bindings:
        m = re.match(r"^Compound\s+([1-9]\d*)-[12]$", binding["cpd"])
        if not m:
            continue
        split_pages.setdefault(binding["page_no"], [])
        base = int(m.group(1))
        if base not in split_pages[binding["page_no"]]:
            split_pages[binding["page_no"]].append(base)

    for page_no, bases in split_pages.items():
        page_rows = _group_structures_by_row([
            p for p in processed_structures if p["page_no"] == page_no
        ])
        pair_min_y_by_base = {}
        for base in bases:
            pair_rows = [
                float(b["struct_y0"])
                for b in existing_bindings
                if b["page_no"] == page_no and b["cpd"] in (f"Compound {base}-1", f"Compound {base}-2")
            ]
            if pair_rows:
                pair_min_y_by_base[base] = min(pair_rows)

        for base in bases:
            label = str(base)
            if label in used_labels:
                continue
            min_pair_y = pair_min_y_by_base.get(base)
            if min_pair_y is None:
                continue
            candidate_rows = [
                row for row in page_rows
                if len(row) >= 2
                and min(float(p["y0"]) for p in row) > min_pair_y + 60
                and all(p["id"] not in used_structures for p in row)
            ]
            if not candidate_rows:
                continue
            row = min(candidate_rows, key=lambda r: min(float(p["y0"]) for p in r))
            struct = row[0]
            binding = _build_binding_from_structure(struct, label)
            binding["binding_rule"] = "split_reaction_starting_material"
            bindings.append(binding)
            used_labels.add(label)
            used_structures.add(struct["id"])

    return bindings


def _labels_near_structure(words: List[Dict], struct: Dict) -> List[str]:
    x0, x1 = float(struct["x0"]), float(struct.get("x1", struct["x0"]))
    y1 = float(struct.get("y1", struct["y0"]))
    cx = (x0 + x1) / 2
    width = max(25.0, x1 - x0)
    labels: List[str] = []
    for word in words:
        label = _normalise_compound_label(word["text"])
        dx = abs(float(word["x"]) - cx)
        y = float(word["y"])
        near = (
            dx <= max(width * 0.6, 40.0)
            and y1 - 10 <= y <= y1 + 65
        )
        if near and label:
            labels.append(label)
    return labels


def _base_cpd_num(value: str) -> Optional[int]:
    m = re.search(r"(\d+)", str(value or ""))
    return int(m.group(1)) if m else None


def _ocr_confusable_num_pattern(num: int | str) -> str:
    """Build a narrow pattern for OCR-confused compound numbers.

    This is meant for Chinese heading/product contexts only. A leading 5 is
    commonly read as S/s/$, and 1/2 can be read as l/I/z in scanned patents.
    """
    pieces: List[str] = []
    for ch in str(num):
        if ch == "5":
            pieces.append(r"[5S＄$s]")
        elif ch == "1":
            pieces.append(r"[1lI]")
        elif ch == "2":
            pieces.append(r"[2zZ]")
        else:
            pieces.append(re.escape(ch))
    return r"\s*".join(pieces)


def _build_active_focus_windows(all_blocks: List[Dict], active_cpds: List[str]) -> Dict[int, List[Tuple[float, float]]]:
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return {}

    by_page: Dict[int, List[Dict]] = {}
    for block in all_blocks:
        by_page.setdefault(int(block.get("page_no") or 0), []).append(block)

    windows: Dict[int, List[Tuple[float, float]]] = {}
    for page_no, page_blocks in by_page.items():
        page_blocks = sorted(page_blocks, key=lambda b: float(b.get("y0") or 0))
        page_windows: List[Tuple[float, float]] = []
        for idx, block in enumerate(page_blocks):
            cpd_num = int(block.get("cpd_num") or 0)
            if cpd_num not in active_bases:
                continue
            start = max(0.0, float(block.get("y0") or 0) - 40.0)
            next_y = float(page_blocks[idx + 1].get("y0") or 0) if idx + 1 < len(page_blocks) else start + 320.0
            end = max(start + 120.0, next_y + 60.0)
            page_windows.append((start, end))
        if page_windows:
            windows[page_no] = page_windows
    return windows


def _insert_missing_active_heading_blocks(
    all_blocks: List[Dict],
    active_cpds: List[str],
    pages_text: Optional[Dict[int, str]] = None,
) -> List[Dict]:
    """Add conservative synthetic heading blocks for active examples missed by OCR.

    Some scanned Chinese examples have titles like "实施例 25" degraded enough
    that the title scanner skips them, while neighboring examples are detected
    normally. For active-led runs, insert only missing active numbers that sit
    between detected examples, using the previous block's page as a safe anchor.
    """
    active_bases = sorted({_base_cpd_num(cpd) for cpd in active_cpds if _base_cpd_num(cpd)})
    if not active_bases or len(all_blocks) < 2:
        return all_blocks

    by_num = {int(b.get("cpd_num") or 0): b for b in all_blocks if b.get("cpd_num")}
    additions: List[Dict] = []
    existing_additions: set[int] = set()
    for num in active_bases:
        if num in by_num or num in existing_additions:
            continue
        similar_re = re.compile(
            rf"(?:Examples?|Compounds?)\s*{num}(?![\dA-Za-z-])"
            rf"[^\n]{{0,120}}(?:prepared|following|similar procedure)",
            re.IGNORECASE,
        )
        matched: Optional[Tuple[int, int, str]] = None
        for page_idx, text in sorted((pages_text or {}).items()):
            for line_no, line in enumerate(str(text or "").splitlines()):
                if similar_re.search(line):
                    matched = (int(page_idx), line_no, line.strip())
                    break
            if matched:
                break
        if not matched:
            continue
        matched_page_idx, matched_line_no, matched_line = matched
        additions.append({
            "cpd": f"Example{num}",
            "cpd_num": num,
            "prefix": "Example",
            "page_no": matched_page_idx + 1,
            "y0": float(matched_line_no) * 14.0,
            "x0": 0,
            "word_index": 0,
            "line_text": f"synthetic active similar-procedure heading: {matched_line[:80]}",
            "synthetic": True,
        })
        existing_additions.add(num)

    for num in active_bases:
        if num in by_num or num in existing_additions:
            continue
        prev_nums = [n for n in by_num if n < num]
        next_nums = [n for n in by_num if n > num]
        if not prev_nums or not next_nums:
            continue
        prev_num = max(prev_nums)
        next_num = min(next_nums)
        if num - prev_num > 2 or next_num - num > 2:
            continue
        prev_block = by_num[prev_num]
        next_block = by_num[next_num]
        prev_page = int(prev_block.get("page_no") or 0)
        next_page = int(next_block.get("page_no") or 0)
        if prev_page <= 0 or next_page <= 0 or next_page - prev_page > 3:
            continue
        additions.append({
            "cpd": f"实施例{num}",
            "cpd_num": num,
            "prefix": "实施例",
            "page_no": prev_page,
            "y0": float(prev_block.get("y0") or 0) + 1.0,
            "x0": 0,
            "word_index": 0,
            "line_text": f"synthetic active heading between 实施例{prev_num} and 实施例{next_num}",
            "synthetic": True,
        })
        existing_additions.add(num)

    existing_additions = {int(b["cpd_num"]) for b in additions}
    for num in active_bases:
        if num in by_num or num in existing_additions:
            continue
        pair_patterns = []
        if num > 1:
            pair_patterns.append((num - 1, num))
        pair_patterns.append((num, num + 1))
        for left, right in pair_patterns:
            pair_re = rf"{left}\s*[,，、.]\s*{right}"
            title_re = re.compile(
                rf"(?:实施例|SCHED|SCHEDULE)?[^\n]{{0,80}}{pair_re}"
                rf"[^\n]{{0,80}}化.?[合台]物[^\n]{{0,80}}{pair_re}"
                rf"[^\n]{{0,80}}[合台]成",
                re.IGNORECASE,
            )
            matched_page: Optional[int] = None
            for page_idx, text in sorted((pages_text or {}).items()):
                if title_re.search(str(text or "")):
                    matched_page = int(page_idx) + 1
                    break
            if matched_page is None:
                continue
            additions.append({
                "cpd": f"实施例{num}",
                "cpd_num": num,
                "prefix": "实施例",
                "page_no": matched_page,
                "y0": 0.0,
                "x0": 0,
                "word_index": 0,
                "line_text": f"synthetic active paired heading {left},{right}",
                "synthetic": True,
            })
            existing_additions.add(num)
            break

    existing_additions = {int(b["cpd_num"]) for b in additions}
    for num in active_bases:
        if num in by_num or num in existing_additions:
            continue
        similar_re = re.compile(
            rf"(?:Examples?|Compounds?)\s*{num}(?![\dA-Za-z-])"
            rf"[^\n]{{0,120}}(?:prepared|following|similar procedure)",
            re.IGNORECASE,
        )
        matched: Optional[Tuple[int, int, str]] = None
        for page_idx, text in sorted((pages_text or {}).items()):
            for line_no, line in enumerate(str(text or "").splitlines()):
                if similar_re.search(line):
                    matched = (int(page_idx), line_no, line.strip())
                    break
            if matched:
                break
        if not matched:
            continue
        matched_page_idx, matched_line_no, matched_line = matched
        additions.append({
            "cpd": f"Example{num}",
            "cpd_num": num,
            "prefix": "Example",
            "page_no": matched_page_idx + 1,
            "y0": float(matched_line_no) * 14.0,
            "x0": 0,
            "word_index": 0,
            "line_text": f"synthetic active similar-procedure heading: {matched_line[:80]}",
            "synthetic": True,
        })
        existing_additions.add(num)

    existing_additions = {int(b["cpd_num"]) for b in additions}
    for num in active_bases:
        if num in by_num or num in existing_additions or "5" not in str(num):
            continue
        fuzzy = _ocr_confusable_num_pattern(num)
        title_re = re.compile(
            rf"(?:实施例|化合物)[^\n]{{0,12}}{fuzzy}(?![\dA-Za-z-])"
            rf"|(?:得到|制备得到|分离制备得到)[^\n]{{0,50}}化.?[合台]物[^\n]{{0,8}}{fuzzy}(?![\dA-Za-z-])",
            re.IGNORECASE,
        )
        matches: List[Tuple[int, int, int, str]] = []
        for page_idx, text in sorted((pages_text or {}).items()):
            for line_no, line in enumerate(str(text or "").splitlines()):
                if not title_re.search(line):
                    continue
                has_product_context = bool(re.search(r"(?:得到|制备得到|分离制备得到|化.?[合台]物)", line))
                has_heading_context = bool(re.search(r"实施例", line))
                score = 0 if has_product_context and not has_heading_context else 1
                matches.append((score, int(page_idx), line_no, line.strip()))
        if not matches:
            continue
        _score, matched_page_idx, matched_line_no, matched_line = min(matches, key=lambda item: (item[0], item[1], item[2]))
        additions.append({
            "cpd": f"实施例{num}",
            "cpd_num": num,
            "prefix": "实施例",
            "page_no": matched_page_idx + 1,
            "y0": float(matched_line_no) * 14.0,
            "x0": 0,
            "word_index": 0,
            "line_text": f"synthetic active OCR-confusable heading: {matched_line[:80]}",
            "synthetic": True,
        })
        existing_additions.add(num)

    if additions:
        all_blocks = [*all_blocks, *additions]
        all_blocks.sort(key=lambda x: (x["page_no"], x["y0"], x["cpd_num"]))
        logger.info(
            "   活性编号补漏: 新增 %d 个合成标题块 %s",
            len(additions),
            [b["cpd"] for b in additions],
        )
    return all_blocks


def _filter_items_by_focus_windows(items: List[Dict], windows: Optional[List[Tuple[float, float]]], margin: float = 0.0) -> List[Dict]:
    if not windows:
        return items
    filtered = []
    for item in items:
        y = float(item.get("y", item.get("y0", 0)) or 0)
        y1 = float(item.get("y1", y) or y)
        for start, end in windows:
            if y1 >= start - margin and y <= end + margin:
                filtered.append(item)
                break
    return filtered


def _extract_table_row_numbers(page_text: str) -> List[int]:
    raw_numbers: List[int] = []
    for raw_line in str(page_text or "").splitlines():
        match = _TABLE_ROW_RE.match(raw_line)
        if not match:
            continue
        value = int(match.group(1))
        if raw_numbers and raw_numbers[-1] == value:
            continue
        raw_numbers.append(value)

    if len(raw_numbers) < 4:
        return raw_numbers

    # Keep the longest left-column-like increasing run and drop OCR noise such
    # as stray "1", "4", mass fragments, or repeated figure labels.
    best_len = 0
    best_sum = -1
    dp = [1] * len(raw_numbers)
    prev = [-1] * len(raw_numbers)
    for i, value in enumerate(raw_numbers):
        for j in range(i):
            prev_value = raw_numbers[j]
            step = value - prev_value
            if step < 1 or step > 3:
                continue
            cand_len = dp[j] + 1
            cand_sum = 0
            k = j
            while k != -1:
                cand_sum += raw_numbers[k]
                k = prev[k]
            cand_sum += value
            if cand_len > dp[i]:
                dp[i] = cand_len
                prev[i] = j
            elif cand_len == dp[i] and cand_sum > best_sum:
                prev[i] = j

        if dp[i] > best_len:
            best_len = dp[i]
            best_sum = value
        elif dp[i] == best_len:
            best_sum = max(best_sum, value)

    end_idx = max(
        range(len(raw_numbers)),
        key=lambda idx: (dp[idx], raw_numbers[idx]),
    )
    if dp[end_idx] < 4:
        return raw_numbers

    sequence: List[int] = []
    while end_idx != -1:
        sequence.append(raw_numbers[end_idx])
        end_idx = prev[end_idx]
    sequence.reverse()
    return sequence


_STRUCTURE_TABLE_CONTEXT_RE = re.compile(
    r"(?:Example|Compound|Cpd|化合物|实施例)\s+(?:Structure|结构)|"
    r"(?:Structure|结构)\s+(?:NMR/MS|NMR|MS|ID)|"
    r"(?:Ex\s*#|Example\s*#).{0,160}(?:Procedures?|Structure).{0,160}(?:LCMS|NMR)|"
    r"Table\s+\d+.{0,120}(?:Example|Structure|NMR/MS)",
    re.IGNORECASE | re.DOTALL,
)
_STRUCTURE_TABLE_MASS_VALUE_RE = re.compile(r"\b\d{3}\.\d\b")
_STRUCTURE_TABLE_CHEM_CONTEXT_RE = re.compile(
    r"哌啶|吡啶|苯基|噻吩|呋喃|二酮|恶唑|噻唑|"
    r"phenyl|pyrid|thien|furyl|piperid|dione|oxazol|thiazol",
    re.IGNORECASE,
)
_STRUCTURE_TABLE_ROUTE_CONTEXT_RE = re.compile(
    r"合成路线|中间体|第一步|第二步|第三步|反应液|反应瓶|加入|搅拌|粗品|纯化|"
    r"Synthesis|Preparation|Intermediate|Step\s*\d+|reaction|mixture",
    re.IGNORECASE,
)

_SPECTRAL_OR_CONDITION_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*H\b|MHz|DMSO|CDCl|METHANOL|NMR|LCMS|MS:|ESI|"
    r"calc|found|Hz|J\s*=|m/z|yield|purity|eq|mg|mL|mol|mmol|umol|℃|°C)",
    re.IGNORECASE,
)


def _normalise_ocr_line_map(
    ocr_line_map: Optional[Dict[int, List[Any]]]
) -> Dict[int, List[Tuple[float, str]]]:
    lines_by_page: Dict[int, List[Tuple[float, str]]] = {}
    for raw_page, raw_lines in (ocr_line_map or {}).items():
        try:
            page_idx = int(raw_page)
        except Exception:
            continue
        if not isinstance(raw_lines, list):
            continue
        normalised: List[Tuple[float, str]] = []
        for item in raw_lines:
            try:
                if isinstance(item, dict):
                    y0 = float(item.get("y0", 0))
                    text = str(item.get("text", "")).strip()
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    y0 = float(item[0])
                    text = str(item[1]).strip()
                else:
                    continue
            except Exception:
                continue
            if text:
                normalised.append((y0, text))
        if normalised:
            lines_by_page[page_idx] = sorted(normalised, key=lambda row: row[0])
    return lines_by_page


_CD3_LINE_RE = re.compile(r"(?:CD\s*[_₃3]?3?|C\s*D\s*[_₃3]?3)", re.IGNORECASE)


def _annotate_isotope_label_evidence(
    bindings: List[Dict],
    ocr_line_map: Optional[Dict[int, List[Any]]],
) -> List[Dict]:
    """Reuse page OCR lines to flag isotope and exact visible-label evidence."""
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    if not bindings or not lines_by_page:
        return bindings
    annotated: List[Dict] = []
    for binding in bindings:
        item = dict(binding)
        try:
            page_idx = int(item.get("page_no") or 0) - 1
            y0 = float(item.get("struct_y0") or item.get("y0") or 0)
            y1 = float(item.get("struct_y1") or item.get("y1") or y0)
        except Exception:
            annotated.append(item)
            continue
        key = _binding_label_key(item)
        if key:
            exact_label = _nearby_exact_product_label(
                {
                    "page_no": item.get("page_no"),
                    "x0": item.get("struct_x0") or item.get("x0"),
                    "x1": item.get("struct_x1") or item.get("x1"),
                    "y0": y0,
                    "y1": y1,
                    "id": item.get("source_structure_id") or item.get("structure_id"),
                },
                key,
                lines_by_page,
            )
            if exact_label:
                item["nearby_exact_product_label"] = exact_label
                if exact_label != key:
                    item["fail_closed"] = True
                    item["accuracy_status"] = "needs_review"
                    item.setdefault("evidence_reasons", [])
                    item["evidence_reasons"].append(
                        f"nearby visible label is {exact_label}, expected {key}"
                    )
        matches = []
        for line_y, text in lines_by_page.get(page_idx, []):
            if y0 - 24 <= float(line_y) <= y1 + 24 and _CD3_LINE_RE.search(str(text or "")):
                matches.append(str(text).strip())
        if matches:
            item["isotope_label_evidence"] = "CD3"
            item["isotope_label_ocr_lines"] = matches[:6]
        annotated.append(item)
    return annotated


def _is_structure_table_context(page_text: str, lines: Optional[List[Tuple[float, str]]] = None) -> bool:
    joined_lines = " ".join(text for _y, text in (lines or []))
    text = re.sub(r"\s+", " ", f"{page_text or ''} {joined_lines}").strip()
    if not text:
        return False
    if _STRUCTURE_TABLE_CONTEXT_RE.search(text):
        return True
    line_id_hits = sum(
        1
        for _y, line_text in (lines or [])
        if re.fullmatch(r"\s*[1-9]\d{0,3}\s*", str(line_text or ""))
    )
    mass_hits = len(_STRUCTURE_TABLE_MASS_VALUE_RE.findall(text))
    chem_hits = len(_STRUCTURE_TABLE_CHEM_CONTEXT_RE.findall(text))
    # Continuation pages in scanned structure tables often lose the table
    # header, but still preserve the true left ID column plus LC-MS masses.
    if _STRUCTURE_TABLE_ROUTE_CONTEXT_RE.search(text):
        return False
    return line_id_hits >= 2 and mass_hits >= 2 and chem_hits >= 2


def _line_is_probable_table_compound_id(text: str, active_bases: set[int]) -> Optional[int]:
    value = re.sub(r"\s+", " ", str(text or "")).strip().strip("()[]{}.,;:，。；：")
    if not value:
        return None
    if _SPECTRAL_OR_CONDITION_RE.search(value):
        return None
    match = re.fullmatch(r"(?:Example|Compound|Cpd|化合物|实施例)?\s*([1-9]\d{0,2})(?:[A-Z])?", value, re.IGNORECASE)
    if not match:
        return None
    num = int(match.group(1))
    if num not in active_bases:
        return None
    return num


def _extract_table_row_numbers_from_lines(
    lines: Optional[List[Tuple[float, str]]],
    active_bases: set[int],
    page_structs: Optional[List[Dict]] = None,
) -> List[Tuple[int, float, str]]:
    """Extract true left-column table IDs from OCR line coordinates."""
    if not lines or not active_bases:
        return []

    struct_rows = _group_structures_by_row(page_structs or [], y_threshold=60.0)
    struct_centers = [
        (min(float(s.get("y0") or 0) for s in row) + max(float(s.get("y1") or 0) for s in row)) / 2.0
        for row in struct_rows
        if row
    ]

    candidates: List[Tuple[int, float, str]] = []
    for y0, text in lines:
        num = _line_is_probable_table_compound_id(text, active_bases)
        if num is None:
            continue
        if struct_centers:
            nearest = min(abs(float(y0) - center) for center in struct_centers)
            # Footer page numbers can look like active compound IDs. Keep only
            # labels that really sit on a structure row.
            if nearest > 75.0:
                continue
        if candidates and candidates[-1][0] == num and abs(candidates[-1][1] - float(y0)) < 18.0:
            continue
        candidates.append((num, float(y0), str(text).strip()))

    if len(candidates) < 2:
        return candidates

    # If OCR sees more numeric labels than structure rows, choose the label
    # subset that best aligns to the row centers. This drops footer page
    # numbers like "301" without blocking genuine multi-range table jumps.
    if struct_centers and len(candidates) > len(struct_centers):
        row_count = len(struct_centers)
        best_score: Optional[float] = None
        best_seq: List[Tuple[int, float, str]] = []

        def walk(cand_idx: int, row_idx: int, seq: List[Tuple[int, float, str]], score: float) -> None:
            nonlocal best_score, best_seq
            if row_idx == row_count:
                if best_score is None or score < best_score:
                    best_score = score
                    best_seq = list(seq)
                return
            remaining_rows = row_count - row_idx
            remaining_candidates = len(candidates) - cand_idx
            if remaining_candidates < remaining_rows:
                return
            if best_score is not None and score >= best_score:
                return
            for i in range(cand_idx, len(candidates) - remaining_rows + 1):
                num, y0, _text = candidates[i]
                if seq and num <= seq[-1][0]:
                    continue
                distance = abs(float(y0) - struct_centers[row_idx])
                if distance > 75.0:
                    continue
                jump_penalty = 0.0
                if seq:
                    step = num - seq[-1][0]
                    if step > 50:
                        # Real tables can jump between ranges (70 -> 141,
                        # 118 -> 240), but prefer the compact run when a
                        # competing footer/page number is present.
                        jump_penalty = min(step, 250) * 0.15
                walk(i + 1, row_idx + 1, [*seq, candidates[i]], score + distance + jump_penalty)

        walk(0, 0, [], 0.0)
        if len(best_seq) >= 2:
            return best_seq

    # Preserve top-to-bottom order while dropping obvious OCR noise. Structure
    # tables may jump across disclosed ranges on the same page, e.g. 70 -> 141
    # or 245 -> 431, so do not collapse to only the longest +1 run.
    monotonic: List[Tuple[int, float, str]] = []
    for item in candidates:
        num, y0, _text = item
        if monotonic and y0 <= monotonic[-1][1] + 8:
            continue
        if monotonic and num <= monotonic[-1][0]:
            break
        monotonic.append(item)
    if len(monotonic) >= 2:
        return monotonic

    # Legacy fallback for very noisy OCR pages with no usable row geometry.
    best: List[Tuple[int, float, str]] = []
    for start in range(len(candidates)):
        seq = [candidates[start]]
        last_num = candidates[start][0]
        last_y = candidates[start][1]
        for item in candidates[start + 1:]:
            num, y0, _text = item
            if y0 <= last_y + 8:
                continue
            if num == last_num:
                continue
            step = num - last_num
            if 1 <= step <= 8:
                seq.append(item)
                last_num = num
                last_y = y0
            elif num > last_num + 40 and len(seq) < 2:
                break
        if len(seq) > len(best) or (len(seq) == len(best) and sum(x[0] for x in seq) > sum(x[0] for x in best)):
            best = seq
    if len(best) >= 2:
        return best
    # Mixed pages can contain one last structure-table row followed by the next
    # prose Example scheme. Do not turn a decreasing sequence like 497, 126 into
    # two table rows; keep the first table-row candidate only.
    for prev, current in zip(candidates, candidates[1:]):
        if current[0] < prev[0]:
            return [candidates[0]]
    return candidates


def _is_structure_table_layout(
    page_structs: List[Dict],
    page_text: str,
    ocr_lines: Optional[List[Tuple[float, str]]] = None,
    active_bases: Optional[set[int]] = None,
) -> bool:
    if len(page_structs) < 1:
        return False
    if not _is_structure_table_context(page_text, ocr_lines):
        return False
    row_numbers = _extract_table_row_numbers(page_text)
    if active_bases:
        line_numbers = _extract_table_row_numbers_from_lines(ocr_lines, active_bases, page_structs)
        if len(line_numbers) >= 2:
            row_numbers = [num for num, _y, _text in line_numbers]
        elif line_numbers:
            row_numbers = [num for num, _y, _text in line_numbers]
    min_rows = 1 if active_bases else (1 if len(page_structs) <= 2 else 2)
    if len(row_numbers) < min_rows:
        return False
    if active_bases and line_numbers:
        return True
    xs = [float(p["x0"]) for p in page_structs]
    x_spread = max(xs) - min(xs) if xs else 0.0
    return x_spread < 240.0


def _extract_structure_table_bindings(
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    existing_bindings: List[Dict],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Bind table rows by vertical order when OCR labels are not attached to structures.

    WIPO structure tables often render each row as:
    row-id | structure | name | LC-MS
    DECIMER sees the left-column structure, but the compound number lives in the
    text row rather than directly under the drawing. In that layout, bind row
    numbers to structures by shared top-to-bottom order.
    """
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return []

    used_structure_ids = {
        str(binding.get("structure_id"))
        for binding in existing_bindings
        if binding.get("structure_id")
    }
    existing_base_nums = {
        _base_cpd_num(binding.get("cpd", ""))
        for binding in existing_bindings
    }
    existing_base_nums.discard(None)
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    bindings: List[Dict] = []
    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_structs = sorted(
            [p for p in processed_structures if p["page_no"] == page_no and p["id"] not in used_structure_ids],
            key=lambda p: (float(p["y0"]), float(p["x0"])),
        )
        if not page_structs:
            continue

        page_text = _page_text_for_page_no(pages_text, page_no)
        page_lines = lines_by_page.get(page_no - 1) or []
        if not _is_structure_table_layout(page_structs, page_text, ocr_lines=page_lines, active_bases=active_bases):
            continue

        row_entries = _extract_table_row_numbers_from_lines(page_lines, active_bases, page_structs)
        if not row_entries:
            # Activity-led table binding must be anchored by the real left ID
            # column. A trailing "Table 3" heading on the previous synthesis page
            # must not let route intermediates consume the next page's row IDs.
            continue
        row_numbers = [num for num, _y, _text in row_entries]
        if not row_numbers:
            row_numbers = _extract_table_row_numbers(page_text)
        if not row_numbers:
            continue

        struct_rows = _group_structures_by_row(page_structs, y_threshold=55.0)
        if not struct_rows:
            continue

        row_structs = []
        for row in struct_rows:
            if not row:
                continue
            struct = _best_table_structure_from_row(row, page_structs)
            if struct:
                row_structs.append(struct)
        if not row_structs:
            continue

        if row_entries:
            row_pairs = []
            row_available = list(enumerate(struct_rows))
            for compound_num, y0, _text in row_entries:
                if not row_available:
                    break
                best_idx, best_row = min(
                    row_available,
                    key=lambda pair: abs(
                        float(y0)
                        - (
                            _structure_row_bounds(pair[1])[2]
                        )
                    ),
                )
                best_distance = abs(
                    float(y0)
                    - _structure_row_bounds(best_row)[2]
                )
                if best_distance > 95.0:
                    continue
                best_struct = _best_table_structure_for_row_label(best_row, y0, page_structs)
                if not best_struct:
                    continue
                row_pairs.append((compound_num, best_struct))
                row_available = [item for item in row_available if item[0] != best_idx]
        elif len(row_numbers) == len(row_structs):
            row_pairs = list(zip(row_numbers, row_structs))
        else:
            row_pairs = []
            if len(row_numbers) == 1:
                row_pairs.append((row_numbers[0], row_structs[0]))
            else:
                last_num_idx = len(row_numbers) - 1
                last_struct_idx = len(row_structs) - 1
                used_struct_indices = set()
                for num_idx, compound_num in enumerate(row_numbers):
                    struct_idx = round(num_idx * last_struct_idx / last_num_idx) if last_struct_idx > 0 else 0
                    if struct_idx in used_struct_indices:
                        continue
                    used_struct_indices.add(struct_idx)
                    row_pairs.append((compound_num, row_structs[struct_idx]))

        for compound_num, struct in row_pairs:
            if compound_num not in active_bases or compound_num in existing_base_nums:
                continue
            binding = _build_binding_from_structure(struct, str(compound_num))
            binding["binding_rule"] = "structure_table_row_order"
            bindings.append(binding)
            used_structure_ids.add(struct["id"])
            existing_base_nums.add(compound_num)

    return bindings


def _extract_structure_table_sequence_bindings(
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    existing_bindings: Optional[List[Dict]] = None,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Build full-page structure-table bindings from row order.

    OCR can misread left-column IDs such as 10/62/68 as 2/30/30 while the page
    still has enough neighboring rows to recover the intended sequence. This
    helper treats the activity list as the canonical allowed sequence and emits
    table candidates only when a page's row order can be anchored by the left
    column or adjacent already-bound table pages.
    """
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return []

    active_numbers = [
        n for n in (_base_cpd_num(cpd) for cpd in active_cpds)
        if n is not None
    ]
    active_number_set = set(active_numbers)
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    # Keep table anchors from existing strong candidates. Direct labels are
    # intentionally not used here because synthesis-route labels can compete
    # with the same compound number printed later in the structure table.
    anchors: List[Tuple[int, int, float]] = []
    for binding in existing_bindings or []:
        if str(binding.get("binding_rule") or "") not in {
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
        }:
            continue
        sig = _table_row_signature_from_binding(binding)
        if sig:
            anchors.append(sig)

    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)

    page_rows: Dict[int, List[Dict]] = {}
    page_entries: Dict[int, List[Tuple[int, float, str]]] = {}
    for page_no in sorted(by_page):
        page_structs = sorted(by_page[page_no], key=lambda p: (float(p.get("y0") or 0), float(p.get("x0") or 0)))
        page_text = _page_text_for_page_no(pages_text, page_no)
        page_lines = lines_by_page.get(page_no - 1) or []
        if not _is_structure_table_layout(page_structs, page_text, ocr_lines=page_lines, active_bases=active_bases):
            continue
        struct_rows = _group_structures_by_row(page_structs, y_threshold=55.0)
        row_structs: List[Dict] = []
        for row in struct_rows:
            struct = _best_table_structure_from_row(row, page_structs)
            if struct:
                row_structs.append(struct)
        if not row_structs:
            continue
        page_rows[page_no] = row_structs
        page_entries[page_no] = _extract_table_row_numbers_from_lines(page_lines, active_bases, page_structs)
        for num, y0, _text in page_entries[page_no]:
            if num in active_number_set:
                anchors.append((page_no, num, float(y0)))

    if not page_rows:
        return []

    # Build compact candidate sequences: exact OCR, same-page anchors, adjacent
    # table-page continuity, and global active-order windows. Scoring prefers
    # row-aligned OCR but allows correction when a minority of OCR IDs are
    # obvious misreads inside an otherwise contiguous active sequence.
    page_order = sorted(page_rows)
    prev_page: Dict[int, int] = {}
    next_page: Dict[int, int] = {}
    for idx, page_no in enumerate(page_order):
        if idx:
            prev_page[page_no] = page_order[idx - 1]
        if idx < len(page_order) - 1:
            next_page[page_no] = page_order[idx + 1]

    bindings: List[Dict] = []
    seen: set[Tuple[int, str]] = set()
    for page_no in page_order:
        row_structs = page_rows[page_no]
        row_count = len(row_structs)
        if not row_count:
            continue
        row_centers = [
            (float(struct.get("y0") or 0) + float(struct.get("y1") or struct.get("y0") or 0)) / 2.0
            for struct in row_structs
        ]
        entries = page_entries.get(page_no, [])

        candidate_sequences: List[Tuple[List[int], int]] = []
        entry_nums = [num for num, _y, _text in entries]
        active_windows = [
            active_numbers[i:i + row_count]
            for i in range(0, max(0, len(active_numbers) - row_count + 1))
            if len(active_numbers[i:i + row_count]) == row_count
        ]
        if entry_nums in active_windows:
            candidate_sequences.append((entry_nums, 0))

        for anchor_page, anchor_num, anchor_y in anchors:
            if anchor_page != page_no or anchor_num not in active_number_set:
                continue
            idx = min(range(row_count), key=lambda i: abs(row_centers[i] - anchor_y))
            if abs(row_centers[idx] - anchor_y) <= 95.0:
                start = anchor_num - idx
                seq = [start + i for i in range(row_count)]
                if all(num in active_number_set for num in seq):
                    candidate_sequences.append((seq, 2))

        prev = prev_page.get(page_no)
        if prev in page_rows:
            # Last reliable row on the previous table page.
            prev_entries = page_entries.get(prev, [])
            prev_nums = [num for num, _y, _text in prev_entries if num in active_number_set]
            if prev_nums:
                seq = [prev_nums[-1] + i for i in range(1, row_count + 1)]
                if all(num in active_number_set for num in seq):
                    candidate_sequences.append((seq, 1))
        nxt = next_page.get(page_no)
        if nxt in page_rows:
            next_entries = page_entries.get(nxt, [])
            next_nums = [num for num, _y, _text in next_entries if num in active_number_set]
            if next_nums:
                start = next_nums[0] - row_count
                seq = [start + i for i in range(row_count)]
                if all(num in active_number_set for num in seq):
                    candidate_sequences.append((seq, 1))

        unique_sequences: List[Tuple[List[int], int]] = []
        seen_sequences: set[Tuple[int, ...]] = set()
        for seq, source_rank in candidate_sequences:
            signature = tuple(seq)
            if signature in seen_sequences:
                for idx, (known_seq, known_rank) in enumerate(unique_sequences):
                    if tuple(known_seq) == signature and source_rank < known_rank:
                        unique_sequences[idx] = (seq, source_rank)
                        break
                continue
            seen_sequences.add(signature)
            unique_sequences.append((seq, source_rank))

        if not unique_sequences:
            continue

        def _seq_score(item: Tuple[List[int], int]) -> Tuple[float, int, int, int, int]:
            seq, source_rank = item
            matches = 0
            distance = 0.0
            for num, y0, _text in entries:
                if num not in seq:
                    continue
                idx = seq.index(num)
                matches += 1
                distance += abs(float(y0) - row_centers[idx])
            monotonic = 0 if all(b > a for a, b in zip(seq, seq[1:])) else 1
            mismatches = max(0, len(entries) - matches)
            # Strongly prefer matching real left-column OCR, but do not let one
            # or two OCR confusions beat a fully active contiguous sequence.
            return (source_rank, -matches, distance + mismatches * 35.0, monotonic, seq[0], len(seq))

        best_seq, _best_source_rank = min(unique_sequences, key=_seq_score)
        best_score = _seq_score((best_seq, _best_source_rank))
        if _best_source_rank > 2:
            continue
        if entries and best_score[2] > 180.0:
            continue

        for num, struct in zip(best_seq, row_structs):
            if num not in active_number_set:
                continue
            sid = str(struct.get("id") or "")
            marker = (num, sid)
            if marker in seen:
                continue
            binding = _build_binding_from_structure(struct, str(num))
            binding["binding_rule"] = "structure_table_row_order_corrected"
            binding["table_sequence_recovery"] = {
                "page_no": page_no,
                "sequence": best_seq,
                "ocr_row_ids": entry_nums,
            }
            bindings.append(binding)
            seen.add(marker)

    return bindings


def _row_center_from_binding(binding: Dict) -> Optional[float]:
    y0 = binding.get("struct_y0")
    if y0 is None:
        return None
    try:
        height = float(binding.get("struct_height") or 0)
        return float(y0) + (height / 2.0)
    except Exception:
        try:
            return float(y0)
        except Exception:
            return None


def _table_row_signature_from_binding(binding: Dict) -> Optional[Tuple[int, int, float]]:
    base = _binding_base_num(binding)
    page_no = binding.get("page_no")
    y_center = _row_center_from_binding(binding)
    if base is None or page_no is None or y_center is None:
        return None
    try:
        return int(page_no), int(base), float(y_center)
    except Exception:
        return None


def _infer_table_page_row_numbers(
    page_no: int,
    row_structs: List[Dict],
    known_bindings: List[Dict],
    active_bases: set[int],
) -> List[int]:
    """Infer missing table-row labels from neighboring bound table rows.

    This is deliberately conservative: it only fills labels on pages that
    already have table-row bindings immediately before or after the current
    page, and it only emits active compound numbers. It repairs OCR misses at
    page boundaries without inventing non-active synthesis rows.
    """
    row_count = len(row_structs)
    if row_count == 0:
        return []

    table_rules = {
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "direct_structure_label",
        "direct_structure_label_right_product_crop",
    }
    known = [
        binding for binding in known_bindings
        if str(binding.get("binding_rule") or "") in table_rules
        and _binding_base_num(binding) in active_bases
    ]

    same_page = [
        item for item in known
        if int(item.get("page_no") or -1) == int(page_no)
    ]
    if same_page:
        signatures = [
            _table_row_signature_from_binding(item)
            for item in same_page
        ]
        signatures = [sig for sig in signatures if sig]
        if signatures:
            signatures.sort(key=lambda sig: sig[2])
            row_centers = [
                (float(struct.get("y0") or 0) + float(struct.get("y1") or struct.get("y0") or 0)) / 2.0
                for struct in row_structs
            ]
            anchors: List[Tuple[int, int]] = []
            for _p, num, y_center in signatures:
                idx = min(range(row_count), key=lambda i: abs(row_centers[i] - y_center))
                if abs(row_centers[idx] - y_center) <= 90.0:
                    anchors.append((idx, num))
            anchors = sorted(set(anchors))
            if anchors:
                candidates = []
                for idx, num in anchors:
                    start = num - idx
                    seq = [start + i for i in range(row_count)]
                    if all(n in active_bases for n in seq):
                        candidates.append(seq)
                if candidates:
                    return candidates[0]

    previous = [
        sig for sig in (_table_row_signature_from_binding(item) for item in known)
        if sig and sig[0] < page_no
    ]
    next_items = [
        sig for sig in (_table_row_signature_from_binding(item) for item in known)
        if sig and sig[0] > page_no
    ]

    candidates: List[List[int]] = []
    if previous:
        prev_page, prev_num, _prev_y = max(previous, key=lambda sig: (sig[0], sig[2]))
        if page_no - prev_page <= 2:
            seq = [prev_num + i for i in range(1, row_count + 1)]
            if all(n in active_bases for n in seq):
                candidates.append(seq)
    if next_items:
        next_page, next_num, _next_y = min(next_items, key=lambda sig: (sig[0], sig[2]))
        if next_page - page_no <= 2:
            start = next_num - row_count
            seq = [start + i for i in range(row_count)]
            if all(n in active_bases for n in seq):
                candidates.append(seq)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 2 and candidates[0] == candidates[1]:
        return candidates[0]
    return []


def _repair_missing_structure_table_bindings(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return final_bindings

    existing_base_nums = {
        _binding_base_num(binding)
        for binding in final_bindings
    }
    existing_base_nums.discard(None)
    missing_bases = active_bases - existing_base_nums
    if not missing_bases:
        return final_bindings

    used_structure_ids = {
        str(binding.get("structure_id") or "")
        for binding in final_bindings
        if binding.get("structure_id")
    }
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    additions: List[Dict] = []

    for page_no in sorted(set(int(p["page_no"]) for p in processed_structures)):
        page_structs = sorted(
            [
                p for p in processed_structures
                if int(p.get("page_no") or 0) == page_no
                and str(p.get("id") or "") not in used_structure_ids
            ],
            key=lambda p: (float(p.get("y0") or 0), float(p.get("x0") or 0)),
        )
        if not page_structs:
            continue
        page_text = _page_text_for_page_no(pages_text, page_no)
        page_lines = lines_by_page.get(page_no - 1) or []
        if not _is_structure_table_layout(page_structs, page_text, ocr_lines=page_lines, active_bases=active_bases):
            continue

        struct_rows = _group_structures_by_row(page_structs, y_threshold=55.0)
        row_structs = []
        for row in struct_rows:
            if not row:
                continue
            struct = _best_table_structure_from_row(row, page_structs)
            if struct:
                row_structs.append(struct)
        if not row_structs:
            continue

        inferred = _infer_table_page_row_numbers(
            page_no,
            row_structs,
            [*final_bindings, *additions],
            active_bases,
        )
        if len(inferred) != len(row_structs):
            continue

        for compound_num, struct in zip(inferred, row_structs):
            if compound_num not in missing_bases:
                continue
            sid = str(struct.get("id") or "")
            if sid in used_structure_ids:
                continue
            binding = _build_binding_from_structure(struct, str(compound_num))
            binding["binding_rule"] = "structure_table_row_order_inferred"
            binding["table_inference"] = "neighbor_page_continuity"
            additions.append(binding)
            used_structure_ids.add(sid)
            missing_bases.discard(compound_num)

    if additions:
        logger.info(
            "   表格续页编号补漏: 新增 %d 个活性结构绑定 %s",
            len(additions),
            [binding["cpd"] for binding in additions],
        )
        return _merge_binding_candidates(final_bindings, additions, active_cpds=active_cpds)
    return final_bindings


def _extract_direct_label_bindings(
    doc,
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Optional[Dict[int, str]] = None,
    word_cache: Optional[Dict[int, List[Dict]]] = None,
    focus_windows: Optional[Dict[int, List[Tuple[float, float]]]] = None,
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Bind structures whose own label matches an active compound number."""
    active_keys = _active_label_keys(active_cpds)
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_keys:
        return []

    bindings: List[Dict] = []
    seen_pairs: set[tuple[int, str]] = set()
    focus_windows = focus_windows or {}
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        if page_no < 1 or page_no > len(doc):
            continue
        page_structs = [
            p for p in processed_structures
            if p["page_no"] == page_no
        ]
        page_text = _page_text_for_page_no(pages_text, page_no)
        page_lines = lines_by_page.get(page_no - 1) or []
        page_structs = _filter_items_by_focus_windows(page_structs, focus_windows.get(page_no), margin=70.0)
        rows_by_page = {
            page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        }
        for struct in page_structs:
            if (
                active_cpds
                and visible_label_cache
                and _is_structure_table_layout(page_structs, page_text, ocr_lines=page_lines, active_bases=active_bases)
                and _is_probable_table_structure(struct, page_structs)
            ):
                # On structure-table pages the authoritative compound number is
                # the left ID column. Numeric OCR inside the drawing is often an
                # atom/NMR/route artifact and must not occupy the structure
                # before table-row binding runs.
                continue
            # Strongest evidence: the label is cropped with the structure
            # itself. Page-level OCR around structures is intentionally not
            # used here because nearby procedure text frequently contains
            # unrelated compound numbers and can steal bindings.
            cache_candidates = _visible_label_candidates_for_structure(struct, visible_label_cache)
            if cache_candidates:
                visual_candidates = _contextual_visible_label_candidates(
                    struct,
                    cache_candidates,
                    active_keys,
                    pages_text,
                    max_context_distance=1,
                    lines_by_page=lines_by_page,
                    row=_row_for_structure(struct, rows_by_page),
                )
            else:
                labels = [
                    label for label in _visible_labels_for_structure(doc, struct, visible_label_cache=visible_label_cache, fast_only=True)
                    if _cpd_label_key(label) in active_keys
                ]
                visual_candidates = [
                    {
                        "label": _normalise_compound_label(str(label)),
                        "source": "ocr",
                        "product_context_distance": _product_context_distance(pages_text, page_no, _base_cpd_num(label) or 0) if pages_text is not None else 0,
                        "multi_label_crop": False,
                    }
                    for label in labels
                ]

            for visual_candidate in visual_candidates:
                label = _normalise_compound_label(str(visual_candidate.get("label") or ""))
                label_key = _cpd_label_key(label)
                if label_key not in active_keys:
                    continue
                nearby_label_kind = _nearby_ocr_label_kind(struct, label_key, lines_by_page)
                if nearby_label_kind == "racemic":
                    # Rac-Cpd-N is the pre-chiral-separation precursor. If the
                    # patent prints Cpd-N products too, activity-led binding
                    # must not let the same visible N steal the final structure.
                    continue
                ok_exact, exact_label = _passes_exact_visual_label_guard(
                    struct,
                    label_key,
                    lines_by_page,
                    row=_row_for_structure(struct, rows_by_page),
                )
                if not ok_exact:
                    continue
                has_product_context = True
                product_context_distance = int(visual_candidate.get("product_context_distance") or 0)
                if pages_text is not None:
                    has_product_context = product_context_distance < 999
                    if not has_product_context:
                        continue
                if not _is_contextual_final_visual_candidate(struct, visual_candidate):
                    continue
                pair_key = (label_key, str(struct.get("id")))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                binding = _build_binding_from_structure(struct, label_key)
                binding["binding_rule"] = "direct_structure_label"
                binding["visible_label"] = str(label)
                binding["visual_label_source"] = "cache" if str(struct.get("id") or "") in (visible_label_cache or {}) else "ocr"
                binding["visible_label_crop_source"] = str(visual_candidate.get("source") or "")
                binding["visible_label_multi_candidate"] = bool(visual_candidate.get("multi_label_crop"))
                binding["product_context_nearby"] = has_product_context
                binding["product_context_distance"] = product_context_distance
                if nearby_label_kind:
                    binding["nearby_ocr_label_kind"] = nearby_label_kind
                if exact_label:
                    binding["nearby_exact_product_label"] = exact_label
                width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
                height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
                binding["struct_width"] = width
                binding["struct_height"] = height
                binding["struct_area"] = width * height
                bindings.append(binding)
    return bindings


def _extract_paired_route_product_bindings(
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    existing_bindings: List[Dict],
) -> List[Dict]:
    """Bind paired final products from a shared route scheme.

    Chinese patents often show "实施例24、25 / 化合物24、25" as one route:
    two product rows are drawn on the page before the text procedures continue
    on the next page. OCR may miss the tiny labels under the structures, so use
    the explicit paired title plus top-to-bottom product rows. This is kept
    narrow to avoid treating intermediate-heavy route rows as final products.
    """
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return []

    used_structure_ids = {
        str(binding.get("structure_id"))
        for binding in existing_bindings
        if binding.get("structure_id")
    }
    existing_base_nums = {
        _base_cpd_num(binding.get("cpd", ""))
        for binding in existing_bindings
    }
    existing_base_nums.discard(None)

    bindings: List[Dict] = []
    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_text = _page_text_for_page_no(pages_text, page_no, include_next=True)
        if not page_text:
            continue
        text_one_line = re.sub(r"\s+", " ", page_text)
        pair_matches: List[Tuple[str, str]] = []
        for base in sorted(active_bases):
            right = base + 1
            if right not in active_bases:
                continue
            left_pat = _ocr_confusable_num_pattern(base)
            right_pat = _ocr_confusable_num_pattern(right)
            if re.search(
                rf"(?:实施例|化.?[合台]物)\s*{left_pat}\s*[、,，]\s*{right_pat}(?![\dA-Za-z-])",
                text_one_line,
                re.IGNORECASE,
            ):
                pair_matches.append((str(base), str(right)))
        pairs = []
        for left, right in pair_matches:
            nums = (int(left), int(right))
            if nums[1] != nums[0] + 1:
                continue
            if nums[0] not in active_bases or nums[1] not in active_bases:
                continue
            if nums[0] in existing_base_nums and nums[1] in existing_base_nums:
                continue
            pairs.append(nums)
        if not pairs:
            continue

        page_structs = [
            p for p in processed_structures
            if p["page_no"] == page_no and str(p["id"]) not in used_structure_ids
        ]
        if len(page_structs) < 4:
            continue
        rows = _group_structures_by_row(page_structs, y_threshold=70.0)
        product_rows = [
            row for row in rows
            if len(row) >= 2
            and max(float(p["x1"]) for p in row) >= 430.0
            and max(float(p["y1"]) - float(p["y0"]) for p in row) >= 35.0
        ]
        if len(product_rows) < 2:
            continue
        product_rows = sorted(product_rows, key=lambda row: min(float(p["y0"]) for p in row))

        for nums in pairs:
            if len(product_rows) < 2:
                break
            for compound_num, row in zip(nums, product_rows[-2:]):
                if compound_num in existing_base_nums:
                    continue
                struct = max(row, key=lambda p: (float(p["x1"]), float(p["x0"])))
                binding = _build_binding_from_structure(struct, str(compound_num))
                binding["binding_rule"] = "paired_route_product_row_order"
                binding["candidates"] = len(row)
                bindings.append(binding)
                used_structure_ids.add(struct["id"])
                existing_base_nums.add(compound_num)

    return bindings


def _extract_triplet_split_row_bindings(
    doc,
    processed_structures: List[Dict],
    used_structures: set[str],
    used_labels: set[str],
    word_cache: Optional[Dict[int, List[Dict]]] = None,
    focus_windows: Optional[Dict[int, List[Tuple[float, float]]]] = None,
) -> List[Dict]:
    """Bind rows laid out as N -> N-1 + N-2 when OCR drops the middle hyphen."""
    bindings: List[Dict] = []

    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        if page_no < 1 or page_no > len(doc):
            continue
        page_structs = [
            p for p in processed_structures
            if p["page_no"] == page_no and p["id"] not in used_structures
        ]
        page_structs = _filter_items_by_focus_windows(page_structs, (focus_windows or {}).get(page_no), margin=60.0)
        rows = _group_structures_by_row(page_structs)
        words = _get_ocr_word_coords(doc[page_no - 1], cache=word_cache)
        words = _filter_items_by_focus_windows(words, (focus_windows or {}).get(page_no), margin=80.0)
        if not words:
            continue

        for row in rows:
            if len(row) < 3 or any(p["id"] in used_structures for p in row[:3]):
                continue
            left_labels = _labels_near_structure(words, row[0])
            right_labels = _labels_near_structure(words, row[2])
            bases = [
                int(label)
                for label in left_labels
                if _BARE_FINAL_LABEL_RE.fullmatch(label)
            ]
            for base in bases:
                if f"{base}-2" not in right_labels:
                    continue
                labels = [str(base), f"{base}-1", f"{base}-2"]
                if any(label in used_labels for label in labels):
                    continue
                for struct, label in zip(row[:3], labels):
                    binding = _build_binding_from_structure(struct, label)
                    binding["binding_rule"] = "triplet_split_row_structure_order"
                    bindings.append(binding)
                    used_labels.add(label)
                    used_structures.add(struct["id"])
                break

    return bindings


def _extract_first_dense_scheme_product(
    processed_structures: List[Dict],
    existing_bindings: List[Dict],
    used_structures: set[str],
    used_labels: set[str],
) -> List[Dict]:
    """Recover Compound 1 from dense multi-step route pages without readable labels."""
    if "1" in used_labels:
        return []
    has_split_1 = any(b["cpd"] in ("Compound 1-1", "Compound 1-2") for b in existing_bindings)
    if not has_split_1:
        return []

    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_structs = [
            p for p in processed_structures
            if p["page_no"] == page_no and p["id"] not in used_structures
        ]
        if len(page_structs) < 8:
            continue
        rows = _group_structures_by_row(page_structs)
        candidate_rows = [row for row in rows if len(row) >= 2]
        if not candidate_rows:
            continue
        row = max(candidate_rows, key=lambda r: max(float(p["y0"]) for p in r))
        struct = max(row, key=lambda p: float(p["x0"]))
        binding = _build_binding_from_structure(struct, "1")
        binding["binding_rule"] = "dense_scheme_final_product"
        used_labels.add("1")
        used_structures.add(struct["id"])
        return [binding]

    return []


def _extract_bare_product_label_bindings(
    doc,
    processed_structures: List[Dict],
    used_structures: set[str],
    used_labels: set[str],
    pages_text: Optional[Dict[int, str]] = None,
    word_cache: Optional[Dict[int, List[Dict]]] = None,
    focus_windows: Optional[Dict[int, List[Tuple[float, float]]]] = None,
) -> List[Dict]:
    """Bind bare-number final products without accepting every numeric label.

    Bare labels like "1" or "8" are valid final products in Chinese synthesis
    pages, but similar labels also appear under intermediates. Restrict this
    rule to isolated structures and the right-most structure in reaction rows.
    """
    bindings: List[Dict] = []
    active_bases = {_base_cpd_num(cpd) for cpd in (used_labels or [])}
    active_bases.discard(None)
    product_context_bases_by_page: Dict[int, set[int]] = {}
    for page_idx, text in (pages_text or {}).items():
        page_no_ctx = int(page_idx) + 1 if isinstance(page_idx, int) else int(page_idx) + 1
        anchors = _product_anchor_lines_from_text(str(text or ""), set(range(1, 301)))
        if anchors:
            product_context_bases_by_page[page_no_ctx] = {num for num, _y, _line in anchors}

    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        if page_no < 1 or page_no > len(doc):
            continue
        page_text = _page_text_for_page_no(pages_text, page_no)
        page_structs = [
            p for p in processed_structures
            if p["page_no"] == page_no and p["id"] not in used_structures
        ]
        if _is_structure_table_layout(page_structs, page_text, active_bases=active_bases):
            continue
        page_structs = _filter_items_by_focus_windows(page_structs, (focus_windows or {}).get(page_no), margin=60.0)
        rows = _group_structures_by_row(page_structs)
        candidate_structs = []
        for row in rows:
            if len(row) == 1:
                candidate_structs.append(row[0])
            elif len(row) >= 2:
                candidate_structs.append(row[-1])

        words = _get_ocr_word_coords(doc[page_no - 1], cache=word_cache)
        words = _filter_items_by_focus_windows(words, (focus_windows or {}).get(page_no), margin=80.0)
        if not words:
            continue

        for struct in candidate_structs:
            if struct["id"] in used_structures:
                continue
            x0, x1 = float(struct["x0"]), float(struct.get("x1", struct["x0"]))
            y0, y1 = float(struct["y0"]), float(struct.get("y1", struct["y0"]))
            cx = (x0 + x1) / 2
            width = max(25.0, x1 - x0)

            candidates = []
            has_hyphen_label_nearby = False
            for word in words:
                label = _normalise_compound_label(word["text"])
                dx = abs(float(word["x"]) - cx)
                y = float(word["y"])
                below = y1 - 5 <= y <= y1 + 55
                inside_or_above_bottom = y0 <= y <= y1 + 20
                near_structure = (
                    dx <= max(width * 0.55, 35.0)
                    and (below or inside_or_above_bottom)
                )
                if near_structure and _FINAL_COMPOUND_LABEL_RE.fullmatch(label):
                    has_hyphen_label_nearby = True
                if not _BARE_FINAL_LABEL_RE.fullmatch(label):
                    continue
                if near_structure:
                    dy = abs(y - y1) if below else abs(y - y0)
                    candidates.append((dy + dx * 0.05, label, word))

            if has_hyphen_label_nearby:
                continue
            if not candidates:
                continue
            _, label, _word = min(candidates, key=lambda x: x[0])
            if label in used_labels:
                continue
            used_labels.add(label)
            used_structures.add(struct["id"])
            binding = _build_binding_from_structure(struct, label)
            binding["binding_rule"] = "ocr_bare_numeric_product_label"
            bindings.append(binding)

    return bindings


def _extract_labeled_product_bindings(
    doc,
    processed_structures: List[Dict],
    pages_text: Optional[Dict[int, str]] = None,
    active_cpds: Optional[List[str]] = None,
    focus_windows: Optional[Dict[int, List[Tuple[float, float]]]] = None,
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Bind structures by OCR labels immediately below/near the drawing.

    This is the primary fallback for scanned Chinese synthesis pages. It keeps
    only product-like numeric labels (1, 2, 4-2, 15-1) and ignores intermediate
    labels with letters (1a, 3b), preventing all reagent/intermediate drawings
    from leaking into final Step9 output.
    """
    bindings: List[Dict] = []
    used_structures: set[str] = set()
    used_labels: set[str] = set()
    word_cache: Dict[int, List[Dict]] = {}
    focus_windows = focus_windows or {}

    if pages_text:
        direct_label_bindings = _extract_direct_label_bindings(
            doc,
            processed_structures,
            active_cpds or [],
            pages_text=pages_text,
            word_cache=word_cache,
            focus_windows=focus_windows,
            visible_label_cache=visible_label_cache,
            ocr_line_map=ocr_line_map,
        )
        bindings.extend(direct_label_bindings)
        used_structures.update(b["structure_id"] for b in direct_label_bindings)
        used_labels.update(b["cpd"].replace("Compound ", "") for b in direct_label_bindings)

        pair_bindings = _extract_pair_heading_product_bindings(doc, pages_text, processed_structures, ocr_line_map=ocr_line_map)
        bindings.extend(pair_bindings)
        used_structures.update(b["structure_id"] for b in pair_bindings)
        used_labels.update(b["cpd"].replace("Compound ", "") for b in pair_bindings)

        letter_pair_bindings = _extract_cpd_letter_pair_product_bindings(
            pages_text,
            processed_structures,
            active_cpds=active_cpds or [],
            ocr_line_map=ocr_line_map,
        )
        bindings.extend(letter_pair_bindings)
        used_structures.update(b["structure_id"] for b in letter_pair_bindings)
        used_labels.update(b["cpd"].replace("Compound ", "") for b in letter_pair_bindings)

        table_bindings = _extract_structure_table_bindings(
            processed_structures,
            pages_text,
            active_cpds or [],
            [],
            ocr_line_map=ocr_line_map,
        )
        bindings.extend(table_bindings)
        used_structures.update(b["structure_id"] for b in table_bindings)
        used_labels.update(b["cpd"].replace("Compound ", "") for b in table_bindings)

        table_sequence_bindings = _extract_structure_table_sequence_bindings(
            processed_structures,
            pages_text,
            active_cpds or [],
            table_bindings,
            ocr_line_map=ocr_line_map,
        )
        bindings.extend(table_sequence_bindings)
        used_structures.update(b["structure_id"] for b in table_sequence_bindings)
        used_labels.update(b["cpd"].replace("Compound ", "") for b in table_sequence_bindings)

        paired_route_bindings = _extract_paired_route_product_bindings(
            processed_structures,
            pages_text,
            active_cpds or [],
            bindings,
        )
        bindings.extend(paired_route_bindings)
        used_structures.update(b["structure_id"] for b in paired_route_bindings)
        used_labels.update(b["cpd"].replace("Compound ", "") for b in paired_route_bindings)

        product_section_bindings = _extract_product_section_bindings(
            processed_structures,
            pages_text,
            active_cpds or [],
            bindings,
        )
        bindings.extend(product_section_bindings)
        used_structures.update(b["structure_id"] for b in product_section_bindings)
        used_labels.update(b["cpd"].replace("Compound ", "") for b in product_section_bindings)

    use_legacy_word_ocr_fallbacks = not active_cpds and not visible_label_cache
    if use_legacy_word_ocr_fallbacks:
        triplet_bindings = _extract_triplet_split_row_bindings(
            doc, processed_structures, used_structures, used_labels, word_cache=word_cache, focus_windows=focus_windows
        )
        bindings.extend(triplet_bindings)

        dense_scheme_bindings = _extract_first_dense_scheme_product(
            processed_structures, bindings, used_structures, used_labels
        )
        bindings.extend(dense_scheme_bindings)

        bare_bindings = _extract_bare_product_label_bindings(
            doc, processed_structures, used_structures, used_labels, pages_text=pages_text, word_cache=word_cache, focus_windows=focus_windows
        )
        bindings.extend(bare_bindings)

        split_reaction_bindings = _extract_split_reaction_bare_bindings(
            processed_structures, bindings, used_structures, used_labels
        )
        bindings.extend(split_reaction_bindings)
    else:
        logger.info("   跳过旧词级OCR fallback：活性表+可见标签缓存已接管结构绑定")

    pages = sorted({p["page_no"] for p in processed_structures})
    if active_cpds and visible_label_cache:
        bindings.sort(key=_binding_sort_key)
        return bindings

    for page_no in pages:
        if page_no < 1 or page_no > len(doc):
            continue
        page_structs = sorted(
            [p for p in processed_structures if p["page_no"] == page_no],
            key=lambda p: (p["y0"], p["x0"]),
        )
        page_windows = focus_windows.get(page_no)
        page_structs = _filter_items_by_focus_windows(page_structs, page_windows, margin=60.0)
        if not page_structs:
            continue
        words = _get_ocr_word_coords(doc[page_no - 1], cache=word_cache)
        words = _filter_items_by_focus_windows(words, page_windows, margin=80.0)
        if not words:
            continue

        for struct in page_structs:
            if struct["id"] in used_structures:
                continue
            x0, x1 = float(struct["x0"]), float(struct.get("x1", struct["x0"]))
            y0, y1 = float(struct["y0"]), float(struct.get("y1", struct["y0"]))
            cx = (x0 + x1) / 2
            width = max(25.0, x1 - x0)

            candidates = []
            for word in words:
                label = _normalise_compound_label(word["text"])
                if not _FINAL_COMPOUND_LABEL_RE.fullmatch(label):
                    continue
                dx = abs(float(word["x"]) - cx)
                y = float(word["y"])
                below = y1 - 5 <= y <= y1 + 55
                inside_or_above_bottom = y0 <= y <= y1 + 20
                if dx <= max(width * 0.55, 35.0) and (below or inside_or_above_bottom):
                    dy = abs(y - y1) if below else abs(y - y0)
                    candidates.append((dy + dx * 0.05, label, word))

            if not candidates:
                continue
            _, label, _word = min(candidates, key=lambda x: x[0])
            if label in used_labels:
                continue
            used_labels.add(label)
            used_structures.add(struct["id"])
            binding = _build_binding_from_structure(struct, label)
            binding["binding_rule"] = "ocr_numeric_structure_label"
            bindings.append(binding)

    bindings.sort(key=_binding_sort_key)
    split_bases = [
        int(m.group(1))
        for b in bindings
        for m in [re.match(r"^Compound\s+(\d+)-[12]$", b["cpd"])]
        if m
    ]
    if split_bases:
        max_split_base = max(split_bases)
        before = len(bindings)
        bindings = [
            b for b in bindings
            if not (
                re.match(r"^Compound\s+\d+$", b["cpd"])
                and int(b["cpd"].split()[-1]) > max_split_base + 2
                and b.get("binding_rule") in {
                    "ocr_numeric_structure_label",
                    "ocr_bare_numeric_product_label",
                }
            )
        ]
        removed = before - len(bindings)
        if removed:
            logger.info(f"   OCR标签后过滤: 去除 {removed} 个疑似粘连数字标签")
    return bindings


# ============================================================================
# 主入口：bind()
# ============================================================================

def bind(
    pdf_path: str,
    profile: dict,
    output_dir: str,
    structures_path: str = None,
    include_intermediates: bool = False,
    cpd_prefix_pattern: str = None,
) -> dict:
    """运行化合物-结构绑定 (Step 6.5)。

    Args:
        pdf_path: OCR PDF 文件路径
        profile: patent_profiler.profile() 的输出字典
        output_dir: 输出目录
        structures_path: Step 6 结构提取的 metadata.json 路径。
            如果为 None，自动在 output_dir 的父目录中查找。
        include_intermediates: 是否保留 Intermediate 中间体
        cpd_prefix_pattern: 覆盖 profile 中的 cpd_pattern（None = 自动取）

    Returns:
        {
            "bindings": [...],
            "total": int,
            "bound": int,
            "unbound_pages": [...],
            "output_files": {"json": str, "csv": str},
        }
    """
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF (fitz) 未安装 — 需要在 paddleocr 或 pymupdf 环境运行")
    
    config = BinderConfig()
    
    # 确定输出目录
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    logger.info(f"📁 输出目录: {out}")
    
    # ── 1. 加载 Step 6 结构数据 ──────────────────────────────────
    if structures_path is None:
        # 自动搜索: output_dir/../structures/metadata.json 或 output_dir/metadata.json
        candidates = [
            out.parent / "structures" / "metadata.json",
            out / "metadata.json",
        ]
        for c in candidates:
            if c.exists():
                structures_path = str(c)
                break
        if structures_path is None:
            raise FileNotFoundError(
                f"找不到 Step 6 结构数据。请提供 structures_path 参数。"
                f"已搜索: {[str(c) for c in candidates]}"
            )
    
    logger.info(f"📦 加载结构数据: {structures_path}")
    with open(structures_path, "r", encoding="utf-8") as f:
        step6_metadata = json.load(f)
    
    structures = step6_metadata.get("structures", [])
    patent_id = step6_metadata.get("patent_number", "unknown")
    logger.info(f"   加载了 {len(structures)} 个结构 (patent={patent_id})")
    
    # ── 2. 打开 PDF，提取页面文本 ──────────────────────────────
    doc = fitz.open(pdf_path)
    logger.info(f"   PDF: {pdf_path} ({len(doc)} 页)")

    candidate_pages = sorted(set(profile.get("structure_candidate_pages", []) or []))
    structure_page_indices: set[int] = set()
    for raw_struct in structures:
        page_idx = raw_struct.get("page_idx")
        if page_idx is None:
            page_no = raw_struct.get("page_no", raw_struct.get("page_num", 0))
            try:
                page_idx = int(page_no) - 1
            except Exception:
                page_idx = None
        try:
            page_idx_int = int(page_idx)
        except Exception:
            continue
        if 0 <= page_idx_int < len(doc):
            structure_page_indices.add(page_idx_int)

    if candidate_pages:
        page_indices = sorted(set(candidate_pages) | structure_page_indices)
    else:
        page_indices = list(range(len(doc)))
    if structure_page_indices and candidate_pages:
        logger.info(
            "   结构页文本上下文补充: candidate=%d, structure_pages=%d, merged=%d",
            len(candidate_pages),
            len(structure_page_indices),
            len(page_indices),
        )
    bind_workers = max(1, int(profile.get("bind_workers", 1) or 1))
    page_ocr_cache_path = Path(str(profile.get("ocr_cache_path") or "")).expanduser() if profile.get("ocr_cache_path") else None
    if page_ocr_cache_path and not page_ocr_cache_path.is_absolute():
        page_ocr_cache_path = out.parent / page_ocr_cache_path
    if not page_ocr_cache_path:
        page_ocr_cache_path = out.parent / "page_classification" / "page_ocr_cache.json"

    page_ocr_cache_payload: Dict[str, Any] = {}
    if page_ocr_cache_path.is_file():
        try:
            with open(page_ocr_cache_path, "r", encoding="utf-8") as f:
                loaded_cache = json.load(f)
            if isinstance(loaded_cache, dict):
                page_ocr_cache_payload = loaded_cache
                logger.info("   加载页面OCR缓存: %s", page_ocr_cache_path)
        except Exception as exc:
            logger.debug("Page OCR cache load failed %s: %s", page_ocr_cache_path, exc)

    profile_line_map = profile.get("ocr_line_map", {}) or {}
    cached_page_texts = page_ocr_cache_payload.get("page_texts", {}) if isinstance(page_ocr_cache_payload, dict) else {}
    cached_page_lines = page_ocr_cache_payload.get("ocr_line_map", {}) if isinstance(page_ocr_cache_payload, dict) else {}

    cached_text_map = {
        int(k): v for k, v in (profile.get("ocr_text_map", {}) or {}).items()
        if str(k).isdigit() and isinstance(v, str)
    }
    for k, v in (cached_page_texts or {}).items():
        if str(k).isdigit() and isinstance(v, str) and int(k) not in cached_text_map:
            cached_text_map[int(k)] = v
    cached_line_map = {
        int(k): [(float(item.get("y0", 0)), str(item.get("text", ""))) for item in v if str(item.get("text", "")).strip()]
        for k, v in (profile_line_map or {}).items()
        if str(k).isdigit() and isinstance(v, list)
    }
    for k, v in (cached_page_lines or {}).items():
        if str(k).isdigit() and isinstance(v, list) and int(k) not in cached_line_map:
            normalised_lines = []
            for item in v:
                try:
                    if isinstance(item, dict):
                        y0 = float(item.get("y0", 0))
                        text = str(item.get("text", "")).strip()
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        y0 = float(item[0])
                        text = str(item[1]).strip()
                    else:
                        continue
                except Exception:
                    continue
                if text:
                    normalised_lines.append((y0, text))
            if normalised_lines:
                cached_line_map[int(k)] = sorted(normalised_lines, key=lambda row: row[0])

    pages_text: Dict[int, str] = {}
    missing_page_indices = []
    for i in page_indices:
        if i < 0 or i >= len(doc):
            continue
        if i in cached_text_map:
            pages_text[i] = cached_text_map[i]
        else:
            missing_page_indices.append(i)

    if bind_workers <= 1 or len(missing_page_indices) <= 1:
        for i in missing_page_indices:
            page = doc[i]
            text = page.get_text("text")
            if not text.strip():
                try:
                    from patent_sar_extractor.core.patent_profiler import (
                        _ocr_page_fallback,
                    )
                    text = _ocr_page_fallback(page)
                except Exception:
                    pass
            if text.strip():
                pages_text[i] = text
    else:
        max_workers = min(bind_workers, len(missing_page_indices))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(_extract_binder_page_text, pdf_path, i): i
                for i in missing_page_indices
            }
            for future in as_completed(future_map):
                page_idx = future_map[future]
                try:
                    resolved_idx, text = future.result()
                except Exception as exc:
                    logger.debug("Binder text extraction failed on page %s: %s", page_idx + 1, exc)
                    continue
                if text.strip():
                    pages_text[resolved_idx] = text

    if candidate_pages:
        logger.info(f"   使用结构候选页约束: {len(candidate_pages)} 页")

    # Structure tables need OCR line coordinates for the left compound-number
    # column. Older locator outputs stored only flattened text, so fill line
    # coordinates here for table-like pages instead of falling back to prose order.
    contextual_table_page_indices = {
        int(page_idx)
        for page_idx, text in pages_text.items()
        if _is_structure_table_context(text)
    }
    authoritative_table_page_indices: set[int] = set()
    for raw_page_idx in (profile.get("authoritative_structure_table_pages", []) or []):
        try:
            page_idx = int(raw_page_idx)
        except Exception:
            continue
        if 0 <= page_idx < len(doc):
            authoritative_table_page_indices.add(page_idx)
    table_page_indices = sorted(
        contextual_table_page_indices | authoritative_table_page_indices
    )
    missing_line_indices = [
        idx for idx in table_page_indices
        if idx not in cached_line_map and 0 <= idx < len(doc)
    ]
    if missing_line_indices:
        logger.info(
            "   表格页OCR行坐标补扫: %d pages (configured OCR)",
            len(missing_line_indices),
        )
        completed_since_checkpoint = 0

        def _checkpoint_page_ocr_lines() -> None:
            page_ocr_cache_payload.setdefault("page_texts", {})
            page_ocr_cache_payload.setdefault("ocr_line_map", {})
            for idx, text in cached_text_map.items():
                page_ocr_cache_payload["page_texts"][str(idx)] = text
            for idx, lines in cached_line_map.items():
                if lines:
                    page_ocr_cache_payload["ocr_line_map"][str(idx)] = [
                        {"y0": round(float(y0), 2), "text": str(text)}
                        for y0, text in lines
                        if str(text).strip()
                    ]
            page_ocr_cache_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(page_ocr_cache_path, page_ocr_cache_payload)

        if bind_workers <= 1 or len(missing_line_indices) <= 1:
            for idx in missing_line_indices:
                lines = _get_ocr_line_coords(doc[idx]) or []
                if lines:
                    cached_line_map[idx] = lines
                completed_since_checkpoint += 1
                if completed_since_checkpoint >= 10:
                    _checkpoint_page_ocr_lines()
                    completed_since_checkpoint = 0
        else:
            max_workers = min(bind_workers, len(missing_line_indices))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {
                    pool.submit(_extract_binder_page_lines, pdf_path, idx): idx
                    for idx in missing_line_indices
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    try:
                        resolved_idx, lines = future.result()
                    except Exception as exc:
                        logger.debug("Binder line OCR failed on page %s: %s", idx + 1, exc)
                        continue
                    if lines:
                        cached_line_map[resolved_idx] = lines
                    completed_since_checkpoint += 1
                    if completed_since_checkpoint >= 10:
                        _checkpoint_page_ocr_lines()
                        completed_since_checkpoint = 0
        logger.info(
            "   表格页OCR行坐标可用: %d/%d",
            sum(1 for idx in table_page_indices if idx in cached_line_map),
            len(table_page_indices),
        )
        try:
            _checkpoint_page_ocr_lines()
            logger.info("   更新页面OCR缓存: %s", page_ocr_cache_path)
        except Exception as exc:
            logger.warning("   页面OCR缓存写入失败 %s: %s", page_ocr_cache_path, exc)
    
    # ── 3. 查找化合物区块 ─────────────────────────────────────
    # 用 profile 的 cpd_prefix / cpd_pattern 做提示，但让 auto 检测做最终决定
    logger.info("🔍 自动检测化合物编号格式...")
    all_blocks, detected_style = _find_blocks_auto(
        doc,
        pages_text,
        ocr_line_map=cached_line_map,
        page_numbers=[i + 1 for i in page_indices],
        workers=bind_workers,
    )
    logger.info(f"   检测风格: {detected_style}")
    logger.info(f"   找到 {len(all_blocks)} 个化合物区块")
    
    for b in all_blocks[:10]:
        logger.info(f"   → {b['cpd']} (p{b['page_no']}, y0={b['y0']:.0f})")
    if len(all_blocks) > 10:
        logger.info(f"   ... 还有 {len(all_blocks) - 10} 个")
    
    # ── 4. OCR 回退补漏 ────────────────────────────────────────
    if detected_style in ("heading", "heading_mixed", "heading_intermediate"):
        # 对 Example 和 Intermediate 分别做 OCR 补漏
        for prefix, pattern in [
            ("Example", r"Example\s*(\d+)"),
            ("Intermediate", r"Intermediate\s+(\d+)"),
        ]:
            prefix_blocks = [b for b in all_blocks if b.get("prefix") == prefix]
            if prefix_blocks:
                ocr_new = _find_missing_blocks_via_ocr_text(
                    doc, prefix_blocks, pages_text, prefix, pattern
                )
                if ocr_new:
                    all_blocks.extend(ocr_new)
                    all_blocks.sort(key=lambda x: (x["page_no"], x["y0"]))
                    logger.info(
                        f"   OCR补漏: {prefix} 新增 {len(ocr_new)} 个区块"
                    )
    
    # ── 5. 处理结构坐标 ───────────────────────────────────────
    logger.info("🔧 处理结构坐标...")
    processed_structures = [_process_structure(s) for s in structures]
    logger.info(f"   处理完成: {len(processed_structures)} 个结构")
    
    struct_pages = set(p["page_no"] for p in processed_structures)
    logger.info(f"   结构分布在 {len(struct_pages)} 个页面上")

    active_cpds = profile.get("active_cpds", []) or []
    numbered_result = bind_numbered_tables(
        doc,
        processed_structures,
        sorted(authoritative_table_page_indices),
        _active_label_keys(active_cpds),
    )
    authoritative_table_bindings = _extract_authoritative_structure_table_sequence_bindings(
        processed_structures,
        pages_text,
        active_cpds,
        profile,
        ocr_line_map=cached_line_map,
        numbered_result=numbered_result,
    )
    if numbered_result.recognized:
        # Recognized original grid cells have one ownership path. Legacy
        # headings, row-sequence recovery and crop OCR must not compete for
        # structures on those pages, including withheld ambiguous cells.
        numbered_pages = set(numbered_result.recognized_pages)
        processed_structures = [
            struct for struct in processed_structures
            if int(struct["page_no"]) - 1 not in numbered_pages
        ]
        all_blocks = [
            block for block in all_blocks
            if int(block["page_no"]) - 1 not in numbered_pages
        ]
        pages_text = {page: text for page, text in pages_text.items() if page not in numbered_pages}
        cached_line_map = {page: lines for page, lines in cached_line_map.items() if page not in numbered_pages}
    from patent_sar_extractor.core.visible_structure_binding import (
        bind_visible_captions,
    )

    caption_pairs = bind_visible_captions(
        doc, processed_structures, _active_label_keys(active_cpds) - set(numbered_result.observed_keys),
    )
    caption_ids = set()
    for pair in caption_pairs:
        binding = _build_binding_from_structure(pair.structure, pair.label)
        binding.update({
            "binding_rule": "direct_structure_label", "visible_label": pair.label,
            "visible_label_candidates": [{"label": pair.label, "source": "pdf_clip"}],
            "visible_label_crop_source": "pdf_clip", "product_context_nearby": True,
            "product_context_distance": 0,
            "exact_caption_evidence": {"bbox": list(pair.label_bbox), "observations": pair.observations},
        })
        authoritative_table_bindings.append(binding)
        caption_ids.add(str(pair.structure["id"]))
    processed_structures = [s for s in processed_structures if str(s["id"]) not in caption_ids]
    spatial_bindings = [
        annotate_binding_accuracy(binding)
        for binding in _active_ordered_bindings(authoritative_table_bindings, active_cpds)
    ]
    if (
        active_cpds and len(spatial_bindings) == len(set(active_cpds))
        and len({b["structure_id"] for b in spatial_bindings}) == len(spatial_bindings)
        and all(b.get("accuracy_status") == "confirmed" and not b.get("fail_closed") for b in spatial_bindings)
    ):
        # Complete original-cell/caption evidence is final: generic repair has
        # no missing compound to resolve and must not compete with it.
        logger.info("   原文空间证据完整覆盖 %d 个活性化合物，跳过通用补漏链路", len(spatial_bindings))
        doc.close()
        return write_binding_result(
            out, patent_id=patent_id, bindings=spatial_bindings,
            detected_style="original_cell_and_caption", include_intermediates=include_intermediates,
            total_structures=len(structures), total_compound_blocks=len(all_blocks),
            table_pages=profile.get("authoritative_structure_table_pages", []) or [],
            table_covered_count=len(profile.get("authoritative_structure_table_cpds", []) or []),
            no_binding=[], unbound_pages=[],
        )
    all_blocks = _insert_missing_active_heading_blocks(all_blocks, active_cpds, pages_text=pages_text)
    active_focus_windows = _build_active_focus_windows(all_blocks, active_cpds)
    compound_sequence = _extract_chinese_compound_sequence(pages_text)
    product_structures = _product_structures_from_triplets(processed_structures)
    if (authoritative_table_bindings and not numbered_result.recognized) or (
        numbered_result.recognized and not processed_structures
    ):
        # A complete per-page I-NNN coordinate map is stronger than repeated
        # OCR of thousands of enlarged structure crops. Avoid the expensive
        # generic visual-candidate path and seed the proven table bindings.
        visible_label_cache: Dict[str, Dict] = {}
        labeled_bindings: List[Dict] = []
        visual_grid_bindings: List[Dict] = []
        seeded_bindings = list(authoritative_table_bindings)
        logger.info(
            "   📋 权威结构表坐标已确认，跳过冗余结构裁图OCR: %d bindings",
            len(seeded_bindings),
        )
    else:
        visible_label_cache = _load_visible_label_cache(output_dir, profile)
        visible_label_cache = _precompute_visible_label_cache(
            processed_structures,
            output_dir,
            profile,
            visible_label_cache,
            workers=bind_workers,
        )
        visible_label_cache = _refine_visible_label_cache_with_page_ocr(
            processed_structures,
            visible_label_cache,
            cached_line_map,
            output_dir,
            profile,
        )
        labeled_bindings = _extract_labeled_product_bindings(
            doc,
            processed_structures,
            pages_text,
            active_cpds=active_cpds,
            focus_windows=active_focus_windows,
            ocr_line_map=cached_line_map,
            visible_label_cache=visible_label_cache,
        )
        visual_grid_bindings = _extract_visual_grid_label_bindings(
            processed_structures,
            active_cpds,
            visible_label_cache,
        )
        seeded_bindings = _seed_singleton_active_compound_binding(
            list(authoritative_table_bindings),
            processed_structures,
            active_cpds,
            pages_text,
        )
    if visual_grid_bindings:
        seeded_bindings = _merge_binding_candidates(visual_grid_bindings, seeded_bindings, active_cpds=active_cpds)
    if labeled_bindings:
        # Numbered cells may cover only part of the activity set. Proven
        # labels from non-table pages still need to reach the same output.
        seeded_bindings = _merge_binding_candidates(seeded_bindings, labeled_bindings, active_cpds=active_cpds)
    if authoritative_table_bindings:
        goto_save = False
    elif labeled_bindings:
        logger.info(
            f"   ✅ OCR结构标签绑定完成: {len(seeded_bindings)} 个产物，继续用标题区间补漏"
        )
        goto_save = False
    elif seeded_bindings:
        logger.info(
            f"   ✅ 单一主化合物结构绑定完成: {len(seeded_bindings)} 个产物，继续用标题区间补漏"
        )
        goto_save = False
    elif compound_sequence and len(compound_sequence) == len(product_structures):
        logger.info(
            "   检测到中文实施例/化合物序列，按三结构反应行的右侧产物自动绑定: "
            f"{len(product_structures)} products"
        )
        final_bindings = []
        for idx, (compound_num, best_p) in enumerate(zip(compound_sequence, product_structures), start=1):
            cpd = f"实施例{idx}"
            final_bindings.append(_attach_structure_geometry({
                "cpd": cpd,
                "example_id": cpd,
                "example_num": idx,
                "compound_id": f"化合物{compound_num}",
                "compound_num": compound_num,
                "cpd_num": idx,
                "prefix": "实施例",
                "structure_id": best_p["id"],
                "page_no": best_p["page_no"],
                "structure_index": best_p["idx"],
                "struct_x0": best_p["x0"],
                "struct_y0": best_p["y0"],
                "image_path": best_p["image_path"],
                "candidates": 3,
                "binding_rule": "chinese_reaction_triplet_product",
            }, best_p))
        no_binding = []
        unbound_pages = []
        all_blocks = [
            {"cpd": b["cpd"], "cpd_num": b["cpd_num"], "prefix": b["prefix"]}
            for b in final_bindings
        ]
        detected_style = "heading_cn_reaction_triplet"
        logger.info(f"   ✅ 中文序列绑定完成: {len(final_bindings)} 个产物")
        # Skip coordinate heading algorithm below.
        goto_save = True
    elif not all_blocks and processed_structures:
        logger.warning(
            "   未识别到化合物标题；按结构图页序生成 Structure-* 兜底绑定"
        )
        final_bindings = []
        for idx, best_p in enumerate(
            sorted(processed_structures, key=lambda p: (p["page_no"], p["y0"], p["x0"])),
            start=1,
        ):
            cpd = f"Structure-{idx:04d}"
            final_bindings.append(_attach_structure_geometry({
                "cpd": cpd,
                "example_id": cpd,
                "example_num": idx,
                "cpd_num": idx,
                "prefix": "Structure",
                "structure_id": best_p["id"],
                "page_no": best_p["page_no"],
                "structure_index": best_p["idx"],
                "struct_x0": best_p["x0"],
                "struct_y0": best_p["y0"],
                "image_path": best_p["image_path"],
                "candidates": 1,
                "binding_rule": "scanned_pdf_structure_sequence_fallback",
            }, best_p))
        no_binding = []
        unbound_pages = []
        all_blocks = [
            {"cpd": b["cpd"], "cpd_num": b["cpd_num"], "prefix": b["prefix"]}
            for b in final_bindings
        ]
        detected_style = "structure_sequence_fallback"
        logger.info(f"   ✅ 结构序列兜底绑定完成: {len(final_bindings)} 个结构")
        goto_save = True
    else:
        goto_save = False
    
    # ── 6. V4.1 绑定算法 ──────────────────────────────────────
    logger.info("🎯 对每个化合物应用选择算法...")
    
    if not goto_save:
        final_bindings: List[Dict] = list(seeded_bindings)
        no_binding: List[str] = []
        unbound_pages: List[Dict] = []
        seeded_bases = {_binding_base_num(b) for b in seeded_bindings}
        seeded_bases.discard(None)
    else:
        seeded_bases = set()
    
    for i, block in enumerate([] if goto_save else all_blocks):
        cpd = block["cpd"]
        block_base = _base_cpd_num(cpd)
        if block_base in seeded_bases:
            continue
        cpd_page = block["page_no"]
        cpd_y0 = block["y0"]
        
        start_page = cpd_page
        start_y0 = cpd_y0
        end_page = None
        end_y0 = None
        
        if i < len(all_blocks) - 1:
            next_block = all_blocks[i + 1]
            if next_block["prefix"] == block["prefix"]:
                end_page = next_block["page_no"]
                end_y0 = next_block["y0"]
        
        # 筛选候选结构
        candidate_structs: List[Dict] = []
        for p in processed_structures:
            in_range = False
            
            if end_page is None:
                if p["page_no"] > start_page:
                    in_range = True
                elif p["page_no"] == start_page and p["y0"] >= start_y0:
                    in_range = True
            else:
                if start_page == end_page:
                    if p["page_no"] == start_page and start_y0 <= p["y0"] < end_y0:
                        in_range = True
                else:
                    if p["page_no"] == start_page and p["y0"] >= start_y0:
                        in_range = True
                    elif start_page < p["page_no"] < end_page:
                        in_range = True
                    elif p["page_no"] == end_page and p["y0"] < end_y0:
                        in_range = True
            
            if in_range:
                candidate_structs.append(p)
        
        # 回退策略：heading 下方无候选 → 搜索上方 → 搜索前页
        if not candidate_structs:
            bound_struct_ids = set(b["structure_id"] for b in final_bindings)
            
            # 同页上方
            above_structs = [
                p for p in processed_structures
                if p["page_no"] == start_page
                and p["y0"] < start_y0
                and p["id"] not in bound_struct_ids
            ]
            if above_structs:
                above_structs.sort(key=lambda x: x["y0"], reverse=True)
                candidate_structs = above_structs
                logger.info(
                    f"   🔄 {cpd} (p{cpd_page}): heading下方无候选，"
                    f"回退搜索上方 {len(candidate_structs)} 个结构"
                )
            
            # 前页底部
            if not candidate_structs and start_page > 1:
                prev_page = start_page - 1
                prev_structs = [
                    p for p in processed_structures
                    if p["page_no"] == prev_page
                    and p["id"] not in bound_struct_ids
                ]
                if prev_structs:
                    prev_structs.sort(key=lambda x: x["y0"], reverse=True)
                    candidate_structs = prev_structs[:3]
                    logger.info(
                        f"   🔄 {cpd} (p{cpd_page}): 回退搜索前页p{prev_page} "
                        f"{len(candidate_structs)} 个结构"
                    )

            # Scanned Chinese examples may have the title at the bottom of one
            # page and the product structure at the top of the next page.
            if not candidate_structs and block_base in {_base_cpd_num(c) for c in active_cpds}:
                for near_page in (start_page + 1, start_page + 2):
                    if block_base and not _page_has_product_context(pages_text, near_page, block_base):
                        continue
                    near_structs = [
                        p for p in processed_structures
                        if p["page_no"] == near_page
                        and p["id"] not in bound_struct_ids
                    ]
                    if not near_structs:
                        continue
                    near_structs.sort(key=lambda x: (x["y0"], x["x0"]))
                    candidate_structs = near_structs[:3]
                    logger.info(
                        f"   🔄 {cpd} (p{cpd_page}): 活性标题跨页，"
                        f"回退搜索后页p{near_page} {len(candidate_structs)} 个结构"
                    )
                    break
        
        # 应用选择算法
        if candidate_structs:
            best_p = _select_best_structure_v4(
                candidate_structs, config, heading_page=start_page
            )
            if best_p:
                final_bindings.append(_attach_structure_geometry({
                    "cpd": cpd,
                    "cpd_num": block["cpd_num"],
                    "prefix": block["prefix"],
                    "structure_id": best_p["id"],
                    "page_no": best_p["page_no"],
                    "structure_index": best_p["idx"],
                    "struct_x0": best_p["x0"],
                    "struct_y0": best_p["y0"],
                    "image_path": best_p["image_path"],
                    "candidates": len(candidate_structs),
                    "binding_rule": "heading_range_fallback",
                }, best_p))
            else:
                no_binding.append(cpd)
                unbound_pages.append({"cpd": cpd, "page": cpd_page, "reason": "no_best"})
        else:
            no_binding.append(cpd)
            unbound_pages.append({"cpd": cpd, "page": cpd_page, "reason": "no_candidates"})
            logger.warning(f"   ⚠️ {cpd} (p{cpd_page}): 无候选结构")
    
    logger.info(f"   ✅ 最终绑定了 {len(final_bindings)} 个化合物")
    if no_binding:
        logger.info(f"   ⚠️ {len(no_binding)} 个未绑定: {no_binding}")

    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    if seeded_bindings and not goto_save:
        before_merge = len(final_bindings)
        seeded_bindings = _annotate_bindings_with_visible_labels(seeded_bindings, visible_label_cache)
        fallback_bindings = [b for b in final_bindings if b not in seeded_bindings]
        final_bindings = _merge_binding_candidates(seeded_bindings, fallback_bindings, active_cpds=active_cpds)
        logger.info(
            f"   🔗 OCR强绑定 + heading补漏合并: {before_merge} → {len(final_bindings)} 个化合物"
        )

    # ── 6b. 去重：对同名化合物添加后缀 ─────────────────────────
    cpd_counts: Dict[str, int] = {}
    for binding in final_bindings:
        cpd = binding["cpd"]
        cpd_counts[cpd] = cpd_counts.get(cpd, 0) + 1

    cpd_suffix: Dict[str, int] = {}
    for binding in final_bindings:
        cpd = binding["cpd"]
        if cpd_counts[cpd] > 1:
            cpd_suffix[cpd] = cpd_suffix.get(cpd, 0) + 1
            suffix = cpd_suffix[cpd]
            # Update all name fields
            binding["cpd"] = f"{cpd}-{suffix}"
            binding["example_id"] = f"{binding.get('example_id', cpd)}-{suffix}"

    renamed = sum(1 for v in cpd_counts.values() if v > 1)
    if renamed:
        logger.info(f"   🏷 对 {renamed} 个重复化合物名添加后缀: "
                    f"{[f'{k}({v}x)' for k, v in cpd_counts.items() if v > 1]}")

    # ── 7. 过滤 Intermediate ──────────────────────────────────
    if not include_intermediates:
        final_bindings = _filter_examples_only(final_bindings)
        all_blocks = [b for b in all_blocks if not _is_intermediate(b)]

    before_activity_gate = len(final_bindings)
    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    final_bindings = _active_ordered_bindings(final_bindings, active_cpds)
    if active_cpds:
        logger.info(
            f"   🎯 活性编号主导输出: {before_activity_gate} → {len(final_bindings)}，"
            "按活性表编号顺序排序并剔除非活性绑定"
        )
    active_candidate_snapshot = list(final_bindings)

    final_bindings = _repair_missing_structure_table_bindings(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        ocr_line_map=cached_line_map,
    )
    final_bindings = _active_ordered_bindings(final_bindings, active_cpds)

    fallback_rules_for_repair = {
        "product_section_context",
        "heading_range_fallback",
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "paired_route_product_row_order",
        "triplet_split_row_structure_order",
        "split_reaction_product_label",
        "ocr_numeric_structure_label",
        "ocr_bare_numeric_product_label",
    }
    current_by_base = {
        _binding_base_num(binding): binding
        for binding in final_bindings
        if _binding_base_num(binding) is not None
    }
    target_repair_bases: set[int] = set()
    for cpd in active_cpds:
        base = _base_cpd_num(cpd)
        if base is None:
            continue
        current = current_by_base.get(base)
        current_rule = str(current.get("binding_rule") or "") if current else ""
        if (
            current is None
            or current_rule in fallback_rules_for_repair
            or _is_weak_direct_visual_binding(current)
        ):
            target_repair_bases.add(base)

    visual_module_bindings = _extract_visual_module_bindings(
        doc,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache=visible_label_cache,
        target_bases=target_repair_bases,
        ocr_line_map=cached_line_map,
    )
    if visual_module_bindings:
        before_visual_repair = len(final_bindings)
        final_bindings = _repair_fallback_bindings_with_visual_modules(
            final_bindings,
            visual_module_bindings,
            active_cpds,
            output_dir=output_dir,
        )
        logger.info(
            f"   👁 完整结构模块视觉修复: {before_visual_repair} → {len(final_bindings)}，"
            "仅覆盖缺失或文本/位置fallback绑定"
        )

    final_bindings = _fill_missing_active_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _repair_conflicting_bindings_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    final_bindings = _replace_with_exact_visible_table_labels(
        final_bindings,
        processed_structures,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _restore_safe_missing_active_bindings(
        final_bindings,
        active_candidate_snapshot,
        processed_structures,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_route_title_rows(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    final_bindings = _confirm_final_bindings_with_visible_cache(
        final_bindings,
        processed_structures,
        pages_text,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_route_title_rows(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    final_bindings = _dedupe_final_bindings_by_structure(
        final_bindings,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _fill_missing_active_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
    )
    final_bindings = _restore_safe_missing_active_bindings(
        final_bindings,
        active_candidate_snapshot,
        processed_structures,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _drop_unsafe_final_fragment_bindings(
        final_bindings,
        active_cpds,
        visible_label_cache,
        processed_structures,
    )
    final_bindings = _fill_missing_active_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
    )
    final_bindings = _restore_safe_missing_active_bindings(
        final_bindings,
        active_candidate_snapshot,
        processed_structures,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_route_title_rows(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    final_bindings = _repair_same_row_fragment_bindings_to_right_product(
        final_bindings,
        processed_structures,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _drop_unsafe_final_fragment_bindings(
        final_bindings,
        active_cpds,
        visible_label_cache,
        processed_structures,
    )
    final_bindings = _fill_missing_active_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_route_title_rows(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    final_bindings = _repair_weak_bindings_with_expanded_strict_fragments(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
        str(out),
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    final_bindings = _merge_split_visible_label_fragments(
        final_bindings,
        processed_structures,
        active_cpds,
        visible_label_cache,
        str(out),
    )
    final_bindings = _replace_with_expanded_strict_crops(final_bindings, str(out))
    final_bindings = _arbitrate_with_clean_standalone_visual_products(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
        cached_line_map,
    )
    if visual_grid_bindings:
        before_visual_grid_restore = len(final_bindings)
        final_bindings = _merge_binding_candidates(
            visual_grid_bindings,
            final_bindings,
            active_cpds=active_cpds,
        )
        logger.info(
            "   👁 视觉网格图下编号最终保护合并: %d → %d",
            before_visual_grid_restore,
            len(final_bindings),
        )
    if authoritative_table_bindings:
        before_authoritative_restore = len(final_bindings)
        final_bindings = _merge_binding_candidates(
            authoritative_table_bindings,
            final_bindings,
            active_cpds=active_cpds,
        )
        logger.info(
            "   📋 权威结构表跨页全局顺序最终保护合并: %d → %d",
            before_authoritative_restore,
            len(final_bindings),
        )
    final_bindings = _enforce_authoritative_structure_table_source(final_bindings, profile)
    if numbered_result.recognized:
        # Do not let late generic repair promote a competing cell or a
        # different source for an observed (even unsegmented/ambiguous) ID.
        final_bindings = [
            binding for binding in final_bindings
            if int(binding.get("page_no") or 0) - 1 not in numbered_result.recognized_pages
            and _binding_label_key(binding) not in numbered_result.observed_keys
        ]
        final_bindings = _active_ordered_bindings(
            [*authoritative_table_bindings, *final_bindings], active_cpds,
        )
    final_bindings = _annotate_bindings_with_visible_labels(final_bindings, visible_label_cache)
    final_bindings = _annotate_isotope_label_evidence(final_bindings, cached_line_map)
    final_bindings = [annotate_binding_accuracy(binding) for binding in final_bindings]
    keep_review_bindings = bool(profile.get("allow_review_bindings"))
    final_bindings = _drop_fail_closed_bindings(
        final_bindings,
        active_cpds,
        keep_review_bindings=keep_review_bindings,
    )
    final_bindings = [annotate_binding_accuracy(binding) for binding in final_bindings]
    # All layouts publish through the same writer and strict downstream gate.
    doc.close()
    return write_binding_result(
        out, patent_id=patent_id, bindings=final_bindings,
        detected_style=detected_style, include_intermediates=include_intermediates,
        total_structures=len(structures), total_compound_blocks=len(all_blocks),
        table_pages=profile.get("authoritative_structure_table_pages", []) or [],
        table_covered_count=len(profile.get("authoritative_structure_table_cpds", []) or []),
        no_binding=no_binding, unbound_pages=unbound_pages,
    )
