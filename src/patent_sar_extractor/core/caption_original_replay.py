"""Original native/optical caption frames, not self-attested saved assignments."""

import hashlib

from .caption_binding_proof import valid_caption_binding_evidence
from .caption_source_windows import original_caption_read_window
from .caption_word_observation import replay_caption_word_form
from .caption_word_proof import WORD_FORM_METHOD
from .cell_frame_proof import valid_cell_frame
from .cell_raster import cell_window_identity, original_reading_image
from .source_geometry import SourceTokens, source_layout
from .source_observations import source_cell_observation
from .source_paint_visibility import visible_native_tokens


def caption_sources(bindings):
    return [
        b
        for b in bindings
        if b.get("binding_rule") == "original_caption_cell"
        or "exact_caption_evidence" in b
    ]


def original_caption_source_errors(document, bindings):

    frames, layouts, errors = {}, {}, []
    for binding in caption_sources(bindings):
        try:
            if not valid_caption_binding_evidence(binding):
                raise ValueError("Original caption assignment is invalid")
            packet = binding["exact_caption_evidence"]
            page_no = packet["page_no"]
            page = document[page_no - 1]
            bounds = original_caption_read_window(
                packet, (page.rect.width, page.rect.height)
            )
            observations = packet["observations"]
            for observation in observations:
                if observation.get("method") == WORD_FORM_METHOD:
                    replay_caption_word_form(page, observation["caption_word_form"])
            count = 0
            for observation in observations:
                method = observation.get("method")
                if method == WORD_FORM_METHOD:
                    continue
                elif method in {"cell_ocr_400dpi", "cell_ocr_600dpi"}:
                    dpi = 400 if method == "cell_ocr_400dpi" else 600
                    frame = observation.get("source_frame")
                    if "source_window" not in observation or not valid_cell_frame(
                        frame, observation, bounds, dpi
                    ):
                        raise ValueError("Original caption cell frame is malformed")
                    window = observation.get("source_window")
                    key = (
                        page_no,
                        tuple(bounds),
                        dpi,
                        (
                            cell_window_identity(window)
                            if "source_window" in observation
                            else "historical"
                        ),
                    )
                    if key not in frames:
                        image = original_reading_image(page, bounds, dpi, observation)
                        frames[key] = {
                            "dpi": dpi,
                            "shape": list(image.shape),
                            "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                        }
                    if frame != frames[key] or not valid_cell_frame(
                        frame, observation, bounds, dpi
                    ):
                        raise ValueError(
                            "Original caption cell frame differs or is missing"
                        )
                    count += 1
                elif method == "native_cell":
                    if page_no not in layouts:
                        layouts[page_no] = source_layout(page)
                    layout = layouts[page_no]
                    original = source_cell_observation(
                        SourceTokens(layout.native, layout), tuple(bounds), native=True
                    )
                    if (
                        original["text"] != observation.get("text")
                        or not visible_native_tokens(page, original)
                        or (observation.get("source_observation") != original)
                    ):
                        raise ValueError(
                            "Original native caption text is missing, changed or covered"
                        )
                    count += 1
            if not count:
                raise ValueError("Original caption has no native or pixel observation")
        except (KeyError, TypeError, ValueError, RuntimeError, IndexError) as exc:
            errors.append(f"{binding.get('structure_id', '')}: {exc}")
    return errors
