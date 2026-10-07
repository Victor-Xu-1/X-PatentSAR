#!/usr/bin/env python3
"""
PatentSAR SMILES engine runner.

Converts bound structure images to SMILES, InChIKey and molecular formula
using DECIMER as the only accepted production OCSR engine.

Default strict chain: DECIMER only, no fallback.  This avoids accepting
conflicting OCSR results from mixed engines and keeps production output
deterministic.

Usage:
    python -m patent_sar_extractor.core.ocsr.run_smiles \
        --input outputs/example/structure_bindings/bindings.json \
        --output outputs/WO2026067249/smiles_results.json \
        --csv-output outputs/WO2026067249/smiles_results.csv \
        --engine decimer \
        --fallback "" \
        --cache outputs/cache/smiles_cache.sqlite \
        --preprocess \
        --timeout 300 \
        --limit 20
"""

import argparse
import json
import os
import runpy
import sys
import time
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "worker_bootstrap.py"),
    run_name="__main__",
)

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    artifact_identity_matches,
)
from patent_sar_extractor.core.cpd_filter import filter_examples_only
from patent_sar_extractor.core.ocsr.observation_completion import (
    publish_scientific_findings,
    require_complete_source_results,
    validate_source_observation_mode,
)
from patent_sar_extractor.core.ocsr.recognition_inputs import (
    ordered_source_results,
    recognition_inputs,
)
from patent_sar_extractor.core.ocsr.smiles_converter import SmilesConverter
from patent_sar_extractor.core.ocsr.stereo_gate import stereo_record_error
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.smiles_artifact import (
    DIAGNOSTIC_SMILES_MODE,
    PRODUCTION_SMILES_MODE,
    build_smiles_artifact,
)

WORKING_ROOT = str(Path.cwd())


def load_bindings(input_path: str) -> list:
    """Load binding results from JSON.

    Handles two formats:
    1. Dict with a ``final_bindings`` key (standard output)
    2. List of binding dicts directly

    Also supports CSV input.
    """
    if input_path.endswith(".csv"):
        import pandas as pd

        df = pd.read_csv(input_path)
        return df.to_dict("records")

    with open(input_path, "r") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        # Look for common keys
        for key in ("final_bindings", "bindings", "results", "structures"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Maybe the dict itself is a single binding
        if "cpd" in data or "image_path" in data:
            return [data]

    raise ValueError(f"Cannot parse binding results from: {input_path}")


def _normalize_cpd(value: str) -> str:
    import re

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    match = re.search(
        r"(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*(\d+(?:-\d+)?[A-Z]?)",
        text,
        re.IGNORECASE,
    )
    return f"Compound {match.group(1).upper()}" if match else text


def validate_strict_binding_input(input_path: str, bindings: list) -> list[str]:
    """Reject direct OCSR use on stale, unconfirmed, or duplicated final bindings."""
    if input_path.lower().endswith(".csv"):
        return ["Strict OCSR requires current-version bindings JSON, not CSV input."]
    try:
        with open(input_path, "r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, ValueError) as exc:
        return [f"Strict OCSR could not read binding payload: {exc}"]
    if not artifact_identity_matches(payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION):
        return ["Binding input does not match the current bindings schema and ruleset."]
    if payload.get("execution_mode") != "production_structure_led":
        return [
            "Binding input was not produced by the production structure-led pipeline."
        ]
    final_bindings = payload.get("final_bindings", [])
    if (
        not isinstance(final_bindings, list)
        or final_bindings != bindings
        or not final_bindings
    ):
        return [
            "Strict OCSR processes only the complete final_bindings list without substitution."
        ]
    errors = []
    seen_structures = set()
    for binding in final_bindings:
        checked = (
            annotate_binding_accuracy(dict(binding))
            if isinstance(binding, dict)
            else {}
        )
        cpd = _normalize_cpd(checked.get("cpd", "")) or "unknown compound"
        sid = str(checked.get("structure_id") or "")
        if checked.get("accuracy_status") != "confirmed" or checked.get("fail_closed"):
            errors.append(
                f"{cpd}: binding does not pass fresh current-rule confirmation."
            )
        if not sid:
            errors.append(f"{cpd}: binding has no structure_id.")
        elif sid in seen_structures:
            errors.append(
                f"{cpd}: structure_id {sid} is already assigned to another final compound."
            )
        seen_structures.add(sid)
    return errors


def validate_strict_smiles_results(bindings: list, results: list) -> list[str]:
    """Require exactly one clean result for each confirmed structure in binding order."""
    expected = [
        (
            _normalize_cpd(binding.get("cpd", binding.get("cpd_id", ""))),
            str(binding.get("structure_id") or ""),
        )
        for binding in bindings
        if isinstance(binding, dict)
    ]
    actual = [
        (
            _normalize_cpd(result.get("cpd_id", "")),
            str(result.get("structure_id") or ""),
        )
        for result in results
        if isinstance(result, dict)
    ]
    errors = []
    if len(actual) != len(results) or actual != expected:
        errors.append(
            "OCSR result records are not a one-to-one ordered match for confirmed structure bindings."
        )
    for result in results:
        if not isinstance(result, dict):
            errors.append("OCSR produced a malformed output record.")
            continue
        cpd = _normalize_cpd(result.get("cpd_id", "")) or "unknown compound"
        suspicious = result.get("suspicious_elements") or []
        stereo_error = stereo_record_error(result)
        if stereo_error:
            errors.append(
                f"{cpd}: source stereochemistry requires review: {stereo_error}"
            )
        if (
            not result.get("rdkit_valid")
            or not result.get("canonical_smiles")
            or result.get("OCSR_quality_flag", "ok") != "ok"
            or suspicious
        ):
            errors.append(
                f"{cpd}: no automatically acceptable SMILES "
                f"(quality={result.get('OCSR_quality_flag')}, suspicious={suspicious})."
            )
    return errors


def _load_structure_image_lookup(base_dir: str = "") -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    if not base_dir:
        return lookup
    base = Path(base_dir).resolve()
    candidate_roots = [base, base.parent, base.parent.parent]
    candidates = [root / "structures" / "metadata.json" for root in candidate_roots]
    for metadata_path in candidates:
        if not metadata_path.is_file():
            continue
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError) as exc:
            raise ValueError("Structure metadata lookup is unreadable") from exc
        records = payload.get("structures") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            sid = str(rec.get("structure_id") or rec.get("id") or "").strip()
            img = str(rec.get("image_path") or "").strip()
            if sid and img:
                lookup[sid] = rec
        if lookup:
            break
    return lookup


def _is_clean_segmented_structure(rec: dict) -> bool:
    bbox = rec.get("bbox_pdf") or []
    if len(bbox) != 4:
        return False
    width = max(0.0, float(bbox[2]) - float(bbox[0]))
    height = max(0.0, float(bbox[3]) - float(bbox[1]))
    area = width * height
    aspect = width / max(height, 1.0)
    return area >= 4200 and width >= 100 and height >= 28 and aspect <= 5.5


def _choose_ocsr_image_path(
    item: dict, structure_lookup: dict[str, dict] | None = None
) -> str:
    """Choose the cleanest available image for OCSR."""
    ocsr_path = str(item.get("ocsr_image_path") or "").strip()
    if ocsr_path and os.path.isfile(ocsr_path):
        return ocsr_path

    image_path = str(
        item.get("image_path") or item.get("structure_image") or ""
    ).strip()
    rule = str(item.get("binding_rule") or "")
    source_sid = str(item.get("source_structure_id") or "").strip()
    if (
        structure_lookup
        and source_sid
        and (
            "expanded_strict_labels" in image_path
            or "merged_fragment" not in rule
            and str(item.get("expanded_from_fragment") or "")
        )
    ):
        # Expanded strict-label crops are visual evidence crops; use the original
        # segmented structure for OCSR when it is available.
        source_rec = structure_lookup.get(source_sid) or {}
        src_img = str(source_rec.get("image_path") or "").strip()
        if (
            _is_clean_segmented_structure(source_rec)
            and src_img
            and os.path.isfile(src_img)
        ):
            return src_img

    source_path = str(item.get("source_image_path") or "").strip()
    if source_path and os.path.isfile(source_path):
        return source_path

    if image_path and os.path.isfile(image_path):
        return image_path
    if image_path:
        return image_path
    return str(item.get("source_image_path") or item.get("ocsr_image_path") or "")


def resolve_image_paths(bindings: list, base_dir: str = "") -> list:
    """Resolve image paths to absolute paths.

    Binding output may contain relative ``image_path`` values.
    Try to resolve them relative to base_dir or the caller's working directory.
    """
    structure_lookup = _load_structure_image_lookup(base_dir)
    resolved = []
    for item in bindings:
        item = dict(item)  # Copy
        img_path = _choose_ocsr_image_path(item, structure_lookup)

        if img_path and not os.path.isabs(img_path):
            # Try relative to base_dir
            if base_dir:
                abs_path = os.path.join(base_dir, img_path)
                if os.path.isfile(abs_path):
                    item["ocsr_image_path"] = os.path.abspath(abs_path)
                    resolved.append(item)
                    continue

            # Try relative to the caller's working directory.
            abs_path = os.path.join(WORKING_ROOT, img_path)
            if os.path.isfile(abs_path):
                item["ocsr_image_path"] = os.path.abspath(abs_path)
                resolved.append(item)
                continue

        if img_path and os.path.isfile(img_path):
            item["ocsr_image_path"] = os.path.abspath(img_path)
        resolved.append(item)

    return resolved


def print_summary(results: list, output_json: str, output_csv: str, elapsed: float):
    """Print a summary of the SMILES conversion results."""
    total = len(results)
    bound = sum(1 for r in results if r.get("OCSR_status") != "not_processed")
    success = sum(1 for r in results if r.get("OCSR_status") == "success")
    rdkit_valid = sum(1 for r in results if r.get("rdkit_valid"))
    invalid = sum(1 for r in results if r.get("OCSR_status") == "invalid_smiles")
    image_missing = sum(1 for r in results if r.get("OCSR_status") == "image_missing")
    engine_unavailable = sum(
        1 for r in results if r.get("OCSR_status") == "engine_unavailable"
    )
    timeout = sum(1 for r in results if r.get("OCSR_status") == "engine_timeout")
    all_failed = sum(1 for r in results if r.get("OCSR_status") == "all_engines_failed")
    markush = sum(
        1 for r in results if r.get("OCSR_quality_flag") == "markush_or_query"
    )

    # Engine usage stats
    engine_counts = {}
    for r in results:
        engine = r.get("OCSR_engine")
        if engine:
            engine_counts[engine] = engine_counts.get(engine, 0) + 1

    print("\n" + "=" * 60)
    print("PatentSAR SMILES Engine - Summary")
    print("=" * 60)
    print(f"Total records:      {total}")
    print(f"Processed:          {bound}")
    print(f"Success:            {success}")
    print(f"  RDKit valid:      {rdkit_valid}")
    print(f"  Markush/query:    {markush}")
    print(f"Invalid SMILES:     {invalid}")
    print(f"Image missing:      {image_missing}")
    print(f"Engine unavailable: {engine_unavailable}")
    print(f"Timeout:            {timeout}")
    print(f"All engines failed: {all_failed}")
    print(f"Engine usage:       {engine_counts}")
    print(f"Elapsed time:       {elapsed:.1f}s")
    print(f"Output JSON:        {output_json}")
    print(f"Output CSV:         {output_csv}")
    print("=" * 60)


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        sys.stderr.write("Output streams do not support line buffering.\n")

    parser = argparse.ArgumentParser(
        description="PatentSAR SMILES engine: convert structure images to SMILES"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Binding results JSON or CSV",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path (default: auto-generated)",
    )
    parser.add_argument(
        "--csv-output",
        default="",
        help="Output CSV path (default: auto-generated)",
    )
    parser.add_argument(
        "--engine",
        default="decimer",
        help="Primary OCSR engine (default: decimer)",
    )
    parser.add_argument(
        "--fallback",
        default="",
        help="Comma-separated fallback engines (default: empty; production OCSR is DECIMER-only)",
    )
    parser.add_argument(
        "--cache",
        default="",
        help="SQLite cache path (default: auto-generated)",
    )
    parser.add_argument(
        "--preprocess",
        action="store_true",
        default=True,
        help="Enable image preprocessing (default: True)",
    )
    parser.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Disable image preprocessing",
    )
    parser.add_argument(
        "--retry-normalization",
        action="store_true",
        help="Allow one same-image normalization retry after a non-clean raw prediction",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-image DECIMER timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of items to process (for testing)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Bounded parallel image-preparation workers; DECIMER inference uses one owned model.",
    )
    parser.add_argument(
        "--only-bound",
        action="store_true",
        default=True,
        help="Only process bound structures (default: True)",
    )
    parser.add_argument(
        "--include-unbound",
        action="store_true",
        help="Also process unbound structures",
    )
    parser.add_argument(
        "--preprocess-long-edge",
        type=int,
        default=1024,
        help="Preprocessing target long edge (default: 1024)",
    )
    parser.add_argument(
        "--preprocess-padding",
        type=int,
        default=20,
        help="Preprocessing padding in pixels (default: 20)",
    )
    parser.add_argument(
        "--include-intermediates",
        action="store_true",
        help="Include Intermediate (中间体) compounds (default: filter them out, keep only Examples)",
    )
    parser.add_argument(
        "--diagnostic-unvalidated-input",
        action="store_true",
        help="Diagnostic only: allow stale/unconfirmed input and non-clean output without accepting deliverables.",
    )
    parser.add_argument(
        "--continue-on-scientific-errors",
        action="store_true",
        help="Source-led coordinator only: retain complete observations for final QA; never accept rejected chemistry.",
    )

    args = parser.parse_args()

    # Parse engine lists
    primary_engines = [e.strip() for e in args.engine.split(",") if e.strip()]
    fallback_engines = [e.strip() for e in args.fallback.split(",") if e.strip()]
    if primary_engines != ["decimer"] or fallback_engines:
        requested = primary_engines + fallback_engines
        raise RuntimeError(
            "Strict production OCSR is DECIMER-only; remove non-DECIMER engines "
            f"and fallback entries. requested={requested}"
        )

    # Handle preprocess flags
    preprocess = args.preprocess and not args.no_preprocess
    only_bound = args.only_bound and not args.include_unbound

    # Auto-generate output paths
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    if not args.output:
        args.output = f"artifacts/smiles_runs/smiles_{timestamp}/smiles_results.json"
    if not args.csv_output:
        args.csv_output = f"artifacts/smiles_runs/smiles_{timestamp}/smiles_results.csv"
    if not args.cache:
        args.cache = f"artifacts/smiles_runs/smiles_{timestamp}/smiles_cache.sqlite"

    # Create output directories
    for path in [args.output, args.csv_output, args.cache]:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    # Load bindings
    print(f"Loading bindings from: {args.input}")
    bindings = load_bindings(args.input)
    print(f"Loaded {len(bindings)} binding records")
    if not args.diagnostic_unvalidated_input:
        input_errors = validate_strict_binding_input(args.input, bindings)
        if input_errors:
            raise RuntimeError(
                "Strict OCSR input gate failed: " + "; ".join(input_errors[:12])
            )

    # Filter out Intermediate (中间体), keep only Example (实施例)
    if not args.include_intermediates:
        bindings = filter_examples_only(bindings)

    # One model process and one QC authority cover the complete proved catalog.
    # Formal QA keeps its ordered association view; no-activity rows are not
    # silently omitted or falsely labelled as formally accepted measurements.
    supplemental = []
    binding_payload = {}
    if not args.diagnostic_unvalidated_input:
        with open(args.input, "r", encoding="utf-8") as source:
            binding_payload = json.load(source)
        _, supplemental = recognition_inputs(binding_payload)
        if not args.include_intermediates:
            supplemental = filter_examples_only(supplemental)
    if args.continue_on_scientific_errors:
        validate_source_observation_mode(
            binding_payload,
            bindings,
            diagnostic=args.diagnostic_unvalidated_input,
            limit=args.limit,
            include_unbound=args.include_unbound,
        )
    formal_count = len(bindings)
    all_inputs = [*bindings, *supplemental]

    # Resolve image paths
    base_dir = os.path.dirname(os.path.abspath(args.input))
    all_inputs = resolve_image_paths(all_inputs, base_dir)
    bindings = all_inputs[:formal_count]
    supplemental = all_inputs[formal_count:]

    # Check how many images are accessible
    images_found = sum(
        1
        for b in all_inputs
        if os.path.isfile(
            b.get("ocsr_image_path")
            or b.get("source_image_path")
            or b.get("image_path", "")
        )
    )
    print(f"Images accessible: {images_found}/{len(all_inputs)}")

    # Preprocessing directory
    preprocess_dir = os.path.join(os.path.dirname(args.output), "preprocessed")

    # Build DECIMER engine config from environment
    engine_configs = {}
    for name in set(primary_engines + fallback_engines):
        config = {}
        if name == "decimer":
            if os.environ.get("DECIMER_PYTHON"):
                config["python_bin"] = os.environ["DECIMER_PYTHON"]
            if os.environ.get("DECIMER_BATCH_WRAPPER"):
                config["batch_wrapper_script"] = os.environ["DECIMER_BATCH_WRAPPER"]
        if config:
            engine_configs[name] = config

    # Initialize converter
    print(f"\nEngines: primary={primary_engines}, fallback={fallback_engines}")
    print(f"Preprocess: {preprocess}, Timeout: {args.timeout}s")

    converter = SmilesConverter(
        engines=primary_engines,
        fallback_engines=fallback_engines,
        cache_path=args.cache,
        preprocess=preprocess,
        timeout=args.timeout,
        preprocess_long_edge=args.preprocess_long_edge,
        preprocess_padding=args.preprocess_padding,
        engine_configs=engine_configs,
        retry_normalization=args.retry_normalization,
    )

    # Check engine availability
    print("\nEngine availability:")
    for name in set(primary_engines + fallback_engines):
        engine = converter.engines.get(name)
        if engine:
            avail = engine.is_available()
            print(f"  {name}: {'✓ available' if avail else '✗ unavailable'}")
        else:
            print(f"  {name}: ✗ not registered")

    # Run conversion
    print("\nProcessing...")
    start_time = time.time()

    results = converter.convert_batch(
        all_inputs,
        preprocess_dir=preprocess_dir,
        only_bound=only_bound,
        limit=args.limit,
        jobs=args.jobs,
        progress_path=str(Path(args.output).parent / "progress.json"),
    )

    elapsed = time.time() - start_time
    formal_results = results[:formal_count]
    source_results = results[formal_count:]
    if args.continue_on_scientific_errors:
        require_complete_source_results(bindings, formal_results)
    if not args.diagnostic_unvalidated_input and not ordered_source_results(
        supplemental, source_results
    ):
        raise RuntimeError(
            "Source recognition output does not match the proved catalog in order."
        )

    # Save one versioned JSON artifact; bare lists are intentionally rejected
    # by downstream formal gates.
    execution_mode = (
        DIAGNOSTIC_SMILES_MODE
        if args.diagnostic_unvalidated_input
        else PRODUCTION_SMILES_MODE
    )
    write_json_atomic(
        args.output,
        build_smiles_artifact(
            formal_results, execution_mode=execution_mode, source_records=source_results
        ),
    )

    # Save CSV output
    try:
        import pandas as pd

        df = pd.DataFrame(results)
        # Convert engine_attempts list to JSON string for CSV
        if "engine_attempts" in df.columns:
            df["engine_attempts"] = df["engine_attempts"].apply(json.dumps)
        df.to_csv(args.csv_output, index=False)
    except (OSError, ValueError, TypeError) as e:
        print(f"Warning: CSV output failed: {e}")

    # Print summary
    print_summary(results, args.output, args.csv_output, elapsed)

    # Cache stats
    if converter.cache:
        stats = converter.cache.get_stats()
        print(
            f"\nCache stats: {stats['total_entries']} entries, "
            f"{stats['valid_entries']} valid"
        )
    if not args.diagnostic_unvalidated_input:
        result_errors = validate_strict_smiles_results(bindings, formal_results)
        publish_scientific_findings(
            os.path.dirname(args.output) or ".",
            result_errors,
            continue_on_scientific_errors=args.continue_on_scientific_errors,
        )


if __name__ == "__main__":
    main()
