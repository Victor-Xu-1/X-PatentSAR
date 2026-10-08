"""Minimal offline presentation from real study records, with no active content."""

from __future__ import annotations

import base64
import html
import io

from ...core.sar.drawing import draw_structure
from ..errors import WebError
from ..prediction_models import METRIC_KEYS, METRIC_SPECS


def render_report(job, report, by_id) -> bytes:
    output = io.StringIO()
    used = 0

    def add(value):
        nonlocal used
        used += len(value.encode())
        if used > 32 * 1024 * 1024:
            raise WebError(
                413,
                "sar_export_limit",
                "Complete HTML exceeds 32 MiB; use the full JSON/CSV/SDF export.",
            )
        output.write(value)

    esc = lambda value: html.escape(str(value), quote=True)
    add("""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><title>SAR research report</title><style>
    *{box-sizing:border-box}body{font:15px/1.6 system-ui,sans-serif;color:#172a2a;margin:32px auto;padding:0 24px;max-width:1280px}h1{font-size:32px}h2{margin-top:36px;font-size:22px}p{color:#536565}section{border-top:1px solid #dde5e5;padding-top:20px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}.card{padding:18px;background:#f5f8f7;border-radius:12px}.card img{width:100%;height:180px;object-fit:contain}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}td,th{text-align:center;padding:10px;border-bottom:1px solid #e0e7e5}th{background:#f3f7f5}.strong{background:#6dd59a}.bar{height:8px;background:#42ba83;border-radius:4px;margin-bottom:12px}code{font-size:11px;word-break:break-all}.notice{background:#fff8e7;padding:12px;border-radius:10px}@media print{body{margin:0}.scroll{overflow:visible}table{white-space:normal}section{break-inside:avoid}}
    </style><body>""")
    add(
        f"<h1>{esc(report.title)}</h1><p>{report.molecule_count} source molecules · {report.eligible_count} eligible structures · {report.observation_count} observations · {report.strict_pair_count} strict-region comparisons</p>"
    )
    add(
        '<p class="notice">Research prioritization only. Grade ties are not equal quantitative potency. Scaffolds are descriptive, not proof of strict fixed-background equality. Model predictions remain separate from measured patent activity.</p>'
    )
    if job.stale:
        add(
            '<p class="notice">Source changed: retained historical report, not current conclusions.</p>'
        )
    names = {context.id: context for context in report.contexts}
    for distribution in report.distributions:
        context = names[distribution.context_id]
        add(
            f"<section><h2>{esc(context.name)} · {esc(context.unit or '')}</h2><p>{esc(context.context)}</p>"
        )
        add(
            f"<p>{distribution.observed_molecules} observed molecules; {distribution.observations} observations; {distribution.missing_molecules} missing; {distribution.unresolved_molecules} unresolved.</p>"
        )
        for item in distribution.bins:
            percent = 100 * item.observations / max(1, distribution.observations)
            add(
                f'<div>{esc(item.label)} · {item.observations} readings · {item.molecules} molecules</div><div class="bar" style="width:{percent:.3f}%"></div>'
            )
        add("</section>")
    add(
        '<section><h2>Lead candidates</h2><p>Transparent strict-context Pareto and evidence priority; selection order is not a precise drug-efficacy ranking. Missing ADMET is unknown, not safe.</p><div class="cards">'
    )
    for row in report.candidates:
        molecule = by_id[row.molecule_id]
        add(f'<article class="card"><h3>{esc(row.label)}</h3>')
        if molecule.eligible and molecule.molfile:
            svg = draw_structure(molecule.molfile)["svg"]
            data = base64.b64encode(svg.encode()).decode()
            add(
                f'<img alt="{esc(row.label)} structure" src="data:image/svg+xml;base64,{data}">'
            )
        add(
            f"<p>Priority group {row.priority_group} · measured coverage {row.coverage:.0%}</p><p>{esc(row.values)}</p><p>Descriptors: {esc(row.properties)}</p><p>Predictions ({esc(row.prediction_origin)}): {esc(row.predictions)}</p><p>{esc(row.reasons)}</p></article>"
        )
    add(
        '</div></section><section><h2>Scaffold overview</h2><div class="scroll"><table><thead><tr><th>Descriptive scaffold</th><th>Molecules</th><th>Strong</th></tr></thead><tbody>'
    )
    for item in report.scaffolds:
        add(
            f"<tr><td>{esc(item.smiles or 'Acyclic / no ring core')}</td><td>{item.molecule_count}</td><td>{item.strong_count}</td></tr>"
        )
    add("</tbody></table></div></section>")
    for summary in report.regions:
        add(
            f"<section><h2>{esc(summary.region.name)} · {esc(summary.reference_label)}</h2><p>{summary.matched} matched · {summary.not_matched} different fixed backgrounds · {summary.ambiguous} ambiguous · {summary.ineligible} ineligible. Independent fixed backgrounds: {summary.independent_backgrounds}.</p>"
        )
        if summary.no_variation:
            add("<p>No selected-region variation in the proved comparison pool.</p>")
        add(
            '<div class="scroll"><table><thead><tr><th>Port-labelled fragment</th><th>Molecules</th><th>Strong</th><th>Better</th><th>Worse</th><th>Indeterminate</th><th>Missing</th></tr></thead><tbody>'
        )
        for item in summary.fragments:
            add(
                f"<tr><td>{esc(item.smiles)}</td><td>{item.molecule_count}</td><td>{item.strong_count}</td><td>{item.better}</td><td>{item.worse}</td><td>{item.indeterminate}</td><td>{item.missing}</td></tr>"
            )
        add("</tbody></table></div></section>")
    add(
        '<section><h2>All source molecules</h2><p>Natural original-identifier order. Full molecular graphs and excluded-record reasons are retained in JSON; eligible structures can be exported as SDF.</p><div class="scroll"><table><thead><tr><th>Identifier</th><th>Candidate</th>'
    )
    for policy in report.policies:
        add(f"<th>{esc(names[policy.context_id].name)}</th>")
    for key in METRIC_KEYS:
        add(f"<th>{esc(METRIC_SPECS[key][0])}</th>")
    add("</tr></thead><tbody>")
    for row in report.rows:
        add(
            f"<tr{(' class=strong' if row.strong else '')}><td>{esc(row.label)}</td><td>{esc(row.candidate_status)}</td>"
        )
        for policy in report.policies:
            add(
                f"<td>{esc(' | '.join(row.values.get(policy.context_id, [])) or '—')}</td>"
            )
        for key in METRIC_KEYS:
            value = row.properties.get(key)
            add(f"<td>{esc(value if value is not None else '—')}</td>")
        add("</tr>")
    add(
        f"</tbody></table></div></section><p>Input SHA-256: <code>{esc(job.input_sha256)}</code><br>Engine SHA-256: <code>{esc(report.engine_sha256)}</code></p></body></html>"
    )
    return output.getvalue().encode()
