"""Explicit immutable JSON source views and bounded independent working copies."""

from __future__ import annotations


def _readonly(*_args, **_kwargs):
    raise TypeError("Original JSON source views are read-only; make a bounded copy")


class FrozenDict(dict):
    """JSON-compatible source object; ordinary mutation is not an audit path."""

    __slots__ = ()
    __init__ = __setitem__ = __delitem__ = __ior__ = _readonly
    clear = pop = popitem = setdefault = update = _readonly

    def __copy__(self):
        return self

    def __deepcopy__(self, _memo):
        return mutable_json_copy(self)


class FrozenList(list):
    """JSON-compatible source sequence with the same explicit copy boundary."""

    __slots__ = ()
    __init__ = __setitem__ = __delitem__ = __iadd__ = __imul__ = _readonly
    append = clear = extend = insert = pop = remove = reverse = sort = _readonly

    def __copy__(self):
        return self

    def __deepcopy__(self, _memo):
        return mutable_json_copy(self)


def readonly_container(kind, contents):
    """Internal construction only, after the graph's allocation preflight."""
    if kind == "object":
        value = dict.__new__(FrozenDict)
        dict.__init__(value, contents)
    else:
        value = list.__new__(FrozenList)
        list.__init__(value, contents)
    return value


def freeze_json(value):
    """Preserve source order, values and sharing without mutating the input."""
    from .artifact_nodes import JsonGraph

    graph = JsonGraph()
    return graph.materialize(graph.visit(value, readonly=True))


def mutable_json_copy(value):
    """Copy without aliases, under the unchanged mutable-expansion budgets."""
    from .artifact_nodes import JsonGraph

    graph = JsonGraph()
    return graph.materialize(graph.visit(value, mutable=True))
