"""Resolve a physical caption's form through the existing single cell reader."""

from dataclasses import replace

from .caption_word_observation import observe_caption_word_form
from .caption_word_proof import merged_caption_nominee, whole_caption_reads
from .cell_identity_proof import confirmed_identity_readings
from .compound_caption import prefixed_label
from .table_cells import _ocr_cell


def reconcile_caption_form(page, bounds, reading, *, bare, role):
    if not bare or role != "compound":
        return reading, bare
    whole = [o for o in reading.observations if o.get("method") == "cell_ocr_400dpi"]
    label = prefixed_label(whole[0].get("raw_text", "")) if len(whole) == 1 else ""
    if not label:
        return reading, bare
    observations = list(reading.observations)
    if not any(o.get("method") == "cell_ocr_600dpi" for o in observations):
        observations.append(_ocr_cell(page, bounds, "id", 600).evidence(600, bounds))
    if confirmed_identity_readings(label, observations, caption=True):
        return replace(
            reading, value=label, observations=observations, needs_review=False
        ), False
    if (
        len(observations) != 3
        or whole_caption_reads(label, observations) is None
        or not any(
            merged_caption_nominee(label, o, bounds) is not None for o in observations
        )
    ):
        return reading, bare
    words = observe_caption_word_form(page, bounds)
    if words is None:
        return reading, bare
    if not confirmed_identity_readings(label, [*observations, words], caption=True):
        return replace(reading, observations=[*observations, words]), bare
    return replace(
        reading, value=label, observations=[*observations, words], needs_review=False
    ), False
