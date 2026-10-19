"""One original-caption reading selector for formal binding and image preparation."""

from collections.abc import Mapping

from .caption_role_proof import caption_role_status
from .caption_word_proof import WORD_FORM_METHOD
from .cell_identity_proof import confirmed_identity_readings


def confirmed_caption_readings(label, observations, ownership, page_no, label_box):
    if (
        not isinstance(ownership, Mapping)
        or not isinstance(observations, (list, tuple))
        or not 1 <= len(observations) <= 4
        or any(not isinstance(o, Mapping) for o in observations)
    ):
        return False
    word_count = sum(o.get("method") == WORD_FORM_METHOD for o in observations)
    if word_count > 1 or len(observations) == 4 and word_count != 1:
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
        (
            not any(o.get("method") == WORD_FORM_METHOD for o in observations)
            or not bare
            and role == "compound"
        )
        and (not bare or role == "compound")
        and ("caption_role" not in ownership or role in {"compound", "unknown"})
        and confirmed_identity_readings(label, observations, caption=not bare)
    )
