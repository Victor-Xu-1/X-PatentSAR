"""Original literal continuation nominations, not row/compound assignments."""

from .caption_role_proof import observed_role, title_key
from .caption_role_semantics import catalog_title_role, continuation_title
from .source_cell_tokens import cell_lines, cell_text


def continuation_identity(text):
    return (
        (title_key(text), catalog_title_role(text))
        if continuation_title(text)
        else None
    )


def continuation_nominees(tokens, size, *, native_tokens=()):
    window = [0, 0, *size]
    output, seen, primary = [], set(), []
    for lane_index, lane in enumerate(
        (tokens, native_tokens or getattr(tokens, "native_tokens", ()))
    ):
        for line in cell_lines(lane, window):
            text = cell_text(line, window)
            identity = continuation_identity(text)
            if not identity:
                continue
            box = [
                min(p["bbox"][0] for p in line),
                min(p["bbox"][1] for p in line),
                max(p["bbox"][2] for p in line),
                max(p["bbox"][3] for p in line),
            ]
            key = (text, tuple(box))
            same_physical_primary = lane_index == 1 and any(
                continuation_identity(old["text"]) == identity
                and min(old["bbox"][2], box[2]) > max(old["bbox"][0], box[0])
                and min(old["bbox"][3], box[3]) > max(old["bbox"][1], box[1])
                for old in primary
            )
            if key not in seen and not same_physical_primary:
                seen.add(key)
                nomination = {"text": text, "bbox": box}
                output.append(nomination)
                if lane_index == 0:
                    primary.append(nomination)
    return output


def anchor_scope(scope):
    return scope.get("anchor_scope", scope)


def nominated_table_keys(scope):
    return {
        title_key(p["text"])
        for p in anchor_scope(scope)["context_sources"]
        if title_key(p["text"])
    }


def qualified_table_key(scope):
    _role, key = observed_role(
        [p for p in anchor_scope(scope)["context_sources"] if p["text"].strip()]
    )
    return key
