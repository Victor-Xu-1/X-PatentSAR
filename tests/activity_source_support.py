"""Actual generated-page partition capture for coordinate writer/QA controls."""

from patent_sar_extractor.core.activity_coverage import coverage_packet
from patent_sar_extractor.core.activity_text import extract_text_tables
from patent_sar_extractor.core.activity_text_capture import capture_text_page
from patent_sar_extractor.core.page_ocr_cache import page_ocr_lines
from patent_sar_extractor.core.source_page_lines import observed_page_text


def original_coordinate_coverage(document, pages, result):
    texts, sources = {}, {}
    for index in pages:
        page = document[index]
        lines = page_ocr_lines(page)
        source = capture_text_page(
            page,
            " ".join(line["text"] for line in lines),
            lines,
            coordinate_regions=[
                region for region in result.coverage if region["page_no"] == index + 1
            ],
        )
        sources[str(index + 1)] = source
        texts[str(index + 1)] = observed_page_text(source)
    parsed = extract_text_tables(
        pages,
        {str(index): sources[str(index + 1)]["nomination_text"] for index in pages},
        page_count=len(document),
        source_reader=lambda index, _text: sources[str(index + 1)],
        coordinate_regions=result.coverage,
    )
    if parsed.rows:
        raise AssertionError(
            "A coordinate-only generated fixture acquired separate text measurements"
        )
    return coverage_packet(
        pages,
        [*result.coverage, *parsed.coverage],
        result.rows,
        text_pages=texts,
        text_sources=sources,
    )
