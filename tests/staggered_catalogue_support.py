"""Independent original title layers at each actual generated table's top."""

import fitz

from tests.parallel_catalogue_support import TITLES, original_parallel_catalogues


def paint_original_title(page, literal, left, baseline, mode, *, width=240):
    if mode == "native":
        page.insert_text((left, baseline), literal, fontsize=9)
        return
    target = fitz.Rect(left, baseline - 16, left + width, baseline + 4)
    with fitz.open() as lettering:
        original = lettering.new_page(width=width, height=20)
        original.insert_text((0, 16), literal, fontsize=9)
        if mode == "raster":
            pixels = original.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            page.insert_image(target, stream=pixels.tobytes("png"))
        else:
            with (
                fitz.open(
                    stream=original.get_svg_image(text_as_path=True).encode(),
                    filetype="svg",
                ) as vector,
                fitz.open(stream=vector.convert_to_pdf(), filetype="pdf") as outlines,
            ):
                page.show_pdf_page(target, outlines, 0)


def staggered_catalogues(
    mode="native",
    *,
    shift=60,
    headers=False,
    open_right=False,
    titles=TITLES,
    unowned=None,
):
    document, structures, boxes, frames = original_parallel_catalogues(
        "native",
        titles=("", ""),
        right_shift=shift,
        headers=headers,
        open_right=open_right,
    )
    for frame, literal in zip(frames, titles, strict=True):
        paint_original_title(
            document[0], literal, frame["xs"][0], frame["ys"][0] - 15, mode
        )
    if unowned:
        paint_original_title(
            document[0],
            unowned,
            290,
            max(g["ys"][0] for g in frames) - 15,
            mode,
            width=100,
        )
    return document, structures, boxes, frames


def prior_original_table(document, frames):
    """A real earlier closed source in one column, not a hand-entered fence."""
    page = document[0]
    grid = {"xs": [30, 150], "ys": [20, 40, 60]}
    for x in grid["xs"]:
        page.draw_line((x, 20), (x, 60))
    for y in grid["ys"]:
        page.draw_line((30, y), (150, y))
    page.insert_text((30, 12), "Table Z. Intermediates", fontsize=6)
    page.insert_text((45, 35), "reference", fontsize=6)
    return [grid, *frames]


def wrapped_staggered_catalogues():
    document, structures, boxes, frames = staggered_catalogues(
        "native", titles=("", "")
    )
    page = document[0]
    for left, baseline, marker, category in (
        (30, 72, "Table A.", "Compounds"),
        (400, 132, "Table B.", "Intermediates"),
    ):
        page.insert_text((left, baseline), marker, fontsize=9)
        page.insert_text((left, baseline + 13), category, fontsize=9)
    prior_original_table(document, frames)
    return document, structures, boxes, frames
