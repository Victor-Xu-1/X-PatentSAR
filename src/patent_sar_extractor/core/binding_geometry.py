"""Pure segmented-structure geometry and row selection."""

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

from .binding_labels import (
    _STRICT_VISIBLE_LABEL_SOURCES,
    _cpd_letter_pair_bases_from_text,
)
from .binding_types import (
    BinderConfig,
)

logger = logging.getLogger(__name__)


def _process_structure(s: Dict) -> Dict:
    """处理结构数据，返回标准化格式"""
    # bbox_pdf 优先，fallback 到 bbox
    for key in ("bbox_pdf", "bbox"):
        bbox_raw = s.get(key, [])
        if len(bbox_raw) == 4:
            x0_pdf, y0_pdf, x1_pdf, y1_pdf = bbox_raw
            break
    else:
        x0_pdf, y0_pdf, x1_pdf, y1_pdf = 0, 0, 0, 0

    page_no = s.get("page_no", s.get("page_num", 0))
    image_path = s.get(
        "image_path",
        s.get("orig_path", s.get("bnw_path", s.get("norm_path", None))),
    )

    return {
        "struct": s,
        "x0": x0_pdf,
        "y0": y0_pdf,
        "x1": x1_pdf,
        "y1": y1_pdf,
        "page_no": page_no,
        "idx": s["structure_index"],
        "id": s["structure_id"],
        "image_path": image_path,
    }


def _select_best_structure_v4(
    candidate_structs: List[Dict],
    config: BinderConfig,
    heading_page: Optional[int] = None,
) -> Optional[Dict]:
    """V4.1 选择算法 — 同页优先，避免跨页远距离误绑。

    Args:
        candidate_structs: 候选结构列表
        config: 绑定配置
        heading_page: 标题所在页码（1-indexed），用于同页优先策略
    """
    if not candidate_structs:
        return None

    if len(candidate_structs) > 1:

        def _area(struct: Dict) -> float:
            return max(
                0.0, float(struct.get("x1", 0)) - float(struct.get("x0", 0))
            ) * max(0.0, float(struct.get("y1", 0)) - float(struct.get("y0", 0)))

        areas = [_area(p) for p in candidate_structs]
        max_area = max(areas) if areas else 0.0
        if max_area > 0:
            large_structs = [
                p for p in candidate_structs if _area(p) >= max(max_area * 0.45, 4500.0)
            ]
            if large_structs:
                candidate_structs = large_structs

    # V4.1: 同页优先策略
    if heading_page is not None and len(candidate_structs) > 1:
        same_page_structs = [
            p for p in candidate_structs if p["page_no"] == heading_page
        ]
        if len(same_page_structs) >= 2:
            candidate_structs = same_page_structs
            logger.debug(f"   V4.1同页优先: {len(same_page_structs)}个同页候选")
        elif len(same_page_structs) == 1:
            return same_page_structs[0]

    max_page = max(p["page_no"] for p in candidate_structs)
    last_page_structs = [p for p in candidate_structs if p["page_no"] == max_page]

    if not last_page_structs:
        return max(candidate_structs, key=lambda x: x["y0"])

    sorted_by_y0 = sorted(last_page_structs, key=lambda x: x["y0"])
    clusters: List[List[Dict]] = []
    current_cluster = [sorted_by_y0[0]]
    for p in sorted_by_y0[1:]:
        if p["y0"] - current_cluster[-1]["y0"] < config.cluster_y_threshold:
            current_cluster.append(p)
        else:
            clusters.append(current_cluster)
            current_cluster = [p]
    clusters.append(current_cluster)

    max_y0_cluster = max(clusters, key=lambda c: max(p["y0"] for p in c))

    if len(max_y0_cluster) >= 2:
        best_cluster = max_y0_cluster
    else:
        best_cluster = None
        max_count = -1
        max_y0 = -1

        for cluster in clusters:
            count = len(cluster)
            cluster_y0 = max(p["y0"] for p in cluster)
            if count > max_count:
                max_count = count
                max_y0 = cluster_y0
                best_cluster = cluster
            elif count == max_count:
                if cluster_y0 > max_y0:
                    max_y0 = cluster_y0
                    best_cluster = cluster

    best_p = max(best_cluster, key=lambda x: x["x0"])
    return best_p


def _row_for_structure(
    struct: Dict,
    rows_by_page: Optional[Dict[int, List[List[Dict]]]],
) -> Optional[List[Dict]]:
    if not rows_by_page:
        return None
    sid = str(struct.get("id") or "")
    page_no = int(struct.get("page_no") or 0)
    for row in rows_by_page.get(page_no, []):
        if any(str(item.get("id") or "") == sid for item in row):
            return row
    return None


def _group_structures_by_row(
    page_structs: List[Dict], y_threshold: float = 65.0
) -> List[List[Dict]]:
    rows: List[List[Dict]] = []
    for struct in sorted(page_structs, key=lambda p: (p["y0"], p["x0"])):
        if not rows or abs(struct["y0"] - rows[-1][0]["y0"]) > y_threshold:
            rows.append([struct])
        else:
            rows[-1].append(struct)
    return [sorted(row, key=lambda p: p["x0"]) for row in rows]


def _structure_row_bounds(row: List[Dict]) -> Tuple[float, float, float]:
    y0 = min(float(s.get("y0") or 0) for s in row)
    y1 = max(float(s.get("y1") or s.get("y0") or 0) for s in row)
    return y0, y1, (y0 + y1) / 2.0


def _is_probable_table_structure(
    struct: Dict, page_structs: Optional[List[Dict]] = None
) -> bool:
    """Keep table row binding focused on the left structure column."""
    geom = _structure_geometry(struct)
    area = geom["struct_area"]
    width = geom["struct_width"]
    height = geom["struct_height"]
    aspect = geom["struct_aspect"]
    x0 = float(struct.get("x0") or 0)
    if area < 5000 or width < 70 or height < 55 or aspect > 4.6:
        return False
    if x0 > 330:
        return False

    if page_structs:
        table_like = [
            p
            for p in page_structs
            if _structure_geometry(p)["struct_area"] >= 5000
            and 70 <= _structure_geometry(p)["struct_width"] <= 190
            and _structure_geometry(p)["struct_height"] >= 55
            and float(p.get("x0") or 0) <= 330
        ]
        if len(table_like) >= 2:
            xs = sorted(float(p.get("x0") or 0) for p in table_like)
            median_x = xs[len(xs) // 2]
            if abs(x0 - median_x) > 95:
                return False
    return True


def _is_complete_visible_product_module(struct: Dict) -> bool:
    geom = _structure_geometry(struct)
    return (
        geom["struct_area"] >= 6500
        and geom["struct_width"] >= 80
        and geom["struct_height"] >= 65
        and geom["struct_aspect"] <= 4.6
    )


def _has_strong_structure_table_row_evidence(binding: Dict) -> bool:
    """Return True when the binding is anchored by a real structure-table row.

    In Ex#/Structure/LCMS/NMR tables the authoritative product ID is often the
    left text column, not a label printed under the drawing. Internal structure
    annotations can be OCR'd as active-looking numbers, so table rows need their
    own confidence gate instead of being treated like direct visual labels.
    """
    rule = str(binding.get("binding_rule") or "")
    if rule not in {
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "cmpd_overview_table_order",
    }:
        return False
    try:
        return float(binding.get("struct_area") or 0) >= 6500
    except Exception:
        return False


def _best_table_structure_from_row(
    row: List[Dict], page_structs: Optional[List[Dict]] = None
) -> Optional[Dict]:
    candidates = [s for s in row if _is_probable_table_structure(s, page_structs)]
    if not candidates:
        candidates = [
            s
            for s in row
            if _structure_geometry(s)["struct_area"] >= 4500
            and float(s.get("x0") or 0) <= 330
        ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda p: (
            abs(float(p.get("x0") or 0) - 150.0),
            -int(_structure_geometry(p)["struct_area"]),
        ),
    )


def _best_table_structure_for_row_label(
    row: List[Dict],
    label_y0: float,
    page_structs: Optional[List[Dict]] = None,
) -> Optional[Dict]:
    """Choose the product drawing on the same table row as a left ID label."""
    if not row:
        return None
    try:
        label_y = float(label_y0)
    except Exception:
        return _best_table_structure_from_row(row, page_structs)

    candidates = []
    for struct in row:
        geom = _structure_geometry(struct)
        center = (
            float(struct.get("y0") or 0)
            + float(struct.get("y1") or struct.get("y0") or 0)
        ) / 2.0
        if abs(center - label_y) > 105.0:
            continue
        if (
            geom["struct_area"] < 5000
            or geom["struct_width"] < 70
            or geom["struct_height"] < 55
        ):
            continue
        candidates.append(struct)
    if not candidates:
        return _best_table_structure_from_row(row, page_structs)

    # In OCR line coordinates the left-column ID is vertically aligned with the
    # row. A row may also contain reagents/intermediates on the left or small
    # fragments near the ID. The final product is usually the largest complete
    # module to the right side of that row.
    return max(
        candidates,
        key=lambda struct: (
            float(struct.get("x0") or 0),
            _structure_geometry(struct)["struct_area"],
        ),
    )


def _right_complete_product_on_same_row(
    struct: Dict,
    rows_by_page: Dict[int, List[List[Dict]]],
    min_area_ratio: float = 1.05,
) -> Optional[Dict]:
    """Return a larger/right-side complete product module from the same visual row."""
    sid = str(struct.get("id") or "")
    if not sid:
        return None
    page_no = int(struct.get("page_no") or 0)
    struct_x0 = float(struct.get("x0") or 0)
    struct_area = _structure_geometry(struct)["struct_area"]
    for row in rows_by_page.get(page_no, []):
        if not any(str(item.get("id") or "") == sid for item in row):
            continue
        right_complete = [
            item
            for item in row
            if float(item.get("x0") or 0) > struct_x0 + 25
            and _is_complete_visible_product_module(item)
            and _structure_geometry(item)["struct_area"]
            >= max(struct_area * min_area_ratio, 6500)
        ]
        if not right_complete:
            return None
        return max(
            right_complete,
            key=lambda item: (
                _structure_geometry(item)["struct_area"],
                float(item.get("x0") or 0),
            ),
        )
    return None


def _is_cpd_letter_pair_product_candidate(struct: Dict) -> bool:
    """Accept compact final-product drawings in Cpd-N/Cpd-NA paired schemes."""
    geom = _structure_geometry(struct)
    return (
        geom["struct_area"] >= 5000
        and geom["struct_width"] >= 60
        and geom["struct_height"] >= 55
        and geom["struct_aspect"] <= 3.2
    )


def _has_cpd_letter_pair_product_text(base: int, page_text: str) -> bool:
    """Return True for result/prose rows mentioning Cpd-N and Cpd-NA."""
    text = re.sub(r"\s+", " ", str(page_text or ""))
    if not text or re.search(r"实施例|Example|制备", text[:160], re.IGNORECASE):
        return False
    if re.search(
        r"备注|相同|采用|参考|参照|same\s+route|same\s+procedure", text, re.IGNORECASE
    ):
        return False
    return base in _cpd_letter_pair_bases_from_text(text)


def _structure_geometry(struct: Dict) -> Dict[str, float]:
    """Return normalized geometry for a processed structure or saved binding."""
    x0 = float(struct.get("x0", struct.get("struct_x0", 0)) or 0)
    y0 = float(struct.get("y0", struct.get("struct_y0", 0)) or 0)
    x1 = float(struct.get("x1", struct.get("struct_x1", x0)) or x0)
    y1 = float(struct.get("y1", struct.get("struct_y1", y0)) or y0)
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    area = width * height
    aspect = width / max(height, 1.0)
    return {
        "struct_x1": x1,
        "struct_y1": y1,
        "struct_width": width,
        "struct_height": height,
        "struct_area": area,
        "struct_aspect": aspect,
    }


def _attach_structure_geometry(binding: Dict, struct: Dict) -> Dict:
    binding.update(_structure_geometry(struct))
    return binding


def _visual_module_score(struct: Dict) -> Tuple[int, int, int]:
    """Score whether a crop looks like a standalone final-product module."""
    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    area = width * height
    # Big complete modules should beat small intermediates/fragments. Keep the
    # threshold permissive because long flat products can have modest height.
    route_rank = 2 if (height > 0 and width / max(height, 1.0) > 5.5) else 0
    complete_rank = 0 if (area >= 6000 and width >= 70 and height >= 35) else 1
    page_y = float(struct.get("y0") or 0)
    # Prefer standalone modules printed before the reaction/prose block when
    # the same label appears twice on the page.
    return (
        route_rank,
        complete_rank,
        int(page_y),
        -int(area),
        int(struct.get("idx") or 999999),
    )


def _is_complete_product_like_structure(struct: Dict) -> bool:
    """Reject route fragments when visual labels are used without text context."""
    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    area = width * height
    aspect = width / max(height, 1.0)
    if area < 5600 or width < 65 or height < 55:
        return False
    if aspect > 4.2:
        return False
    return True


def _is_ocsr_single_molecule_source(struct: Dict) -> bool:
    """Return whether a segmented crop is large enough for standalone OCSR.

    Final products can be long and flat, so this is more permissive than the
    binding module check. It still rejects compact route fragments such as
    protected intermediates that carry an incidental visible number.
    """
    geom = _structure_geometry(struct)
    width = geom["struct_width"]
    height = geom["struct_height"]
    area = geom["struct_area"]
    aspect = geom["struct_aspect"]
    return area >= 4200 and width >= 100 and height >= 28 and aspect <= 5.5


def _is_final_label_band_product_like(
    struct: Dict, visual_candidate: Optional[Dict[str, Any]] = None
) -> bool:
    """Allow compact final products when a strict label is printed under them."""
    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    area = width * height
    aspect = width / max(height, 1.0)
    source = str((visual_candidate or {}).get("source") or "")
    if source not in _STRICT_VISIBLE_LABEL_SOURCES:
        return False
    return area >= 4200 and width >= 60 and height >= 55 and aspect <= 2.4


def _route_product_structures_from_page(page_structs: List[Dict]) -> List[Dict]:
    products: List[Dict] = []
    rows = _group_structures_by_row(page_structs, y_threshold=65.0)
    for row in rows:
        if len(row) < 2:
            continue
        candidates = [
            struct for struct in row if _is_complete_visible_product_module(struct)
        ]
        if not candidates:
            continue
        product = max(
            candidates,
            key=lambda struct: (
                float(struct.get("x0") or 0),
                _structure_geometry(struct)["struct_area"],
            ),
        )
        products.append(product)
    return products
