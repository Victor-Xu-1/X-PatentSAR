"""Formal QA policy for the application layer."""

from __future__ import annotations

from typing import Any


def compose_qa_decision(deterministic: dict[str, Any], advisory: dict[str, Any]) -> dict[str, Any]:
    """Combine reports without granting an LLM formal acceptance authority.

    The deterministic report is the sole fail-closed gate.  The advisory
    report is preserved verbatim for operator review but cannot promote or
    veto a formal result.
    """

    acceptance = deterministic.get("acceptance", {}) if isinstance(deterministic, dict) else {}
    formal_ok = bool(deterministic.get("ok")) and bool(acceptance.get("ok"))
    deterministic_warnings = [
        str(item).strip()
        for item in (deterministic.get("warnings", []) or [])
        if str(item).strip()
    ]
    return {
        "ok": formal_ok,
        "acceptance": acceptance,
        "warnings": deterministic_warnings,
        "deterministic": {
            "ok": bool(deterministic.get("ok")),
            "warnings": deterministic_warnings,
        },
        "advisory": advisory if isinstance(advisory, dict) else {},
    }
