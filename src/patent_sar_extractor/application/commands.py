"""CLI use-case dispatch; stage execution and policies have explicit owners."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.artifact_io import load_json as _load_json
from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.core.env_runner import run_in_env
from patent_sar_extractor.core.page_classifier import classify_pdf
from patent_sar_extractor.paths import PACKAGE_ROOT, state_dir
from patent_sar_extractor.smiles_artifact import (
    build_smiles_artifact,
    smiles_records,
)

from .activity_policy import (
    _activity_acceptance_errors,
    _annotate_activity_payload,
)
from .binding_policy import (
    _standalone_smiles_binding_preflight_errors,
)
from .pipeline import execute_pipeline as _execute_pipeline
from .pipeline_io import (
    _write_accuracy_failure_marker,
)
from .smiles_policy import (
    _smiles_acceptance_errors,
)
from .worker_policy import (
    _gpu_env_extra,
)

logger = logging.getLogger("patent_sar_extractor")
WORKING_ROOT = Path.cwd()


def cmd_classify(args):
    print(f"📄 [PatentSAR] classify: {args.pdf}")
    result = classify_pdf(
        args.pdf,
        args.output or os.path.join(os.path.dirname(args.pdf), "page_classification"),
        force_ocr_cache=getattr(args, "force", False),
    )
    print(
        f"  synthesis={len(result.get('synthesis_pages', []))}, activity={len(result.get('activity_pages', []))}"
    )
    return result


def cmd_excerpt(args):
    from patent_sar_extractor.core.review_excerpt import create_review_excerpt_pdf

    metadata_path = args.metadata or os.path.splitext(args.output)[0] + "_metadata.json"
    meta = create_review_excerpt_pdf(args.pdf, args.output, metadata_path, dpi=args.dpi)
    print(
        f"✂️ [PatentSAR] excerpt={meta.get('page_count_excerpt', '?')}/{meta.get('page_count_original', '?')}"
    )
    return meta


def cmd_activity(args):
    from patent_sar_extractor.core.activity_extractor import extract

    output_dir = args.output or os.path.join(
        os.path.dirname(args.pdf) or ".", "activity_output"
    )
    os.makedirs(output_dir, exist_ok=True)
    classification_dir = os.path.join(output_dir, "page_classification")
    profile = classify_pdf(
        args.pdf, classification_dir, force_ocr_cache=getattr(args, "force", False)
    )
    if args.cpd_prefix:
        profile["cpd_pattern"] = args.cpd_prefix
        profile["cpd_prefix_pattern"] = args.cpd_prefix
    result = extract(
        args.pdf,
        profile,
        output_dir,
        include_intermediates=args.include_intermediates,
    )
    activity_json = os.path.join(output_dir, "activity_data.json")
    active_cpds = (
        _annotate_activity_payload(activity_json)
        if os.path.isfile(activity_json)
        else []
    )
    payload = _load_json(activity_json, {}) if os.path.isfile(activity_json) else {}
    errors = _activity_acceptance_errors(payload, active_cpds)
    if errors:
        _write_accuracy_failure_marker(output_dir, "activity", errors)
        raise RuntimeError(
            "Strict activity acceptance gate failed: " + "; ".join(errors[:8])
        )
    print(f"📊 [PatentSAR] activity rows={len(result.get('rows', []))}")
    return result


def cmd_smiles(args):
    script = str(PACKAGE_ROOT / "core" / "ocsr" / "run_smiles.py")
    output_json = (
        args.output
        if args.output.endswith(".json")
        else os.path.join(args.output, "smiles_results.json")
    )
    output_csv = output_json.replace(".json", ".csv")
    os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
    bindings_payload = _load_json(args.bindings, {})
    preflight_errors = _standalone_smiles_binding_preflight_errors(bindings_payload)
    if preflight_errors:
        _write_accuracy_failure_marker(
            os.path.dirname(output_json) or ".",
            "binding_preflight",
            preflight_errors,
        )
        raise RuntimeError(
            "Strict SMILES input gate failed: " + "; ".join(preflight_errors[:8])
        )
    smiles_args = [
        "--input",
        args.bindings,
        "--output",
        output_json,
        "--csv-output",
        output_csv,
        "--engine",
        "decimer",
        "--fallback",
        "",
        "--timeout",
        str(args.timeout),
    ]
    if args.limit:
        smiles_args.extend(["--limit", str(args.limit)])
    if args.include_intermediates:
        smiles_args.append("--include-intermediates")
    proc = run_in_env(
        "smiles_engine",
        script,
        args=smiles_args,
        timeout=7200,
        env_extra=_gpu_env_extra("smiles_engine"),
        stream_output=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:1200]
        raise RuntimeError(f"smiles failed: {err}")
    smiles_payload = _load_json(output_json, {})
    smiles_results = smiles_records(smiles_payload)
    errors = _smiles_acceptance_errors(
        smiles_results if isinstance(smiles_results, list) else [],
        bindings_payload
        if isinstance(bindings_payload, dict)
        else {"final_bindings": bindings_payload},
    )
    if errors:
        _write_accuracy_failure_marker(
            os.path.dirname(output_json) or ".", "smiles", errors
        )
        raise RuntimeError(
            "Strict SMILES acceptance gate failed: " + "; ".join(errors[:8])
        )
    print(f"🧪 [PatentSAR] smiles output={output_json}")
    return {"output_json": output_json, "output_csv": output_csv}


def cmd_validate(args):
    from patent_sar_extractor.core.cpd_validator import validate_cpd_sequence

    known = _load_json(args.known, {})
    known_set = set(known) if isinstance(known, list) else set(known.keys())
    ocr_rows = _load_json(args.ocr_rows, [])
    result = validate_cpd_sequence(ocr_rows, known_set, args.prefix)
    if args.output:
        _write_json(args.output, result)
    print(f"✅ [PatentSAR] validate corrections={len(result['corrections'])}")
    return result


def cmd_score(args):
    from patent_sar_extractor.core.confidence_scorer import score_smiles

    data = _load_json(args.smiles_json, {})
    items = (
        smiles_records(data)
        if isinstance(data, dict)
        else (data if isinstance(data, list) else [])
    )
    for item in items:
        smi = item.get("smiles", item.get("SMILES", ""))
        cs = score_smiles(smi)
        item["confidence"] = {
            "overall": cs.overall,
            "level": cs.level,
            "engine_consensus": cs.engine_consensus,
            "structural_plausibility": cs.structural_plausibility,
            "context_coherence": cs.context_coherence,
        }
    if args.output:
        _write_json(
            args.output,
            build_smiles_artifact(items, execution_mode="diagnostic_scored"),
        )
    print(f"📈 [PatentSAR] score items={len(items)}")
    return items


def cmd_health(args):
    from patent_sar_extractor.core.health_check import write_health_report

    output = args.output or str(state_dir() / "health_check.json")
    report = write_health_report(output, require_gpu=not args.no_gpu)
    print(f"Health: {'OK' if report.get('ok') else 'FAILED'}")
    print(f"Report: {output}")
    if not report.get("ok"):
        raise SystemExit(2)
    return report


def cmd_check_envs(args):
    from patent_sar_extractor.core.env_runner import check_all_envs

    results = check_all_envs()
    print("🔍 [PatentSAR] check-envs")
    for name, info in results.items():
        status = "✅" if info["available"] else "❌"
        print(f"  {status} {name:15s} {info.get('version') or ''}")
    return results


def cmd_qa(args):
    from patent_sar_extractor.core.qa_report import write_qa_report

    print(f"🔎 [PatentSAR] qa: {args.output}")
    result = write_qa_report(args.output, patent_id=getattr(args, "patent_id", ""))
    print(
        f"  {'✅ ACCEPTED' if result.get('acceptance', {}).get('ok') else '❌ STRICT ACCEPTANCE FAILED'}"
    )
    if not result.get("acceptance", {}).get("ok") and not getattr(
        args, "allow_failed", False
    ):
        raise SystemExit(2)
    return result


def cmd_run(args):
    progress = PipelineProgress()
    try:
        return _execute_pipeline(args, progress)
    except BaseException:
        progress.fail_current()
        raise
