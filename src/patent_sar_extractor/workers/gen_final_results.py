#!/usr/bin/env python3
"""
最终结果生成：Excel + SDF
输入：绑定 JSON + SMILES JSON + 活性数据 JSON（含 assay 元数据）
输出：XXX_final.xlsx + XXX_final.sdf

活性数据JSON格式：
{
  "assays": [
    {
      "target": "IGF-1R",
      "test_type": "IC50",
      "unit": "nM",
      "description": "ADP-Glo kinase assay",
      "grades": {
        "A": "0 < IC50 < 500 nM（最强）",
        "B": "500 nM < IC50 < 2 μM",
        ...
      }
    },
    ...
  ],
  "data": {
    "Example1": {"IGF-1R": "C", "IR": "C"},
    ...
  }
}

也兼容旧格式（无assays字段，直接{CpdID: {target: grade}}）
"""
import json, os, sys, argparse, shutil, re, tempfile
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XlImage

try:
    from rdkit import Chem
    from rdkit.Chem import rdFingerprintGenerator, Descriptors, DataStructs
    RDKIT_AVAILABLE = True
except ImportError:
    RDKIT_AVAILABLE = False

# ===== 配置 =====
PACKAGE_IMPORT_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_IMPORT_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_IMPORT_ROOT))

WORKING_ROOT = str(Path.cwd())

from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    artifact_identity_matches,
)
from patent_sar_extractor.failures import clear_failure_marker, write_failure_marker
from patent_sar_extractor.smiles_artifact import smiles_artifact_is_current, smiles_records
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy, summarise_binding_accuracy
from patent_sar_extractor.core.activity_values import has_usable_activity_values

# 活性分级填充色
GRADE_FILLS = {
    "A": PatternFill("solid", fgColor="92D050"),
    "B": PatternFill("solid", fgColor="FFC000"),
    "C": PatternFill("solid", fgColor="FF9900"),
    "D": PatternFill("solid", fgColor="FF4444"),
    "+": PatternFill("solid", fgColor="92D050"),
    "-": PatternFill("solid", fgColor="FF4444"),
}

# Excel样式
HEADER_FILL = PatternFill("solid", fgColor="4472C4")
HEADER_FONT = Font(bold=True, size=11, color="FFFFFF")
THIN_BORDER = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin')
)
NOTE_FONT = Font(size=9, color="666666")
NOTE_FILL = PatternFill("solid", fgColor="F2F2F2")

# 图片嵌入尺寸
IMG_WIDTH_PX = 450
IMG_HEIGHT_PX = 300
ROW_HEIGHT_PT = 230

# 固定列定义 (name, width) — 活性列在运行时动态生成
FIXED_COLUMNS = [
    ("Cpd ID", 14),
    ("正文化合物编号", 16),
    ("页码", 8),
    ("结构索引", 10),
    ("结构图", 62),
    ("SMILES", 55),
    ("分子式", 16),
    ("分子量", 10),
    ("环数", 6),
    ("手性中心", 8),
]


def _normalize_cpd_label(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if re.fullmatch(
        r"(?:claim\s*1\s+compound|claimed\s+compound|main\s+compound|single(?:ton)?\s+compound)",
        text,
        re.IGNORECASE,
    ):
        return "Claim 1 compound"
    m = re.search(r"(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*(\d+(?:-\d+)?[A-Z]?)", text, re.IGNORECASE)
    if m:
        return f"Compound {m.group(1).upper()}"
    bare = re.fullmatch(r"(\d+(?:-\d+)?[A-Z]?)", text, re.IGNORECASE)
    if bare:
        return f"Compound {bare.group(1).upper()}"
    return text


_CONTROL_LABEL_RE = re.compile(
    r"^(?:ref\.?\s*\d+|reference\b|vehicle\b|dmso\b|control\b|nab[-\s]?paclitaxel\b|paclitaxel\b)",
    re.IGNORECASE,
)


def _is_control_or_reference_label(value):
    return bool(_CONTROL_LABEL_RE.match(re.sub(r"\s+", " ", str(value or "")).strip()))


def _resolve_display_image_path(binding, project_root):
    """Choose the human-facing structure image, not an OCSR repair crop."""
    for key in ("display_image_path", "source_image_path", "image_path"):
        path = str(binding.get(key, "") or "").strip()
        if not path:
            continue
        if not os.path.isabs(path):
            path = os.path.join(project_root, path)
        if os.path.exists(path):
            return path
    return ""


def _binding_is_safe_for_final(binding):
    if binding.get("fail_closed") is True:
        return False
    status = str(binding.get("accuracy_status") or "").strip()
    return status == "confirmed"


def _expand_cpd_labels(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    prefix_match = re.match(r"^(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*(.+)$", text, re.IGNORECASE)
    if prefix_match and "/" in text:
        labels = []
        for part in prefix_match.group(1).split("/"):
            part = part.strip()
            if re.fullmatch(r"\d+(?:-\d+)?[A-Z]?", part, re.IGNORECASE):
                labels.append(f"Compound {part.upper()}")
        if labels:
            return list(dict.fromkeys(labels))
    normalized = _normalize_cpd_label(text)
    return [normalized] if normalized else []


def _cpd_sort_key(value):
    norm = _normalize_cpd_label(value)
    parts = re.findall(r"\d+|\D+", norm)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def _score_smiles_record(record):
    if not isinstance(record, dict):
        return (-1, -1, -1, -1)
    valid = 1 if record.get("rdkit_valid") else 0
    clean_ocsr = 1 if record.get("OCSR_quality_flag", "ok") == "ok" else 0
    has_smiles = 1 if (record.get("canonical_smiles") or record.get("raw_smiles")) else 0
    mw = float(record.get("mol_weight") or 0)
    return (clean_ocsr, valid, has_smiles, mw)


def _has_activity_values(values):
    return has_usable_activity_values(values)


def _row_activity_values(row):
    values = {}
    for field in ("activity_values", "cell_line_data"):
        bucket = row.get(field, {}) or {}
        if isinstance(bucket, dict):
            values.update(bucket)
    return values


PREFERRED_ACTIVITY_TARGET_ORDER = [
    "VCaP AR DC50 (nM)",
    "LNCaP AR DC50 (nM)",
    "LNCaP AR Dmax (%)",
    "VCaP proliferation IC50 (nM)",
    "LNCaP proliferation IC50 (nM)",
    "Human liver microsome remaining at 60 min (%)",
    "Mouse IV AUC (ng*h/mL)",
    "Mouse IV t1/2 (h)",
    "Mouse IV CL (L/hr/kg)",
    "Mouse PO AUC (ng*h/mL)",
    "Mouse PO t1/2 (h)",
    "Mouse PO Cmax (ng/mL)",
    "Mouse oral bioavailability F (%)",
]


def _activity_target_sort_key(target):
    try:
        return (0, PREFERRED_ACTIVITY_TARGET_ORDER.index(target))
    except ValueError:
        return (1, str(target))


def _build_smiles_maps(smiles_list):
    smiles_map = {}
    smiles_by_binding_key = {}
    smiles_by_structure_id = {}
    for record in smiles_list:
        cpd_id = record.get("cpd_id", "")
        structure_id = record.get("structure_id", "")
        cpd_keys = [k for k in {cpd_id, _normalize_cpd_label(cpd_id)} if k]
        for cpd_key in cpd_keys:
            current = smiles_map.get(cpd_key)
            if current is None or _score_smiles_record(record) > _score_smiles_record(current):
                smiles_map[cpd_key] = record
        if structure_id:
            current = smiles_by_structure_id.get(structure_id)
            if current is None or _score_smiles_record(record) > _score_smiles_record(current):
                smiles_by_structure_id[structure_id] = record
            for cpd_key in cpd_keys:
                smiles_by_binding_key[(cpd_key, structure_id)] = record
    return smiles_map, smiles_by_binding_key, smiles_by_structure_id


def _get_smiles_for_binding(binding, smiles_map, smiles_by_binding_key, smiles_by_structure_id=None):
    if binding.get("activity_only") or not binding.get("structure_id"):
        return {}
    cpd = binding.get("cpd", binding.get("cpd_id", ""))
    norm_cpd = _normalize_cpd_label(cpd)
    structure_id = binding.get("structure_id", "")
    for key in [cpd, norm_cpd]:
        if key and structure_id and (key, structure_id) in smiles_by_binding_key:
            return smiles_by_binding_key[(key, structure_id)]
    if structure_id:
        return (smiles_by_structure_id or {}).get(structure_id, {})
    for key in [cpd, norm_cpd]:
        if key and key in smiles_map:
            return smiles_map[key]
    return {}


def load_data(bindings_path, smiles_path, activity_data=None, activity_path=None, allow_partial=False):
    """加载绑定、SMILES、活性数据
    
    Returns:
        examples: list of binding dicts
        smiles_map: {cpd_id: smiles_result}
        activity_data: {cpd_id: {target: grade}}
        assays: list of assay metadata dicts (may be empty)
    """
    # 绑定
    with open(bindings_path) as f:
        raw = json.load(f)
    all_bindings = raw.get('final_bindings', raw.get('bindings', raw.get('compound_bindings', [])))
    fallback_structures = [
        b for b in all_bindings
        if b.get('prefix') == 'Structure'
        or b.get('binding_rule') == 'scanned_pdf_structure_sequence_fallback'
    ]
    if fallback_structures and len(fallback_structures) == len(all_bindings):
        print(
            "⚠️ 绑定结果为 Structure-* 兜底结构，未识别到正文化合物编号；"
            "不将这些结构写入最终化合物主表。"
        )
        all_bindings = []

    # 支持英文和中文实施例/化合物编号
    examples = [
        b for b in all_bindings
        if b.get('prefix', b.get('cpd', '')).startswith(
            ('Example', 'Cpd', 'Compound', 'Claim', '实施例', '化合物')
        )
    ]
    
    # SMILES
    with open(smiles_path) as f:
        smiles_payload = json.load(f)
    smiles_list = smiles_records(smiles_payload)
    smiles_map, smiles_by_binding_key, smiles_by_structure_id = _build_smiles_maps(smiles_list)
    
    # 活性
    act_data = {}
    activity_order = []
    assays = []
    
    if activity_path and os.path.exists(activity_path):
        with open(activity_path) as f:
            loaded = json.load(f)
        
        if isinstance(loaded, dict):
            # Activity extractor row format.
            if 'rows' in loaded and isinstance(loaded['rows'], list):
                for row in loaded['rows']:
                    values = _row_activity_values(row)
                    for cpd in _expand_cpd_labels(row.get('cpd', '')):
                        act_data.setdefault(cpd, {}).update(values)
                        if (
                            cpd not in activity_order
                            and _has_activity_values(values)
                            and not _is_control_or_reference_label(cpd)
                        ):
                            activity_order.append(cpd)
                    for key in values:
                        assays.append({
                            "target": key,
                            "test_type": "",
                            "unit": "",
                            "description": "",
                            "grades": {}
                        })
                # De-duplicate assays by target.
                seen = set()
                assays = [a for a in assays if not (a["target"] in seen or seen.add(a["target"]))]
            # 新格式: {assays: [...], data: {...}}
            elif 'assays' in loaded and 'data' in loaded:
                assays = loaded['assays']
                act_data = loaded['data']
                activity_order = [
                    _normalize_cpd_label(cpd)
                    for cpd, values in act_data.items()
                    if _normalize_cpd_label(cpd) and _has_activity_values(values)
                ]
            # 旧格式兼容: {CpdID: {target: grade}} — 无assay元数据
            elif any(isinstance(v, dict) for v in loaded.values()):
                act_data = loaded
                activity_order = [
                    _normalize_cpd_label(cpd)
                    for cpd, values in act_data.items()
                    if _normalize_cpd_label(cpd) and _has_activity_values(values)
                ]
                # 尝试从data中推断target列表
                targets = set()
                for v in act_data.values():
                    if isinstance(v, dict):
                        targets.update(v.keys())
                # 无assay元数据，生成默认
                for t in sorted(targets):
                    assays.append({
                        "target": t,
                        "test_type": "Activity",
                        "unit": "",
                        "description": "",
                        "grades": {}
                    })
            else:
                print(f"⚠️ 活性数据格式无法识别，跳过")
    elif activity_data:
        act_data = activity_data
        activity_order = [
            _normalize_cpd_label(cpd)
            for cpd, values in act_data.items()
            if _normalize_cpd_label(cpd) and _has_activity_values(values)
        ]

    # Only activity-bearing compounds may enter the deliverable. Normalize
    # labels and preserve their first appearance in the source tables.
    candidate_order = activity_order or list(act_data)
    active_act_data = {}
    for raw_cpd in candidate_order:
        cpd = _normalize_cpd_label(raw_cpd)
        values = act_data.get(raw_cpd, act_data.get(cpd, {}))
        if not cpd or _is_control_or_reference_label(cpd) or not _has_activity_values(values):
            continue
        active_act_data.setdefault(cpd, {}).update(values)
    act_data = active_act_data
    activity_order = list(act_data)
    
    binding_by_cpd = {}
    for binding in examples:
        norm_cpd = _normalize_cpd_label(binding.get('cpd', binding.get('cpd_id', '')))
        if not norm_cpd or _is_control_or_reference_label(norm_cpd):
            continue
        if not allow_partial and not _binding_is_safe_for_final(binding):
            continue
        values = _activity_for_cpd(act_data, norm_cpd)
        if act_data and not _has_activity_values(values):
            continue
        binding['original_cpd'] = binding.get('cpd', binding.get('cpd_id', ''))
        binding['cpd'] = norm_cpd
        binding['cpd_id'] = norm_cpd
        binding['compound_id'] = binding.get('compound_id') or norm_cpd
        current = binding_by_cpd.get(norm_cpd)
        if current is None or _score_smiles_record(_get_smiles_for_binding(binding, smiles_map, smiles_by_binding_key, smiles_by_structure_id)) > _score_smiles_record(_get_smiles_for_binding(current, smiles_map, smiles_by_binding_key, smiles_by_structure_id)):
            binding_by_cpd[norm_cpd] = binding

    examples = []
    canonical_order = activity_order or sorted(act_data, key=_cpd_sort_key)
    if isinstance(act_data, dict):
        for raw_cpd in canonical_order:
            values = act_data.get(raw_cpd, {})
            cpd = _normalize_cpd_label(raw_cpd)
            if not cpd or _is_control_or_reference_label(cpd):
                continue
            if not isinstance(values, dict):
                continue
            if not _has_activity_values(values):
                continue
            if cpd in binding_by_cpd:
                examples.append(binding_by_cpd[cpd])
                continue
            examples.append({
                'cpd': cpd,
                'cpd_id': cpd,
                'compound_id': cpd,
                'page_no': '',
                'structure_index': '',
                'struct_idx': '',
                'structure_id': '',
                'image_path': '',
                'activity_only': True,
            })
    
    return examples, smiles_map, smiles_by_binding_key, smiles_by_structure_id, act_data, assays


def build_assay_columns(assays):
    """从assay元数据动态生成活性列定义
    
    Returns:
        list of (column_header, width, target, sdf_prop_name)
    """
    columns = []
    for assay in assays:
        target = assay.get('target', 'Unknown')
        test_type = assay.get('test_type', '')
        unit = assay.get('unit', '')
        
        # 生成列标题: "IGF-1R IC50" 或 "IR IC50 (nM)"
        header = target
        if test_type:
            header = f"{target} {test_type}"
        if unit:
            header = f"{header} ({unit})"
        
        # SDF属性名: Activity_IGF1R_IC50
        sdf_prop = f"Activity_{target.replace('-', '').replace(' ', '_')}_{test_type}" if test_type else f"Activity_{target.replace('-', '')}"
        
        columns.append((header, 14, target, sdf_prop))
    
    return columns


def build_grade_note(assays):
    """从assay元数据自动生成分级说明"""
    if not assays:
        return ""
    
    lines = []
    for assay in assays:
        target = assay.get('target', '')
        test_type = assay.get('test_type', '')
        grades = assay.get('grades', {})
        
        if not grades:
            continue
        
        header = f"{target} {test_type}" if test_type else target
        lines.append(f"【{header}】")
        for grade_key, grade_desc in sorted(grades.items()):
            lines.append(f"  {grade_key}: {grade_desc}")
    
    return "\n".join(lines) if lines else ""


def _activity_for_cpd(act_data, cpd, bound_cpds=None):
    if not isinstance(act_data, dict):
        return {}
    cpd = _normalize_cpd_label(cpd)
    bound_cpds = bound_cpds or set()
    bound_cpds = {_normalize_cpd_label(c) for c in bound_cpds if _normalize_cpd_label(c)}
    direct = act_data.get(cpd, {})
    if isinstance(direct, dict) and direct:
        return direct

    combo_values = {}
    m = re.match(r"^Compound\s+(\d+)-([12])$", str(cpd))
    if m:
        base, suffix = m.groups()
        for combo in (f"Compound {base}-1/{base}-2", f"Compound {base}-1 和 {base}-2"):
            values = act_data.get(combo, {})
            if isinstance(values, dict):
                combo_values.update(values)
        if combo_values:
            return combo_values

        parent_key = f"Compound {base}"
        parent = act_data.get(parent_key, {})
        if parent_key not in bound_cpds and isinstance(parent, dict):
            return parent
    return combo_values


def _dedupe_bindings_exact_cpd(bindings, smiles_map, smiles_by_binding_key, smiles_by_structure_id=None):
    grouped = {}
    for binding in bindings:
        cpd = binding.get("cpd", binding.get("cpd_id", ""))
        grouped.setdefault(cpd, []).append(binding)

    deduped = []
    removed = []
    for cpd, members in grouped.items():
        if len(members) == 1:
            deduped.append(members[0])
            continue

        def _binding_score(binding):
            sr = _get_smiles_for_binding(binding, smiles_map, smiles_by_binding_key, smiles_by_structure_id)
            page_no = -(binding.get("page_no") or 0)
            structure_index = -(binding.get("structure_index") or 0)
            return _score_smiles_record(sr) + (page_no, structure_index)

        best = max(members, key=_binding_score)
        deduped.append(best)
        for binding in members:
            if binding is best:
                continue
            sr = _get_smiles_for_binding(binding, smiles_map, smiles_by_binding_key, smiles_by_structure_id)
            removed.append({
                "cpd": cpd,
                "structure_id": binding.get("structure_id", ""),
                "rule": "duplicate_cpd",
                "mol_weight": sr.get("mol_weight"),
            })

    if removed:
        print(f"⚠️  去重过滤掉 {len(removed)} 个同名重复条目")
    return deduped, removed


def _filter_intermediates_by_structure(bindings, smiles_map, smiles_by_binding_key, smiles_by_structure_id=None):
    """基于分子量和结构相似度过滤中间体。

    策略：
    1. 按base编号分组（Compound 1 vs 1-1, 1-2）
    2. 对每组，取MW最大的作为终产物
    3. 用Tanimoto相似度检查：与终产物相似度低(<0.5)的判为中间体
    4. 相似度接近但MW远小于终产物的(<70%)也判为中间体

    Returns:
        filtered_bindings, 过滤掉的列表
    """
    if not RDKIT_AVAILABLE:
        print("⚠️  RDKit不可用，跳过结构相似度中间体过滤")
        return bindings, []

    # Group by base compound number
    groups = {}
    for b in bindings:
        cpd = b.get('cpd', b.get('cpd_id', ''))
        m = re.search(r'(\d+)(?:-(\d+))?$', cpd)
        if m:
            base = int(m.group(1))
            suffix = m.group(2)
            groups.setdefault(base, []).append((cpd, b, suffix is not None))
        else:
            groups.setdefault(cpd, []).append((cpd, b, False))

    filtered = []
    removed = []

    for base, members in groups.items():
        if len(members) == 1:
            filtered.append(members[0][1])
            continue

        # Get molecules with valid SMILES
        valid_mols = []
        for cpd, b, is_intermediate in members:
            sr = _get_smiles_for_binding(b, smiles_map, smiles_by_binding_key, smiles_by_structure_id)
            sm = sr.get('canonical_smiles') or sr.get('raw_smiles') or ''
            mol = Chem.MolFromSmiles(sm) if sm else None
            if mol:
                mw = Descriptors.MolWt(mol)
                fp = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048).GetFingerprint(mol)
                valid_mols.append((cpd, b, mol, mw, fp))
            else:
                filtered.append(b)

        if len(valid_mols) <= 1:
            for _, b, _, _, _ in valid_mols:
                filtered.append(b)
            continue

        # Find the molecule with highest MW as the "final product"
        valid_mols.sort(key=lambda x: x[3], reverse=True)
        final_cpd, final_b, final_mol, final_mw, final_fp = valid_mols[0]
        # Always keep the highest MW compound as the final product
        filtered.append(final_b)

        for cpd, b, mol, mw, fp in valid_mols[1:]:
            sim = DataStructs.TanimotoSimilarity(final_fp, fp)
            mw_ratio = mw / final_mw if final_mw > 0 else 0

            # Exact duplicate: same SMILES as final product
            if sim >= 0.99 and abs(mw - final_mw) < 0.1:
                removed.append({
                    'cpd': cpd,
                    'final': final_cpd,
                    'mw': mw,
                    'final_mw': final_mw,
                    'similarity': sim,
                    'rule': 'exact_duplicate',
                })
            # Intermediate if: low similarity OR much smaller MW
            elif sim < 0.5 or mw_ratio < 0.7:
                removed.append({
                    'cpd': cpd,
                    'final': final_cpd,
                    'mw': mw,
                    'final_mw': final_mw,
                    'similarity': sim,
                    'rule': 'low_similarity' if sim < 0.5 else 'low_mw_ratio',
                })
            else:
                filtered.append(b)

    if removed:
        print(f"⚠️  结构相似度过滤掉 {len(removed)} 个中间体/原料片段:")
        for r in removed:
            print(f"    {r['cpd']:20s} MW={r['mw']:7.1f} vs {r['final']}(MW={r['final_mw']:.1f}) "
                  f"Tanimoto={r['similarity']:.3f} [{r['rule']}]")

    return filtered, removed


_AUTO_ACCEPTED_ELEMENTS = {
    "H", "B", "C", "N", "O", "F", "Na", "Mg", "Si", "P", "S",
    "Cl", "K", "Ca", "Br", "I",
}


def _suspicious_smiles_elements(record):
    smiles = str(record.get("canonical_smiles") or record.get("raw_smiles") or "")
    reported = record.get("suspicious_elements") or []
    detected = {
        element
        for element in re.findall(r"\[([A-Z][a-z]?)", smiles)
        if element not in _AUTO_ACCEPTED_ELEMENTS
    }
    detected.update(str(element) for element in reported if str(element))
    return sorted(detected)


def _validate_strict_export(bindings, smiles_map, smiles_by_binding_key, smiles_by_structure_id, act_data):
    """Reject final deliverables unless all active rows are safely resolved."""
    errors = []
    expected_cpds = [
        _normalize_cpd_label(cpd)
        for cpd, values in (act_data or {}).items()
        if _normalize_cpd_label(cpd)
        and not _is_control_or_reference_label(cpd)
        and _has_activity_values(values)
    ]
    actual_cpds = [_normalize_cpd_label(b.get("cpd", b.get("cpd_id", ""))) for b in bindings]
    if not expected_cpds:
        errors.append("no non-empty activity compound rows were supplied")
    if actual_cpds != expected_cpds:
        missing = [cpd for cpd in expected_cpds if cpd not in set(actual_cpds)]
        extra = [cpd for cpd in actual_cpds if cpd not in set(expected_cpds)]
        errors.append(f"final compound order/coverage differs from activity table (missing={missing[:10]}, extra={extra[:10]})")

    structure_ids = []
    for binding in bindings:
        cpd = _normalize_cpd_label(binding.get("cpd", binding.get("cpd_id", "")))
        if binding.get("activity_only") or not binding.get("structure_id"):
            errors.append(f"{cpd}: active compound has no confirmed structure binding")
            continue
        structure_ids.append(str(binding.get("structure_id")))
        if not _binding_is_safe_for_final(binding):
            errors.append(f"{cpd}: binding is not confirmed for final export")
            continue
        if not _resolve_display_image_path(binding, WORKING_ROOT):
            errors.append(f"{cpd}: confirmed structure image is missing")
            continue
        record = _get_smiles_for_binding(binding, smiles_map, smiles_by_binding_key, smiles_by_structure_id)
        suspicious = _suspicious_smiles_elements(record)
        if not record.get("rdkit_valid") or not record.get("canonical_smiles"):
            errors.append(f"{cpd}: no RDKit-valid SMILES")
        elif record.get("OCSR_quality_flag", "ok") != "ok" or suspicious:
            errors.append(f"{cpd}: SMILES needs review (quality={record.get('OCSR_quality_flag')}, elements={suspicious})")
    if len(set(structure_ids)) != len(structure_ids):
        errors.append("multiple active compounds use the same final structure image")

    if errors:
        detail = "; ".join(errors[:12])
        if len(errors) > 12:
            detail += f"; plus {len(errors) - 12} more"
        raise RuntimeError(f"Strict accuracy gate blocked final export: {detail}")


def _validate_activity_source_for_export(activity_path):
    if not activity_path or not os.path.exists(activity_path):
        raise RuntimeError("Strict accuracy gate blocked final export: activity JSON is required.")
    with open(activity_path, encoding="utf-8") as source:
        payload = json.load(source)
    if not artifact_identity_matches(payload, ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION):
        raise RuntimeError(
            "Strict accuracy gate blocked final export: activity data was not produced "
            "by the current ruleset."
        )
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    review_cpds = [
        _normalize_cpd_label(row.get("cpd", ""))
        for row in rows
        if isinstance(row, dict)
        and row.get("needs_review")
        and not _is_control_or_reference_label(row.get("cpd", ""))
        and _has_activity_values(_row_activity_values(row))
    ]
    if review_cpds:
        raise RuntimeError(
            "Strict accuracy gate blocked final export: activity rows require review "
            f"before export ({review_cpds[:12]})."
        )


def _validate_binding_source_for_export(bindings_path):
    with open(bindings_path, encoding="utf-8") as source:
        payload = json.load(source)
    if not artifact_identity_matches(payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION):
        raise RuntimeError(
            "Strict accuracy gate blocked final export: bindings were not produced "
            "by the current ruleset."
        )
    if payload.get("execution_mode") != "production_activity_led":
        raise RuntimeError(
            "Strict accuracy gate blocked final export: bindings came from a "
            "diagnostic path rather than the production activity-led pipeline."
        )
    accuracy = payload.get("accuracy_summary", {}) or {}
    raw_bindings = payload.get("final_bindings", []) if isinstance(payload.get("final_bindings"), list) else []
    bindings = [
        annotate_binding_accuracy(dict(binding)) if isinstance(binding, dict) else {}
        for binding in raw_bindings
    ]
    recalculated_accuracy = summarise_binding_accuracy(bindings)
    def count(summary, field, missing):
        value = summary.get(field, missing)
        return missing if value is None else int(value)
    if (
        int(recalculated_accuracy.get("review_required", 0) or 0)
        or int(recalculated_accuracy.get("confirmed", -1) or -1) != len(bindings)
        or int(recalculated_accuracy.get("total", -1) or -1) != len(bindings)
        or any(
            count(accuracy, field, -1) != count(recalculated_accuracy, field, -2)
            for field in ("total", "confirmed", "review_required")
        )
    ):
        raise RuntimeError(
            "Strict accuracy gate blocked final export: bindings do not pass "
            "fresh current-rule confirmation or their accuracy summary is stale."
        )
    return bindings


def _validate_smiles_source_for_export(smiles_path, bindings):
    with open(smiles_path, encoding="utf-8") as source:
        payload = json.load(source)
    if not smiles_artifact_is_current(payload):
        raise RuntimeError(
            "Strict accuracy gate blocked final export: SMILES output does not "
            "match the current production artifact contract."
        )
    records = smiles_records(payload)
    expected_pairs = [
        (_normalize_cpd_label(binding.get("cpd", binding.get("cpd_id", ""))), str(binding.get("structure_id") or ""))
        for binding in bindings
    ]
    actual_pairs = [
        (_normalize_cpd_label(record.get("cpd_id", "")), str(record.get("structure_id") or ""))
        for record in records
        if isinstance(record, dict)
    ]
    errors = []
    if len(actual_pairs) != len(records) or actual_pairs != expected_pairs:
        errors.append("SMILES records are not a one-to-one ordered match for confirmed structure bindings")
    for record in records:
        if not isinstance(record, dict):
            continue
        cpd = _normalize_cpd_label(record.get("cpd_id", "")) or "unknown compound"
        suspicious = _suspicious_smiles_elements(record)
        if not record.get("rdkit_valid") or not record.get("canonical_smiles"):
            errors.append(f"{cpd}: no RDKit-valid SMILES")
        elif record.get("OCSR_quality_flag", "ok") != "ok" or suspicious:
            errors.append(
                f"{cpd}: SMILES needs review "
                f"(quality={record.get('OCSR_quality_flag')}, elements={suspicious})"
            )
    if errors:
        raise RuntimeError("Strict accuracy gate blocked final export: " + "; ".join(errors[:12]))


def _write_strict_export_failure(output_dir, error):
    normalized = os.path.normpath(output_dir)
    marker_root = os.path.dirname(normalized) if os.path.basename(normalized) == "final_results" else normalized
    write_failure_marker(marker_root, "final_export", [error])


def generate_excel(bindings, smiles_map, smiles_by_binding_key, smiles_by_structure_id, act_data, assays, output_path, project_root):
    """生成最终 Excel。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Final Results"
    
    # 构建列定义: 固定列 + 动态活性列 + 分级说明列
    assay_cols = build_assay_columns(assays)
    grade_note = build_grade_note(assays)
    
    all_columns = list(FIXED_COLUMNS) + [(h, w) for h, w, _, _ in assay_cols]
    if grade_note:
        all_columns.append(("活性分级说明", 40))
    
    # 表头
    for col_idx, (h, w) in enumerate(all_columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = w
    
    # 活性列起始位置
    activity_col_start = len(FIXED_COLUMNS) + 1
    bound_cpds = {_normalize_cpd_label(b.get('cpd', b.get('cpd_id', ''))) for b in bindings}
    
    # 数据行
    img_count = 0
    for row_idx, b in enumerate(bindings, 2):
        cpd = _normalize_cpd_label(b.get('cpd', b.get('cpd_id', '')))
        compound_id = _normalize_cpd_label(b.get('compound_id', '')) or cpd
        page = b.get('page_no', '')
        sidx = b.get('structure_index', b.get('struct_idx', ''))
        
        # 固定列
        ws.cell(row=row_idx, column=1, value=cpd).border = THIN_BORDER
        ws.cell(row=row_idx, column=2, value=compound_id).border = THIN_BORDER
        ws.cell(row=row_idx, column=3, value=page).border = THIN_BORDER
        ws.cell(row=row_idx, column=4, value=sidx).border = THIN_BORDER
        
        # 结构图
        img_path = _resolve_display_image_path(b, project_root)
        if img_path and os.path.exists(img_path):
            try:
                img = XlImage(img_path)
                img.width = IMG_WIDTH_PX
                img.height = IMG_HEIGHT_PX
                ws.add_image(img, f"E{row_idx}")
                img_count += 1
            except Exception as e:
                ws.cell(row=row_idx, column=5, value=f"图片加载失败: {e}").border = THIN_BORDER
        else:
            ws.cell(row=row_idx, column=5, value="" if b.get('activity_only') else "图片未找到").border = THIN_BORDER
        
        # SMILES
        sr = _get_smiles_for_binding(b, smiles_map, smiles_by_binding_key, smiles_by_structure_id)
        ws.cell(row=row_idx, column=6, value=sr.get('canonical_smiles', '')).border = THIN_BORDER
        ws.cell(row=row_idx, column=6).alignment = Alignment(wrap_text=True)
        ws.cell(row=row_idx, column=7, value=str(sr.get('mol_formula', ''))).border = THIN_BORDER
        ws.cell(row=row_idx, column=8, value=str(sr.get('mol_weight', ''))).border = THIN_BORDER
        ws.cell(row=row_idx, column=9, value=sr.get('ring_count', '')).border = THIN_BORDER
        ws.cell(row=row_idx, column=10, value=sr.get('chiral_centers', '')).border = THIN_BORDER
        
        # 动态活性列
        act = _activity_for_cpd(act_data, cpd, bound_cpds)
        for i, (header, width, target, sdf_prop) in enumerate(assay_cols):
            col = activity_col_start + i
            grade = act.get(target, '') if isinstance(act, dict) else ''
            cell = ws.cell(row=row_idx, column=col, value=grade)
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = THIN_BORDER
            cell.font = Font(bold=True, size=14)
            if grade in GRADE_FILLS:
                cell.fill = GRADE_FILLS[grade]
        
        # 活性分级说明
        if grade_note:
            note_col = activity_col_start + len(assay_cols)
            note_cell = ws.cell(row=row_idx, column=note_col, value=grade_note)
            note_cell.font = NOTE_FONT
            note_cell.fill = NOTE_FILL
            note_cell.alignment = Alignment(wrap_text=True, vertical='center')
            note_cell.border = THIN_BORDER
        
        ws.row_dimensions[row_idx].height = ROW_HEIGHT_PT
    
    if act_data:
        act_ws = wb.create_sheet("Activity Results")
        activity_targets = []
        for values in act_data.values():
            if not isinstance(values, dict):
                continue
            for target in values:
                if target not in activity_targets:
                    activity_targets.append(target)
        act_headers = ["Cpd ID"] + activity_targets
        for col_idx, header in enumerate(act_headers, 1):
            cell = act_ws.cell(row=1, column=col_idx, value=header)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = THIN_BORDER
            act_ws.column_dimensions[get_column_letter(col_idx)].width = 18 if col_idx == 1 else 24

        for row_idx, cpd in enumerate(act_data, 2):
            values = act_data.get(cpd, {}) if isinstance(act_data.get(cpd), dict) else {}
            act_ws.cell(row=row_idx, column=1, value=cpd).border = THIN_BORDER
            for col_idx, target in enumerate(activity_targets, 2):
                act_ws.cell(row=row_idx, column=col_idx, value=values.get(target, "")).border = THIN_BORDER

    wb.save(output_path)
    return img_count


def generate_sdf(bindings, smiles_map, smiles_by_binding_key, smiles_by_structure_id, act_data, assays, grade_note, output_path, rdkit_python=None):
    """生成最终 SDF 文件（含 2D 坐标和全部属性）。"""
    import subprocess
    
    if rdkit_python is None:
        rdkit_python = sys.executable
    if not os.path.exists(rdkit_python):
        fallback = shutil.which("python3") or sys.executable
        print(f"⚠️ RDKit Python不存在: {rdkit_python}，改用 {fallback}")
        rdkit_python = fallback
    
    # 构建SDF属性映射
    assay_cols = build_assay_columns(assays)
    bound_cpds = {_normalize_cpd_label(b.get('cpd', b.get('cpd_id', ''))) for b in bindings}
    
    # 准备数据传给子进程
    data = []
    for b in bindings:
        cpd = _normalize_cpd_label(b.get('cpd', b.get('cpd_id', '')))
        sr = _get_smiles_for_binding(b, smiles_map, smiles_by_binding_key, smiles_by_structure_id)
        act = _activity_for_cpd(act_data, cpd, bound_cpds)
        
        smiles = sr.get('canonical_smiles') or sr.get('raw_smiles') or ''
        row = {
            "Cpd_ID": cpd,
            "Compound_ID": b.get('compound_id', ''),
            "Page_No": str(b.get('page_no', '')),
            "Struct_Index": str(b.get('structure_index', b.get('struct_idx', ''))),
            "SMILES_canonical": smiles,
            "Mol_Formula": str(sr.get('mol_formula', '')),
            "Mol_Weight": str(sr.get('mol_weight', '')),
            "Ring_Count": str(sr.get('ring_count', '')),
            "Chiral_Centers": str(sr.get('chiral_centers', '')),
        }
        
        # 动态活性属性
        for header, width, target, sdf_prop in assay_cols:
            grade = act.get(target, '') if isinstance(act, dict) else ''
            row[sdf_prop] = grade
        
        # 分级说明
        if grade_note:
            row["Grade_Note"] = grade_note.replace('\n', '; ')
        
        data.append(row)
    
    with tempfile.TemporaryDirectory(prefix="patentsar-sdf-") as temp_dir:
        data_path = Path(temp_dir) / "sdf_data.json"
        script_path = Path(temp_dir) / "sdf_writer.py"
        data_path.write_text(json.dumps(data), encoding="utf-8")
        script_path.write_text('''#!/usr/bin/env python3
import json, sys
from rdkit import Chem
from rdkit.Chem import AllChem

data_path = sys.argv[1]
output_path = sys.argv[2]

with open(data_path) as f:
    records = json.load(f)

writer = Chem.SDWriter(output_path)
success = 0
failed = 0

for rec in records:
    smiles = rec.get('SMILES_canonical', '')
    if not smiles:
        failed += 1
        continue
    
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        failed += 1
        continue
    
    mol = Chem.AddHs(mol)
    AllChem.Compute2DCoords(mol)
    
    # 设置所有属性
    for key, val in rec.items():
        if key == 'SMILES_canonical':
            continue  # SMILES已编码在分子结构中
        if val is not None and str(val) != '':
            mol.SetProp(key, str(val))
    
    writer.write(mol)
    success += 1

writer.close()
print(f"SDF: {success} written, {failed} failed, total {len(records)}")
''', encoding="utf-8")
        child_env = os.environ.copy()
        child_env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [rdkit_python, str(script_path), str(data_path), output_path],
            capture_output=True,
            text=True,
            timeout=120,
            env=child_env,
        )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(f"SDF生成错误: {result.stderr}", file=sys.stderr)
        return {"path": output_path, "success": 0, "failed": len(data), "returncode": result.returncode}
    import re
    m = re.search(r"SDF:\s+(\d+)\s+written,\s+(\d+)\s+failed", result.stdout)
    success = int(m.group(1)) if m else 0
    failed = int(m.group(2)) if m else len(data)
    
    return {"path": output_path, "success": success, "failed": failed, "returncode": result.returncode}


def main():
    parser = argparse.ArgumentParser(description="生成最终 Excel 和 SDF")
    parser.add_argument("--bindings", required=True, help="绑定 JSON 路径")
    parser.add_argument("--smiles", required=True, help="SMILES JSON 路径")
    parser.add_argument("--activity", default=None, help="活性数据JSON路径(可选)")
    parser.add_argument("--output-dir", default=None, help="输出目录(默认与bindings同目录/final_results)")
    parser.add_argument("--patent", default=None, help="专利号(自动检测)")
    parser.add_argument("--rdkit-python", default=sys.executable,
                        help="RDKit Python路径")
    parser.add_argument("--no-sdf", action="store_true", help="不生成SDF")
    parser.add_argument("--no-excel", action="store_true", help="不生成Excel")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Generate best-effort deliverables even when strict acceptance is not yet met.",
    )
    args = parser.parse_args()
    
    # 检测专利号
    patent = args.patent
    if not patent:
        import re
        # 从bindings或activity路径中提取WO号
        for path in [args.bindings, args.activity or '', args.smiles]:
            m = re.search(r'(WO\d{6,})', path)
            if m:
                patent = m.group(1)
                break
        if not patent:
            patent = "UNKNOWN"
    
    # 输出目录
    output_dir = args.output_dir
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(args.bindings)), "final_results")
    os.makedirs(output_dir, exist_ok=True)
    
    excel_path = os.path.join(output_dir, f"{patent}_final.xlsx")
    sdf_path = os.path.join(output_dir, f"{patent}_final.sdf")
    
    # 加载数据
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        if (args.no_excel or args.no_sdf) and not args.allow_partial:
            raise RuntimeError(
                "Strict accuracy gate blocked final export: final deliverables require both Excel and SDF outputs."
            )
        if not args.allow_partial:
            _validate_activity_source_for_export(args.activity)
            source_bindings = _validate_binding_source_for_export(args.bindings)
            _validate_smiles_source_for_export(args.smiles, source_bindings)
        examples, smiles_map, smiles_by_binding_key, smiles_by_structure_id, act_data, assays = load_data(
            args.bindings,
            args.smiles,
            activity_path=args.activity,
            allow_partial=args.allow_partial,
        )

        # 严格活性驱动主链要求活性化合物保留到最终表，因此这里只做
        # 同名重复绑定去重，不对活性命中条目做结构相似度裁剪。
        examples, removed_dup = _dedupe_bindings_exact_cpd(examples, smiles_map, smiles_by_binding_key, smiles_by_structure_id)
        removed = list(removed_dup)
        if not args.allow_partial:
            _validate_strict_export(examples, smiles_map, smiles_by_binding_key, smiles_by_structure_id, act_data)
    except RuntimeError as exc:
        _write_strict_export_failure(output_dir, exc)
        raise

    # 活性分级说明
    grade_note = build_grade_note(assays)

    # 活性列信息
    assay_cols = build_assay_columns(assays)

    print(f"专利: {patent}")
    print(f"Example数: {len(examples)}")
    print(f"SMILES有效: {sum(1 for r in smiles_map.values() if r.get('canonical_smiles'))}/{len(smiles_map)}")
    print(f"活性数据: {len(act_data)} 条")
    assay_info = ", ".join(f"{a['target']} {a['test_type']}" for a in assays)
    print(f"活性靶点: {assay_info}")
    print()
    
    # 生成Excel
    if not args.no_excel:
        img_count = generate_excel(examples, smiles_map, smiles_by_binding_key, smiles_by_structure_id, act_data, assays, excel_path, project_root)
        print(f"✅ Excel: {excel_path} ({img_count}/{len(examples)} 图片)")
    
    # 生成SDF
    if not args.no_sdf:
        sdf_result = generate_sdf(examples, smiles_map, smiles_by_binding_key, smiles_by_structure_id, act_data, assays, grade_note, sdf_path, args.rdkit_python)
        size = os.path.getsize(sdf_path) if os.path.exists(sdf_path) else 0
        if sdf_result["success"] == 0 or size == 0:
            if os.path.exists(sdf_path) and size == 0:
                os.remove(sdf_path)
            print(f"⚠️ SDF skipped: no valid molecules for export")
        else:
            print(f"✅ SDF: {sdf_path} ({size/1024:.1f} KB, {sdf_result['success']} molecules)")

    normalized_output = os.path.normpath(output_dir)
    marker_root = os.path.dirname(normalized_output) if os.path.basename(normalized_output) == "final_results" else normalized_output
    clear_failure_marker(marker_root)


if __name__ == "__main__":
    main()
