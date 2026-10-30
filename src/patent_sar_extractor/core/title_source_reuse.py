"""Call-local original title observations; no persistent cache or admission flag."""

from copy import deepcopy

from .cell_frame_proof import valid_cell_frame
from .title_original_replay import replay_source_title
from .title_source_proof import MAX_TITLE_SOURCES, source_title_geometry


def _key(proof, cache):
    if cache is None:
        return None
    if not isinstance(cache, dict) or len(cache) > MAX_TITLE_SOURCES:
        raise ValueError("Invalid call-local original title observations")
    return proof["page_no"], tuple(proof["bbox"])


def reuse_title_observation(page, proof, cache, *, layout, paint_view):
    key = _key(proof, cache)
    if key is None or key not in cache:
        return False
    previous = cache[key]
    if not isinstance(previous, dict) or any(
        previous.get(name) != proof[name]
        for name in (
            "page_no",
            "page_size",
            "bbox",
            "native_source",
            "native_window",
            "raster_bounds",
        )
    ):
        raise ValueError("Original source changed during title capture")
    replay_source_title(page, previous, layout=layout, paint_view=paint_view)
    for name in ("observations", "rendered_frames"):
        proof[name] = deepcopy(previous[name])
    if proof["version"] == 2:
        proof["auxiliary_title"] = deepcopy(previous.get("auxiliary_title"))
        proof["auxiliary_title_attempts"] = deepcopy(
            previous.get("auxiliary_title_attempts", [])
        )
    return True


def remember_title_observation(proof, cache):
    key = _key(proof, cache)
    if key is None or key in cache or len(cache) >= MAX_TITLE_SOURCES:
        return
    readings, frames = proof["observations"], proof["rendered_frames"]
    if (
        source_title_geometry(proof) is not None
        and len(readings) == len(frames) == 2
        and all(
            valid_cell_frame(frame, reading, proof["bbox"], dpi)
            for frame, reading, dpi in zip(frames, readings, (400, 600), strict=True)
        )
    ):
        # Retain weak/failed attempts too: another member must not silently
        # repeat that same physical read until a preferred role appears.
        cache[key] = proof
