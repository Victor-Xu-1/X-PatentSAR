"""Source-grounded evidence counts; no LLM or inferred potency/mechanism claims."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from pydantic import ValidationError

from .analysis_models import (
    ActivityEvidence,
    EvidenceCounts,
    EvidenceSummary,
    TargetEvidence,
)
from .errors import WebError
from .models import Compound, Project
from .storage import now

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_EXACT = re.compile(rf"^{_NUMBER}$")
_RANGE = re.compile(rf"^{_NUMBER}\s*(?:-|–|—|~|～|to)\s*{_NUMBER}$", re.IGNORECASE)
_CENSORED = re.compile(r"^(?:[<>≤≥≲≳≈~]|[≠])")


def numeric_evidence(value: str | float | int | None) -> tuple[float | None, bool]:
    if value is None or isinstance(value, bool):
        return None, False
    text = str(value).strip().replace("−", "-")
    if _CENSORED.match(text) or _RANGE.fullmatch(text):
        return None, True
    if not _EXACT.fullmatch(text):
        return None, False
    number = float(text)
    return (number, False) if math.isfinite(number) else (None, False)


@dataclass
class Group:
    rows: int = 0
    censored: int = 0
    numbers: list[float] = field(default_factory=list)


def summarize(project: Project, compounds: list[Compound]) -> EvidenceSummary:
    groups: dict[tuple[str, str | None, str | None, str | None], Group] = {}
    targets: Counter[str] = Counter()
    pages: set[int] = set()
    located = 0
    missing_values = 0
    invalid_pages = 0
    activity_count = 0

    def source_page(page: int | None) -> bool:
        nonlocal invalid_pages
        if page is None:
            return False
        if not 1 <= page <= project.pdf.page_count:
            invalid_pages += 1
            return False
        pages.add(page)
        return True

    for compound in compounds:
        located += int(source_page(compound.source.page))
        for activity in compound.activities:
            activity_count += 1
            if activity_count > 250000:
                raise WebError(
                    413,
                    "evidence_limit",
                    "Evidence summary exceeds its activity-value limit.",
                )
            # Different assay conditions are kept separate too, without inventing a new DTO field.
            key = (activity.name, activity.unit, activity.target, activity.assay)
            group = groups.setdefault(key, Group())
            if len(groups) > 5000:
                raise WebError(
                    413,
                    "evidence_limit",
                    "Evidence summary has too many incomparable groups.",
                )
            group.rows += 1
            number, censored = numeric_evidence(activity.value)
            group.censored += int(censored)
            if number is not None:
                group.numbers.append(number)
            elif not censored:
                missing_values += 1
            if activity.target:
                targets[activity.target] += 1
            source_page(activity.page)
    limitations = [
        "Evidence summary uses original stored fields only; analysis-cache SMILES are not pipeline SMILES.",
        "Groups preserve metric, unit, target and assay; no unit conversion or cross-assay potency ranking is performed.",
    ]
    censored_count = sum(group.censored for group in groups.values())
    if censored_count:
        limitations.append(
            f"{censored_count} censored/range values are retained as such and excluded from exact-value min/max."
        )
    if missing_values:
        limitations.append(
            f"{missing_values} missing/non-numeric values are excluded from exact-value min/max; originals are unchanged."
        )
    if invalid_pages:
        limitations.append(
            f"{invalid_pages} out-of-document source references are excluded; no page was invented."
        )
    if not project.pdf.available:
        limitations.append(
            "The verified original PDF is not attached; source pages are stored provenance, not rendered-original evidence."
        )
    if project.acceptance.state != "accepted":
        limitations.append(
            "This project has not passed current formal acceptance; evidence and analysis are for review only."
        )
    signatures = Counter((name, unit, target) for name, unit, target, _ in groups)
    if any(count > 1 for count in signatures.values()):
        limitations.append(
            "Repeated name/unit/target entries represent separate original assay conditions and are intentionally not merged."
        )
    activities = [
        ActivityEvidence(
            name=name,
            unit=unit,
            target=target,
            rows=group.rows,
            numeric_rows=len(group.numbers),
            min=min(group.numbers) if group.numbers else None,
            max=max(group.numbers) if group.numbers else None,
            censored_rows=group.censored,
        )
        for (name, unit, target, _), group in sorted(
            groups.items(), key=lambda item: tuple(v or "" for v in item[0])
        )
    ]
    try:
        return EvidenceSummary(
            project_id=project.id,
            generated_at=now(),
            acceptance=project.acceptance,
            counts=EvidenceCounts(
                structures=project.summary.structures,
                activity_rows=project.summary.activity_rows,
                compounds=len(compounds),
                smiles=sum(bool(c.smiles) for c in compounds),
                source_located=located,
                needs_review=project.summary.needs_review,
            ),
            activities=activities,
            targets=[
                TargetEvidence(name=name, rows=count)
                for name, count in sorted(targets.items())
            ],
            limitations=limitations,
            source_pages=sorted(pages),
        )
    except ValidationError as exc:
        raise WebError(
            422,
            "invalid_evidence",
            "Stored evidence has invalid counts or non-finite values.",
        ) from exc
