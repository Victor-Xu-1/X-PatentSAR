"""Passive report figures from the same recorded counts and immutable graphs."""

from __future__ import annotations

import base64
import json
from html import escape
from importlib.resources import files

from ...core.sar.drawing import draw_fragment, draw_molecule_preview, draw_structure

COLORS = (
    "#106c57",
    "#278a6d",
    "#4da885",
    "#78bea0",
    "#a8d4bd",
    "#cee6d9",
    "#e6f2eb",
    "#edf5f1",
)
REGION_COLORS = ("#137e78", "#466ca4", "#a17421", "#865ba3", "#407b3a", "#a05166")
ACTIVITY_COLORS = json.loads(
    files(__package__).joinpath("chart_palette.json").read_text()
)


def image(svg: str, label: str) -> str:
    data = base64.b64encode(svg.encode()).decode()
    return f'<img alt="{escape(label, quote=True)}" src="data:image/svg+xml;base64,{data}">'


def composition(
    bins, *, current: bool, vertical: bool = False, strong_rule: bool | None = None
) -> str:
    unit = "molecules" if current else "observations"
    total = sum(getattr(item, unit) for item in bins)
    pieces, legend = [], []
    for index, item in enumerate(bins):
        value = getattr(item, unit)
        color = (
            ACTIVITY_COLORS.get(item.label, ACTIVITY_COLORS["unclassified"])
            if item.kind == "strength"
            else (
                COLORS[index % len(COLORS)]
                if item.kind in {"numeric", "ordinal"}
                else ACTIVITY_COLORS.get(item.kind, ACTIVITY_COLORS["unclassified"])
            )
        )
        percent = 100 * value / max(1, total)
        style = f"height:{percent:.4f}%;" if vertical else f"width:{percent:.4f}%;"
        pieces.append(
            f'<span style="{style}background:{color}" title="{escape(item.label, quote=True)}: {value}"></span>'
        )
        legend.append(
            f'<li><i style="background:{color}"></i>{escape(item.label)} <b>{value}</b></li>'
        )
    label = (
        "source IDs / records" if current else "raw observations (historical counting)"
    )
    orientation = "vertical" if vertical else "horizontal"
    strong = sum(getattr(item, unit) for item in bins if item.strong)
    classified = (
        any(item.kind == "strength" or item.strong for item in bins)
        if strong_rule is None
        else strong_rule
    )
    share = (
        f"<div>Strong {100 * strong / total:.1f}%</div>" if total and classified else ""
    )
    return f'<div class="composition"><strong>{total} {label}</strong>{share}<div class="stack {orientation}" aria-label="Activity composition">{"".join(pieces)}</div><ul class="legend">{"".join(legend)}</ul></div>'


class ReportFigures:
    def __init__(self):
        self.cache: dict[tuple[str, str], str] = {}

    def fragment(self, smiles: str | None, label: str) -> str:
        if not smiles:
            return '<p class="notice">Structure needs review; no graph is invented.</p>'
        key = ("fragment", smiles)
        if key not in self.cache:
            self.cache[key] = draw_fragment(smiles)
        return image(self.cache[key], label)

    def molecule(self, molecule) -> str:
        if not molecule.eligible or not molecule.molfile:
            return "<span>Structure needs review</span>"
        key = ("molecule", molecule.graph_sha256)
        if key not in self.cache:
            self.cache[key] = draw_molecule_preview(molecule.molfile)
        return image(self.cache[key], molecule.label)

    def region_map(self, molecule, regions) -> str:
        drawing = draw_structure(molecule.molfile)
        marks, legend = [], []
        for order, region in enumerate(regions):
            color = REGION_COLORS[order % len(REGION_COLORS)]
            atoms = [
                atom
                for atom in drawing["atoms"]
                if atom["index"] in region.atom_indices
                or atom["index"] == region.hydrogen_anchor
            ]
            for atom in atoms:
                marks.append(
                    f'<circle cx="{atom["x"] * 1000:.3f}" cy="{atom["y"] * 800:.3f}" r="12" fill="{color}" fill-opacity=".1" stroke="{color}" stroke-width="1.5"/>'
                )
            if atoms:
                x = min(
                    960, max(24, sum(atom["x"] for atom in atoms) / len(atoms) * 1000)
                )
                y = max(24, min(atom["y"] for atom in atoms) * 800 - 25)
                marks.append(
                    f'<text x="{x:.3f}" y="{y:.3f}" fill="{color}" text-anchor="middle" font-size="20">R{order + 1}{" (H)" if region.hydrogen_anchor is not None else ""}</text>'
                )
            legend.append(
                f'<li><i style="background:{color}"></i>R{order + 1} · {escape(region.name or "")}</li>'
            )
        # Same drawer coordinates and immutable atom identities as online selection.
        marked = drawing["svg"].replace("</svg>", "".join(marks) + "</svg>")
        return (
            image(marked, molecule.label + " reference region map")
            + '<ul class="legend">'
            + "".join(legend)
            + "</ul>"
        )
