"""Existing evidence-led structure-table layout strategies."""

from __future__ import annotations

import logging
import re
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from .binding_candidates import (
    _build_binding_from_structure,
    _merge_binding_candidates,
)
from .binding_geometry import (
    _best_table_structure_for_row_label,
    _best_table_structure_from_row,
    _group_structures_by_row,
    _structure_row_bounds,
)
from .binding_labels import (
    _base_cpd_num,
    _binding_base_num,
    _page_text_for_page_no,
)
from .binding_observations import (
    _normalise_ocr_line_map,
)

logger = logging.getLogger(__name__)


_TABLE_ROW_RE = re.compile(r"^\s*(\d{1,3})(?=\s|$)")


_STRUCTURE_TABLE_CONTEXT_RE = re.compile(
    r"(?:Example|Compound|Cpd|化合物|实施例)\s+(?:Structure|结构)|"
    r"(?:Structure|结构)\s+(?:NMR/MS|NMR|MS|ID)|"
    r"(?:Ex\s*#|Example\s*#).{0,160}(?:Procedures?|Structure).{0,160}(?:LCMS|NMR)|"
    r"Table\s+\d+.{0,120}(?:Example|Structure|NMR/MS)",
    re.IGNORECASE | re.DOTALL,
)


_STRUCTURE_TABLE_MASS_VALUE_RE = re.compile(r"\b\d{3}\.\d\b")


_STRUCTURE_TABLE_CHEM_CONTEXT_RE = re.compile(
    r"哌啶|吡啶|苯基|噻吩|呋喃|二酮|恶唑|噻唑|"
    r"phenyl|pyrid|thien|furyl|piperid|dione|oxazol|thiazol",
    re.IGNORECASE,
)


_STRUCTURE_TABLE_ROUTE_CONTEXT_RE = re.compile(
    r"合成路线|中间体|第一步|第二步|第三步|反应液|反应瓶|加入|搅拌|粗品|纯化|"
    r"Synthesis|Preparation|Intermediate|Step\s*\d+|reaction|mixture",
    re.IGNORECASE,
)


_SPECTRAL_OR_CONDITION_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*H\b|MHz|DMSO|CDCl|METHANOL|NMR|LCMS|MS:|ESI|"
    r"calc|found|Hz|J\s*=|m/z|yield|purity|eq|mg|mL|mol|mmol|umol|℃|°C)",
    re.IGNORECASE,
)


def _extract_table_row_numbers(page_text: str) -> List[int]:
    raw_numbers: List[int] = []
    for raw_line in str(page_text or "").splitlines():
        match = _TABLE_ROW_RE.match(raw_line)
        if not match:
            continue
        value = int(match.group(1))
        if raw_numbers and raw_numbers[-1] == value:
            continue
        raw_numbers.append(value)

    if len(raw_numbers) < 4:
        return raw_numbers

    # Keep the longest left-column-like increasing run and drop OCR noise such
    # as stray "1", "4", mass fragments, or repeated figure labels.
    best_len = 0
    best_sum = -1
    dp = [1] * len(raw_numbers)
    prev = [-1] * len(raw_numbers)
    for i, value in enumerate(raw_numbers):
        for j in range(i):
            prev_value = raw_numbers[j]
            step = value - prev_value
            if step < 1 or step > 3:
                continue
            cand_len = dp[j] + 1
            cand_sum = 0
            k = j
            while k != -1:
                cand_sum += raw_numbers[k]
                k = prev[k]
            cand_sum += value
            if cand_len > dp[i]:
                dp[i] = cand_len
                prev[i] = j
            elif cand_len == dp[i] and cand_sum > best_sum:
                prev[i] = j

        if dp[i] > best_len:
            best_len = dp[i]
            best_sum = value
        elif dp[i] == best_len:
            best_sum = max(best_sum, value)

    end_idx = max(
        range(len(raw_numbers)),
        key=lambda idx: (dp[idx], raw_numbers[idx]),
    )
    if dp[end_idx] < 4:
        return raw_numbers

    sequence: List[int] = []
    while end_idx != -1:
        sequence.append(raw_numbers[end_idx])
        end_idx = prev[end_idx]
    sequence.reverse()
    return sequence


def _is_structure_table_context(
    page_text: str, lines: Optional[List[Tuple[float, str]]] = None
) -> bool:
    joined_lines = " ".join(text for _y, text in (lines or []))
    text = re.sub(r"\s+", " ", f"{page_text or ''} {joined_lines}").strip()
    if not text:
        return False
    if _STRUCTURE_TABLE_CONTEXT_RE.search(text):
        return True
    line_id_hits = sum(
        1
        for _y, line_text in (lines or [])
        if re.fullmatch(r"\s*[1-9]\d{0,3}\s*", str(line_text or ""))
    )
    mass_hits = len(_STRUCTURE_TABLE_MASS_VALUE_RE.findall(text))
    chem_hits = len(_STRUCTURE_TABLE_CHEM_CONTEXT_RE.findall(text))
    # Continuation pages in scanned structure tables often lose the table
    # header, but still preserve the true left ID column plus LC-MS masses.
    if _STRUCTURE_TABLE_ROUTE_CONTEXT_RE.search(text):
        return False
    return line_id_hits >= 2 and mass_hits >= 2 and chem_hits >= 2


def _line_is_probable_table_compound_id(
    text: str, active_bases: set[int]
) -> Optional[int]:
    value = re.sub(r"\s+", " ", str(text or "")).strip().strip("()[]{}.,;:，。；：")
    if not value:
        return None
    if _SPECTRAL_OR_CONDITION_RE.search(value):
        return None
    match = re.fullmatch(
        r"(?:Example|Compound|Cpd|化合物|实施例)?\s*([1-9]\d{0,2})(?:[A-Z])?",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    num = int(match.group(1))
    if num not in active_bases:
        return None
    return num


def _extract_table_row_numbers_from_lines(
    lines: Optional[List[Tuple[float, str]]],
    active_bases: set[int],
    page_structs: Optional[List[Dict]] = None,
) -> List[Tuple[int, float, str]]:
    """Extract true left-column table IDs from OCR line coordinates."""
    if not lines or not active_bases:
        return []

    struct_rows = _group_structures_by_row(page_structs or [], y_threshold=60.0)
    struct_centers = [
        (
            min(float(s.get("y0") or 0) for s in row)
            + max(float(s.get("y1") or 0) for s in row)
        )
        / 2.0
        for row in struct_rows
        if row
    ]

    candidates: List[Tuple[int, float, str]] = []
    for y0, text in lines:
        num = _line_is_probable_table_compound_id(text, active_bases)
        if num is None:
            continue
        if struct_centers:
            nearest = min(abs(float(y0) - center) for center in struct_centers)
            # Footer page numbers can look like active compound IDs. Keep only
            # labels that really sit on a structure row.
            if nearest > 75.0:
                continue
        if (
            candidates
            and candidates[-1][0] == num
            and abs(candidates[-1][1] - float(y0)) < 18.0
        ):
            continue
        candidates.append((num, float(y0), str(text).strip()))

    if len(candidates) < 2:
        return candidates

    # If OCR sees more numeric labels than structure rows, choose the label
    # subset that best aligns to the row centers. This drops footer page
    # numbers like "301" without blocking genuine multi-range table jumps.
    if struct_centers and len(candidates) > len(struct_centers):
        row_count = len(struct_centers)
        best_score: Optional[float] = None
        best_seq: List[Tuple[int, float, str]] = []

        def walk(
            cand_idx: int, row_idx: int, seq: List[Tuple[int, float, str]], score: float
        ) -> None:
            nonlocal best_score, best_seq
            if row_idx == row_count:
                if best_score is None or score < best_score:
                    best_score = score
                    best_seq = list(seq)
                return
            remaining_rows = row_count - row_idx
            remaining_candidates = len(candidates) - cand_idx
            if remaining_candidates < remaining_rows:
                return
            if best_score is not None and score >= best_score:
                return
            for i in range(cand_idx, len(candidates) - remaining_rows + 1):
                num, y0, _text = candidates[i]
                if seq and num <= seq[-1][0]:
                    continue
                distance = abs(float(y0) - struct_centers[row_idx])
                if distance > 75.0:
                    continue
                jump_penalty = 0.0
                if seq:
                    step = num - seq[-1][0]
                    if step > 50:
                        # Real tables can jump between ranges (70 -> 141,
                        # 118 -> 240), but prefer the compact run when a
                        # competing footer/page number is present.
                        jump_penalty = min(step, 250) * 0.15
                walk(
                    i + 1,
                    row_idx + 1,
                    [*seq, candidates[i]],
                    score + distance + jump_penalty,
                )

        walk(0, 0, [], 0.0)
        if len(best_seq) >= 2:
            return best_seq

    # Preserve top-to-bottom order while dropping obvious OCR noise. Structure
    # tables may jump across disclosed ranges on the same page, e.g. 70 -> 141
    # or 245 -> 431, so do not collapse to only the longest +1 run.
    monotonic: List[Tuple[int, float, str]] = []
    for item in candidates:
        num, y0, _text = item
        if monotonic and y0 <= monotonic[-1][1] + 8:
            continue
        if monotonic and num <= monotonic[-1][0]:
            break
        monotonic.append(item)
    if len(monotonic) >= 2:
        return monotonic

    # Legacy fallback for very noisy OCR pages with no usable row geometry.
    best: List[Tuple[int, float, str]] = []
    for start in range(len(candidates)):
        seq = [candidates[start]]
        last_num = candidates[start][0]
        last_y = candidates[start][1]
        for item in candidates[start + 1 :]:
            num, y0, _text = item
            if y0 <= last_y + 8:
                continue
            if num == last_num:
                continue
            step = num - last_num
            if 1 <= step <= 8:
                seq.append(item)
                last_num = num
                last_y = y0
            elif num > last_num + 40 and len(seq) < 2:
                break
        if len(seq) > len(best) or (
            len(seq) == len(best) and sum(x[0] for x in seq) > sum(x[0] for x in best)
        ):
            best = seq
    if len(best) >= 2:
        return best
    # Mixed pages can contain one last structure-table row followed by the next
    # prose Example scheme. Do not turn a decreasing sequence like 497, 126 into
    # two table rows; keep the first table-row candidate only.
    for prev, current in zip(candidates, candidates[1:]):
        if current[0] < prev[0]:
            return [candidates[0]]
    return candidates


def _is_structure_table_layout(
    page_structs: List[Dict],
    page_text: str,
    ocr_lines: Optional[List[Tuple[float, str]]] = None,
    active_bases: Optional[set[int]] = None,
) -> bool:
    if len(page_structs) < 1:
        return False
    if not _is_structure_table_context(page_text, ocr_lines):
        return False
    row_numbers = _extract_table_row_numbers(page_text)
    if active_bases:
        line_numbers = _extract_table_row_numbers_from_lines(
            ocr_lines, active_bases, page_structs
        )
        if len(line_numbers) >= 2:
            row_numbers = [num for num, _y, _text in line_numbers]
        elif line_numbers:
            row_numbers = [num for num, _y, _text in line_numbers]
    min_rows = 1 if active_bases else (1 if len(page_structs) <= 2 else 2)
    if len(row_numbers) < min_rows:
        return False
    if active_bases and line_numbers:
        return True
    xs = [float(p["x0"]) for p in page_structs]
    x_spread = max(xs) - min(xs) if xs else 0.0
    return x_spread < 240.0


def _extract_structure_table_bindings(
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    existing_bindings: List[Dict],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Bind table rows by vertical order when OCR labels are not attached to structures.

    WIPO structure tables often render each row as:
    row-id | structure | name | LC-MS
    DECIMER sees the left-column structure, but the compound number lives in the
    text row rather than directly under the drawing. In that layout, bind row
    numbers to structures by shared top-to-bottom order.
    """
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return []

    used_structure_ids = {
        str(binding.get("structure_id"))
        for binding in existing_bindings
        if binding.get("structure_id")
    }
    existing_base_nums = {
        _base_cpd_num(binding.get("cpd", "")) for binding in existing_bindings
    }
    existing_base_nums.discard(None)
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    bindings: List[Dict] = []
    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_structs = sorted(
            [
                p
                for p in processed_structures
                if p["page_no"] == page_no and p["id"] not in used_structure_ids
            ],
            key=lambda p: (float(p["y0"]), float(p["x0"])),
        )
        if not page_structs:
            continue

        page_text = _page_text_for_page_no(pages_text, page_no)
        page_lines = lines_by_page.get(page_no - 1) or []
        if not _is_structure_table_layout(
            page_structs, page_text, ocr_lines=page_lines, active_bases=active_bases
        ):
            continue

        row_entries = _extract_table_row_numbers_from_lines(
            page_lines, active_bases, page_structs
        )
        if not row_entries:
            # Activity-led table binding must be anchored by the real left ID
            # column. A trailing "Table 3" heading on the previous synthesis page
            # must not let route intermediates consume the next page's row IDs.
            continue
        row_numbers = [num for num, _y, _text in row_entries]
        if not row_numbers:
            row_numbers = _extract_table_row_numbers(page_text)
        if not row_numbers:
            continue

        struct_rows = _group_structures_by_row(page_structs, y_threshold=55.0)
        if not struct_rows:
            continue

        row_structs = []
        for row in struct_rows:
            if not row:
                continue
            struct = _best_table_structure_from_row(row, page_structs)
            if struct:
                row_structs.append(struct)
        if not row_structs:
            continue

        if row_entries:
            row_pairs = []
            row_available = list(enumerate(struct_rows))
            for compound_num, y0, _text in row_entries:
                if not row_available:
                    break
                best_idx, best_row = min(
                    row_available,
                    key=lambda pair: abs(
                        float(y0) - (_structure_row_bounds(pair[1])[2])
                    ),
                )
                best_distance = abs(float(y0) - _structure_row_bounds(best_row)[2])
                if best_distance > 95.0:
                    continue
                best_struct = _best_table_structure_for_row_label(
                    best_row, y0, page_structs
                )
                if not best_struct:
                    continue
                row_pairs.append((compound_num, best_struct))
                row_available = [item for item in row_available if item[0] != best_idx]
        elif len(row_numbers) == len(row_structs):
            row_pairs = list(zip(row_numbers, row_structs))
        else:
            row_pairs = []
            if len(row_numbers) == 1:
                row_pairs.append((row_numbers[0], row_structs[0]))
            else:
                last_num_idx = len(row_numbers) - 1
                last_struct_idx = len(row_structs) - 1
                used_struct_indices = set()
                for num_idx, compound_num in enumerate(row_numbers):
                    struct_idx = (
                        round(num_idx * last_struct_idx / last_num_idx)
                        if last_struct_idx > 0
                        else 0
                    )
                    if struct_idx in used_struct_indices:
                        continue
                    used_struct_indices.add(struct_idx)
                    row_pairs.append((compound_num, row_structs[struct_idx]))

        for compound_num, struct in row_pairs:
            if compound_num not in active_bases or compound_num in existing_base_nums:
                continue
            binding = _build_binding_from_structure(struct, str(compound_num))
            binding["binding_rule"] = "structure_table_row_order"
            bindings.append(binding)
            used_structure_ids.add(struct["id"])
            existing_base_nums.add(compound_num)

    return bindings


def _extract_structure_table_sequence_bindings(
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    existing_bindings: Optional[List[Dict]] = None,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Build full-page structure-table bindings from row order.

    OCR can misread left-column IDs such as 10/62/68 as 2/30/30 while the page
    still has enough neighboring rows to recover the intended sequence. This
    helper treats the activity list as the canonical allowed sequence and emits
    table candidates only when a page's row order can be anchored by the left
    column or adjacent already-bound table pages.
    """
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return []

    active_numbers = [
        n for n in (_base_cpd_num(cpd) for cpd in active_cpds) if n is not None
    ]
    active_number_set = set(active_numbers)
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    # Keep table anchors from existing strong candidates. Direct labels are
    # intentionally not used here because synthesis-route labels can compete
    # with the same compound number printed later in the structure table.
    anchors: List[Tuple[int, int, float]] = []
    for binding in existing_bindings or []:
        if str(binding.get("binding_rule") or "") not in {
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
        }:
            continue
        sig = _table_row_signature_from_binding(binding)
        if sig:
            anchors.append(sig)

    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)

    page_rows: Dict[int, List[Dict]] = {}
    page_entries: Dict[int, List[Tuple[int, float, str]]] = {}
    for page_no in sorted(by_page):
        page_structs = sorted(
            by_page[page_no],
            key=lambda p: (float(p.get("y0") or 0), float(p.get("x0") or 0)),
        )
        page_text = _page_text_for_page_no(pages_text, page_no)
        page_lines = lines_by_page.get(page_no - 1) or []
        if not _is_structure_table_layout(
            page_structs, page_text, ocr_lines=page_lines, active_bases=active_bases
        ):
            continue
        struct_rows = _group_structures_by_row(page_structs, y_threshold=55.0)
        row_structs: List[Dict] = []
        for row in struct_rows:
            struct = _best_table_structure_from_row(row, page_structs)
            if struct:
                row_structs.append(struct)
        if not row_structs:
            continue
        page_rows[page_no] = row_structs
        page_entries[page_no] = _extract_table_row_numbers_from_lines(
            page_lines, active_bases, page_structs
        )
        for num, y0, _text in page_entries[page_no]:
            if num in active_number_set:
                anchors.append((page_no, num, float(y0)))

    if not page_rows:
        return []

    # Build compact candidate sequences: exact OCR, same-page anchors, adjacent
    # table-page continuity, and global active-order windows. Scoring prefers
    # row-aligned OCR but allows correction when a minority of OCR IDs are
    # obvious misreads inside an otherwise contiguous active sequence.
    page_order = sorted(page_rows)
    prev_page: Dict[int, int] = {}
    next_page: Dict[int, int] = {}
    for idx, page_no in enumerate(page_order):
        if idx:
            prev_page[page_no] = page_order[idx - 1]
        if idx < len(page_order) - 1:
            next_page[page_no] = page_order[idx + 1]

    bindings: List[Dict] = []
    seen: set[Tuple[int, str]] = set()
    for page_no in page_order:
        row_structs = page_rows[page_no]
        row_count = len(row_structs)
        if not row_count:
            continue
        row_centers = [
            (
                float(struct.get("y0") or 0)
                + float(struct.get("y1") or struct.get("y0") or 0)
            )
            / 2.0
            for struct in row_structs
        ]
        entries = page_entries.get(page_no, [])

        candidate_sequences: List[Tuple[List[int], int]] = []
        entry_nums = [num for num, _y, _text in entries]
        active_windows = [
            active_numbers[i : i + row_count]
            for i in range(0, max(0, len(active_numbers) - row_count + 1))
            if len(active_numbers[i : i + row_count]) == row_count
        ]
        if entry_nums in active_windows:
            candidate_sequences.append((entry_nums, 0))

        for anchor_page, anchor_num, anchor_y in anchors:
            if anchor_page != page_no or anchor_num not in active_number_set:
                continue
            idx = min(range(row_count), key=lambda i: abs(row_centers[i] - anchor_y))
            if abs(row_centers[idx] - anchor_y) <= 95.0:
                start = anchor_num - idx
                seq = [start + i for i in range(row_count)]
                if all(num in active_number_set for num in seq):
                    candidate_sequences.append((seq, 2))

        prev = prev_page.get(page_no)
        if prev in page_rows:
            # Last reliable row on the previous table page.
            prev_entries = page_entries.get(prev, [])
            prev_nums = [
                num for num, _y, _text in prev_entries if num in active_number_set
            ]
            if prev_nums:
                seq = [prev_nums[-1] + i for i in range(1, row_count + 1)]
                if all(num in active_number_set for num in seq):
                    candidate_sequences.append((seq, 1))
        nxt = next_page.get(page_no)
        if nxt in page_rows:
            next_entries = page_entries.get(nxt, [])
            next_nums = [
                num for num, _y, _text in next_entries if num in active_number_set
            ]
            if next_nums:
                start = next_nums[0] - row_count
                seq = [start + i for i in range(row_count)]
                if all(num in active_number_set for num in seq):
                    candidate_sequences.append((seq, 1))

        unique_sequences: List[Tuple[List[int], int]] = []
        seen_sequences: set[Tuple[int, ...]] = set()
        for seq, source_rank in candidate_sequences:
            signature = tuple(seq)
            if signature in seen_sequences:
                for idx, (known_seq, known_rank) in enumerate(unique_sequences):
                    if tuple(known_seq) == signature and source_rank < known_rank:
                        unique_sequences[idx] = (seq, source_rank)
                        break
                continue
            seen_sequences.add(signature)
            unique_sequences.append((seq, source_rank))

        if not unique_sequences:
            continue

        def _seq_score(item: Tuple[List[int], int]) -> Tuple[float, int, int, int, int]:
            seq, source_rank = item
            matches = 0
            distance = 0.0
            for num, y0, _text in entries:
                if num not in seq:
                    continue
                idx = seq.index(num)
                matches += 1
                distance += abs(float(y0) - row_centers[idx])
            monotonic = 0 if all(b > a for a, b in zip(seq, seq[1:])) else 1
            mismatches = max(0, len(entries) - matches)
            # Strongly prefer matching real left-column OCR, but do not let one
            # or two OCR confusions beat a fully active contiguous sequence.
            return (
                source_rank,
                -matches,
                distance + mismatches * 35.0,
                monotonic,
                seq[0],
                len(seq),
            )

        best_seq, _best_source_rank = min(unique_sequences, key=_seq_score)
        best_score = _seq_score((best_seq, _best_source_rank))
        if _best_source_rank > 2:
            continue
        if entries and best_score[2] > 180.0:
            continue

        for num, struct in zip(best_seq, row_structs):
            if num not in active_number_set:
                continue
            sid = str(struct.get("id") or "")
            marker = (num, sid)
            if marker in seen:
                continue
            binding = _build_binding_from_structure(struct, str(num))
            binding["binding_rule"] = "structure_table_row_order_corrected"
            binding["table_sequence_recovery"] = {
                "page_no": page_no,
                "sequence": best_seq,
                "ocr_row_ids": entry_nums,
            }
            bindings.append(binding)
            seen.add(marker)

    return bindings


def _row_center_from_binding(binding: Dict) -> Optional[float]:
    y0 = binding.get("struct_y0")
    if y0 is None:
        return None
    try:
        height = float(binding.get("struct_height") or 0)
        return float(y0) + (height / 2.0)
    except Exception:
        try:
            return float(y0)
        except Exception:
            return None


def _table_row_signature_from_binding(
    binding: Dict,
) -> Optional[Tuple[int, int, float]]:
    base = _binding_base_num(binding)
    page_no = binding.get("page_no")
    y_center = _row_center_from_binding(binding)
    if base is None or page_no is None or y_center is None:
        return None
    try:
        return int(page_no), int(base), float(y_center)
    except Exception:
        return None


def _infer_table_page_row_numbers(
    page_no: int,
    row_structs: List[Dict],
    known_bindings: List[Dict],
    active_bases: set[int],
) -> List[int]:
    """Infer missing table-row labels from neighboring bound table rows.

    This is deliberately conservative: it only fills labels on pages that
    already have table-row bindings immediately before or after the current
    page, and it only emits active compound numbers. It repairs OCR misses at
    page boundaries without inventing non-active synthesis rows.
    """
    row_count = len(row_structs)
    if row_count == 0:
        return []

    table_rules = {
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "direct_structure_label",
        "direct_structure_label_right_product_crop",
    }
    known = [
        binding
        for binding in known_bindings
        if str(binding.get("binding_rule") or "") in table_rules
        and _binding_base_num(binding) in active_bases
    ]

    same_page = [
        item for item in known if int(item.get("page_no") or -1) == int(page_no)
    ]
    if same_page:
        signatures = [_table_row_signature_from_binding(item) for item in same_page]
        signatures = [sig for sig in signatures if sig]
        if signatures:
            signatures.sort(key=lambda sig: sig[2])
            row_centers = [
                (
                    float(struct.get("y0") or 0)
                    + float(struct.get("y1") or struct.get("y0") or 0)
                )
                / 2.0
                for struct in row_structs
            ]
            anchors: List[Tuple[int, int]] = []
            for _p, num, y_center in signatures:
                idx = min(
                    range(row_count), key=lambda i: abs(row_centers[i] - y_center)
                )
                if abs(row_centers[idx] - y_center) <= 90.0:
                    anchors.append((idx, num))
            anchors = sorted(set(anchors))
            if anchors:
                candidates = []
                for idx, num in anchors:
                    start = num - idx
                    seq = [start + i for i in range(row_count)]
                    if all(n in active_bases for n in seq):
                        candidates.append(seq)
                if candidates:
                    return candidates[0]

    previous = [
        sig
        for sig in (_table_row_signature_from_binding(item) for item in known)
        if sig and sig[0] < page_no
    ]
    next_items = [
        sig
        for sig in (_table_row_signature_from_binding(item) for item in known)
        if sig and sig[0] > page_no
    ]

    candidates: List[List[int]] = []
    if previous:
        prev_page, prev_num, _prev_y = max(previous, key=lambda sig: (sig[0], sig[2]))
        if page_no - prev_page <= 2:
            seq = [prev_num + i for i in range(1, row_count + 1)]
            if all(n in active_bases for n in seq):
                candidates.append(seq)
    if next_items:
        next_page, next_num, _next_y = min(next_items, key=lambda sig: (sig[0], sig[2]))
        if next_page - page_no <= 2:
            start = next_num - row_count
            seq = [start + i for i in range(row_count)]
            if all(n in active_bases for n in seq):
                candidates.append(seq)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 2 and candidates[0] == candidates[1]:
        return candidates[0]
    return []


def _repair_missing_structure_table_bindings(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return final_bindings

    existing_base_nums = {_binding_base_num(binding) for binding in final_bindings}
    existing_base_nums.discard(None)
    missing_bases = active_bases - existing_base_nums
    if not missing_bases:
        return final_bindings

    used_structure_ids = {
        str(binding.get("structure_id") or "")
        for binding in final_bindings
        if binding.get("structure_id")
    }
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    additions: List[Dict] = []

    for page_no in sorted(set(int(p["page_no"]) for p in processed_structures)):
        page_structs = sorted(
            [
                p
                for p in processed_structures
                if int(p.get("page_no") or 0) == page_no
                and str(p.get("id") or "") not in used_structure_ids
            ],
            key=lambda p: (float(p.get("y0") or 0), float(p.get("x0") or 0)),
        )
        if not page_structs:
            continue
        page_text = _page_text_for_page_no(pages_text, page_no)
        page_lines = lines_by_page.get(page_no - 1) or []
        if not _is_structure_table_layout(
            page_structs, page_text, ocr_lines=page_lines, active_bases=active_bases
        ):
            continue

        struct_rows = _group_structures_by_row(page_structs, y_threshold=55.0)
        row_structs = []
        for row in struct_rows:
            if not row:
                continue
            struct = _best_table_structure_from_row(row, page_structs)
            if struct:
                row_structs.append(struct)
        if not row_structs:
            continue

        inferred = _infer_table_page_row_numbers(
            page_no,
            row_structs,
            [*final_bindings, *additions],
            active_bases,
        )
        if len(inferred) != len(row_structs):
            continue

        for compound_num, struct in zip(inferred, row_structs):
            if compound_num not in missing_bases:
                continue
            sid = str(struct.get("id") or "")
            if sid in used_structure_ids:
                continue
            binding = _build_binding_from_structure(struct, str(compound_num))
            binding["binding_rule"] = "structure_table_row_order_inferred"
            binding["table_inference"] = "neighbor_page_continuity"
            additions.append(binding)
            used_structure_ids.add(sid)
            missing_bases.discard(compound_num)

    if additions:
        logger.info(
            "   表格续页编号补漏: 新增 %d 个活性结构绑定 %s",
            len(additions),
            [binding["cpd"] for binding in additions],
        )
        return _merge_binding_candidates(
            final_bindings, additions, active_cpds=active_cpds
        )
    return final_bindings
