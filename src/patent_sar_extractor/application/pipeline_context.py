"""Explicit facts passed along the sole formal extraction pipeline."""

from __future__ import annotations

import time
from argparse import Namespace
from dataclasses import dataclass, field
from typing import Any

from .progress import PipelineProgress


@dataclass
class PipelineContext:
    args: Namespace
    progress: PipelineProgress
    patent_id: str = ""
    base_dir: str = ""
    force: bool = False
    strict_gates: bool = True
    started_monotonic: float = field(default_factory=time.monotonic)
    scientific_errors: dict[str, list[str]] = field(default_factory=dict)
    source_cpds: list[str] = field(default_factory=list)
    step_dirs: dict[str, str] = field(default_factory=dict)
    pipeline_log: dict[str, Any] = field(default_factory=dict)
    classify_json: str = ""
    classification: dict[str, Any] = field(default_factory=dict)
    ocr_cache_path: str = ""
    act_json: str = ""
    active_cpds: list[str] = field(default_factory=list)
    activity_payload: dict[str, Any] = field(default_factory=dict)
    locate_json: str = ""
    locator: dict[str, Any] = field(default_factory=dict)
    structure_pages: list[int] = field(default_factory=list)
    crop_regions_json: str = ""
    structures_json: str = ""
    n_structures: int = 0
    bind_json: str = ""
    bind_payload: dict[str, Any] = field(default_factory=dict)
    n_bound: int = 0
    smiles_json: str = ""
