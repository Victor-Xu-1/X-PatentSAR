"""Auxiliary observation replay is independent of saved success flags or OCR calls."""

import re

from patent_sar_extractor.contracts import AUXILIARY_TEXT_CELL_VERSION
from patent_sar_extractor.core.table_cells import cell_image

from .cell_frames import literal, source_rows
from .cell_packets import view_summary
from .identity import recipe
from .protocol import frame_digest


def has_auxiliary_text(reading):
    if not isinstance(reading, dict):
        return False
    return (
        "auxiliary_text" in reading
        or "auxiliary_text_version" in reading
        or (
            any(
                isinstance(reading.get(name), dict)
                and reading[name].get("version") == AUXILIARY_TEXT_CELL_VERSION
                for name in ("physical_header_lines", "physical_text_chunks")
            )
        )
    )


def effective_cells(packet):
    if (
        isinstance(packet, dict)
        and type(packet.get("version")) is int
        and packet["version"] == 2
    ):
        from .recovery_proof import effective_recovery_cells

        return effective_recovery_cells(packet)
    if (
        not isinstance(packet, dict)
        or set(packet) != {"version", "model", "views"}
        or type(packet["version"]) is not int
        or packet["version"] != 1
    ):
        raise ValueError("Unknown auxiliary text evidence")
    model, views, spec = packet["model"], packet["views"], recipe()
    if (
        not isinstance(model, dict)
        or set(model) != {"name", "revision", "adapter_version", "fingerprint"}
        or model["name"] != spec["model_name"]
        or model["revision"] != spec["model_revision"]
        or model["adapter_version"] != spec["adapter_version"]
        or not isinstance(model["fingerprint"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", model["fingerprint"])
        or not isinstance(views, list)
        or len(views) != 2
        or [v.get("dpi") for v in views if isinstance(v, dict)] != [400, 600]
    ):
        raise ValueError("Unproved auxiliary model/views")
    first, second = [view_summary(view, model["fingerprint"]) for view in views]
    from patent_sar_extractor.core.cell_text_proof import valid_text_components

    if all(valid_text_components(v["primary"], v["dpi"]) for v in views):
        raise ValueError(
            "Qualified primary cells cannot be replaced by auxiliary voting"
        )
    if (
        views[0]["primary"]["bbox"] != views[1]["primary"]["bbox"]
        or len(first["parts"]) != len(second["parts"])
        or any(
            literal(a["text"]) != literal(b["text"])
            for a, b in zip(first["parts"], second["parts"])
        )
    ):
        raise ValueError("Auxiliary original views disagree")
    return tuple(
        {
            **{
                k: v
                for k, v in view["primary"].items()
                if k not in {"single_row_readings", "physical_caption_line"}
            },
            **selected,
            "auxiliary_text": packet,
        }
        for view, selected in zip(views, (first, second))
    )


def valid_auxiliary_cell(reading, dpi):
    try:
        packet = reading["auxiliary_text"]
        selected = effective_cells(packet)[(400, 600).index(dpi)]
        return type(dpi) is int and reading == selected
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return False


def replay_auxiliary_cell(reading, page):
    """Render the same original windows, without models, paths from artifacts or edits."""
    if not valid_auxiliary_cell(reading, reading.get("render_dpi")):
        return False
    if reading["auxiliary_text"]["version"] == 2:
        from .recovery_proof import replay_recovery_cell

        try:
            return replay_recovery_cell(reading, page)
        except (TypeError, ValueError, KeyError, IndexError, RuntimeError):
            return False
    for view in reading["auxiliary_text"]["views"]:
        image = cell_image(page, view["primary"]["bbox"], view["dpi"])
        actual = source_rows(image, view["dpi"])
        if actual is None:
            return False
        for key in ("frame", "crop", "border", "shape", "pixel_sha256", "ink_pixels"):
            if actual[key] != view[key]:
                return False
        if actual["row_bounds"] != [row["bbox"] for row in view["rows"]]:
            return False
        if any(
            frame_digest(pixels) != row["observation"]["pixel_sha256"]
            for pixels, row in zip(actual["images"], view["rows"])
        ):
            return False
    return True
