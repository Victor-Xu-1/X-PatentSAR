"""Optional page-work observations; they never qualify source or chemistry."""

from collections.abc import Callable
from typing import Literal, get_args

PageSourcePhase = Literal["page_ocr", "empty_text_retry", "page_classification"]
PAGE_SOURCE_PHASES = get_args(PageSourcePhase)
PageObserver = Callable[[PageSourcePhase, int, int, int], None]


def observe_page_work(
    observer: PageObserver | None,
    phase: PageSourcePhase,
    completed: int,
    total: int,
    cache_hits: int = 0,
) -> None:
    if observer is not None:
        observer(phase, completed, total, cache_hits)


def empty_retry_observer(observer: PageObserver | None) -> PageObserver | None:
    if observer is None:
        return None

    def observe(
        _phase: PageSourcePhase, completed: int, total: int, cache_hits: int
    ) -> None:
        observer("empty_text_retry", completed, total, cache_hits)

    return observe
