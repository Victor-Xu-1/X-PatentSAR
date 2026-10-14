"""Complete mock column envelopes for isolated header semantic unit checks."""

from patent_sar_extractor.core.activity_header_columns import HeaderColumns


def observed_headers(matrix, region, limit, dpi, verified=None):
    headers = matrix[-1]
    xs, ys = region["xs"], region["ys"]
    columns = tuple(
        {
            "method": f"cell_ocr_{dpi}dpi",
            "render_dpi": dpi,
            "physical_column": index,
            "coordinate_space": "original_pdf_points",
            "bbox": [xs[index], ys[0], xs[index + 1], ys[limit]],
            "text": header,
            "raw_text": header,
            "confidence": 0.99,
            "crosses_boundary": False,
            "native_text": "",
            "detection_parts": [],
            "parts": [{"text": header, "confidence": 0.99}],
        }
        for index, header in enumerate(headers)
    )
    return HeaderColumns(matrix, columns, verified or (True,) * len(headers))
