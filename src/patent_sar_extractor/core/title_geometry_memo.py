"""Bounded content-addressed geometry memo for one synchronous validation call."""

from collections import OrderedDict
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps

from .source_evidence_identity import SourceEvidenceLimit, proof_id

_ACTIVE = ContextVar("original_title_geometry_call", default=None)


def title_geometry_call(function):
    """Nested consumers share computed geometry, never original replay results."""

    @wraps(function)
    def checked(*args, **kwargs):
        if _ACTIVE.get() is not None:
            return function(*args, **kwargs)
        from .title_source_proof import MAX_TITLE_SOURCES

        token = _ACTIVE.set((MAX_TITLE_SOURCES, OrderedDict()))
        try:
            return function(*args, **kwargs)
        finally:
            _ACTIVE.reset(token)

    return checked


def memoized_title_geometry(source, calculate):
    """Only immutable-by-content serialized facts; actual source is never cached.

    Rehash on every lookup, so in-place mutation cannot reuse a prior result.
    Defensively copy row results; no raw pixels, model, role or acceptance stamp
    is retained. The existing source bound caps entries and the outer finally
    releases all state, including on exceptions. Independent requests revalidate.
    """
    active = _ACTIVE.get()
    if active is None:
        return calculate(source)
    try:
        key = proof_id({"status": "original_title_geometry", "source": source})
    except (SourceEvidenceLimit, TypeError, ValueError):
        # An unhashable/over-budget packet still takes its ordinary validator;
        # inability to memoize never makes the packet valid or skips a check.
        return calculate(source)
    limit, entries = active
    if key in entries:
        entries.move_to_end(key)
        return deepcopy(entries[key])
    result = calculate(source)
    if len(entries) >= limit:
        entries.popitem(last=False)
    entries[key] = deepcopy(result)
    return result
