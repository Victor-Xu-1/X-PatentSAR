"""
SMILES Converter - orchestrates DECIMER OCSR execution.

Reads binding results, runs OCSR engines on structure images,
performs RDKit QC, and produces comprehensive SMILES results.
"""

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from patent_sar_extractor.contracts import (
    OCSR_OBSERVATION_VERSION,
    OCSR_PREPARATION_VERSION,
)

from .candidate_inventory import validate_candidate_input
from .engines.base_engine import BaseOCSREngine
from .engines.decimer_engine import DECIMEREngine
from .generation import truncated_observation
from .image_preprocess import preprocess_structure_image
from .label_mask import mask_visible_label as _mask_visible_label_for_ocsr
from .recognition_source_paths import resolve_ocsr_image_path
from .smiles_cache import SmilesCache, compute_image_sha256
from .smiles_qc import COMMON_FINAL_PRODUCT_ELEMENTS, qc_smiles
from .stereo_evidence import observe_stereo_symbols, source_checked_qc

DEFAULT_EXTRA_PREPROCESS = False


def _qc_ocr_smiles(raw_smiles: str | None) -> tuple[str | None, dict, bool]:
    """Observe the exact engine string; syntactic/chemical edits are forbidden."""
    return raw_smiles, qc_smiles(raw_smiles), False


def _is_clean_rdkit_result(qc_result: dict) -> bool:
    return (
        bool(qc_result.get("rdkit_valid"))
        and qc_result.get("quality_flag") == "ok"
        and not qc_result.get("suspicious_elements")
        and not qc_result.get("has_dummy_atom")
        and not qc_result.get("has_query_atom")
    )


def _largest_fragment_mol(smiles: str | None):
    """Return the largest RDKit fragment, ignoring detached salts/noise."""
    if not smiles:
        return None
    try:
        from rdkit import Chem
    except ImportError:
        return None
    mol = Chem.MolFromSmiles(str(smiles))
    if mol is None:
        return None
    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
    return max(frags or [mol], key=lambda frag: frag.GetNumHeavyAtoms())


def _review_fallback_is_graph_compatible(
    review_smiles: str | None, fallback_smiles: str | None
) -> bool:
    """Guard against a clean fallback replacing the wrong review candidate.

    OCR sometimes emits a wildcard or a syntactically valid but improbable atom
    such as ``[Cf]`` for ``Cl``. A fallback may remove that symptom by reading a
    different product altogether. Accept it automatically only when the stable
    product core still matches after uncertain atoms are removed.
    """
    query_mol = _largest_fragment_mol(review_smiles)
    fallback_mol = _largest_fragment_mol(fallback_smiles)
    if query_mol is None or fallback_mol is None:
        return False
    try:
        from rdkit import Chem
    except ImportError:
        return False
    editable = Chem.RWMol(query_mol)
    review_indices = [
        atom.GetIdx()
        for atom in editable.GetAtoms()
        if atom.GetAtomicNum() == 0
        or atom.GetSymbol() not in COMMON_FINAL_PRODUCT_ELEMENTS
    ]
    if not review_indices:
        return True
    for idx in sorted(review_indices, reverse=True):
        editable.RemoveAtom(idx)
    core = editable.GetMol()
    try:
        Chem.SanitizeMol(core)
    except (ValueError, RuntimeError):
        return False
    core_heavy = max(1, core.GetNumHeavyAtoms())
    fallback_heavy = fallback_mol.GetNumHeavyAtoms()
    # A single wildcard is usually an unlabeled atom or a compact substituent.
    # Do not let a fallback replace it with a larger functional group while still
    # sharing the same scaffold as the query candidate.
    if abs(fallback_heavy - core_heavy) > max(len(review_indices) + 1, 2):
        return False
    try:
        return fallback_mol.HasSubstructMatch(core)
    except (ValueError, RuntimeError):
        return False


# Engine registry: production OCSR is DECIMER-only.
ENGINE_MAP = {
    "decimer": DECIMEREngine,
}


def _infer_patent_id(item: dict) -> str:
    for key in ("patent_id", "patent", "patent_number"):
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    for key in ("image_path", "structure_image"):
        value = str(item.get(key, "") or "")
        match = re.search(r"(WO\d{6,})", value, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


class SmilesConverter:
    """Orchestrates DECIMER OCSR execution with QC.

    Workflow for each bound structure:
    1. Check if structure is bound and image exists
    2. Preserve the source pixels by default; the verified SDK prepares its input
    3. Compute image hash for caching
    4. Try configured engine list
    5. Apply RDKit QC to each raw SMILES
    6. Require clean molecular and source-symbol QC (not proof of exact chemistry)
    7. Record all engine attempts
    """

    def __init__(
        self,
        engines: list[str],
        fallback_engines: list[str],
        cache_path: str = "",
        preprocess: bool = DEFAULT_EXTRA_PREPROCESS,
        timeout: int = 60,
        preprocess_long_edge: int = 1024,
        preprocess_padding: int = 20,
        engine_configs: dict | None = None,
        retry_normalization: bool = False,
    ):
        """Initialize SmilesConverter.

        Args:
            engines: List of primary engine names (tried in order).
            fallback_engines: List of fallback engine names.
            cache_path: Path to SQLite cache file. Empty string disables caching.
            preprocess: Explicit extra lossy normalization before SDK preprocessing.
                        Disabled by default, as in the formal coordinator.
            timeout: Timeout in seconds per prediction per engine (default: 60).
            preprocess_long_edge: Target long edge for preprocessing.
            preprocess_padding: Padding for preprocessing.
            engine_configs: Optional dict of engine-specific config overrides.
                          e.g. {"decimer": {"python_bin": "/path/to/python"}}
        """
        self.engine_names = engines
        self.fallback_engine_names = fallback_engines
        self.all_engine_names = engines + fallback_engines
        self.preprocess = preprocess
        self.timeout = timeout
        self.preprocess_long_edge = preprocess_long_edge
        self.preprocess_padding = preprocess_padding
        self.engine_configs = engine_configs or {}
        self.retry_normalization = retry_normalization

        # Initialize cache
        self.cache = None
        if cache_path:
            self.cache = SmilesCache(cache_path)

        # Initialize engine instances
        self.engines: dict[str, BaseOCSREngine] = {}
        for name in set(self.all_engine_names):
            if name in ENGINE_MAP:
                config = self.engine_configs.get(name, {})
                self.engines[name] = ENGINE_MAP[name](**config)

    def _prepare_input(self, item: dict, preprocess_dir: str = "") -> dict:
        candidate = validate_candidate_input(item)
        cpd_id = item.get("cpd", "")
        image_path = item.get("image_path", "")
        ocsr_image_path = resolve_ocsr_image_path(item)
        original_input = ocsr_image_path or (item["image_path"] if candidate else "")
        ocsr_label_mask_info: dict = {}
        if ocsr_image_path and os.path.isfile(ocsr_image_path):
            ocsr_image_path, ocsr_label_mask_info = _mask_visible_label_for_ocsr(
                ocsr_image_path,
                item,
                preprocess_dir,
            )
        page_no = item.get("page_no", 0)
        structure_id = item.get("structure_id", "")
        struct_x0 = item.get("struct_x0")
        struct_y0 = item.get("struct_y0")
        patent_id = _infer_patent_id(item)

        result = {
            "patent_id": patent_id,
            "page_no": page_no,
            "cpd_id": cpd_id,
            "structure_id": structure_id,
            "structure_image": image_path,
            "ocsr_structure_image": ocsr_image_path,
            "ocsr_original_input": original_input,
            "OCSR_preparation_version": OCSR_PREPARATION_VERSION,
            "ocsr_source_structure_id": item.get("source_structure_id") or structure_id,
            "source_image_path": str(item.get("source_image_path") or image_path),
            "bbox": f"{struct_x0},{struct_y0}" if struct_x0 is not None else "",
            "raw_smiles": None,
            "canonical_smiles": None,
            "inchikey": None,
            "mol_formula": None,
            "mol_weight": None,
            "heavy_atom_count": 0,
            "ring_count": 0,
            "chiral_centers": 0,
            "rdkit_valid": False,
            "OCSR_engine": None,
            "OCSR_status": "not_processed",
            "OCSR_quality_flag": "empty_prediction",
            "OCSR_failure_reason": None,
            "engine_attempts": [],
            "image_hash": None,
        }
        result.update(ocsr_label_mask_info)
        if candidate:
            result["candidate_source_id"] = item["candidate_source_id"]
        if item.get("_ocsr_source_frame_unavailable"):
            result["OCSR_source_frame_status"] = "unavailable"

        if not ocsr_image_path or not os.path.isfile(ocsr_image_path):
            result["OCSR_status"] = "image_missing"
            result["OCSR_failure_reason"] = (
                f"Image file not found: {ocsr_image_path}"
                if ocsr_image_path
                else "No image_path"
            )
            return {"item": item, "result": result, "ready": False}

        working_image = ocsr_image_path
        if self.preprocess and preprocess_dir:
            try:
                working_image = preprocess_structure_image(
                    ocsr_image_path,
                    preprocess_dir,
                    padding=self.preprocess_padding,
                    long_edge=self.preprocess_long_edge,
                )
            except (OSError, ValueError) as exc:
                result["OCSR_status"] = "preprocessing_failed"
                result["OCSR_failure_reason"] = str(exc)
                return {"item": item, "result": result, "ready": False}

        try:
            image_hash = compute_image_sha256(original_input)
            result["image_hash"] = image_hash
        except (OSError, ValueError) as e:
            result["OCSR_status"] = "image_missing"
            result["OCSR_failure_reason"] = f"Cannot compute image hash: {e}"
            return {"item": item, "result": result, "ready": False}

        if candidate and image_hash != item["candidate_source"]["image_sha256"]:
            raise ValueError("Detected-image source changed before model execution")

        try:
            # Always inspect the source crop, never a model-normalized retry.
            evidence = observe_stereo_symbols(original_input)
        except (OSError, ValueError) as exc:
            result.update(
                OCSR_status="review_required",
                OCSR_quality_flag="stereo_source_unavailable",
                OCSR_failure_reason=f"Source stereochemistry inspection failed: {exc}",
            )
            return {"item": item, "result": result, "ready": False}

        return {
            "item": item,
            "result": result,
            "ready": True,
            "image_hash": image_hash,
            "working_image": working_image,
            "ocsr_image_path": ocsr_image_path,
            "stereo_evidence": evidence,
        }

    def _prediction(
        self, engine_name: str, engine, image: str, *, timeout=None
    ) -> tuple[dict, dict]:
        """Cache only exact unmodified observations under the current epoch."""
        from .generation import completed_observation

        image_hash = compute_image_sha256(image)
        notes: dict = {"input_image_sha256": image_hash}
        identity = None
        if callable(getattr(engine, "runtime_identity", None)):
            try:
                identity = engine.runtime_identity()["fingerprint"]
            except (OSError, RuntimeError, ValueError) as exc:
                return {
                    "status": "unavailable",
                    "raw_smiles": None,
                    "error": str(exc),
                }, notes
        cache_key = f"{engine_name}:raw-v{OCSR_OBSERVATION_VERSION}:{identity}"
        if identity is None:
            notes["cache_disabled_unversioned_runtime"] = True
        cached = (
            self.cache.get_cached_result(image_hash, cache_key)
            if self.cache and identity
            else None
        )
        if cached is not None:
            checked = qc_smiles(cached.get("raw_smiles"))
            if (
                cached.get("status") == "success"
                and (engine_name != "decimer" or completed_observation(cached))
                and cached.get("model_fingerprint") == identity
                and (
                    _is_clean_rdkit_result(checked)
                    or engine_name == "decimer"
                    and checked.get("rdkit_valid") is True
                    and checked.get("quality_flag") == "stereochemistry_not_retained"
                )
            ):
                # Reuse only the exact raw lost-stereo observation, never its
                # acceptance. Current source/QC and independent rescue proof
                # decide each attempt; other non-clean entries still re-infer.
                notes["from_cache"] = True
                return cached, notes
            notes[
                "ignored_cached_empty"
                if not cached.get("raw_smiles")
                else "ignored_cached_non_clean"
            ] = True
        elif self.cache:
            legacy = self.cache.get_cached_result(image_hash, engine_name)
            if legacy is not None:
                notes["ignored_cached_precontract"] = True
                notes[
                    "ignored_cached_empty"
                    if not legacy.get("raw_smiles")
                    else "ignored_cached_non_clean"
                ] = True
        # Infrastructure/admission exceptions stop the batch and preserve its
        # clean checkpoints; never turn them into hundreds of false graph failures.
        prediction = engine.predict(
            image, timeout=self.timeout if timeout is None else timeout
        )
        if not isinstance(prediction, dict):
            prediction = {
                "status": "failed",
                "raw_smiles": None,
                "error": "Invalid engine response",
            }
        raw = prediction.get("raw_smiles")
        if raw is not None and not isinstance(raw, str):
            prediction = {
                **prediction,
                "status": "failed",
                "raw_smiles": None,
                "error": "Invalid SMILES response type",
            }
        if engine_name == "decimer" and not completed_observation(prediction):
            prediction = {
                **prediction,
                "status": "failed",
                "error": prediction.get("error")
                or "DECIMER generated-token completion is unproved",
            }
        if self.cache and identity:
            checked = qc_smiles(prediction.get("raw_smiles"))
            self.cache.save_result(
                image_hash,
                cache_key,
                {
                    **prediction,
                    **checked,
                    "model_version": prediction.get("model_version"),
                },
            )
        return prediction, notes

    def convert_one(
        self, item: dict, preprocess_dir: str = "", prepared: dict | None = None
    ) -> dict:
        """One evidence-preserving path: image -> raw prediction -> RDKit QC.

        A single bounded normalization retry changes image presentation, never
        atoms, bonds, ring digits, suffixes or stereochemistry in a prediction.
        """
        prepared = prepared or self._prepare_input(item, preprocess_dir=preprocess_dir)
        result = dict(prepared.get("result", {}))
        if not prepared.get("ready"):
            return result
        attempts = []
        for engine_name in self.all_engine_names:
            engine = self.engines.get(engine_name)
            if engine is None:
                attempts.append(
                    {
                        "engine": engine_name,
                        "status": "unavailable",
                        "quality_flag": "empty_prediction",
                        "error": "Engine is not registered",
                    }
                )
                continue
            images = [(prepared["working_image"], "segmented_image")]
            for attempt_index in range(2):
                if attempt_index >= len(images):
                    break
                image, source = images[attempt_index]
                prediction, notes = self._prediction(engine_name, engine, image)
                raw, checked, _unused = _qc_ocr_smiles(prediction.get("raw_smiles"))
                checked = source_checked_qc(checked, prepared["stereo_evidence"])
                attempt = {
                    "engine": engine_name,
                    "status": prediction.get("status", "failed"),
                    "raw_smiles": raw,
                    "quality_flag": checked["quality_flag"],
                    "stereochemistry": checked["stereochemistry"],
                    "error": prediction.get("error"),
                    "elapsed_sec": prediction.get("elapsed_sec", 0),
                    "model_fingerprint": prediction.get("model_fingerprint"),
                    "token_confidence": prediction.get("token_confidence"),
                    "generation": prediction.get("generation"),
                    "device": prediction.get("device"),
                    "peak_rss_mb": prediction.get("peak_rss_mb"),
                    "device_used": prediction.get("device_used"),
                    "device_warning": prediction.get("device_warning"),
                    "input_source": source,
                    "input_image": image,
                    **notes,
                }
                if checked.get("suspicious_elements"):
                    attempt["suspicious_elements"] = checked["suspicious_elements"]
                attempts.append(attempt)
                clean = prediction.get(
                    "status"
                ) == "success" and _is_clean_rdkit_result(checked)
                if (
                    clean
                    and result.get("OCSR_quality_flag")
                    in {"markush_or_query", "suspicious_element"}
                    and not _review_fallback_is_graph_compatible(
                        result.get("raw_smiles"), raw
                    )
                ):
                    attempt["rejected_review_fallback"] = (
                        "product core differs from review candidate"
                    )
                    continue
                if raw:
                    for key in (
                        "canonical_smiles",
                        "inchikey",
                        "mol_formula",
                        "mol_weight",
                        "heavy_atom_count",
                        "ring_count",
                        "chiral_centers",
                        "rdkit_valid",
                    ):
                        result[key] = checked[key]
                    result.update(
                        raw_smiles=raw,
                        engine_raw_smiles=raw,
                        OCSR_engine=engine_name,
                        OCSR_quality_flag=checked["quality_flag"],
                        stereochemistry=checked["stereochemistry"],
                        ocsr_structure_image=image,
                        model_fingerprint=prediction.get("model_fingerprint"),
                        token_confidence=prediction.get("token_confidence"),
                        generation=prediction.get("generation"),
                        device=prediction.get("device"),
                        peak_rss_mb=prediction.get("peak_rss_mb"),
                    )
                    if checked.get("suspicious_elements"):
                        result["suspicious_elements"] = checked["suspicious_elements"]
                    else:
                        result.pop("suspicious_elements", None)
                if clean:
                    result.update(
                        OCSR_status="success",
                        OCSR_failure_reason=None,
                        engine_attempts=attempts,
                    )
                    return result
                status = prediction.get("status")
                if status == "success" and raw:
                    result["OCSR_status"] = (
                        "review_required"
                        if checked["rdkit_valid"]
                        else "invalid_smiles"
                    )
                    result["OCSR_failure_reason"] = (
                        f"Raw prediction requires review: {checked['quality_flag']}"
                    )
                elif status == "timeout":
                    result["OCSR_status"] = "engine_timeout"
                    result["OCSR_failure_reason"] = (
                        f"Engine timed out after {self.timeout}s"
                    )
                else:
                    result["OCSR_status"] = (
                        "engine_unavailable"
                        if status == "unavailable"
                        else "all_engines_failed"
                    )
                    result["OCSR_failure_reason"] = (
                        prediction.get("error") or "Engine failed"
                    )
                if (
                    self.retry_normalization
                    and attempt_index == 0
                    and (
                        status == "success"
                        or engine_name == "decimer"
                        and truncated_observation(prediction)
                    )
                    and raw
                    and not str(checked["quality_flag"]).startswith("stereo_source_")
                    and preprocess_dir
                    and len(self.all_engine_names) == 1
                ):
                    from .retry_inputs import normalized_retry_image

                    try:
                        alternate = normalized_retry_image(
                            prepared["ocsr_image_path"], preprocess_dir
                        )
                        if alternate is not None:
                            images.append((alternate, "normalized_image"))
                    except (OSError, ValueError) as exc:
                        attempts.append(
                            {
                                "engine": engine_name,
                                "status": "preprocessing_failed",
                                "quality_flag": "retry_input_unavailable",
                                "error": str(exc),
                            }
                        )
        result["engine_attempts"] = attempts
        return result

    def close(self) -> None:
        for engine in self.engines.values():
            closer = getattr(engine, "close", None)
            if callable(closer):
                closer()

    def finalize_batch(
        self,
        results: list[dict],
        *,
        source_paths=None,
        progress=None,
        check_cancel=None,
    ) -> list[dict]:
        """Shared post-primary boundary for formal and source-completion work."""
        from .conversion_progress import ConversionProgress
        from .stereo_rescue_pass import apply_stereo_rescue

        self.close()
        if progress is None:
            progress = ConversionProgress("", len(results))
            for result in results:
                progress.record(result)
        return apply_stereo_rescue(
            results,
            source_paths
            if source_paths is not None
            else [r.get("ocsr_original_input", "") for r in results],
            lambda name, engine, image: self._prediction(
                name, engine, image, timeout=min(self.timeout, 60)
            ),
            engine_configs=self.engine_configs,
            progress=progress,
            check_cancel=check_cancel,
        )

    def convert_batch(
        self,
        items: list[dict],
        preprocess_dir: str = "",
        only_bound: bool = True,
        limit: int = 0,
        jobs: int = 1,
        progress_path: str = "",
    ) -> list[dict]:
        """Bounded parallel image preparation feeding one owned model queue."""
        from .conversion_progress import ConversionProgress

        filtered = []
        for item in items:
            candidate = validate_candidate_input(item)
            if (
                candidate
                or not only_bound
                or item.get("bind_status", "bound") == "bound"
            ):
                filtered.append(item)
        if limit > 0:
            filtered = filtered[:limit]
        jobs = max(1, min(int(jobs or 1), 8))
        progress = ConversionProgress(progress_path, len(filtered))
        results = []
        source_paths = []
        started = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=jobs) as executor:
                # Only one small window is prepared ahead; inference is never duplicated.
                for offset in range(0, len(filtered), jobs):
                    window = filtered[offset : offset + jobs]
                    prepared = executor.map(
                        lambda item: self._prepare_input(item, preprocess_dir), window
                    )
                    for item, observation in zip(window, prepared):
                        result = self.convert_one(
                            item, preprocess_dir, prepared=observation
                        )
                        results.append(result)
                        source_paths.append(observation.get("ocsr_image_path", ""))
                        progress.record(result)
                        if result.get("OCSR_status") in {
                            "all_engines_failed",
                            "engine_timeout",
                            "engine_unavailable",
                        } and any(
                            getattr(engine, "session_exhausted", False)
                            for engine in self.engines.values()
                        ):
                            raise RuntimeError(
                                "OCSR infrastructure is unavailable; clean observation checkpoints retained for resume"
                            )
                        print(
                            f"  [{len(results)}/{len(filtered)}] {result.get('cpd_id') or result.get('structure_id')}: "
                            f"{result.get('OCSR_status')} engine={result.get('OCSR_engine')} "
                            f"(total {time.monotonic() - started:.0f}s)",
                            flush=True,
                        )
            # No competing resident model: primary children are reaped before
            # the bounded optional local rescue queue can load its native SDK.
            return self.finalize_batch(
                results, source_paths=source_paths, progress=progress
            )
        finally:
            self.close()
