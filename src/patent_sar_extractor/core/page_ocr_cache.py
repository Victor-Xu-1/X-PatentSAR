"""
Shared page OCR cache utilities.

This keeps page-level OCR text and line coordinates consistent across
classification, activity extraction, and structure-location/binding steps.
"""

from __future__ import annotations

import json
import base64
import hashlib
import logging
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
import tempfile

import fitz
from PIL import Image

from patent_sar_extractor.contracts import (
    PAGE_OCR_CACHE_SCHEMA,
    PAGE_OCR_CACHE_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.artifact_io import write_json_atomic

logger = logging.getLogger(__name__)
_OCR_ENGINE = None
_PADDLEX_OCR_URL_RESOLVED: str | None = None
_PADDLEX_OCR_PROBED = False
_PDF_HASH_CACHE: dict[str, tuple[int, int, str]] = {}
_THREAD_OCR = threading.local()


def _paddlex_ocr_url() -> str:
    """Return a PaddleX OCR endpoint validated with the real image payload."""
    global _PADDLEX_OCR_URL_RESOLVED, _PADDLEX_OCR_PROBED
    configured = os.environ.get("PATENTSAR_PADDLEX_OCR_URL", "").strip()
    if configured.lower() in {"off", "none", "0"}:
        return ""
    if _PADDLEX_OCR_PROBED:
        return _PADDLEX_OCR_URL_RESOLVED or ""
    _PADDLEX_OCR_PROBED = True
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    candidates.extend([
        "http://127.0.0.1:8090/ocr",
        "http://127.0.0.1:8080/ocr",
    ])
    seen: set[str] = set()
    for url in candidates:
        url = str(url or "").strip()
        if not url or url.lower() in seen:
            continue
        seen.add(url.lower())
        if _paddlex_endpoint_accepts_payload(url):
            _PADDLEX_OCR_URL_RESOLVED = url
            return url
    _PADDLEX_OCR_URL_RESOLVED = ""
    return ""


def _paddlex_request_payload_from_png(png_bytes: bytes) -> dict:
    return {
        "file": base64.b64encode(png_bytes).decode("ascii"),
        "fileType": 1,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useTextlineOrientation": False,
        "textRecScoreThresh": 0.0,
        "visualize": False,
    }


def _paddlex_pruned_result(data: dict) -> dict:
    result = (data or {}).get("result") or {}
    ocr_results = result.get("ocrResults") or []
    if not ocr_results:
        return {}
    pruned = (ocr_results[0] or {}).get("prunedResult") or {}
    return pruned if isinstance(pruned, dict) else {}


def _paddlex_endpoint_accepts_payload(url: str, timeout: float = 2.5) -> bool:
    try:
        import requests  # type: ignore
    except Exception:
        return False
    try:
        buf = BytesIO()
        img = Image.new("RGB", (120, 48), "white")
        try:
            from PIL import ImageDraw
            ImageDraw.Draw(img).text((10, 14), "123", fill="black")
        except Exception:
            pass
        img.save(buf, format="PNG")
        session = requests.Session()
        session.trust_env = False
        response = session.post(
            url,
            json=_paddlex_request_payload_from_png(buf.getvalue()),
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        result = (data or {}).get("result") or {}
        if "ocrResults" not in result or not isinstance(result.get("ocrResults"), list):
            return False
        pruned = _paddlex_pruned_result(data)
        if not pruned and result.get("ocrResults") == []:
            return True
        return isinstance(pruned.get("rec_texts", []), list) and isinstance(pruned.get("rec_boxes", []), list)
    except Exception:
        return False


def _allow_tesseract_fallback() -> bool:
    return os.environ.get("PATENTSAR_ALLOW_TESSERACT_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}


def _tesseract_lang() -> str:
    return os.environ.get("PATENTSAR_TESSERACT_LANG", "chi_sim+eng")


def _paddlex_payload_from_image(img: Image.Image, timeout: float = 20.0) -> tuple[list[str], list[list[float]]]:
    url = _paddlex_ocr_url()
    if not url or url.lower() in {"off", "none", "0"}:
        return [], []
    try:
        import requests  # type: ignore
    except Exception:
        return [], []
    try:
        buf = BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        session = requests.Session()
        session.trust_env = False
        response = session.post(
            url,
            json=_paddlex_request_payload_from_png(buf.getvalue()),
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        pruned = _paddlex_pruned_result(data)
        texts = [str(text or "").strip() for text in (pruned.get("rec_texts") or [])]
        boxes = pruned.get("rec_boxes") or []
        pairs = [(text, box) for text, box in zip(texts, boxes) if text]
        return [text for text, _box in pairs], [box for _text, box in pairs]
    except Exception:
        return [], []


def _build_ocr_engine():
    if _paddlex_ocr_url().lower() not in {"", "off", "none", "0"}:
        return ("paddlex", None)
    try:
        from rapidocr_onnxruntime import RapidOCR

        # ONNX defaults to a large per-session pool on many-core hosts. Four
        # page workers then multiply three SDK pools, wasting CPU and memory.
        return ("rapidocr", RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1))
    except Exception:
        if not _allow_tesseract_fallback():
            return False
        try:
            import pytesseract  # type: ignore

            return ("tesseract", pytesseract)
        except Exception:
            tesseract_bin = shutil.which("tesseract")
            if tesseract_bin:
                return ("tesseract_cli", tesseract_bin)
    return False


def get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    _OCR_ENGINE = _build_ocr_engine()
    return _OCR_ENGINE


def page_text(page, ocr_engine=None, min_native_chars: int = 40) -> str:
    text = page.get_text("text").strip()
    if len(text) > min_native_chars:
        return text
    engine = ocr_engine if ocr_engine is not None else get_ocr_engine()
    if not engine:
        return text
    import numpy as np

    pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
    img = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
    engine_name, backend = engine
    if engine_name == "paddlex":
        texts, _boxes = _paddlex_payload_from_image(img)
        if texts:
            return " ".join(texts)
        return text
    if engine_name == "rapidocr":
        result, _ = backend(np.array(img))
        if result:
            return " ".join(str(item[1]) for item in result)
        return text
    if engine_name == "tesseract":
        ocr_text = backend.image_to_string(img, lang=_tesseract_lang())
        return str(ocr_text or "").strip() or text
    if engine_name == "tesseract_cli":
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            img.save(tmp.name)
            proc = subprocess.run(
                [backend, tmp.name, "stdout", "-l", _tesseract_lang(), "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0 and str(proc.stdout or "").strip():
                return proc.stdout.strip()
    return text


def page_ocr_lines(page, ocr_engine=None) -> list[dict]:
    engine = ocr_engine if ocr_engine is not None else get_ocr_engine()
    if not engine:
        return []
    import numpy as np

    dpi = 150
    scale = 72.0 / dpi
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
    img = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
    engine_name, backend = engine
    if engine_name == "paddlex":
        texts, boxes = _paddlex_payload_from_image(img)
        lines = []
        for text, box in zip(texts, boxes):
            if not text or not isinstance(box, list) or len(box) < 4:
                continue
            try:
                y0_pdf = float(box[1]) * scale
            except Exception:
                continue
            lines.append({"y0": round(float(y0_pdf), 2), "text": text})
        lines.sort(key=lambda item: item["y0"])
        return lines
    if engine_name != "rapidocr":
        return []
    result, _ = backend(np.array(img))
    lines = []
    for item in result or []:
        text = str(item[1]).strip()
        if not text:
            continue
        box = item[0]
        y0_pdf = min(p[1] for p in box) * scale
        lines.append({"y0": round(float(y0_pdf), 2), "text": text})
    lines.sort(key=lambda item: item["y0"])
    return lines


def _page_payload(page, ocr_engine=None, min_native_chars: int = 40, native_text: str | None = None) -> tuple[str, list[dict]]:
    """Read one coherent text/coordinate observation, with lazy OCR startup."""
    native = page.get_text("text").strip() if native_text is None else native_text
    if len(native) >= min_native_chars:
        return native, []
    engine = ocr_engine if ocr_engine is not None else get_ocr_engine()
    if not engine:
        return native, []
    if engine[0] in {"rapidocr", "paddlex"}:
        lines = page_ocr_lines(page, ocr_engine=engine)
        return " ".join(line["text"] for line in lines) or native, lines
    # Explicitly enabled text-only backends do not supply coordinate evidence.
    return page_text(page, ocr_engine=engine, min_native_chars=min_native_chars), []


def _extract_page_payload(pdf_path: str, page_idx: int, min_native_chars: int = 40) -> tuple[int, str, list[dict]]:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_idx]
        native_text = page.get_text("text").strip()
        if len(native_text) >= min_native_chars:
            return page_idx, native_text, []
        if not getattr(_THREAD_OCR, "initialized", False):
            _THREAD_OCR.engine = _build_ocr_engine()
            _THREAD_OCR.initialized = True
        engine = getattr(_THREAD_OCR, "engine", None)
        text, lines = _page_payload(page, engine, min_native_chars, native_text)
        return page_idx, text, lines
    finally:
        doc.close()


def _pdf_sha256(pdf_path: str) -> str:
    path = os.path.abspath(pdf_path)
    stat = os.stat(path)
    cached = _PDF_HASH_CACHE.get(path)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _PDF_HASH_CACHE[path] = (stat.st_mtime_ns, stat.st_size, value)
    return value


def build_cache_metadata(pdf_path: str, total_pages: int | None = None) -> dict:
    from patent_sar_extractor.contracts import PAGE_OCR_OBSERVATION_SCHEMA, PAGE_OCR_OBSERVATION_VERSION
    if total_pages is None:
        doc = fitz.open(pdf_path)
        try:
            total_pages = len(doc)
        finally:
            doc.close()
    stat = os.stat(pdf_path)
    return {
        **artifact_identity(PAGE_OCR_CACHE_SCHEMA, PAGE_OCR_CACHE_SCHEMA_VERSION),
        "observation_contract": {"name": PAGE_OCR_OBSERVATION_SCHEMA, "version": PAGE_OCR_OBSERVATION_VERSION},
        "pdf_sha256": _pdf_sha256(pdf_path),
        "pdf_size": int(stat.st_size),
        "page_count": int(total_pages),
    }


def cache_matches_pdf(cache: dict, pdf_path: str, total_pages: int | None = None) -> bool:
    from patent_sar_extractor.contracts import PAGE_OCR_COMPATIBLE_RULESETS
    if not isinstance(cache, dict):
        return False
    metadata = cache.get("metadata")
    if not isinstance(metadata, dict):
        return False
    if not isinstance(metadata.get("page_count"), int) or isinstance(metadata.get("page_count"), bool):
        return False
    try:
        expected = build_cache_metadata(pdf_path, total_pages)
    except Exception:
        return False
    identity_matches = all(
        metadata.get(key) == expected[key]
        for key in ("schema", "product", "pipeline_contract")
    )
    raw_rule = metadata.get("ruleset") or {}
    compatible_rule = isinstance(raw_rule, dict) and (raw_rule.get("name"), raw_rule.get("version")) in PAGE_OCR_COMPATIBLE_RULESETS
    observation = metadata.get("observation_contract")
    compatible_observation = observation == expected["observation_contract"] or (
        observation is None and isinstance(raw_rule, dict) and raw_rule.get("version") == "2.0.1"
    )
    return (
        identity_matches
        and compatible_rule and compatible_observation
        and metadata.get("pdf_sha256") == expected["pdf_sha256"]
        and int(metadata.get("page_count", -1)) == expected["page_count"]
    )


def inherit_page_ocr_cache(source: str, destination: str, pdf_path: str) -> bool:
    """Seed only absent raw-cache state after exact PDF/observation checks.

    Derived classifications, activities, bindings and QA are never inherited
    here. The source file is immutable and the pipeline reclassifies with the
    current rules, preserving the original failed run as an audit unit.
    """
    if Path(destination).exists():
        return False
    cache = load_page_ocr_cache(source)
    if not cache_matches_pdf(cache, pdf_path):
        raise ValueError("OCR observation cache does not match this PDF or supported observation contract")
    if not isinstance(cache.get("page_texts"), dict) or not isinstance(cache.get("ocr_line_map"), dict):
        raise ValueError("OCR observation cache collections are malformed")
    save_page_ocr_cache(destination, cache)
    return True


def build_page_ocr_cache(pdf_path: str, page_indices: list[int], workers: int = 1, min_native_chars: int = 40) -> dict:
    doc = fitz.open(pdf_path)
    try:
        total_pages = len(doc)
    finally:
        doc.close()
    cache = {
        "metadata": build_cache_metadata(pdf_path, total_pages),
        "page_texts": {},
        "ocr_line_map": {},
    }
    if not page_indices:
        return cache

    unique_indices = sorted(set(int(i) for i in page_indices if int(i) >= 0))
    workers = max(1, int(workers or 1))

    if workers <= 1 or len(unique_indices) <= 1:
        doc = fitz.open(pdf_path)
        try:
            for idx in unique_indices:
                if idx >= len(doc):
                    continue
                page = doc[idx]
                text, lines = _page_payload(page, min_native_chars=min_native_chars)
                cache["page_texts"][str(idx)] = text
                if lines:
                    cache["ocr_line_map"][str(idx)] = lines
        finally:
            doc.close()
        return cache

    max_workers = min(workers, len(unique_indices))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_extract_page_payload, pdf_path, idx, min_native_chars): idx
            for idx in unique_indices
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                resolved_idx, text, lines = future.result()
            except Exception:
                continue
            cache["page_texts"][str(resolved_idx)] = text
            if lines:
                cache["ocr_line_map"][str(resolved_idx)] = lines
    return cache


def update_page_ocr_cache(
    pdf_path: str,
    page_indices: list[int],
    cache_path: str,
    workers: int = 1,
    min_native_chars: int = 40,
    flush_every: int = 10,
    force: bool = False,
    retry_empty: bool = True,
) -> dict:
    """Fill missing page OCR cache entries with progress and partial flushes."""
    cache = load_page_ocr_cache(cache_path)
    doc = fitz.open(pdf_path)
    try:
        total_pages = len(doc)
    finally:
        doc.close()
    expected_metadata = build_cache_metadata(pdf_path, total_pages)
    if force or not cache_matches_pdf(cache, pdf_path, total_pages):
        if cache.get("page_texts") or cache.get("metadata"):
            logger.info("Discarding page OCR cache for a different PDF: %s", cache_path)
        cache = {
            "metadata": expected_metadata,
            "page_texts": {},
            "ocr_line_map": {},
        }
    else:
        cache["metadata"] = expected_metadata
        cache.setdefault("page_texts", {})
        cache.setdefault("ocr_line_map", {})
    unique_indices = [
        idx for idx in sorted(set(int(i) for i in page_indices if int(i) >= 0))
        if idx < total_pages
    ]
    missing = [
        idx for idx in unique_indices
        if str(idx) not in cache.get("page_texts", {})
        or not str(cache.get("page_texts", {}).get(str(idx), "")).strip()
    ]
    if not missing:
        logger.info("Shared page OCR cache hit: %s/%s pages", len(unique_indices), len(unique_indices))
        return cache

    workers = max(1, int(workers or 1))
    flush_every = max(1, int(flush_every or 1))
    logger.info(
        "Building shared page OCR cache: missing=%d/%d, workers=%d, path=%s",
        len(missing),
        len(unique_indices),
        workers,
        cache_path,
    )

    completed = 0
    if workers <= 1 or len(missing) <= 1:
        doc = fitz.open(pdf_path)
        try:
            for idx in missing:
                page = doc[idx]
                text, lines = _page_payload(page, min_native_chars=min_native_chars)
                cache["page_texts"][str(idx)] = text
                if lines:
                    cache["ocr_line_map"][str(idx)] = lines
                completed += 1
                if completed % flush_every == 0 or completed == len(missing):
                    save_page_ocr_cache(cache_path, cache)
                    logger.info("Shared page OCR cache progress: %d/%d missing pages", completed, len(missing))
        finally:
            doc.close()
        if retry_empty:
            empty_after = [
                idx for idx in unique_indices
                if not str(cache.get("page_texts", {}).get(str(idx), "")).strip()
            ]
            if empty_after:
                logger.info("Retrying empty shared page OCR cache entries: %d pages", len(empty_after))
                return update_page_ocr_cache(
                    pdf_path,
                    empty_after,
                    cache_path,
                    workers=1,
                    min_native_chars=min_native_chars,
                    flush_every=flush_every,
                    force=False,
                    retry_empty=False,
                )
        return cache

    max_workers = min(workers, len(missing))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_extract_page_payload, pdf_path, idx, min_native_chars): idx
            for idx in missing
        }
        for future in as_completed(future_map):
            try:
                resolved_idx, text, lines = future.result()
            except Exception as exc:
                logger.warning("Page OCR cache extraction failed: %s", exc)
                completed += 1
                continue
            cache["page_texts"][str(resolved_idx)] = text
            if lines:
                cache["ocr_line_map"][str(resolved_idx)] = lines
            completed += 1
            if completed % flush_every == 0 or completed == len(missing):
                save_page_ocr_cache(cache_path, cache)
                logger.info("Shared page OCR cache progress: %d/%d missing pages", completed, len(missing))
    if retry_empty:
        empty_after = [
            idx for idx in unique_indices
            if not str(cache.get("page_texts", {}).get(str(idx), "")).strip()
        ]
        if empty_after:
            logger.info("Retrying empty shared page OCR cache entries: %d pages", len(empty_after))
            return update_page_ocr_cache(
                pdf_path,
                empty_after,
                cache_path,
                workers=1,
                min_native_chars=min_native_chars,
                flush_every=flush_every,
                force=False,
                retry_empty=False,
            )
    return cache


def load_page_ocr_cache(path: str) -> dict:
    if not path or not Path(path).is_file():
        return {"metadata": {}, "page_texts": {}, "ocr_line_map": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "metadata": data.get("metadata", {}) if isinstance(data, dict) else {},
        "page_texts": data.get("page_texts", {}) if isinstance(data, dict) else {},
        "ocr_line_map": data.get("ocr_line_map", {}) if isinstance(data, dict) else {},
    }


def save_page_ocr_cache(path: str, cache: dict) -> None:
    write_json_atomic(path, cache)
