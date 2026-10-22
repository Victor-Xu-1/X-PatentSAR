"""
PatentSAR SMILES engine runner.

Recognizes proved numbered products, retaining unassigned source inventory only,
using DECIMER as the only accepted production OCSR engine.

Default strict chain: DECIMER only, no fallback.  This avoids accepting
conflicting OCSR results from mixed engines and keeps production output
deterministic.

Usage:
    python -m patent_sar_extractor.core.ocsr.run_smiles \
        --input outputs/example/structure_bindings/bindings.json \
        --structures outputs/example/structures/metadata.json \
        --source-pdf inputs/example.pdf \
        --output outputs/example/smiles_results.json \
        --csv-output outputs/example/smiles_results.csv \
        --engine decimer \
        --fallback "" \
        --cache outputs/cache/smiles_cache.sqlite \
        --no-preprocess \
        --timeout 300
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

from patent_sar_extractor.artifact_catalog import read_artifact_json
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    artifact_identity_matches,
)
from patent_sar_extractor.core.binding_records import binding_records
from patent_sar_extractor.core.ocsr.candidate_inputs import load_source_observation_plan
from patent_sar_extractor.core.ocsr.candidate_observations import (
    validate_candidate_observations,
)
from patent_sar_extractor.core.ocsr.observation_completion import (
    publish_scientific_findings,
    require_complete_source_results,
    validate_source_observation_mode,
)
from patent_sar_extractor.core.ocsr.recognition_inputs import (
    ordered_source_results,
    recognition_inputs,
)
from patent_sar_extractor.core.ocsr.recognition_policy import (
    recognition_acceptance_errors,
    validate_strict_smiles_results,
)
from patent_sar_extractor.core.ocsr.recognition_selection import deferred_source_records
from patent_sar_extractor.core.ocsr.recognition_source_paths import resolve_image_paths
from patent_sar_extractor.core.ocsr.smiles_converter import (
    DEFAULT_EXTRA_PREPROCESS,
    SmilesConverter,
)
from patent_sar_extractor.core.pipeline_rules import (
    _label_key,
    annotate_binding_accuracy,
)
from patent_sar_extractor.smiles_artifact import (
    DIAGNOSTIC_SMILES_MODE,
    PRODUCTION_SMILES_MODE,
    build_smiles_artifact,
)

__all__ = ["resolve_image_paths", "validate_strict_smiles_results"]


def load_bindings(input_path: str) -> list:
    """Load binding results from JSON.

    Handles two formats:
    1. Current artifact with the single ``compound_catalog`` record collection
    2. List of binding dicts directly

    Also supports explicit diagnostic CSV and historical JSON input.
    """
    if input_path.endswith(".csv"):
        import pandas as pd

        df = pd.read_csv(input_path)
        return df.to_dict("records")

    with open(input_path, "r") as f:
        data = read_artifact_json(f)

    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        if "compound_catalog" in data:
            return binding_records(data, legacy=True)
        # Look for common keys
        for key in ("final_bindings", "bindings", "results", "structures"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Maybe the dict itself is a single binding
        if "cpd" in data or "image_path" in data:
            return [data]

    raise ValueError(f"Cannot parse binding results from: {input_path}")


def validate_strict_binding_input(
    input_path: str, bindings: list, *, allow_empty_catalog: bool = False
) -> list[str]:
    """Reject direct OCSR use on stale, unconfirmed, or duplicated final bindings."""
    if input_path.lower().endswith(".csv"):
        return ["Strict OCSR requires current-version bindings JSON, not CSV input."]
    try:
        with open(input_path, "r", encoding="utf-8") as source:
            payload = read_artifact_json(source)
    except (OSError, ValueError) as exc:
        return [f"Strict OCSR could not read binding payload: {exc}"]
    if not artifact_identity_matches(payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION):
        return ["Binding input does not match the current bindings schema and ruleset."]
    if payload.get("execution_mode") != "production_structure_led":
        return [
            "Binding input was not produced by the production structure-led pipeline."
        ]
    try:
        final_bindings = binding_records(payload)
    except ValueError as exc:
        return [str(exc)]
    if (
        not isinstance(final_bindings, list)
        or final_bindings != bindings
        or not final_bindings
        and not allow_empty_catalog
    ):
        return [
            "Strict OCSR processes only the complete source catalogue without substitution."
        ]
    errors = []
    seen_structures = set()
    for binding in final_bindings:
        checked = (
            annotate_binding_accuracy(dict(binding))
            if isinstance(binding, dict)
            else {}
        )
        cpd = _label_key(checked.get("cpd", "")) or "unknown compound"
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
        "--structures", default="", help="Current complete structure metadata JSON"
    )
    parser.add_argument(
        "--source-pdf", default="", help="The original PDF for source-input identity"
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
    preparation = parser.add_mutually_exclusive_group()
    preparation.add_argument(
        "--preprocess",
        action="store_true",
        default=DEFAULT_EXTRA_PREPROCESS,
        help="Opt in to extra lossy normalization before the SDK's own preprocessing",
    )
    preparation.add_argument(
        "--no-preprocess",
        dest="preprocess",
        action="store_false",
        help="Preserve source pixels before SDK preprocessing (default)",
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
    if not args.diagnostic_unvalidated_input and (
        not args.structures or not args.source_pdf
    ):
        raise ValueError(
            "Production source observations require the complete structures input and original PDF"
        )
    if bool(args.structures) != bool(args.source_pdf):
        raise ValueError("Structures and original PDF must be supplied together")

    # Parse engine lists
    primary_engines = [e.strip() for e in args.engine.split(",") if e.strip()]
    fallback_engines = [e.strip() for e in args.fallback.split(",") if e.strip()]
    if primary_engines != ["decimer"] or fallback_engines:
        requested = primary_engines + fallback_engines
        raise RuntimeError(
            "Strict production OCSR is DECIMER-only; remove non-DECIMER engines "
            f"and fallback entries. requested={requested}"
        )

    # One policy/flag value: the default preserves the same input as the
    # coordinator, with the SDK owning its required image transforms.
    preprocess = args.preprocess

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
    # One model process and one QC authority cover the complete proved catalog.
    # Formal QA keeps its ordered association view; no-activity rows are not
    # silently omitted or falsely labelled as formally accepted measurements.
    supplemental = []
    reprints = []
    candidates = []
    candidate_plan = None
    binding_payload = {}
    if not args.diagnostic_unvalidated_input:
        with open(args.input, "r", encoding="utf-8") as source:
            binding_payload = read_artifact_json(source)
        plan = recognition_inputs(binding_payload)
        candidate_plan = load_source_observation_plan(
            plan,
            structures_json=args.structures,
            pdf_path=args.source_pdf,
            binding_dir=Path(args.input).resolve().parent,
            binding_pdf_sha256=(
                binding_payload.get("source_reference_scope") or {}
            ).get("original_pdf_sha256", ""),
        )
        plan = candidate_plan.proven
        supplemental, reprints, candidates = (
            plan.supplemental,
            plan.reprints,
            candidate_plan.candidates,
        )
        input_errors = validate_strict_binding_input(
            args.input,
            bindings,
            allow_empty_catalog=args.continue_on_scientific_errors and bool(candidates),
        )
        if input_errors:
            raise RuntimeError(
                "Strict OCSR input gate failed: " + "; ".join(input_errors[:12])
            )
    if args.continue_on_scientific_errors:
        validate_source_observation_mode(
            binding_payload,
            bindings,
            diagnostic=args.diagnostic_unvalidated_input,
            limit=args.limit,
            include_unbound=False,
            candidate_plan=candidate_plan,
        )
    formal_count = len(bindings)
    primary_count = formal_count + len(supplemental)
    reprint_count = primary_count + len(reprints)
    all_inputs = [*bindings, *supplemental, *reprints]

    # Resolve image paths
    base_dir = os.path.dirname(os.path.abspath(args.input))
    all_inputs = resolve_image_paths(all_inputs, base_dir)
    bindings = all_inputs[:formal_count]
    supplemental = all_inputs[formal_count:primary_count]
    reprints = all_inputs[primary_count:reprint_count]

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

    start_time = time.time()
    converter = None
    if all_inputs:
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
        print("\nEngine availability:")
        for name in set(primary_engines + fallback_engines):
            engine = converter.engines.get(name)
            if engine:
                avail = engine.is_available()
                print(f"  {name}: {'✓ available' if avail else '✗ unavailable'}")
            else:
                print(f"  {name}: ✗ not registered")
        print("\nProcessing numbered products...")
        results = converter.convert_batch(
            all_inputs,
            preprocess_dir=preprocess_dir,
            limit=args.limit,
            jobs=args.jobs,
            progress_path=str(Path(args.output).parent / "progress.json"),
        )
    else:
        results = []
        print("No proved numbered products; model inference was not started.")

    elapsed = time.time() - start_time
    formal_results = results[:formal_count]
    source_results = results[formal_count:primary_count]
    reprint_results = results[primary_count:reprint_count]
    if len(results) > reprint_count:
        raise RuntimeError("Model returned results outside the numbered product queue")
    candidate_results = (
        deferred_source_records(candidate_plan.inventory)
        if candidate_plan is not None
        else []
    )
    if args.continue_on_scientific_errors:
        require_complete_source_results(bindings, formal_results)
    if not args.diagnostic_unvalidated_input and not ordered_source_results(
        supplemental, source_results
    ):
        raise RuntimeError(
            "Source recognition output does not match the proved catalog in order."
        )
    if not args.diagnostic_unvalidated_input and not ordered_source_results(
        reprints, reprint_results
    ):
        raise RuntimeError(
            "Reprint recognition omitted or misassigned original sources."
        )

    # Save one versioned JSON artifact; bare lists are intentionally rejected
    # by downstream formal gates.
    execution_mode = (
        DIAGNOSTIC_SMILES_MODE
        if args.diagnostic_unvalidated_input
        else PRODUCTION_SMILES_MODE
    )
    artifact = build_smiles_artifact(
        formal_results,
        execution_mode=execution_mode,
        source_records=source_results,
        reprint_records=reprint_results,
        candidate_records=candidate_results,
        candidate_inventory=candidate_plan.inventory
        if candidate_plan is not None
        else None,
    )
    if candidate_plan is not None:
        validate_candidate_observations(candidate_plan, artifact)
    write_json_atomic(args.output, artifact)

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
    if converter is not None and converter.cache:
        stats = converter.cache.get_stats()
        print(
            f"\nCache stats: {stats['total_entries']} entries, "
            f"{stats['valid_entries']} valid"
        )
    if not args.diagnostic_unvalidated_input:
        result_errors = recognition_acceptance_errors(artifact, binding_payload)
        publish_scientific_findings(
            os.path.dirname(args.output) or ".",
            result_errors,
            continue_on_scientific_errors=args.continue_on_scientific_errors,
        )


if __name__ == "__main__":
    main()
