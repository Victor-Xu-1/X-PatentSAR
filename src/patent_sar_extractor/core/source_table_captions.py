"""Literal table-caption nominations shared by original source consumers."""

from .caption_role_semantics import catalog_title_role
from .source_cell_tokens import cell_lines, cell_text
from .source_table_markers import TABLE_CAPTION_START
from .source_table_roles import title_key


def table_caption_nominees(tokens, size, *, native_tokens=()):
    """Keep distinct original positions/claims; never parse a prose reference."""
    window = [0, 0, *size]
    output, seen, primary = [], set(), []
    for lane_index, lane in enumerate(
        (tokens, native_tokens or getattr(tokens, "native_tokens", ()))
    ):
        for line in cell_lines(lane, window):
            text = cell_text(line, window)
            if not TABLE_CAPTION_START.match(text):
                continue
            box = [
                min(p["bbox"][0] for p in line),
                min(p["bbox"][1] for p in line),
                max(p["bbox"][2] for p in line),
                max(p["bbox"][3] for p in line),
            ]
            identity = (title_key(text), catalog_title_role(text))
            # Unknown literal keys still have an exact raw identity, not a
            # fabricated number or a shared empty-key equivalence class.
            identity = identity if identity[0] else (*identity, text.casefold())
            key = (text, tuple(box))
            duplicate = lane_index == 1 and any(
                old_identity == identity
                and min(old["bbox"][2], box[2]) > max(old["bbox"][0], box[0])
                and min(old["bbox"][3], box[3]) > max(old["bbox"][1], box[1])
                for old, old_identity in primary
            )
            if key not in seen and not duplicate:
                seen.add(key)
                nomination = {"text": text, "bbox": box}
                output.append(nomination)
                if lane_index == 0:
                    primary.append((nomination, identity))
    return output
