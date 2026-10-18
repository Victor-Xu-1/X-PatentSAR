"""Rejected binding proposals in the existing bounded source diagnostic catalog."""

import re

from .source_evidence_identity import proof_id


def validate_binding_diagnostic(observation, *, original_pdf_sha256=None):
    fields = {
        "version",
        "kind",
        "status",
        "reason",
        "page_no",
        "cpd",
        "structure_id",
        "proposal",
    }
    if (
        not isinstance(observation, dict)
        or set(observation) not in (fields, fields | {"original_pdf_sha256"})
        or type(observation.get("version")) is not int
        or observation["version"] != 2
        or observation.get("kind") != "binding_proposal"
        or observation.get("status") != "unresolved"
        or type(observation.get("page_no")) is not int
        or not 1 <= observation["page_no"] <= 20000
        or not isinstance(observation.get("proposal"), dict)
    ):
        raise ValueError("Malformed original binding diagnostic")
    for name, limit, minimum in (
        ("reason", 128, 1),
        ("cpd", 1000, 0),
        ("structure_id", 256, 0),
    ):
        value = observation[name]
        if not isinstance(value, str) or not minimum <= len(value) <= limit:
            raise ValueError("Malformed original binding diagnostic identity")
    sha = observation.get("original_pdf_sha256")
    if sha is not None and (
        not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha)
    ):
        raise ValueError("Malformed original binding diagnostic document")
    if original_pdf_sha256 is not None and sha != original_pdf_sha256:
        raise ValueError("Original binding diagnostic belongs to a different document")


def retain_binding_diagnostics(issues, buffer, *, original_pdf_sha256=""):
    """Keep the entire attempted source, not a reason-only or successful prefix."""
    retained = []
    for issue in issues:
        evidence = issue.get("evidence") if isinstance(issue, dict) else None
        if not isinstance(evidence, dict) or "proposal" not in evidence:
            retained.append(issue)
            continue
        structure_id = issue.get("structure_id", evidence.get("structure_id", ""))
        observation = {
            "version": 2,
            "kind": "binding_proposal",
            "status": "unresolved",
            "reason": issue["reason"],
            "page_no": issue["page_no"],
            "cpd": issue.get("cpd") or "",
            "structure_id": structure_id or "",
            "proposal": evidence["proposal"],
            **(
                {"original_pdf_sha256": original_pdf_sha256}
                if original_pdf_sha256
                else {}
            ),
        }
        # The same live buffer enforces per-region/node/aggregate/attempt limits.
        buffer.extend([observation])
        retained.append(
            {
                **issue,
                **({"structure_id": structure_id} if structure_id else {}),
                "evidence": {
                    **{
                        key: value
                        for key, value in evidence.items()
                        if key != "proposal"
                    },
                    "source_diagnostic": proof_id(observation),
                },
            }
        )
    return retained


def binding_diagnostic_issues(catalog, declared=()):
    """Validated unresolved observations survive omitted saved issue flags."""
    for issue in declared:
        evidence = issue.get("evidence") if isinstance(issue, dict) else None
        if isinstance(evidence, dict) and "source_diagnostic" in evidence:
            key = evidence["source_diagnostic"]
            if (
                not isinstance(key, str)
                or key not in catalog
                or catalog[key].get("version") != 2
            ):
                raise ValueError("Original binding diagnostic reference is missing")
    return [
        {
            "cpd": item["cpd"],
            "page_no": item["page_no"],
            "reason": item["reason"],
            **({"structure_id": item["structure_id"]} if item["structure_id"] else {}),
            "evidence": {"source_diagnostic": key},
        }
        for key, item in catalog.items()
        if item["version"] == 2
    ]
