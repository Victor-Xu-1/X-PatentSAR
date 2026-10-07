"""Pure deterministic Lead-candidate heuristics, no model calls or persistence.

The caller supplies all current effective project compounds and its full exact
activity catalog. Score weights are policy heuristics, not calibrated biological
probabilities. Quality gates precede diversity; up to eight candidates are chosen
with O(8*N) fixed-size fingerprint comparisons, never an N-by-N matrix.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from patent_sar_extractor.core.identifier_order import natural_identifier_key

from .errors import WebError
from .lead_activity import ActivityEvidence, activity_evidence, check_cancel
from .lead_chemistry import (
    CYP_ENDPOINTS,
    RISK_ENDPOINTS,
    ChemicalFeatures,
    admet_score,
    chemical_features,
    novelty,
    physchem_score,
    similarity,
    validated_endpoints,
    validated_properties,
)
from .lead_models import LeadAssessment
from .models import ActivityColumn, Compound

MAX_LEAD_ROWS = 25_000
MAX_LEAD_MOLECULES = 5_000
LEAD_TARGET = 8
QUALITY_WEIGHTS = {
    "potency": 0.35,
    "coverage": 0.20,
    "admet": 0.20,
    "physchem": 0.15,
    "evidence": 0.10,
}
_BLOCKED_FLAGS = frozenset(
    {
        "structure_number_unconfirmed",
        "ambiguous_binding",
        "ambiguous_smiles",
        "historical_identity",
        "structure_unmatched",
    }
)
_RESEARCH_WARNING = (
    "仅为公开启发式 Lead 候选优先级；不是实测药效、安全性或临床 Lead 证明。"
)


@dataclass(slots=True)
class _Candidate:
    compound: Compound
    assessment: LeadAssessment
    features: ChemicalFeatures
    quality: float
    nearest: float = 0.0
    same_scaffold: bool = False


def _messages(values: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            " ".join(value.split())[:300] for value in values if value.strip()
        )
    )[:12]


def _refusal(compound: Compound) -> str | None:
    if (
        compound.id.startswith("source-structure:")
        or compound.confidence.level != "high"
        or not compound.structure_id
        or not compound.structure_image_url
        or compound.source.page is None
        or not 1 <= compound.source.page <= 20_000
        or _BLOCKED_FLAGS.intersection(compound.flags)
    ):
        return "原文编号与结构归属尚未证实，不参与 Lead 推荐。"
    if compound.review and compound.review.decision in {"rejected", "needs_review"}:
        return "人工审核拒绝或待复核，不参与 Lead 推荐。"
    if compound.correction and compound.correction.stale:
        return "在线修订已过期，必须先核对当前原文/分子图。"
    if (
        compound.recognition.status != "valid"
        or compound.recognition.quality_flag not in {"ok", "manual_correction"}
    ):
        return "当前结构识别/手性证据不合格，不参与 Lead 推荐。"
    from .prediction_identity import compound_prediction_eligible

    try:
        eligible = compound_prediction_eligible(compound)
    except WebError:
        eligible = False
    if not eligible:
        return "当前分子图或手性表示不合格，不参与 Lead 推荐。"
    return None


def _unranked(evidence: ActivityEvidence, reason: str) -> LeadAssessment:
    return LeadAssessment(
        status="unranked",
        activity_coverage=evidence.coverage,
        reasons=[reason],
        warnings=[_RESEARCH_WARNING],
    )


def _qualified_inputs(
    compounds: list[Compound],
    evidence: dict[str, ActivityEvidence],
    cancel: Callable[[], bool] | None,
) -> tuple[
    dict[str, LeadAssessment], list[tuple[Compound, dict[str, float], dict[str, float]]]
]:
    assessments: dict[str, LeadAssessment] = {}
    ready = []
    for compound in compounds:
        check_cancel(cancel)
        refusal = _refusal(compound)
        if refusal:
            assessments[compound.id] = LeadAssessment(
                status="ineligible", reasons=[refusal], warnings=[_RESEARCH_WARNING]
            )
            continue
        observed = evidence[compound.id]
        if not observed.ranked_columns:
            assessments[compound.id] = _unranked(
                observed,
                "没有可排名的已知方向活性；缺失、删失、冲突及 counter/safety 读数不代入药效。",
            )
            continue
        endpoints = validated_endpoints(compound)
        if endpoints is None:
            assessments[compound.id] = _unranked(
                observed, "缺少当前完整且有效的 11 项 ADMET 概览，缺失风险不视为安全。"
            )
            continue
        values = validated_properties(compound)
        if values is None:
            assessments[compound.id] = _unranked(
                observed, "六项当前理化/LogS 数据不完整或无效，显式手工空值不借用模型。"
            )
            continue
        try:
            from .prediction_identity import readable_digests

            current = readable_digests(compound.smiles, compound.structure_molfile)
        except WebError:
            assessments[compound.id] = LeadAssessment(
                status="ineligible",
                reasons=["当前分子图无效或尚有不支持的表示，不能参与 Lead 推荐。"],
                warnings=[_RESEARCH_WARNING],
            )
            continue
        if compound.admet.smiles_sha256 not in current:
            assessments[compound.id] = _unranked(
                observed, "ADMET 概览不属于当前分子图，不能借用历史预测。"
            )
            continue
        if (
            compound.descriptors is not None
            and compound.descriptors.status == "complete"
            and compound.descriptors.smiles_sha256 not in current
        ):
            assessments[compound.id] = _unranked(
                observed, "独立理化计算不属于当前分子图，不能混用历史指标。"
            )
            continue
        ready.append((compound, values, endpoints))
        if len(ready) > MAX_LEAD_MOLECULES:
            raise WebError(
                422,
                "lead_limit",
                "Lead eligible molecules exceed 5000; no partial ranking was produced.",
            )
    return assessments, ready


def _candidate(
    compound: Compound,
    values: dict[str, float],
    endpoints: dict[str, float],
    observed: ActivityEvidence,
) -> _Candidate:
    features = chemical_features(compound.smiles)
    physical, warnings = physchem_score(values, features)
    components = {
        "potency": observed.potency,
        "coverage": 100 * observed.coverage,
        "admet": admet_score(endpoints),
        "physchem": physical,
        "evidence": 60 + 40 * observed.provenance,
        "diversity": 100.0,
    }
    quality = sum(components[key] * weight for key, weight in QUALITY_WEIGHTS.items())
    reasons = [
        f"活性覆盖 {observed.ranked_columns}/{observed.total_columns} 个可排名独立列；同列重复观察使用最差读数。",
        "质量权重：活性强度35%、覆盖20%、ADMET20%、理化15%、证据10%；每列先在全项目内计算并列百分位。",
        "选择权重：质量80%＋结构新颖度20%；仅从质量合格池选择，不为凑数降低标准。",
    ]
    if observed.excluded_columns:
        warnings.append(
            f"另有 {observed.excluded_columns} 个观察列因方向、数值、单位或类型不确定而未排名。"
        )
    if observed.provenance < 1:
        warnings.append(
            "部分活性观察缺少有效原文页，证据分已降低；不把数值有效当作来源已验证。"
        )
    risk = [key for key in RISK_ENDPOINTS if endpoints[key] >= 0.8]
    if risk:
        reasons.append(
            "核心 ADMET 预测风险较高："
            + ", ".join(f"{key}={endpoints[key]:.3f}" for key in risk)
            + "；已连续扣分，候选必须进行风险复核。"
        )
        warnings.insert(
            0,
            "高预测风险待复核；0.8仅为提醒界限，不是实测毒性或临床安全的一票否决阈值。",
        )
    high_cyp = [key for key in CYP_ENDPOINTS if endpoints[key] >= 0.8]
    if high_cyp:
        warnings.append(
            "预测 CYP 抑制信号较高：" + ", ".join(high_cyp) + "；需要实验验证。"
        )
    if compound.correction and compound.correction.has_changes:
        warnings.append(
            "包含当前在线修订；候选比较使用有效修订，不改变原始专利或正式 QA。"
        )
    warnings.extend(compound.admet.warnings[:3])
    assessment = LeadAssessment(
        status="not_selected",
        score=round(quality, 6),
        activity_coverage=observed.coverage,
        components={key: round(value, 6) for key, value in components.items()},
        reasons=_messages(reasons),
        warnings=_messages([_RESEARCH_WARNING, *warnings]),
        scaffold=features.scaffold,
        risk_review_required=bool(risk),
    )
    return _Candidate(compound, assessment, features, quality)


def _in_pool(candidate: _Candidate) -> bool:
    return candidate.quality >= 60 and candidate.assessment.components["potency"] >= 50


def _publish(
    candidate: _Candidate,
    *,
    rank: int | None,
    chosen: bool,
    first: bool = False,
    extra_reason: str = "",
) -> LeadAssessment:
    diverse = (
        100.0
        if first
        else novelty(candidate.features, candidate.nearest, candidate.same_scaffold)
    )
    components = {**candidate.assessment.components, "diversity": round(diverse, 6)}
    packet = candidate.assessment.model_dump()
    packet.update(
        status="selected" if chosen else "not_selected",
        rank=rank,
        score=round(0.8 * candidate.quality + 0.2 * diverse, 6),
        components=components,
        nearest_similarity=None if first else round(candidate.nearest, 6),
        reasons=_messages(
            candidate.assessment.reasons + ([extra_reason] if extra_reason else [])
        ),
    )
    return LeadAssessment.model_validate(packet)


def _select(
    candidates: list[_Candidate],
    assessments: dict[str, LeadAssessment],
    cancel: Callable[[], bool] | None,
) -> None:
    selected: list[_Candidate] = []
    selected_graphs: set[tuple[str, str]] = set()
    pending = candidates[:]
    while pending and len(selected) < LEAD_TARGET:
        check_cancel(cancel)
        winner_index = max(
            range(len(pending)),
            key=lambda index: (
                0.8 * pending[index].quality
                + 0.2
                * (
                    100
                    if not selected
                    else novelty(
                        pending[index].features,
                        pending[index].nearest,
                        pending[index].same_scaffold,
                    )
                )
            ),
        )
        winner = pending.pop(winner_index)
        identity = winner.features.graph, winner.features.isomer
        selected_graphs.add(identity)
        selected.append(winner)
        assessments[winner.compound.id] = _publish(
            winner, rank=len(selected), chosen=True, first=len(selected) == 1
        )
        remaining = []
        for candidate in pending:
            check_cancel(cancel)
            candidate.nearest = max(
                candidate.nearest, similarity(candidate.features, winner.features)
            )
            candidate.same_scaffold |= bool(
                candidate.features.scaffold
                and candidate.features.scaffold == winner.features.scaffold
            )
            if (candidate.features.graph, candidate.features.isomer) in selected_graphs:
                assessments[candidate.compound.id] = _publish(
                    candidate,
                    rank=None,
                    chosen=False,
                    extra_reason="与已选候选为同一完整分子图及构型，不重复占用 Lead 名额。",
                )
            else:
                remaining.append(candidate)
        pending = remaining
    for candidate in pending:
        check_cancel(cancel)
        assessments[candidate.compound.id] = _publish(
            candidate,
            rank=None,
            chosen=False,
            extra_reason="质量合格，但未进入本轮最多8个、兼顾化学空间的候选集合。",
        )


def prioritize_leads(
    compounds: list[Compound],
    activity_columns: list[ActivityColumn],
    cancel: Callable[[], bool] | None = None,
) -> dict[str, LeadAssessment]:
    """Evaluate all rows atomically in memory; bounds/cancellation return no partial result."""
    check_cancel(cancel)
    if len(compounds) > MAX_LEAD_ROWS:
        raise WebError(
            422,
            "lead_limit",
            "Lead project rows exceed 25000; no partial ranking was produced.",
        )
    identifiers = [compound.id for compound in compounds]
    if len(set(identifiers)) != len(identifiers) or any(
        not key or len(key) > 200 for key in identifiers
    ):
        raise WebError(
            422,
            "lead_identity",
            "Lead input requires unique bounded compound identifiers.",
        )
    observed = activity_evidence(compounds, activity_columns, cancel)
    assessments, ready = _qualified_inputs(compounds, observed, cancel)
    candidates = []
    for compound, values, endpoints in sorted(
        ready, key=lambda item: (natural_identifier_key(item[0].display_id), item[0].id)
    ):
        check_cancel(cancel)
        candidate = _candidate(compound, values, endpoints, observed[compound.id])
        if _in_pool(candidate):
            candidates.append(candidate)
        else:
            packet = candidate.assessment.model_dump()
            packet["components"]["diversity"] = 0.0
            packet["score"] = round(0.8 * candidate.quality, 6)
            packet["reasons"] = _messages(
                packet["reasons"]
                + [
                    "未满足研究候选池：活性百分位≥50、综合质量≥60；模型风险已计入质量分并独立提示。"
                ]
            )
            assessments[compound.id] = LeadAssessment.model_validate(packet)
    _select(candidates, assessments, cancel)
    check_cancel(cancel)
    return {
        compound_id: assessments[compound_id]
        for compound_id in sorted(
            assessments, key=lambda key: (natural_identifier_key(key), key)
        )
    }
