"""Bounded page ownership/coverage, independent of the OCR backend and writer."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

PagePayload = tuple[int, str, list[dict]]


class PageObservationError(RuntimeError):
    """Original page source is incomplete or does not belong to its request."""


def original_pages(indices: Sequence[int], total: int) -> list[int]:
    if any(type(index) is not int or not 0 <= index < total for index in indices):
        raise ValueError("Page index is outside the original PDF or is not an integer")
    return sorted(set(indices))


def _lines(lines: object) -> None:
    if not isinstance(lines, list):
        raise PageObservationError("Page OCR lines must be an original list")
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("text"), str):
            raise PageObservationError("Page OCR line text is invalid")
        for value in [line["y0"]] if "y0" in line else []:
            if type(value) not in {int, float} or not math.isfinite(value):
                raise PageObservationError("Page OCR line coordinate is invalid")
        if "bbox" in line and (
            not isinstance(line["bbox"], list)
            or len(line["bbox"]) != 4
            or any(
                type(value) not in {int, float} or not math.isfinite(value)
                for value in line["bbox"]
            )
        ):
            raise PageObservationError("Page OCR box is invalid")


def page_observation(expected: int, payload: object) -> PagePayload:
    if not isinstance(payload, tuple) or len(payload) != 3:
        raise PageObservationError("Page OCR response does not match its request")
    actual, text, lines = payload
    if type(actual) is not int or actual != expected or not isinstance(text, str):
        raise PageObservationError(
            "Page OCR response has foreign ownership or invalid text"
        )
    _lines(lines)
    return actual, text, lines


def validate_cache(cache: dict, total: int, *, required: Sequence[int] = ()) -> None:
    texts, lines = cache.get("page_texts"), cache.get("ocr_line_map")
    if not isinstance(texts, dict) or not isinstance(lines, dict):
        raise PageObservationError("Original page cache collections are invalid")
    for key, text in texts.items():
        if (
            not isinstance(key, str)
            or not key.isascii()
            or not key.isdecimal()
            or str(int(key)) != key
            or not 0 <= int(key) < total
            or not isinstance(text, str)
        ):
            raise PageObservationError(
                "Original page cache has invalid page ownership or text"
            )
    for key, values in lines.items():
        if key not in texts:
            raise PageObservationError(
                "Original OCR coordinates have no matching page text"
            )
        _lines(values)
    missing = sorted(set(required) - {int(key) for key in texts})
    if missing:
        shown = ",".join(str(index + 1) for index in missing[:12])
        raise PageObservationError(
            f"Original page source is incomplete: {len(missing)} pages missing ({shown})"
        )


def parallel_pages(
    indices: Sequence[int], reader: Callable[[int], PagePayload], workers: int
) -> Iterator[PagePayload]:
    """At most one pending request per worker; failures never launch more work.

    Drain already-owned successful requests so the sole caller can checkpoint
    them. Failed/cancelled requests never become empty-page observations.
    """
    if type(workers) is not int or workers < 1:
        raise ValueError("Page OCR workers must be a positive integer")
    todo = iter(indices)
    failed: list[int] = []
    first_error: Exception | None = None
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(indices)))) as pool:
        pending = {}

        def submit() -> None:
            while not failed and len(pending) < workers:
                index = next(todo, None)
                if index is None:
                    return
                pending[pool.submit(reader, index)] = index

        submit()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda item: pending[item]):
                index = pending.pop(future)
                try:
                    value = page_observation(index, future.result())
                except (
                    OSError,
                    RuntimeError,
                    ValueError,
                    TypeError,
                    IndexError,
                    MemoryError,
                ) as error:
                    failed.append(index)
                    first_error = first_error or error
                else:
                    yield value
            if failed:
                for future in list(pending):
                    if future.cancel():
                        pending.pop(future)
            else:
                submit()
    if failed:
        shown = ",".join(str(index + 1) for index in sorted(failed)[:12])
        raise PageObservationError(
            f"Original page observation failed: {shown}; completed pages retained"
        ) from first_error
