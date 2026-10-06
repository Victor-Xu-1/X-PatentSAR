"""Bounded native RDKit SDF carrier for already-qualified exact source pairs."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from patent_sar_extractor.core.activity_identity import normalize_compound
from patent_sar_extractor.core.activity_join import activity_for_compound

from .final_data import get_smiles_for_binding
from .final_workbook import build_assay_columns


def generate_sdf(
    bindings,
    smiles_map,
    smiles_by_binding_key,
    smiles_by_structure_id,
    act_data,
    assays,
    grade_note,
    output_path,
    rdkit_python=None,
):
    """生成最终 SDF 文件（含 2D 坐标和全部属性）。"""
    import subprocess

    if rdkit_python is None:
        rdkit_python = sys.executable
    if not os.path.exists(rdkit_python):
        raise FileNotFoundError(f"RDKit interpreter is unavailable: {rdkit_python}")

    # 构建SDF属性映射
    assay_cols = build_assay_columns(assays)

    # 准备数据传给子进程
    data = []
    for b in bindings:
        cpd = normalize_compound(b.get("cpd", b.get("cpd_id", "")))
        sr = get_smiles_for_binding(
            b, smiles_map, smiles_by_binding_key, smiles_by_structure_id
        )
        act = activity_for_compound(act_data, cpd)

        smiles = sr.get("canonical_smiles") or sr.get("raw_smiles") or ""
        row = {
            "Cpd_ID": cpd,
            "Compound_ID": b.get("compound_id", ""),
            "Page_No": str(b.get("page_no", "")),
            "Struct_Index": str(b.get("structure_index", b.get("struct_idx", ""))),
            "SMILES_canonical": smiles,
            "Mol_Formula": str(sr.get("mol_formula", "")),
            "Mol_Weight": str(sr.get("mol_weight", "")),
            "Ring_Count": str(sr.get("ring_count", "")),
            "Chiral_Centers": str(sr.get("chiral_centers", "")),
        }

        # 动态活性属性
        for header, width, target, sdf_prop in assay_cols:
            grade = act.get(target, "") if isinstance(act, dict) else ""
            row[sdf_prop] = grade

        # 分级说明
        if grade_note:
            row["Grade_Note"] = grade_note.replace("\n", "; ")

        data.append(row)

    with tempfile.TemporaryDirectory(prefix="patentsar-sdf-") as temp_dir:
        data_path = Path(temp_dir) / "sdf_data.json"
        script_path = Path(temp_dir) / "sdf_writer.py"
        data_path.write_text(json.dumps(data), encoding="utf-8")
        script_path.write_text(
            """#!/usr/bin/env python3
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
""",
            encoding="utf-8",
        )
        child_env = os.environ.copy()
        child_env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [rdkit_python, "-B", str(script_path), str(data_path), output_path],
            capture_output=True,
            text=True,
            timeout=120,
            env=child_env,
        )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(f"SDF生成错误: {result.stderr}", file=sys.stderr)
        return {
            "path": output_path,
            "success": 0,
            "failed": len(data),
            "returncode": result.returncode,
        }
    import re

    m = re.search(r"SDF:\s+(\d+)\s+written,\s+(\d+)\s+failed", result.stdout)
    success = int(m.group(1)) if m else 0
    failed = int(m.group(2)) if m else len(data)

    return {
        "path": output_path,
        "success": success,
        "failed": failed,
        "returncode": result.returncode,
    }
