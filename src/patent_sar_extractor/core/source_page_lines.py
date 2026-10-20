"""Original native line order and shared physical row presentation, no OCR."""

from .source_cell_tokens import cell_text


def native_page_lines(layout):
    groups = {}
    for token in layout.native:
        groups.setdefault(tuple(token["line"]), []).append(token)
    return [
        {
            "text": " ".join(token["text"] for token in group),
            "bbox": [
                min(token["bbox"][0] for token in group),
                min(token["bbox"][1] for token in group),
                max(token["bbox"][2] for token in group),
                max(token["bbox"][3] for token in group),
            ],
        }
        for group in groups.values()
    ]


def observed_page_text(source):
    if source["origin"] == "native":
        # Native order is an original fact; display rotation must not reverse
        # a native table row or exchange its identifier and measured value.
        return source["nomination_text"]
    tokens = [
        {
            "text": line["text"],
            "bbox": line["bbox"],
            "x": (line["bbox"][0] + line["bbox"][2]) / 2,
            "y": (line["bbox"][1] + line["bbox"][3]) / 2,
        }
        for line in source["lines"]
    ]
    return cell_text(tokens, [0, 0, *source["page_size"]])
