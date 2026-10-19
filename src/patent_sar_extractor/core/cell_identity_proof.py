"""One literal printed-ID observation proof for all original structure owners."""

import math
from collections.abc import Mapping

from .caption_word_proof import WORD_FORM_METHOD, caption_form_aliases
from .cell_caption_identity import refined_caption_conflicts
from .cell_caption_lines import physical_caption_valid
from .compound_caption import prefixed_label
from .printed_identifiers import identifier_fragments_conflict, identifier_key
from .source_cell_claims import cell_source_conflict, cell_source_status
from .source_section_roles import nonfinal_original_label


def confirmed_identity_readings(label, observations, *, caption=False):
    aliases = caption_form_aliases(label, observations)
    if aliases is None or aliases and not caption:
        return False
    methods = set()
    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping) or not physical_caption_valid(
            observation
        ):
            return False
        if observation.get("method") == WORD_FORM_METHOD:
            continue  # Word scope verifies form; it is not another ID observation.
        from .text_ocr.cell_proof import has_auxiliary_text

        original = observation
        if has_auxiliary_text(observation):
            # Physical-caption validation above replays the full paired packet.
            # Preserve the primary's role and detector veto, not only fresh text.
            original = observation["auxiliary_text"]["views"][
                (400, 600).index(observation["render_dpi"])
            ]["primary"]
            if nonfinal_original_label(original.get("raw_text")):
                return False
        if refined_caption_conflicts(
            label, original.get("parts"), original.get("detection_parts")
        ):
            return False
        method = str(observation.get("method") or "")
        original_cell = method in {"native_cell", "page_ocr_cell"}
        original_caption = caption and original_cell
        if original_cell:
            status = cell_source_status(observation)
            if index not in aliases and cell_source_conflict(
                observation, label, "label" if caption else "id"
            ):
                return False
            if status not in {"qualified", "legacy"}:
                continue
        if nonfinal_original_label(observation.get("text")):
            return False
        observed = (
            prefixed_label(str(observation.get("text") or ""))
            if original_caption
            else identifier_key(
                observation.get("text"), wrapped=True, terminal_period=True
            )
        )
        if (
            not observed
            and not original_cell
            and identifier_fragments_conflict(
                str(observation.get("text") or ""), label, caption=original_caption
            )
        ):
            return False
        if observed and observed != label:
            return False
        if observed != label:
            continue
        if method.startswith("cell_ocr_"):
            if (
                caption
                and "raw_text" in observation
                and prefixed_label(str(observation["raw_text"] or "")) != label
            ):
                return False
            if isinstance(observation.get("confidence"), bool):
                continue
            try:
                score = float(observation.get("confidence", 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(score) or not 0.85 <= score <= 1:
                continue
        methods.add(method)
    return (
        "native_cell" in methods
        or "cell_ocr_400dpi" in methods
        and bool(methods & {"page_ocr_cell", "cell_ocr_600dpi"})
    )
