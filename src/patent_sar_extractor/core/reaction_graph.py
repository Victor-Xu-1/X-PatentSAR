"""A complete directed source-arrow graph must have exactly one terminal node."""

from collections import defaultdict, deque

from .reaction_layout import resolve_layout_endpoints
from .reaction_reactants import explicit_reactant_groups
from .reaction_steps import MAX_REACTION_DIAGRAMS, page_reaction_steps


def reaction_route(
    candidates,
    pages,
    *,
    source_regions=None,
    endpoint_uncertainty=None,
    allow_co_reactants=False,
    input_operators=None,
    allow_continuations=False,
):
    """All candidates participate; disconnected, cyclic and multiple ends refuse."""
    if not 2 <= len(candidates) <= MAX_REACTION_DIAGRAMS or not all(
        c["inside"] for c in candidates
    ):
        raise ValueError("A native reaction requires its complete bounded drawings")
    nodes = {c["structure_id"] for c in candidates}
    if len(nodes) != len(candidates):
        raise ValueError("Native reaction contains duplicate source identities")
    if endpoint_uncertainty is not None and (
        not isinstance(endpoint_uncertainty, dict)
        or set(endpoint_uncertainty) != {page["page_no"] for page in pages}
    ):
        raise ValueError("Reaction uncertainty page inventory differs from its sources")
    if input_operators is not None and (
        not allow_co_reactants
        or not isinstance(input_operators, dict)
        or set(input_operators) != {page["page_no"] for page in pages}
    ):
        raise ValueError("Reaction operator page inventory differs from its sources")
    outgoing, incoming = defaultdict(set), defaultdict(set)
    observed, role_inventory = set(), []
    reports, page_groups, protected_pages = {}, {}, {}
    for page in pages:
        diagrams = [c for c in candidates if c["page_no"] == page["page_no"]]
        protected = (source_regions or {}).get(
            page["page_no"], [d["bbox"] for d in diagrams]
        )
        report = page_reaction_steps(
            page,
            diagrams,
            protected,
            (endpoint_uncertainty or {}).get(page["page_no"]),
        )
        groups = (
            explicit_reactant_groups(
                page,
                diagrams,
                protected,
                report,
                operators=(input_operators or {}).get(page["page_no"], []),
            )
            if allow_co_reactants
            else []
        )
        if groups:
            role_inventory.append({"page_no": page["page_no"], "steps": groups})
        reports[page["page_no"]], page_groups[page["page_no"]] = report, groups
        protected_pages[page["page_no"]] = protected
    resolutions, joins = (
        resolve_layout_endpoints(
            pages,
            candidates,
            reports,
            page_groups,
            protected_pages,
        )
        if allow_continuations
        else ({}, [])
    )
    for page in pages:
        report, groups = reports[page["page_no"]], page_groups[page["page_no"]]
        grouped = {group["step_index"]: group["input_ids"] for group in groups}
        for index, step in enumerate(report["steps"]):
            first = step["from"] or resolutions.get((page["page_no"], index, "from"))
            last = step["to"] or resolutions.get((page["page_no"], index, "to"))
            if first is None or last is None:
                raise ValueError(
                    "Native route has an unresolved original arrow endpoint"
                )
            for source in grouped.get(index, [first]):
                outgoing[source].add(last)
                incoming[last].add(source)
                observed.update((source, last))
    terminals = nodes - set(outgoing)
    if observed != nodes or len(terminals) != 1:
        raise ValueError("Native route has orphan drawings or multiple terminals")
    degrees = {node: len(incoming[node]) for node in nodes}
    ready = deque(node for node, degree in degrees.items() if not degree)
    visited = set()
    while ready:
        node = ready.popleft()
        visited.add(node)
        for following in outgoing[node]:
            degrees[following] -= 1
            if degrees[following] == 0:
                ready.append(following)
    if visited != nodes:
        raise ValueError("Native reaction contains a cycle")
    # In a finite acyclic graph every node reaches a sink. A single sink and
    # conservation of every node establish one connected terminal, not a rank.
    return {
        "terminal_structure_id": next(iter(terminals)),
        "reactant_groups": role_inventory,
        "layout_joins": joins,
    }
