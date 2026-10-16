"""One original-caption reading selector for formal binding and image preparation."""

from collections.abc import Mapping

from .caption_role_proof import caption_role_status
from .numbered_structure_pairs import _confirmed_observations


def confirmed_caption_readings(label, observations, ownership, page_no, label_box):
    if not isinstance(ownership, Mapping):
        return False
    form = ownership.get("identifier_form")
    if form is not None and form != "bare":
        return False
    bare = form == "bare"
    role = (
        caption_role_status(ownership.get("caption_role"), page_no, label_box)
        if ("caption_role" in ownership)
        else None
    )
    return bool(
        (not bare or role == "compound")
        and ("caption_role" not in ownership or role in {"compound", "unknown"})
        and _confirmed_observations(label, observations, caption=not bare)
    )
