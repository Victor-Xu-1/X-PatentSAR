"""Original PDF/OCR observations and one OCR runtime availability state."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
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

logger = logging.getLogger(__name__)


try:
    import fitz

    PYMUPDF_AVAILABLE = True
except ImportError:
    fitz = None
    PYMUPDF_AVAILABLE = False


_PADDLEX_OCR_AVAILABLE: Optional[bool] = None


def _paddlex_ocr_url() -> str:
    return _shared_paddlex_ocr_url()


def _allow_tesseract_fallback() -> bool:
    return os.environ.get("WIPO_ALLOW_TESSERACT_FALLBACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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


def _extract_binder_page_lines(
    pdf_path: str, page_idx: int
) -> tuple[int, List[Tuple[float, str]]]:
    doc = fitz.open(pdf_path)
    try:
        return page_idx, _get_ocr_line_coords(doc[page_idx]) or []
    finally:
        doc.close()


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
            return [
                (float(item.get("y0", 0)), str(item.get("text", "")))
                for item in lines
                if str(item.get("text", "")).strip()
            ]
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
            line_parts.setdefault((block_num, par_num, line_num), []).append(
                (top, left, text)
            )

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


def _get_ocr_word_coords(
    page, cache: Optional[Dict[int, List[Dict]]] = None
) -> List[Dict]:
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
                words.append(
                    {
                        "text": value,
                        "x": ((left + right) / 2.0) * scale,
                        "y": ((top + bottom) / 2.0) * scale,
                    }
                )
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
            words.append(
                {
                    "text": text,
                    "x": (sum(xs) / len(xs)) * scale,
                    "y": (sum(ys) / len(ys)) * scale,
                }
            )
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
            left, top, width, height = (
                int(cols[6]),
                int(cols[7]),
                int(cols[8]),
                int(cols[9]),
            )
            words.append(
                {
                    "text": text,
                    "x": (left + width / 2) * scale,
                    "y": (top + height / 2) * scale,
                }
            )
        if cache is not None and page_idx >= 0:
            cache[page_idx] = words
        return words
    except Exception as e:
        logger.debug(f"OCR word coords failed: {e}")
        if cache is not None and page_idx >= 0:
            cache[page_idx] = []
        return []


def _paddlex_ocr_texts_batch(
    images: List[Any], workers: int = 4, timeout: float = 12.0
) -> List[List[str]]:
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


def paddlex_available() -> Optional[bool]:
    """Read the single OCR runtime state without copying mutable globals."""
    return _PADDLEX_OCR_AVAILABLE
