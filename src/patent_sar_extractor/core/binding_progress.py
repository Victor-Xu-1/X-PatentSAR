"""Optional post-body source-work observation, independent of scientific proof."""

from collections.abc import Callable, Iterable, Sequence
from typing import Literal, get_args

BindingSourcePhase = Literal[
    "caption_sources",
    "numbered_sources",
    "numbered_cells",
    "declaration_sources",
    "visible_captions",
    "reference_sources",
    "heading_sources",
    "heading_bindings",
]
BINDING_SOURCE_PHASES = get_args(BindingSourcePhase)
BindingObserver = Callable[[BindingSourcePhase, int, int], None]


def observed_items[Item](
    phase: BindingSourcePhase,
    items: Sequence[Item],
    observer: BindingObserver | None = None,
) -> Iterable[Item]:
    """Count an item only after its consumer returns for the next iteration.

    Exceptions, cancellation, break or generator close do not finish the current
    item. There is no finally increment, estimated work or accepted-ID count.
    With no observer, callers receive their exact original sequence unchanged.
    """
    if observer is None:
        return items
    if phase not in BINDING_SOURCE_PHASES:
        raise ValueError("Unknown binding source-work phase")
    total = len(items)
    observer(phase, 0, total)

    def iterate():
        for completed, item in enumerate(items, 1):
            yield item
            observer(phase, completed, total)

    return iterate()
