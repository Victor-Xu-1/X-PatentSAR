"""
Confidence Scorer — 三维 SMILES 置信度评分

为每个 SMILES 结果计算三个维度的置信度：
  1. Engine Consensus (引擎共识): 多引擎结果是否一致
  2. Structural Plausibility (结构合理性): SMILES 语法/化学合理性
  3. Context Coherence (上下文一致性): 分子量/原子数是否在合理范围

评分输出:
  - 每维 0-1 分
  - 加权平均 overall
  - 离散等级: high / medium / low
"""

import re
import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from patent_sar_extractor.core.env_runner import get_python

logger = logging.getLogger(__name__)

# RDKit environment path. Resolved through env_runner so production machines can
# override it without patching source.
SMILES_ENGINE_PYTHON = get_python("smiles_engine")


@dataclass
class ConfidenceScore:
    """SMILES 三维置信度评分"""
    engine_consensus: float = 0.0       # 0-1
    structural_plausibility: float = 0.0  # 0-1
    context_coherence: float = 0.0       # 0-1
    overall: float = 0.0                 # 加权平均
    level: str = "low"                   # high / medium / low
    details: dict = field(default_factory=dict)

    # 权重
    _WEIGHTS = {"engine_consensus": 0.35, "structural_plausibility": 0.45, "context_coherence": 0.20}

    def __post_init__(self):
        self.overall = (
            self.engine_consensus * self._WEIGHTS["engine_consensus"]
            + self.structural_plausibility * self._WEIGHTS["structural_plausibility"]
            + self.context_coherence * self._WEIGHTS["context_coherence"]
        )
        if self.overall >= 0.7:
            self.level = "high"
        elif self.overall >= 0.4:
            self.level = "medium"
        else:
            self.level = "low"


# ---- SMILES 基本语法检查 (无 RDKit) ----

# 合法 SMILES 字符集
_SMILES_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789[]()=#@+-/\\.:%")


def _check_basic_syntax(smiles: str) -> tuple[float, list[str]]:
    """
    基本 SMILES 语法检查（无需 RDKit）。
    返回 (score, issues)
    """
    issues = []
    score = 1.0

    if not smiles or len(smiles) < 3:
        return 0.0, ["empty or too short"]

    # 非法字符
    illegal = set(smiles) - _SMILES_CHARS
    if illegal:
        issues.append(f"illegal chars: {illegal}")
        score -= 0.3

    # 方括号平衡
    if smiles.count("[") != smiles.count("]"):
        issues.append("unbalanced brackets []")
        score -= 0.3

    # 圆括号平衡
    if smiles.count("(") != smiles.count(")"):
        issues.append("unbalanced parentheses ()")
        score -= 0.2

    # 连续点号
    if ".." in smiles:
        issues.append("consecutive dots")
        score -= 0.2

    # 开头/结尾异常
    if smiles.startswith(".") or smiles.endswith("."):
        issues.append("starts/ends with dot")
        score -= 0.1

    # 无碳原子
    if not re.search(r"[Cc]", smiles):
        # 可能是无机物，但对专利化合物不常见
        issues.append("no carbon atoms")
        score -= 0.2

    # 极端长度
    if len(smiles) > 500:
        issues.append(f"very long SMILES ({len(smiles)} chars)")
        score -= 0.2
    elif len(smiles) < 5:
        issues.append(f"very short SMILES ({len(smiles)} chars)")
        score -= 0.2

    return max(score, 0.0), issues


def _check_rdkit_validity(smiles: str) -> tuple[float, Optional[dict]]:
    """
    通过子进程调用 RDKit 检查 SMILES 有效性。
    返回 (score, info_dict)
    info_dict: {valid: bool, mol_weight: float, num_atoms: int, num_rings: int}
    """
    if not smiles:
        return 0.0, None

    # 写临时脚本
    script = f'''
import sys
import json
try:
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    mol = Chem.MolFromSmiles(sys.argv[1])
    if mol is None:
        print(json.dumps({{"valid": False}}))
    else:
        mw = Descriptors.MolWt(mol)
        na = mol.GetNumAtoms()
        nr = Descriptors.RingCount(mol)
        print(json.dumps({{"valid": True, "mol_weight": mw, "num_atoms": na, "num_rings": nr}}))
except Exception as e:
    print(json.dumps({{"valid": False, "error": str(e)}}))
'''
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script)
            script_path = f.name

        result = subprocess.run(
            [SMILES_ENGINE_PYTHON, script_path, smiles],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return 0.0, None

        info = json.loads(result.stdout.strip())
        if info.get("valid"):
            score = 1.0
            # 原子数合理性检查
            num_atoms = info.get("num_atoms", 0)
            if num_atoms < 5 or num_atoms > 100:
                score -= 0.15
            # 分子量合理性
            mw = info.get("mol_weight", 0)
            if mw < 50 or mw > 1500:
                score -= 0.15
            return max(score, 0.7), info
        else:
            return 0.0, info

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        logger.warning(f"RDKit check failed: {e}")
        return 0.0, None
    finally:
        import os
        try:
            os.unlink(script_path)
        except Exception:
            pass


def score_engine_consensus(smiles_list: list[str]) -> float:
    """
    计算引擎共识分数。
    多个引擎给出相同/相似 SMILES → 高分。
    """
    if len(smiles_list) <= 1:
        return 0.5  # 单引擎无法评估共识

    valid_smiles = [s for s in smiles_list if s and len(s) >= 3]
    if len(valid_smiles) <= 1:
        return 0.3

    # 完全相同的比例
    from collections import Counter
    counts = Counter(valid_smiles)
    max_count = max(counts.values())
    exact_agreement = max_count / len(valid_smiles)

    # 字符串相似度（Jaccard on character sets）
    char_sets = [set(s) for s in valid_smiles]
    if len(char_sets) >= 2:
        jaccard_sum = 0
        pair_count = 0
        for i in range(len(char_sets)):
            for j in range(i + 1, len(char_sets)):
                union = char_sets[i] | char_sets[j]
                inter = char_sets[i] & char_sets[j]
                if union:
                    jaccard_sum += len(inter) / len(union)
                pair_count += 1
        avg_jaccard = jaccard_sum / pair_count if pair_count > 0 else 0
    else:
        avg_jaccard = 0

    # 综合分数
    score = 0.6 * exact_agreement + 0.4 * avg_jaccard
    return min(score, 1.0)


def score_structural_plausibility(smiles: str) -> tuple[float, dict]:
    """
    计算结构合理性分数。
    Phase 1: 基本语法检查（无 RDKit）
    Phase 2: RDKit 有效性验证
    """
    # Phase 1: 基本语法
    basic_score, issues = _check_basic_syntax(smiles)

    # Phase 2: RDKit
    rdkit_score, rdkit_info = _check_rdkit_validity(smiles)

    # 如果 RDKit 验证通过，大幅加分
    if rdkit_info and rdkit_info.get("valid"):
        final_score = 0.3 * basic_score + 0.7 * rdkit_score
    elif rdkit_info is not None:
        # RDKit 验证失败
        final_score = 0.1
        issues.append("RDKit: invalid SMILES")
    else:
        # RDKit 不可用，仅依赖基本检查
        final_score = basic_score * 0.8  # 降权

    details = {
        "basic_score": round(basic_score, 2),
        "rdkit_info": rdkit_info,
        "issues": issues,
    }

    return round(final_score, 3), details


def score_context_coherence(smiles: str, rdkit_info: Optional[dict] = None) -> float:
    """
    计算上下文一致性分数。
    基于分子量、原子数是否在典型药物化合物范围内。
    """
    if rdkit_info is None or not rdkit_info.get("valid"):
        return 0.3  # 无 RDKit 信息，默认低分

    mw = rdkit_info.get("mol_weight", 0)
    num_atoms = rdkit_info.get("num_atoms", 0)
    num_rings = rdkit_info.get("num_rings", 0)

    score = 1.0

    # Lipinski 五规则范围
    if 150 <= mw <= 600:
        pass  # 理想范围
    elif 100 <= mw < 150 or 600 < mw <= 800:
        score -= 0.15
    elif mw < 100 or mw > 800:
        score -= 0.3

    # 原子数 (典型 15-60)
    if 15 <= num_atoms <= 60:
        pass
    elif 8 <= num_atoms < 15 or 60 < num_atoms <= 80:
        score -= 0.1
    else:
        score -= 0.2

    # 环数 (典型 1-6)
    if 1 <= num_rings <= 6:
        pass
    elif num_rings == 0 or num_rings > 6:
        score -= 0.1

    return max(score, 0.0)


def score_smiles(
    smiles: str,
    all_engine_results: Optional[list[str]] = None,
) -> ConfidenceScore:
    """
    对单个 SMILES 计算三维置信度。

    Args:
        smiles: 待评分的 SMILES 字符串
        all_engine_results: 所有引擎对此图的结果列表（用于共识计算）

    Returns:
        ConfidenceScore 实例
    """
    # 1. 结构合理性（含 RDKit 信息，后续复用）
    struct_score, struct_details = score_structural_plausibility(smiles)
    rdkit_info = struct_details.get("rdkit_info")

    # 2. 引擎共识
    if all_engine_results:
        consensus_score = score_engine_consensus(all_engine_results)
    else:
        consensus_score = 0.5  # 无信息时默认

    # 3. 上下文一致性
    context_score = score_context_coherence(smiles, rdkit_info)

    cs = ConfidenceScore(
        engine_consensus=round(consensus_score, 3),
        structural_plausibility=struct_score,
        context_coherence=round(context_score, 3),
        details=struct_details,
    )

    return cs


def main():
    """CLI: 对 SMILES JSON 文件评分"""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Score SMILES confidence (3-dimensional)")
    parser.add_argument("--smiles", help="Single SMILES to score")
    parser.add_argument("--json", help="JSON file with SMILES results")
    parser.add_argument("--output", help="Output JSON file")
    args = parser.parse_args()

    if args.smiles:
        cs = score_smiles(args.smiles)
        print(json.dumps(cs.__dict__, indent=2, default=str))
    elif args.json:
        with open(args.json) as f:
            data = json.load(f)

        results = []
        items = data if isinstance(data, list) else data.get("results", [data])
        for item in items:
            smi = item.get("smiles", item.get("SMILES", ""))
            all_results = item.get("all_engine_results", None)
            cs = score_smiles(smi, all_results)
            results.append({**item, "confidence": cs.__dict__})

        output = json.dumps(results, indent=2, ensure_ascii=False, default=str)
        print(f"Scored {len(results)} SMILES")

        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Saved to {args.output}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
