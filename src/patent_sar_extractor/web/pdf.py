"""Streamed PDF ingestion and serialized, bounded real PyMuPDF rendering."""

from __future__ import annotations

import hashlib
import io
import math
import os
import re
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, UnidentifiedImageError
from starlette.requests import Request

from .activity_focus import FocusEvidence, rendered_focus
from .errors import WebError
from .files import SafeFiles, private_directory
from .models import Annotation, Compound, Page, SourceMode

MAX_PDF_BYTES = 128 * 1024 * 1024
MAX_PDF_PAGES = 10000
MAX_PIXELS = 12_000_000
_PDF_LOCK = threading.RLock()


@dataclass
class UploadedPDF:
    path: Path
    sha256: str
    page_count: int


def filename_title(filename: str) -> tuple[str, str]:
    if (
        not filename
        or len(filename) > 200
        or "/" in filename
        or "\\" in filename
        or any(ord(c) < 32 for c in filename)
    ):
        raise WebError(
            400, "invalid_filename", "Provide a plain PDF filename, not a path."
        )
    if not filename.lower().endswith(".pdf"):
        raise WebError(400, "invalid_filename", "Filename must end in .pdf.")
    stem = filename[:-4]
    patent = re.search(r"(?:WO|CN|US|EP)\d{6,}", stem, re.IGNORECASE)
    return stem, patent.group(0).upper() if patent else ""


def validate_pdf(path: Path) -> int:
    with _PDF_LOCK:
        try:
            with fitz.open(path) as document:
                if not document.is_pdf or document.needs_pass or document.is_encrypted:
                    raise WebError(
                        422,
                        "invalid_pdf",
                        "Encrypted or non-PDF documents are not supported.",
                    )
                if not 1 <= document.page_count <= MAX_PDF_PAGES:
                    raise WebError(
                        413,
                        "pdf_page_limit",
                        "PDF page count exceeds the supported limit.",
                    )
                page = document[0]
                if page.rect.is_empty or max(page.rect.width, page.rect.height) > 20000:
                    raise WebError(
                        422, "invalid_pdf", "PDF has invalid page dimensions."
                    )
                return document.page_count
        except (
            fitz.FileDataError,
            fitz.EmptyFileError,
            RuntimeError,
            ValueError,
        ) as exc:
            raise WebError(422, "invalid_pdf", "PDF could not be parsed.") from exc


async def stream_upload(
    request: Request, upload_root: Path, *, max_bytes: int
) -> UploadedPDF:
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/pdf"
    ):
        raise WebError(
            400, "content_type", "Upload must have Content-Type application/pdf."
        )
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isdecimal():
            raise WebError(400, "content_length", "Content-Length is invalid.")
        if int(length) > max_bytes:
            raise WebError(413, "upload_limit", "PDF exceeds the upload limit.")
    private_directory(upload_root)
    fd, raw_path = tempfile.mkstemp(prefix="upload-", suffix=".pdf", dir=upload_root)
    path = Path(raw_path)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > max_bytes:
                    raise WebError(413, "upload_limit", "PDF exceeds the upload limit.")
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if not size:
            raise WebError(422, "invalid_pdf", "Upload is empty.")
        # The upload itself is streamed to disk; parsing never buffers the body.
        from starlette.concurrency import run_in_threadpool

        count = await run_in_threadpool(validate_pdf, path)
        return UploadedPDF(path, digest.hexdigest(), count)
    except BaseException:
        path.unlink(missing_ok=True)  # Only the new, exclusive incomplete upload.
        raise


def copy_original(source: str | Path, upload_root: Path) -> UploadedPDF:
    """CLI-only copy of an explicit operator-chosen original; never an HTTP path."""
    source = Path(source).expanduser().absolute()
    private_directory(upload_root)
    fd, raw_path = tempfile.mkstemp(prefix="original-", suffix=".pdf", dir=upload_root)
    destination = Path(raw_path)
    digest = hashlib.sha256()
    total = 0
    try:
        with (
            os.fdopen(fd, "wb") as output,
            SafeFiles(source.parent).open(
                source.name, max_bytes=MAX_PDF_BYTES
            ) as stream,
        ):
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise WebError(
                        413, "upload_limit", "Original PDF exceeds the upload limit."
                    )
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        return UploadedPDF(destination, digest.hexdigest(), validate_pdf(destination))
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


@contextmanager
def open_pdf(state_root: Path, project: dict[str, Any]) -> Iterator[fitz.Document]:
    if not project.get("pdf_rel"):
        raise WebError(
            404, "pdf_unavailable", "The verified original PDF is not attached."
        )
    with _PDF_LOCK:
        content = SafeFiles(state_root).read(
            project["pdf_rel"], max_bytes=MAX_PDF_BYTES
        )
        if hashlib.sha256(content).hexdigest() != project["sha256"]:
            raise WebError(
                409,
                "source_changed",
                "Original PDF fingerprint no longer matches the workspace.",
            )
        try:
            document = fitz.open(stream=content, filetype="pdf")
        except (RuntimeError, ValueError) as exc:
            raise WebError(
                422, "invalid_pdf", "Original PDF could not be parsed."
            ) from exc
        try:
            yield document
        finally:
            document.close()


def rendered_box(
    page: fitz.Page, bbox: list[float], geometry_space: str
) -> list[float] | None:
    rectangle = fitz.Rect(bbox)
    if geometry_space == "unrotated":
        rectangle = rectangle * page.rotation_matrix
    rectangle &= page.rect
    if rectangle.is_empty or rectangle.is_infinite:
        return None
    return [float(x) for x in rectangle]


def page_info(
    state_root: Path,
    project: dict[str, Any],
    number: int,
    compounds: list[dict[str, Any]],
    *,
    historical_text: str = "",
    activity_focus: FocusEvidence | None = None,
) -> Page:
    if not 1 <= number <= project["page_count"]:
        raise WebError(
            404, "page_not_found", "Page number is outside the original document."
        )
    if not project.get("pdf_rel"):
        return Page(
            page=number,
            page_count=project["page_count"],
            width=None,
            height=None,
            image_url=None,
            text=historical_text,
            source_mode="historical" if historical_text else "unavailable",
            annotations=[],
        )
    with open_pdf(state_root, project) as document:
        page = document[number - 1]
        text = page.get_text("text")
        if len(text) > 200000:
            raise WebError(
                413, "page_text_limit", "Page text exceeds its response limit."
            )
        annotations = []
        for item in compounds:
            dto = Compound.model_validate_json(item["payload"])
            if dto.source.page != number or not dto.source.bbox:
                continue
            bbox = rendered_box(page, dto.source.bbox, item["geometry_space"])
            if bbox:
                annotations.append(
                    Annotation(
                        compound_id=dto.id,
                        bbox=bbox,
                        kind="structure",
                        verified=dto.confidence.level == "high",
                    )
                )
        if len(annotations) > 5000:
            raise WebError(413, "annotation_limit", "Page has too many annotations.")
        source_mode: SourceMode = (
            "native"
            if text.strip()
            else "ocr"
            if historical_text and not project["historical"]
            else "historical"
            if historical_text
            else "unavailable"
        )
        return Page(
            page=number,
            page_count=document.page_count,
            width=page.rect.width,
            height=page.rect.height,
            image_url=f"/api/v1/projects/{project['id']}/pages/{number}/image",
            text=text if text.strip() else historical_text,
            source_mode=source_mode,
            annotations=annotations,
            activity_focus=rendered_focus(page, activity_focus)
            if activity_focus
            else None,
        )


def render_page(
    state_root: Path,
    project: dict[str, Any],
    number: int,
    scale: float,
    *,
    bbox: list[float] | None = None,
    geometry_space: str = "rendered",
) -> bytes:
    if not math.isfinite(scale) or not 0.5 <= scale <= 3:
        raise WebError(422, "render_scale", "Scale must be between 0.5 and 3.")
    if not 1 <= number <= project["page_count"]:
        raise WebError(
            404, "page_not_found", "Page number is outside the original document."
        )
    with open_pdf(state_root, project) as document:
        page = document[number - 1]
        clip = page.rect
        if bbox:
            bounds = rendered_box(page, bbox, geometry_space)
            if bounds is None:
                raise WebError(
                    404,
                    "crop_unavailable",
                    "Structure geometry does not intersect the original page.",
                )
            clip = fitz.Rect(bounds)
        if math.ceil(clip.width * scale) * math.ceil(clip.height * scale) > MAX_PIXELS:
            raise WebError(
                413, "render_limit", "Rendered image exceeds its pixel limit."
            )
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(scale, scale),
            clip=clip,
            alpha=False,
            colorspace=fitz.csRGB,
        )
        return pixmap.tobytes("png")


def crop_image(run_root: Path, image_path: str) -> bytes:
    data = SafeFiles(run_root).read(image_path, max_bytes=16 * 1024 * 1024)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if (
                image.width * image.height > MAX_PIXELS
                or getattr(image, "n_frames", 1) != 1
            ):
                raise WebError(
                    413, "image_limit", "Structure image exceeds pixel or frame limits."
                )
            image.load()
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            return buffer.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise WebError(
            422, "invalid_image", "Structure image could not be decoded."
        ) from exc
