"""Original header semantics over the shared physical text-frame proof."""

from .cell_text_proof import physical_text_valid


def physical_header_valid(reading):
    return physical_text_valid(
        reading,
        packet_name="physical_header_lines",
        part_method="physical_header_line",
        minimum_rows=2,
        maximum_rows=8,
    ) and reading.get("text") == reading.get("raw_text")
