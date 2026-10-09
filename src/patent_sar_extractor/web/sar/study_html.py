"""Complete passive report; source data never becomes active HTML."""

from __future__ import annotations

import html
import io

from ..errors import WebError
from ..prediction_models import METRIC_KEYS, METRIC_SPECS
from .models import Region
from .study_html_charts import ReportFigures, composition

STYLE = """
*{box-sizing:border-box}body{font:14px/1.6 system-ui,sans-serif;color:#18332f;margin:32px auto;padding:0 24px;max-width:1440px}h1{font-size:30px;letter-spacing:-.03em}h2{margin-top:32px;font-size:21px}h3{font-size:16px}p,small{color:#526962}section{border-top:1px solid #dde8e3;padding-top:16px;margin-top:20px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}.card{padding:18px;border:1px solid #dce7e1;border-radius:12px;min-width:0}.card img{width:100%;height:210px;object-fit:contain}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}td,th{text-align:center;padding:10px;border:1px solid #e0e7e5}th{background:#f3f7f5}td img{width:150px;height:95px;object-fit:contain}.stack{display:flex;background:#f1f5f3;overflow:hidden;border-radius:3px}.stack.horizontal{height:18px}.stack.vertical{flex-direction:column-reverse;width:72px;height:180px;margin:10px auto}.legend{display:flex;flex-wrap:wrap;gap:8px 16px;padding:0;list-style:none;font-size:11px}.legend i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}.legend b{padding-left:5px}.fragment-strip{display:flex;overflow:auto;gap:14px}.fragment-strip .card{flex:0 0 250px}.fragment-strip .legend{display:none}.maps img{width:100%;height:340px;object-fit:contain}.notice{background:#fff8e7;padding:10px 14px;border-radius:8px}.facts{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 20px}.facts dt{color:#526962}.facts dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}code,pre{font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere}details{margin-block:10px}summary{cursor:pointer}nav{display:flex;flex-wrap:wrap;gap:16px;border-block:1px solid #dce7e1;padding:12px 0}a{color:#156655}@media(max-width:600px){body{padding:0 14px;margin-top:16px}.maps img{height:240px}}@media print{body{margin:0}.scroll,.fragment-strip{overflow:visible}.fragment-strip{flex-wrap:wrap}table{white-space:normal}.card{break-inside:avoid}nav{display:none}}
"""


def render_report(job, report, by_id) -> bytes:
    output, figures = io.StringIO(), ReportFigures()
    used = 0

    def add(value):
        nonlocal used
        used += len(value.encode())
        if used > 32 * 1024 * 1024:
            raise WebError(
                413,
                "sar_export_limit",
                "Complete HTML exceeds 32 MiB; use JSON/CSV/SDF.",
            )
        output.write(value)

    def esc(value):
        return html.escape(str(value), quote=True)

    names = {context.id: context for context in report.contexts}
    current = report.counting_contract == "unique-molecules-v2"

    def values(row):
        text = '<dl class="facts">'
        for policy in report.policies:
            raw = " | ".join(row.values.get(policy.context_id, [])) or "—"
            text += f"<dt>{esc(names[policy.context_id].name)}</dt><dd>{esc(raw)}</dd>"
        return text + "</dl>"

    add(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><title>{esc(report.title)}</title><style>{STYLE}</style></head><body>"""
    )
    add(
        f"<h1>{esc(report.title)}</h1><p>{report.molecule_count} source records · {report.eligible_count} eligible structures · {report.observation_count} observations · {report.matched_pair_count} strict matches / {report.strict_pair_count} checked</p>"
    )
    add(
        '<p class="notice">Research only, not validated leads or a reproduction of the article author’s unpublished ranking. Predictions are separate from measurements. Grade ties and overlapping intervals do not establish equal potency.</p>'
    )
    state = report.source_acceptance.state if report.source_acceptance else "unknown"
    add(
        f"<p>Source extraction QA: <strong>{esc(state)}</strong>. This study does not change source acceptance.</p>"
    )
    if job.stale:
        add(
            '<p class="notice">Source changed: historical report, not current conclusions.</p>'
        )
    add(
        '<nav><a href="#overview">Overview</a><a href="#cores">Scaffolds</a><a href="#leads">Candidates</a><a href="#regions">Local SAR</a><a href="#table">Full activity table</a></nav>'
    )
    add('<section id="overview"><h2>Activity overview</h2><div class="cards">')
    for distribution in report.distributions:
        context = names[distribution.context_id]
        add(f'<article class="card"><h3>{esc(context.name)}</h3>')
        policy = next(p for p in report.policies if p.context_id == context.id)
        if policy.strength_method == "tenth_decade":
            scale = policy.strength_scale
            unit = " " + context.unit if context.unit else ""
            caption = (
                f"Strong &lt;{esc(scale.strong_boundary)}{esc(unit)}; medium {esc(scale.strong_boundary)}{esc(unit)}–&lt;{esc(scale.medium_boundary)}{esc(unit)}; weak ≥{esc(scale.medium_boundary)}{esc(unit)}"
                if scale and scale.status == "ready"
                else "Unclassified: insufficient or uncertain tenth measurement, or unsupported endpoint."
            )
            add(f"<p>Tenth potency decade · {caption}</p>")
        add(composition(distribution.bins, current=current))
        add(
            f"<p>{distribution.observed_molecules} observed · {distribution.missing_molecules} missing · {distribution.unresolved_molecules} unresolved · {distribution.strong_molecules} proved strong</p><details><summary>Recorded conditions</summary><pre>{esc(context.context)}</pre></details></article>"
        )
    add("</div>")
    if report.context_declarations:
        add(
            "<details><summary>Source-documented conditions (operator review, not automatic verification)</summary>"
        )
        for declaration in report.context_declarations:
            add(
                f"<h3>{esc(names[declaration.context_id].name)}</h3><pre>{esc(declaration.fields)}</pre><p>Original PDF pages: {esc(declaration.source_pages)} · {esc(declaration.note)}</p><code>Document SHA-256: {esc(declaration.source_document_sha256)}</code>"
            )
        add("</details>")
    add(
        '</section><section id="leads"><h2>Candidate comparison</h2><p>Transparent evidence/Pareto priority; selection order is not a precise drug-efficacy ranking. Missing ADMET remains unknown.</p><div class="cards">'
    )
    for row in report.candidates:
        add(
            f'<article class="card"><h3>{esc(row.label)} · Priority group {row.priority_group}</h3>'
        )
        add(figures.molecule(by_id[row.molecule_id]) + values(row))
        add(
            f"<p>Measured coverage {row.coverage:.0%} · Pareto front {row.pareto_front}</p><details><summary>Properties and predictions</summary><pre>Descriptors: {esc(row.properties)}\nOrigins: {esc(row.property_origins)}\nPredictions ({esc(row.prediction_origin)}): {esc(row.predictions)}</pre></details><details><summary>Evidence</summary><pre>{esc(row.reasons)}</pre></details></article>"
        )
    if not report.candidates:
        add(
            "<p>No supported candidates. Missing conditions and unresolved structures are not guessed.</p>"
        )
    add(
        '</div></section><section id="cores"><h2>Scaffold overview</h2><p>Descriptive groups are not strict fixed-background proof; confirmed core groups can overlap.</p><div class="cards">'
    )
    for index, item in enumerate(report.scaffolds, 1):
        add(
            f'<article class="card"><h3>Core {index} · {esc(item.assignment_kind)}</h3>'
        )
        add(figures.fragment(item.smiles, f"Core {index}"))
        add(composition(item.bins, current=current))
        add(
            f"<p>{item.molecule_count} source records · {item.strong_count} strong</p></article>"
        )
    add(
        '</div></section><section id="regions"><h2>Strict local SAR</h2><p>Only the specified region varies. Fixed graphs, attachment identities and stereochemistry are preserved; one reference background is not independent replication.</p>'
    )
    maps: dict[str, list[Region]] = {}
    for summary in report.regions:
        maps.setdefault(summary.region.molecule_id, []).append(summary.region)
    add('<div class="cards maps">')
    for identifier, regions in maps.items():
        add(
            '<article class="card">'
            + figures.region_map(by_id[identifier], regions)
            + "</article>"
        )
    add("</div>")
    for summary in report.regions:
        add(
            f"<h3>{esc(summary.region.name)} · reference {esc(summary.reference_label)}</h3><p>{summary.matched} matched · {summary.not_matched} different fixed backgrounds · {summary.ambiguous} ambiguous · {summary.ineligible} ineligible</p>"
        )
        if summary.no_variation:
            add("<p>No selected-region variation in the proved comparison pool.</p>")
        add('<div class="fragment-strip">')
        for index, item in enumerate(summary.fragments, 1):
            add(
                f'<article class="card"><h3>Fragment {index}{" · reference" if item.is_reference else ""}</h3>'
            )
            add(composition(item.bins, current=current, vertical=True))
            add(figures.fragment(item.smiles, f"Fragment {index}"))
            add(
                f"<p>{item.strong_count}/{item.molecule_count} strong · Better {item.better} · Worse {item.worse} · Indeterminate {item.indeterminate} · Missing {item.missing}</p></article>"
            )
        add("</div>")
    add(
        '</section><section id="table"><h2>All source records</h2><p>Natural original-identifier order. Structure-only records and unknown measurements remain present.</p><div class="scroll"><table><thead><tr><th>Original identifier</th><th>Structure</th><th>Candidate</th>'
    )
    for policy in report.policies:
        add(f"<th>{esc(names[policy.context_id].name)}</th>")
    for key in METRIC_KEYS:
        add(f"<th>{esc(METRIC_SPECS[key][0])}</th>")
    add("<th>Source page</th></tr></thead><tbody>")
    for row in report.rows:
        molecule = by_id[row.molecule_id]
        add(
            f"<tr><td>{esc(row.label)}</td><td>{figures.molecule(molecule)}</td><td>{esc(row.candidate_status)}</td>"
        )
        for policy in report.policies:
            add(
                f"<td>{esc(' | '.join(row.values.get(policy.context_id, [])) or '—')}</td>"
            )
        for key in METRIC_KEYS:
            value = row.properties.get(key)
            add(f"<td>{esc(value if value is not None else '—')}</td>")
        add(f"<td>{esc(molecule.source_page or '—')}</td></tr>")
    add(
        "</tbody></table></div></section><details><summary>Technical evidence and research limitations</summary><pre>"
    )
    add(esc("\n".join(report.warnings)))
    add(
        f"</pre><code>Input SHA-256: {esc(job.input_sha256)}<br>Engine SHA-256: {esc(report.engine_sha256)}</code></details></body></html>"
    )
    return output.getvalue().encode()
