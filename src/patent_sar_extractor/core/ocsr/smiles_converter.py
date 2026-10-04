"""
SMILES Converter - orchestrates DECIMER OCSR execution.

Reads binding results, runs OCSR engines on structure images,
performs RDKit QC, and produces comprehensive SMILES results.
"""

import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from patent_sar_extractor.contracts import OCSR_OBSERVATION_VERSION

from .engines.base_engine import BaseOCSREngine
from .engines.decimer_engine import DECIMEREngine
from .image_preprocess import preprocess_structure_image
from .smiles_cache import SmilesCache, compute_image_sha256
from .smiles_qc import COMMON_FINAL_PRODUCT_ELEMENTS, qc_smiles
from .stereo_evidence import observe_stereo_symbols, source_checked_qc


def _resolve_ocsr_image_path(item: dict) -> str:
    """Prefer a clean OCSR input image over the display/visual crop."""
    for key in (
        "ocsr_image_path",
        "source_image_path",
        "image_path",
        "structure_image",
    ):
        path = str(item.get(key) or "").strip()
        if path and os.path.isfile(path):
            return path
    source_sid = str(item.get("source_structure_id") or "").strip()
    if source_sid:
        display_path = str(item.get("image_path") or "").strip()
        display_dir = Path(display_path).resolve().parent if display_path else None
        candidate_roots = []
        if display_dir is not None:
            candidate_roots.extend(
                [display_dir, display_dir.parent, display_dir.parent.parent]
            )
        for root in candidate_roots:
            if not root:
                continue
            candidate = (
                root / "structures" / f"structure_{int(source_sid[1:]):04d}.png"
                if re.fullmatch(r"S\d{4}", source_sid)
                else None
            )
            if candidate and candidate.is_file():
                return str(candidate)
    return str(item.get("image_path") or item.get("structure_image") or "")


def _compound_label_for_ocsr_mask(item: dict) -> str:
    """Return a short visible compound label that may contaminate OCSR crops."""
    labels = []
    for key in ("visible_label", "label"):
        value = str(item.get(key) or "").strip()
        if value:
            labels.append(value)
    for candidate in item.get("visible_label_candidates") or []:
        if isinstance(candidate, dict):
            value = str(candidate.get("label") or "").strip()
            if value:
                labels.append(value)
    for key in ("cpd", "cpd_id", "compound_id", "example_id"):
        value = str(item.get(key) or "").strip()
        match = re.search(
            r"(?:compound|cpd|example|实施例|化合物)?\s*[-:]?\s*(\d{1,4}[A-Z]?)",
            value,
            re.I,
        )
        if match:
            labels.append(match.group(1).upper())
    for label in labels:
        label = re.sub(r"\s+", "", str(label or "")).upper()
        if re.fullmatch(r"\d{1,4}[A-Z]?", label):
            return label
    return ""


def _component_overlap(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    overlap = max(0, min(ay1, by1) - max(ay0, by0))
    return overlap / max(1, min(ay1 - ay0, by1 - by0))


def _detect_visible_label_bbox(
    image_path: str, label: str
) -> tuple[int, int, int, int] | None:
    """Locate a printed compound number inside a structure crop.

    The detector is intentionally conservative: it only masks compact, isolated
    glyph clusters in the lower half of the crop and near the horizontal center.
    Chemical atom labels and bonds that are part of the molecular graph should
    remain untouched and continue through strict QC.
    """
    if not label:
        return None
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except Exception:
        return None

    try:
        image = Image.open(image_path).convert("L")
    except Exception:
        return None
    width, height = image.size
    if width < 40 or height < 28:
        return None
    arr = np.array(image)
    binary = (arr < 145).astype("uint8")
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)

    components: list[dict] = []
    for idx in range(1, count):
        x, y, w, h, area = [int(v) for v in stats[idx]]
        if area < 4 or h < 4 or w < 1:
            continue
        x1 = x + w
        y1 = y + h
        center_x, center_y = centroids[idx]
        if y < height * 0.62 or center_y < height * 0.68:
            continue
        if h > max(26, height * 0.34) or w > max(40, width * 0.22):
            continue
        if abs(center_x - width / 2) > max(48, width * 0.32):
            continue
        fill = area / max(1, w * h)
        if fill < 0.08:
            continue
        components.append(
            {
                "bbox": (x, y, x1, y1),
                "center_x": float(center_x),
                "center_y": float(center_y),
                "area": area,
            }
        )

    if not components:
        return None

    best: tuple[float, tuple[int, int, int, int]] | None = None
    max_label_width = max(18, min(width * 0.24, 10 * len(label) + 18))
    for seed in components:
        cluster = [seed]
        sx0, sy0, sx1, sy1 = seed["bbox"]
        for comp in components:
            if comp is seed:
                continue
            bx0, by0, bx1, by1 = comp["bbox"]
            if _component_overlap((sx0, sy0, sx1, sy1), (bx0, by0, bx1, by1)) < 0.35:
                continue
            gap = max(0, max(bx0 - sx1, sx0 - bx1))
            if gap > max(16, height * 0.18):
                continue
            cluster.append(comp)
            sx0, sy0 = min(sx0, bx0), min(sy0, by0)
            sx1, sy1 = max(sx1, bx1), max(sy1, by1)

        bbox = (sx0, sy0, sx1, sy1)
        bw, bh = sx1 - sx0, sy1 - sy0
        if bw < 3 or bh < 5:
            continue
        if bw > max_label_width or bh > max(24, height * 0.26):
            continue
        if bw / max(1, len(label)) > 14:
            continue
        if len(label) > 1 and len(cluster) < min(2, len(label)):
            continue
        if len(cluster) > max(6, len(label) + 3):
            continue
        center_x = (sx0 + sx1) / 2
        center_y = (sy0 + sy1) / 2
        score = center_y / height
        score += 0.35 * (
            1.0 - min(1.0, abs(center_x - width / 2) / max(1.0, width / 2))
        )
        score += 0.15 * min(1.0, len(cluster) / max(1, len(label)))
        if best is None or score > best[0]:
            best = (score, bbox)

    return best[1] if best else None


def _mask_visible_label_for_ocsr(
    image_path: str, item: dict, output_dir: str = ""
) -> tuple[str, dict]:
    """Create a cached OCSR-only image with the visible compound number removed."""
    label = _compound_label_for_ocsr_mask(item)
    bbox = _detect_visible_label_bbox(image_path, label)
    if not bbox:
        return image_path, {}
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return image_path, {}

    try:
        image = Image.open(image_path).convert("RGB")
    except Exception:
        return image_path, {}
    width, height = image.size
    x0, y0, x1, y1 = bbox
    pad_x = max(3, int(width * 0.01))
    pad_y = max(3, int(height * 0.025))
    x0 = max(0, x0 - pad_x)
    y0 = max(0, y0 - pad_y)
    x1 = min(width, x1 + pad_x)
    y1 = min(height, y1 + pad_y)
    if x1 <= x0 or y1 <= y0:
        return image_path, {}

    source_hash = compute_image_sha256(image_path)[:16]
    safe_label = re.sub(r"[^A-Z0-9_-]+", "_", label or "label")
    if output_dir:
        clean_dir = Path(output_dir) / "ocsr_label_masked"
    else:
        clean_dir = Path(image_path).resolve().parent / ".ocsr_label_masked"
    clean_dir.mkdir(parents=True, exist_ok=True)
    name_key = hashlib.sha1(
        f"{image_path}|{source_hash}|{safe_label}|{x0},{y0},{x1},{y1}".encode("utf-8")
    ).hexdigest()[:12]
    output_path = clean_dir / f"{Path(image_path).stem}_{safe_label}_{name_key}.png"

    draw = ImageDraw.Draw(image)
    draw.rectangle((x0, y0, x1, y1), fill="white")
    image.save(output_path)
    return str(output_path), {
        "ocsr_label_masked": True,
        "ocsr_label_mask_source": image_path,
        "ocsr_label_mask_label": label,
        "ocsr_label_mask_bbox": [x0, y0, x1, y1],
    }


def _qc_ocr_smiles(raw_smiles: Optional[str]) -> tuple[Optional[str], dict, bool]:
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


def _largest_fragment_mol(smiles: Optional[str]):
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
    review_smiles: Optional[str], fallback_smiles: Optional[str]
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
    except Exception:
        pass
    core_heavy = max(1, core.GetNumHeavyAtoms())
    fallback_heavy = fallback_mol.GetNumHeavyAtoms()
    # A single wildcard is usually an unlabeled atom or a compact substituent.
    # Do not let a fallback replace it with a larger functional group while still
    # sharing the same scaffold as the query candidate.
    if abs(fallback_heavy - core_heavy) > max(len(review_indices) + 1, 2):
        return False
    try:
        return fallback_mol.HasSubstructMatch(core)
    except Exception:
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
    2. Optionally preprocess the image
    3. Compute image hash for caching
    4. Try configured engine list
    5. Apply RDKit QC to each raw SMILES
    6. Stop at first rdkit_valid=True result
    7. Record all engine attempts
    """

    def __init__(
        self,
        engines: List[str],
        fallback_engines: List[str],
        cache_path: str = "",
        preprocess: bool = True,
        timeout: int = 60,
        preprocess_long_edge: int = 1024,
        preprocess_padding: int = 20,
        engine_configs: Optional[dict] = None,
        retry_normalization: bool = False,
    ):
        """Initialize SmilesConverter.

        Args:
            engines: List of primary engine names (tried in order).
            fallback_engines: List of fallback engine names.
            cache_path: Path to SQLite cache file. Empty string disables caching.
            preprocess: Whether to preprocess images before OCSR.
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
        cpd_id = item.get("cpd", "")
        image_path = item.get("image_path", "")
        ocsr_image_path = _resolve_ocsr_image_path(item)
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
            image_hash = compute_image_sha256(ocsr_image_path)
            result["image_hash"] = image_hash
        except Exception as e:
            result["OCSR_status"] = "image_missing"
            result["OCSR_failure_reason"] = f"Cannot compute image hash: {e}"
            return {"item": item, "result": result, "ready": False}

        try:
            # Always inspect the source crop, never a model-normalized retry.
            evidence = observe_stereo_symbols(ocsr_image_path)
        except (OSError, ValueError) as exc:
            result.update(OCSR_status="review_required", OCSR_quality_flag="stereo_source_unavailable",
                          OCSR_failure_reason=f"Source stereochemistry inspection failed: {exc}")
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

    def _prediction(self, engine_name: str, engine, image: str) -> tuple[dict, dict]:
        """Cache only exact unmodified observations under the current epoch."""
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
                and cached.get("model_fingerprint") == identity
                and _is_clean_rdkit_result(checked)
            ):
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
        try:
            prediction = engine.predict(image, timeout=self.timeout)
        except Exception as exc:
            prediction = {"status": "failed", "raw_smiles": None, "error": str(exc)}
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
        self, item: dict, preprocess_dir: str = "", prepared: Optional[dict] = None
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
                    and status == "success"
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

    def convert_batch(
        self,
        items: List[dict],
        preprocess_dir: str = "",
        only_bound: bool = True,
        limit: int = 0,
        jobs: int = 1,
        progress_path: str = "",
    ) -> List[dict]:
        """Bounded parallel image preparation feeding one owned model queue."""
        from .conversion_progress import ConversionProgress

        filtered = [
            item
            for item in items
            if not only_bound or item.get("bind_status", "bound") == "bound"
        ]
        if limit > 0:
            filtered = filtered[:limit]
        jobs = max(1, min(int(jobs or 1), 8))
        progress = ConversionProgress(progress_path, len(filtered))
        results = []
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
                        progress.record(result)
                        print(
                            f"  [{len(results)}/{len(filtered)}] {result.get('cpd_id')}: "
                            f"{result.get('OCSR_status')} engine={result.get('OCSR_engine')} "
                            f"(total {time.monotonic() - started:.0f}s)",
                            flush=True,
                        )
            return results
        finally:
            self.close()
