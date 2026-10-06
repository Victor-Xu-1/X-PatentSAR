"""Original identifier, competing-label and element QA observations."""

from __future__ import annotations

import re

from .activity_identity import normalize_compound
from .identifier_order import natural_identifier_key


def _cpd_sort_key(cpd: str):
    return natural_identifier_key(cpd)


_AUTO_ACCEPTED_ELEMENTS = {
    "H",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Na",
    "Mg",
    "Si",
    "P",
    "S",
    "Cl",
    "K",
    "Ca",
    "Br",
    "I",
}


def _items_from_bindings(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("final_bindings", "bindings", "results", "structures"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _binding_visual_label_risks(bindings):
    strict_sources = {"page_strict", "direct", "pdf_clip"}
    active_labels = {
        normalize_compound(b.get("cpd", "")) for b in bindings if isinstance(b, dict)
    }
    strict_conflicts = []
    weak_conflicts = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        cpd = normalize_compound(binding.get("cpd", ""))
        if not cpd:
            continue
        candidates = binding.get("visible_label_candidates") or []
        strict_labels = set()
        weak_labels = set()
        exact_visual_match = False
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                label = normalize_compound(candidate.get("label", ""))
                if not label:
                    continue
                if label == cpd:
                    exact_visual_match = True
                    continue
                if candidate.get("source") in strict_sources:
                    strict_labels.add(label)
                else:
                    weak_labels.add(label)
        for label in binding.get("visible_labels") or []:
            norm = normalize_compound(label)
            if norm == cpd:
                exact_visual_match = True
            elif norm:
                weak_labels.add(norm)
        strict_labels = {label for label in strict_labels if label in active_labels}
        weak_labels = {label for label in weak_labels if label in active_labels}
        # If the crop contains the target label itself, additional small numbers
        # are usually atom/reagent annotations. Keep them review-only.
        if exact_visual_match:
            weak_labels.update(strict_labels)
            strict_labels = set()
        if (
            binding.get("binding_rule")
            in {"structure_table_row_order", "structure_table_row_order_inferred"}
            and re.fullmatch(r"Compound\s+\d{3}[A-Za-z]?", cpd or "")
            and all(
                re.fullmatch(r"Compound\s+\d{1,2}[A-Za-z]?", label or "")
                for label in strict_labels
            )
        ):
            weak_labels.update(strict_labels)
            strict_labels = set()
        target_match = re.fullmatch(r"Compound\s+(\d{3}[A-Za-z]?)", cpd or "")
        if target_match:
            target_key = target_match.group(1).upper()
            truncated = {
                label
                for label in strict_labels
                if (m := re.fullmatch(r"Compound\s+(\d{1,2}[A-Za-z]?)", label or ""))
                and target_key.startswith(m.group(1).upper())
            }
            if truncated:
                weak_labels.update(truncated)
                strict_labels -= truncated
        if strict_labels:
            strict_conflicts.append(
                {
                    "cpd": cpd,
                    "structure_id": binding.get("structure_id"),
                    "binding_rule": binding.get("binding_rule"),
                    "visible_labels": sorted(strict_labels, key=_cpd_sort_key),
                }
            )
        elif weak_labels:
            weak_conflicts.append(
                {
                    "cpd": cpd,
                    "structure_id": binding.get("structure_id"),
                    "binding_rule": binding.get("binding_rule"),
                    "visible_labels": sorted(weak_labels, key=_cpd_sort_key),
                }
            )
    return strict_conflicts, weak_conflicts


def _binding_accuracy_risks(bindings):
    review_required = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        if binding.get("accuracy_status") == "confirmed" and not binding.get(
            "fail_closed"
        ):
            continue
        review_required.append(
            {
                "cpd": normalize_compound(binding.get("cpd", "")),
                "structure_id": binding.get("structure_id"),
                "binding_rule": binding.get("binding_rule"),
                "evidence_tier": binding.get("evidence_tier", "unknown"),
                "evidence_reasons": binding.get("evidence_reasons", []),
            }
        )
    return review_required


def _suspicious_smiles_elements(record: dict) -> list[str]:
    text = str(record.get("canonical_smiles") or record.get("raw_smiles") or "")
    elements = {
        element
        for element in re.findall(r"\[([A-Z][a-z]?)", text)
        if element not in _AUTO_ACCEPTED_ELEMENTS
    }
    elements.update(
        str(element)
        for element in (record.get("suspicious_elements") or [])
        if str(element)
    )
    return sorted(elements)
