"""One original-axis observation/refinement path, shared by saved replay."""

from .cell_frame_proof import inside_box
from .plot_axis_words import axis_word_parts, observe_axis_words, refined_axis_tokens
from .plot_reference_axes import axis_word_window, observe_axes
from .plot_reference_geometry import plot_axes, plot_axis_nomination
from .plot_reference_marker import observe_marker
from .source_geometry import overlaps


def refinement_bounds(figure, size):
    refinement = figure["axis_refinement"]
    if refinement is None:
        return None
    if not isinstance(refinement, dict) or set(refinement) != {
        "nomination",
        "axis_strokes",
        "word_observation",
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
    bounds = axis_word_window(
        refinement["axis_strokes"], nomination, figure["caption"], size
    )
    if bounds is None:
        raise ValueError("Unproved complete original-axis strip")
    return bounds


def replay_axis_tokens(figure, tokens, native, hint, size):
    refinement = figure["axis_refinement"]
    if refinement is None:
        return tokens, native
    bounds = refinement_bounds(figure, size)
    if (
        plot_axis_nomination(
            tokens, figure["caption"], hint["bbox"], size, independent_tokens=native
        )
        != refinement["nomination"]
    ):
        return None
    parts = axis_word_parts(refinement["word_observation"], bounds)
    if parts is None:
        return None
    projected = refined_axis_tokens(tokens, native, parts, bounds)
    if projected is None:
        return None
    remaining = [p for p in native if not overlaps(p["bbox"], bounds)]
    axes = plot_axes(
        projected,
        figure["caption"],
        hint["bbox"],
        size,
        independent_tokens=remaining,
    )
    # Reading every word is not enough if the final numeric nomination can omit
    # one again. Every retained original word must belong to the proved x axis.
    if axes is None or axes["x"] != parts:
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
            axes := plot_axes(
                tokens, caption, line["bbox"], size, independent_tokens=native
            )
        )
        is not None
    ]
    refinement = None
    if len(options) > 1:
        return None
    if not options:
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
        nominal_strokes = observe_axes(page, nomination, size)
        if nominal_strokes is None:
            return None
        bounds = axis_word_window(nominal_strokes, nomination, caption, size)
        if bounds is None:
            return None
        refinement = {
            "nomination": nomination,
            "axis_strokes": nominal_strokes,
            "word_observation": observe_axis_words(page, bounds),
        }
        attempt = {
            "caption": caption,
            "axes": nomination,
            "axis_strokes": nominal_strokes,
            "axis_refinement": refinement,
            "marker": marker,
        }
        figure = {"caption": caption, "axis_refinement": refinement}
        projected = replay_axis_tokens(figure, tokens, native, line, size)
        if projected is None:
            return attempt
        axes = plot_axes(
            projected[0], caption, line["bbox"], size, independent_tokens=projected[1]
        )
        if axes is None:
            return attempt
    else:
        caption, axes = options[0]
    anchor = (
        {"axes": refinement["nomination"], "pixels": refinement["axis_strokes"]}
        if refinement is not None
        else None
    )
    strokes = observe_axes(page, axes, size, anchor=anchor)
    if strokes is None:
        return attempt if refinement is not None else None
    return {
        "caption": caption,
        "axes": axes,
        "axis_strokes": strokes,
        "axis_refinement": refinement,
        "marker": marker,
    }
