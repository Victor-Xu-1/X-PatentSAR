"""Conserve literal ID observations from complete original unruled columns."""

from .activity_context_geometry import valid_box
from .cell_identity_proof import confirmed_identity_readings
from .printed_identifiers import identifier_key
from .source_cell_tokens import cell_lines, cell_text
from .source_observations import source_observation_status
from .source_window_chunks import (
    source_packet_projection,
    validate_source_projection,
    validate_source_window,
)
from .unruled_body_scope import body_context_window


def label_windows(chunks, window):
    validate_source_window(chunks, window)
    tokens = [part for chunk in chunks for part in chunk["sources"][0]["tokens"]]
    output = []
    for line in cell_lines(tokens, window):
        bounds = [
            min(t["bbox"][0] for t in line),
            min(t["bbox"][1] for t in line),
            max(t["bbox"][2] for t in line),
            max(t["bbox"][3] for t in line),
        ]
        if not valid_box(bounds):
            raise ValueError("Invalid original unruled identifier-line bounds")
        box = [
            window[0],
            max(window[1], bounds[1] - 4),
            window[2],
            min(window[3], bounds[3] + 4),
        ]
        if not valid_box(box):
            raise ValueError("Unruled identifier line leaves its source window")
        output.append({"text": cell_text(line, window), "bbox": bounds, "window": box})
    return output


def _original_label_source(observed, chunks, bounds):
    packet = observed["source_observation"]
    if source_observation_status(packet, bounds, observed.get("text")) == "invalid":
        return False
    return source_packet_projection(packet, chunks, bounds)


def _qualified_label(label, original, sources):
    if (
        not isinstance(label, dict)
        or set(label) != {"pair", "nomination", "value", "observations", "needs_review"}
        or any(label.get(k) != v for k, v in original.items())
        or not isinstance(label["value"], str)
        or type(label["needs_review"]) is not bool
        or not isinstance(label["observations"], list)
        or not 1 <= len(label["observations"]) <= 4
    ):
        raise ValueError("Malformed original unruled label observation")
    value = identifier_key(label["value"], wrapped=True, terminal_period=True)
    window = label["nomination"]["window"]
    if any(
        not isinstance(o, dict) or o.get("bbox", window) != window
        for o in label["observations"]
    ):
        raise ValueError("Unruled label readings lost their original window")
    current = [
        o
        for o in label["observations"]
        if o.get("method") in {"native_cell", "page_ocr_cell"}
        and "source_observation" in o
    ]
    for observed in current:
        packet = observed["source_observation"]
        if not isinstance(packet, dict) or not _original_label_source(
            observed, sources[label["pair"]]["chunks"], window
        ):
            raise ValueError("Malformed original unruled label source")
    return bool(
        value
        and current
        and not label["needs_review"]
        and confirmed_identity_readings(value, label["observations"])
    )


def label_population(region, xs, ys, bottom, nominated):
    """Replay every nominated line before any diagram matching is considered."""
    sources = region["pair_sources"]
    if not isinstance(sources, list) or len(sources) != len(nominated):
        raise ValueError("Incomplete original unruled source columns")
    expected = []
    for pair, (identifier, _structure) in enumerate(nominated):
        source = sources[pair]
        window = [xs[identifier], ys[1], xs[identifier + 1], bottom]
        if (
            not isinstance(source, dict)
            or set(source) != {"window", "chunks"}
            or source["window"] != window
        ):
            raise ValueError("Unruled original identifier column was changed")
        validate_source_projection(
            source["chunks"],
            window,
            region["body_context"],
            body_context_window(region["header_scope"]),
        )
        expected.extend(
            {"pair": pair, "nomination": line}
            for line in label_windows(source["chunks"], window)
        )
    labels = region["labels"]
    if (
        not isinstance(labels, list)
        or len(labels) != len(expected)
        or len(labels) > 25000
    ):
        raise ValueError("Original unruled label population was omitted or changed")
    return labels, [
        _qualified_label(label, original, sources)
        for label, original in zip(labels, expected)
    ]
