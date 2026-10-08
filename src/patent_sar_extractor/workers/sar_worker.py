"""Single-process, bounded strict-reference SAR; immutable chunk checkpoints."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from patent_sar_extractor.core.sar.errors import SARInputError


def _pair(reference, candidate, region, request, matcher):
    from patent_sar_extractor.core.sar.statistics import compare_observations
    from patent_sar_extractor.web.sar.models import Pair

    values = lambda row: [
        obs.value for obs in row.observations if obs.metric_id == request.metric_id
    ]
    graph = {"match_status": "ineligible", "reasons": ["structure_unavailable"]}
    if candidate.eligible and candidate.molfile:
        graph = matcher.compare(candidate.molfile)
    measured = {
        "comparison": "indeterminate",
        "reference_values": values(reference),
        "candidate_values": values(candidate),
        "fold_change": None,
        "evidence_basis": "insufficient",
        "reasons": [],
    }
    if graph["match_status"] == "matched":
        measured = compare_observations(
            [
                obs.model_dump()
                for obs in reference.observations
                if obs.metric_id == request.metric_id
            ],
            [
                obs.model_dump()
                for obs in candidate.observations
                if obs.metric_id == request.metric_id
            ],
            request.metric_id,
            request.direction,
            request.grade_order,
            request.confirm_context,
        )
    return Pair(
        reference_id=reference.id,
        molecule_id=candidate.id,
        label=candidate.label,
        match_status=graph["match_status"],
        reasons=list(dict.fromkeys([*graph["reasons"], *measured.pop("reasons", [])])),
        **measured,
    )


def analyse(root: Path, input_sha256: str) -> dict:
    from patent_sar_extractor.core.sar.matching import compile_reference
    from patent_sar_extractor.web.files import SafeFiles
    from patent_sar_extractor.web.sar.assets import atomic_json, digest
    from patent_sar_extractor.web.sar.engine import engine_identity
    from patent_sar_extractor.web.sar.models import (
        AnalysisRequest,
        Dataset,
        Molecule,
        Pair,
        Region,
    )

    safe = SafeFiles(root)
    packet = safe.json("input.json", optional=False)
    if isinstance(packet, dict) and packet.get("schema") == 2:
        from .study_analysis import analyse_study

        return analyse_study(root, input_sha256)
    if (
        not isinstance(packet, dict)
        or packet.get("schema") != 1
        or digest(packet) != input_sha256
        or packet.get("engine_sha256") != engine_identity()
    ):
        raise ValueError("input identity")
    dataset = Dataset.model_validate(packet["dataset"])
    region = Region.model_validate(packet["region"])
    request = AnalysisRequest.model_validate(packet["request"])
    rows = [Molecule.model_validate(row) for row in packet["molecules"]]
    if (
        not 2 <= len(rows) <= 25000
        or len({row.id for row in rows}) != len(rows)
        or dataset.row_count != len(rows)
    ):
        raise ValueError("input completeness")
    reference = next(row for row in rows if row.id == region.molecule_id)
    if (
        not reference.eligible
        or reference.graph_sha256 != region.graph_sha256
        or region.dataset_id != dataset.id
    ):
        raise ValueError("region identity")
    candidates = [row for row in rows if row.id != reference.id]
    matcher = compile_reference(reference.molfile, region.atom_indices)
    count = (len(candidates) + 24) // 25
    processed = matched = 0
    started = time.monotonic()
    for index in range(count):
        if time.monotonic() - started > 175:
            raise TimeoutError("SAR attempt deadline")
        batch = candidates[index * 25 : (index + 1) * 25]
        name = f"chunk-{index:04d}.json"
        saved = safe.json(name)
        if saved is not None:
            if (
                not isinstance(saved, dict)
                or set(saved)
                != {"input_sha256", "engine_sha256", "start", "pairs", "pairs_sha256"}
                or saved["input_sha256"] != input_sha256
                or saved["engine_sha256"] != packet["engine_sha256"]
                or saved["start"] != index * 25
                or digest(saved["pairs"]) != saved["pairs_sha256"]
            ):
                raise ValueError("checkpoint identity")
            pairs = [Pair.model_validate(pair) for pair in saved["pairs"]]
            if len(pairs) != len(batch) or any(
                pair.molecule_id != row.id
                or pair.reference_id != reference.id
                or pair.label != row.label
                for pair, row in zip(pairs, batch, strict=True)
            ):
                raise ValueError("checkpoint coverage")
        else:
            pairs = [_pair(reference, row, region, request, matcher) for row in batch]
            data = [pair.model_dump() for pair in pairs]
            atomic_json(
                root,
                name,
                {
                    "input_sha256": input_sha256,
                    "engine_sha256": packet["engine_sha256"],
                    "start": index * 25,
                    "pairs": data,
                    "pairs_sha256": digest(data),
                },
            )
        processed += len(pairs)
        matched += sum(pair.match_status == "matched" for pair in pairs)
        atomic_json(
            root,
            "progress.json",
            {"input_sha256": input_sha256, "processed": processed, "matched": matched},
        )
    return {
        "input_sha256": input_sha256,
        "engine_sha256": packet["engine_sha256"],
        "chunks": count,
    }


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("request bound")
        request = json.loads(raw)
        if not isinstance(request, dict) or set(request) != {"root", "input_sha256"}:
            raise ValueError("request schema")
        root = Path(request["root"])
        if not root.is_absolute() or root.is_symlink():
            raise ValueError("request location")
        result = analyse(root, request["input_sha256"])
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    except SARInputError as error:
        from patent_sar_extractor.web.sar.engine import engine_identity

        # A typed domain failure is a successful protocol exchange, NOT a
        # successful analysis. The sole parent publishes an explicit failed job.
        print(
            json.dumps(
                {
                    "ok": True,
                    "result": {
                        "input_sha256": request["input_sha256"],
                        "engine_sha256": engine_identity(),
                        "failure_code": error.code,
                    },
                },
                allow_nan=False,
            )
        )
        return 0
    except (
        ValueError,
        OSError,
        RuntimeError,
        KeyError,
        TypeError,
        StopIteration,
        ImportError,
        MemoryError,
    ):
        # Untrusted CSV/chemistry and process locations must not leak to logs/API.
        print(json.dumps({"ok": False, "code": "sar_worker_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
