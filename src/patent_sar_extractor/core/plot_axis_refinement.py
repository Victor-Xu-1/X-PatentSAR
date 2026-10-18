"""One original-axis observation/refinement path, shared by saved replay."""

from .cell_frame_proof import inside_box
from .plot_axis_words import axis_word_parts, observe_axis_words, refined_axis_tokens
from .plot_reference_axes import axis_word_window, complete_axis_windows, observe_axes
from .plot_reference_geometry import plot_axes, plot_axis_nomination
from .plot_reference_marker import observe_marker
from .source_geometry import overlaps


def refinement_windows(figure, size):
    refinement = figure["axis_refinement"]
    if refinement is None:
        return None
    if not isinstance(refinement, dict):
        raise TypeError("Invalid original-axis refinement inventory")
    current = "word_observations" in refinement
    if set(refinement) != {
        "nomination",
        "axis_strokes",
        "word_observations" if current else "word_observation",
    }:
        raise ValueError("Invalid original-axis refinement inventory")
    nomination = refinement["nomination"]
    if not isinstance(nomination, dict) or set(nomination) != {"x", "y"}:
        raise ValueError("Invalid original-axis nomination")
    for group in nomination.values():
        if (
            not isinstance(group, list)
            or not 3 <= len(group) <= 32
            or any(
                not isinstance(part, dict)
                or set(part) != {"text", "bbox"}
                or not isinstance(part["text"], str)
                or len(part["text"]) > 4096
                or not inside_box(part["bbox"], [0, 0, *size])
                for part in group
            )
        ):
            raise ValueError("Invalid original-axis word positions")
    windows = (
        complete_axis_windows(
            refinement["axis_strokes"], nomination, figure["caption"], size
        )
        if current
        else {
            "x": axis_word_window(
                refinement["axis_strokes"], nomination, figure["caption"], size
            )
        }
    )
    if windows is None or any(box is None for box in windows.values()):
        raise ValueError("Unproved complete original-axis strip")
    if current and (
        not isinstance(refinement["word_observations"], dict)
        or set(refinement["word_observations"]) != {"x", "y"}
    ):
        raise ValueError("Invalid complete original-axis word inventory")
    return windows


def refinement_bounds(figure, size):
    windows = refinement_windows(figure, size)
    if windows is None:
        return None
    boxes = list(windows.values())
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def replay_axis_tokens(figure, tokens, native, hint, size):
    refinement = figure["axis_refinement"]
    if refinement is None:
        return tokens, native
    windows = refinement_windows(figure, size)
    if (
        plot_axis_nomination(
            tokens, figure["caption"], hint["bbox"], size, independent_tokens=native
        )
        != refinement["nomination"]
    ):
        return None
    projected, remaining, observed = tokens, native, {}
    for axis, bounds in windows.items():
        current = "word_observations" in refinement
        packet = (
            refinement["word_observations"][axis]
            if current
            else refinement["word_observation"]
        )
        reading = axis_word_parts(
            packet, bounds, layout="rows" if axis == "y" else "columns", with_scope=True
        )
        if reading is None:
            return None
        parts, scope = reading
        projected = refined_axis_tokens(projected, remaining, parts, scope)
        if projected is None:
            return None
        remaining = [p for p in remaining if not overlaps(p["bbox"], scope)]
        observed[axis] = parts
    axes = plot_axes(
        projected,
        figure["caption"],
        hint["bbox"],
        size,
        independent_tokens=remaining,
    )
    # Reading every word is not enough if the final numeric nomination can omit
    # one again. Every retained original word must belong to the proved x axis.
    if axes is None or any(axes[axis] != parts for axis, parts in observed.items()):
        return None
    return projected, remaining


def observe_reference_axes(page, tokens, captions, line, size):
    native = tokens.native_tokens
    marker = observe_marker(page, line["bbox"], size)
    if marker is None:
        return None
    options = [
        (caption, axes)
        for caption in captions
        if (
            axes := plot_axis_nomination(
                tokens, caption, line["bbox"], size, independent_tokens=native
            )
        )
        is not None
    ]
    if len(options) != 1:
        return None
    caption, nomination = options[0]
    nominal_strokes = observe_axes(page, nomination, size, nomination=True)
    if nominal_strokes is None:
        return None
    windows = complete_axis_windows(nominal_strokes, nomination, caption, size)
    if windows is None:
        return None
    refinement = {
        "nomination": nomination,
        "axis_strokes": nominal_strokes,
        "word_observations": {
            axis: observe_axis_words(
                page, bounds, layout="rows" if axis == "y" else "columns"
            )
            for axis, bounds in windows.items()
        },
    }
    attempt = {
        "caption": caption,
        "axes": nomination,
        "axis_strokes": nominal_strokes,
        "axis_refinement": refinement,
        "marker": marker,
    }
    projected = replay_axis_tokens(attempt, tokens, native, line, size)
    if projected is None:
        return attempt
    axes = plot_axes(
        projected[0], caption, line["bbox"], size, independent_tokens=projected[1]
    )
    if axes is None:
        return attempt
    anchor = {"axes": nomination, "pixels": nominal_strokes}
    strokes = observe_axes(page, axes, size, anchor=anchor)
    if strokes is None:
        return attempt
    return {
        "caption": caption,
        "axes": axes,
        "axis_strokes": strokes,
        "axis_refinement": refinement,
        "marker": marker,
    }
