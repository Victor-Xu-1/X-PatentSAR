"""Batch the existing cell observer; retain one complete physical source carrier."""

from .role_grid_windows import role_work_windows
from .source_geometry import native_region


def observe_complete_role_grid(page, region, tokens, *, evidence_sink=None):
    from .activity_grid_role_observation import _observe_role_cells, observe_role_cells

    xs, ys = list(region["xs"]), list(region["ys"])
    windows = role_work_windows(xs, ys)
    if windows is None:
        return None
    if len(windows) == 1:
        return observe_role_cells(page, region, tokens, evidence_sink=evidence_sink)
    carrier = {"xs": xs, "ys": ys, "native_hints": [], "observations": []}
    if evidence_sink is not None:
        evidence_sink.append(carrier)
    # Keep the same original WHOLE-grid source decision as the prior observer.
    # A blank child window cannot promote missing text or turn into a new source.
    native = native_region(
        tokens, [xs[0], ys[0], xs[-1], ys[-1]], bool(page.get_text("words"))
    )
    views = {}
    for start, stop in windows:
        attempted = []
        result = _observe_role_cells(
            page,
            {"xs": xs, "ys": ys[start : stop + 1]},
            tokens,
            native=native,
            evidence_sink=attempted,
        )
        observed = result if result is not None else attempted[0] if attempted else None
        if observed is not None:
            carrier["native_hints"].extend(observed["native_hints"])
            for view in observed["observations"]:
                method = view["method"]
                if method not in views:
                    views[method] = {"method": method, "matrix": [], "cells": []}
                    carrier["observations"].append(views[method])
                views[method]["matrix"].extend(view["matrix"])
                views[method]["cells"].extend(view["cells"])
        if result is None:
            return None  # Full/partial attempts remain diagnostic, never a role.
    return carrier
