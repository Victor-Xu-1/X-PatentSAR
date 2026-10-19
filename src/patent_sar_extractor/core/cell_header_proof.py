"""Original header semantics over the shared physical text-frame proof."""

from patent_sar_extractor.contracts import AUXILIARY_TEXT_CELL_VERSION

from .cell_text_proof import physical_text_valid


def physical_header_valid(reading):
    packet = reading.get("physical_header_lines") if isinstance(reading, dict) else None
    auxiliary = (
        isinstance(packet, dict)
        and packet.get("version") == AUXILIARY_TEXT_CELL_VERSION
    )
    return physical_text_valid(
        reading,
        packet_name="physical_header_lines",
        part_method="physical_header_line",
        minimum_rows=1 if auxiliary else 2,
        maximum_rows=8,
    ) and reading.get("text") == reading.get("raw_text")
