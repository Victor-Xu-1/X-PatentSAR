"""
SMILES Converter - orchestrates DECIMER OCSR execution.

Reads binding results, runs OCSR engines on structure images,
performs RDKit QC, and produces comprehensive SMILES results.
"""

import hashlib
import os
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from .engines.base_engine import BaseOCSREngine
from .engines.decimer_engine import DECIMEREngine
from .image_preprocess import preprocess_structure_image
from .smiles_cache import SmilesCache, compute_image_sha256
from .smiles_qc import COMMON_FINAL_PRODUCT_ELEMENTS, qc_smiles


_DETACHED_DUMMY_COMPONENTS = {"*", "[*]"}
_DETACHED_CARBON_NOISE_COMPONENTS = {
    "C",
    "CC",
    "[CH3+]",
    "C[CH3+]",
}


def _resolve_ocsr_image_path(item: dict) -> str:
    """Prefer a clean OCSR input image over the display/visual crop."""
    for key in ("ocsr_image_path", "source_image_path", "image_path", "structure_image"):
        path = str(item.get(key) or "").strip()
        if path and os.path.isfile(path):
            return path
    source_sid = str(item.get("source_structure_id") or "").strip()
    if source_sid:
        display_path = str(item.get("image_path") or "").strip()
        display_dir = Path(display_path).resolve().parent if display_path else None
        candidate_roots = []
        if display_dir is not None:
            candidate_roots.extend([display_dir, display_dir.parent, display_dir.parent.parent])
        for root in candidate_roots:
            if not root:
                continue
            candidate = root / "structures" / f"structure_{int(source_sid[1:]):04d}.png" if re.fullmatch(r"S\d{4}", source_sid) else None
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
        match = re.search(r"(?:compound|cpd|example|实施例|化合物)?\s*[-:]?\s*(\d{1,4}[A-Z]?)", value, re.I)
        if match:
            labels.append(match.group(1).upper())
    for label in labels:
        label = re.sub(r"\s+", "", str(label or "")).upper()
        if re.fullmatch(r"\d{1,4}[A-Z]?", label):
            return label
    return ""


def _component_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    overlap = max(0, min(ay1, by1) - max(ay0, by0))
    return overlap / max(1, min(ay1 - ay0, by1 - by0))


def _detect_visible_label_bbox(image_path: str, label: str) -> tuple[int, int, int, int] | None:
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
        components.append({
            "bbox": (x, y, x1, y1),
            "center_x": float(center_x),
            "center_y": float(center_y),
            "area": area,
        })

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
        score += 0.35 * (1.0 - min(1.0, abs(center_x - width / 2) / max(1.0, width / 2)))
        score += 0.15 * min(1.0, len(cluster) / max(1, len(label)))
        if best is None or score > best[0]:
            best = (score, bbox)

    return best[1] if best else None


def _mask_visible_label_for_ocsr(image_path: str, item: dict, output_dir: str = "") -> tuple[str, dict]:
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
    name_key = hashlib.sha1(f"{image_path}|{source_hash}|{safe_label}|{x0},{y0},{x1},{y1}".encode("utf-8")).hexdigest()[:12]
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


def _drop_detached_dummy_components(smiles: Optional[str]) -> tuple[Optional[str], bool]:
    """Drop OCSR-only wildcard specks that are disconnected from the molecule.

    A clipped label edge or a stereochemistry note can be read as one or more
    standalone ``*`` components.  Those isolated stars are never connected to
    the chemical graph.  Keep attached dummy/query atoms untouched so real
    Markush structures still fail closed and reach fallback/review.
    """
    if not smiles or "." not in smiles:
        return smiles, False
    parts = [part.strip() for part in str(smiles).split(".")]
    kept = [part for part in parts if part and part not in _DETACHED_DUMMY_COMPONENTS]
    if len(kept) == len(parts) or not kept:
        return smiles, False
    return ".".join(kept), True


def _correct_cf_ocr_halogen(smiles: Optional[str]) -> tuple[Optional[str], bool]:
    """Correct a common OCSR ``Cl`` -> ``[Cf]`` hallucination.

    Californium is not a plausible final-product atom in these medicinal
    chemistry patent tables. Some OCSR models emit ``[Cf]`` where the drawing
    visibly contains ``Cl``. Only apply the replacement when the corrected
    string is RDKit-parseable; strict QC still runs afterwards.
    """
    if not smiles or "[Cf]" not in str(smiles):
        return smiles, False
    candidate = str(smiles).replace("[Cf]", "Cl")
    # Detached OCR specks can make the complete dot-separated prediction
    # invalid even when the medicinal-chemistry product graph is valid. Check
    # individual components here; final strict QC still validates the cleaned
    # complete result after noise removal.
    try:
        from rdkit import Chem
    except ImportError:
        return smiles, False
    for component in candidate.split("."):
        mol = Chem.MolFromSmiles(component)
        if mol is not None and mol.GetNumHeavyAtoms() >= 20:
            return candidate, True
    return smiles, False


def _strip_detached_carbon_noise_fragments(smiles: Optional[str]) -> tuple[Optional[str], bool]:
    """Drop tiny disconnected carbon fragments caused by text/label OCR.

    Expanded visual crops can include headings or compound labels. OCSR engines
    sometimes convert those glyphs into disconnected ``CC``/``[CH3+]`` specks.
    Keep salts and heteroatom fragments fail-closed; strip only carbon-only
    fragments with at most two heavy atoms when there is one clear large product.
    """
    if not smiles or "." not in str(smiles):
        return smiles, False
    try:
        from rdkit import Chem
    except ImportError:
        return smiles, False
    parts = [part.strip() for part in str(smiles).split(".") if part.strip()]
    if len(parts) < 3:
        return smiles, False
    frags = []
    dropped_invalid_noise = False
    for part in parts:
        mol = Chem.MolFromSmiles(part)
        if mol is None:
            if part in _DETACHED_CARBON_NOISE_COMPONENTS:
                dropped_invalid_noise = True
                continue
            return smiles, False
        frags.append(mol)
    if not frags:
        return smiles, False
    indexed = sorted(
        enumerate(frags),
        key=lambda item: item[1].GetNumHeavyAtoms(),
        reverse=True,
    )
    largest_idx, largest = indexed[0]
    largest_heavy = largest.GetNumHeavyAtoms()
    if largest_heavy < 20:
        return smiles, False
    dropped = []
    for idx, frag in indexed[1:]:
        heavy = frag.GetNumHeavyAtoms()
        symbols = {atom.GetSymbol() for atom in frag.GetAtoms() if atom.GetAtomicNum() > 1}
        if heavy <= 2 and symbols <= {"C"}:
            dropped.append(idx)
            continue
        return smiles, False
    if not dropped and not dropped_invalid_noise:
        return smiles, False
    return Chem.MolToSmiles(largest, isomericSmiles=True), True


def _ring_digit_positions(smiles: str) -> list[tuple[str, int]]:
    """Return single-character ring digit positions outside brackets."""
    positions: list[tuple[str, int]] = []
    in_bracket = False
    for idx, char in enumerate(smiles):
        if char == "[":
            in_bracket = True
            continue
        if char == "]":
            in_bracket = False
            continue
        if in_bracket or not char.isdigit():
            continue
        if idx > 0 and smiles[idx - 1] == "%":
            continue
        positions.append((char, idx))
    return positions


def _repair_single_ring_digit_mismatch(smiles: Optional[str]) -> tuple[Optional[str], bool]:
    """Repair one DECIMER ring digit swap when the evidence is unambiguous.

    Some DECIMER predictions contain one overused ring digit and one unclosed
    ring digit, e.g. ``...CC2...C8=C1...`` where the final ``1`` should close
    the early ``2``.  This changes exactly one single-character ring index and
    only accepts the repair if RDKit parses the candidate cleanly afterwards.
    """
    if not smiles:
        return smiles, False
    text = str(smiles)
    try:
        from rdkit import Chem
    except ImportError:
        return smiles, False
    if Chem.MolFromSmiles(text) is not None:
        return smiles, False

    positions = _ring_digit_positions(text)
    by_digit: dict[str, list[int]] = {}
    for digit, idx in positions:
        by_digit.setdefault(digit, []).append(idx)
    odd = {digit: idxs for digit, idxs in by_digit.items() if len(idxs) % 2 == 1}
    if len(odd) != 2:
        return smiles, False
    missing = [digit for digit, idxs in odd.items() if len(idxs) == 1]
    overused = [digit for digit, idxs in odd.items() if len(idxs) == 3]
    if len(missing) != 1 or len(overused) != 1:
        return smiles, False

    missing_digit = missing[0]
    overused_digit = overused[0]
    for replace_idx in sorted(odd[overused_digit], reverse=True):
        candidate = text[:replace_idx] + missing_digit + text[replace_idx + 1:]
        # Guard against introducing another mismatch.
        repaired_counts: dict[str, int] = {}
        for digit, _idx in _ring_digit_positions(candidate):
            repaired_counts[digit] = repaired_counts.get(digit, 0) + 1
        if any(count % 2 for count in repaired_counts.values()):
            continue
        if Chem.MolFromSmiles(candidate) is not None:
            return candidate, True
    return smiles, False


def _qc_ocr_smiles(raw_smiles: Optional[str]) -> tuple[Optional[str], dict, bool]:
    cleaned_smiles, dropped_dummy_components = _drop_detached_dummy_components(raw_smiles)
    cleaned_smiles, _fixed_cf = _correct_cf_ocr_halogen(cleaned_smiles)
    cleaned_smiles, _stripped_noise = _strip_detached_carbon_noise_fragments(cleaned_smiles)
    checked = qc_smiles(cleaned_smiles)
    if checked.get("quality_flag") == "invalid_smiles":
        repaired_smiles, repaired_ring = _repair_single_ring_digit_mismatch(cleaned_smiles)
        if repaired_ring:
            repaired_checked = qc_smiles(repaired_smiles)
            if _is_clean_rdkit_result(repaired_checked):
                repaired_checked["ocr_repair"] = "single_ring_digit_mismatch"
                repaired_checked["engine_raw_smiles"] = cleaned_smiles
                return repaired_smiles, repaired_checked, dropped_dummy_components
    return cleaned_smiles, checked, dropped_dummy_components


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


def _review_fallback_is_graph_compatible(review_smiles: Optional[str], fallback_smiles: Optional[str]) -> bool:
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
        if atom.GetAtomicNum() == 0 or atom.GetSymbol() not in COMMON_FINAL_PRODUCT_ELEMENTS
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


def _restore_cd3_wildcard(smiles: Optional[str], item: dict) -> Optional[str]:
    """Use visual OCR CD3 evidence to restore one wildcard isotope methyl."""
    if not smiles or str(item.get("isotope_label_evidence") or "").upper() != "CD3":
        return None
    try:
        from rdkit import Chem
    except ImportError:
        return None
    mol = Chem.MolFromSmiles(str(smiles))
    if mol is None:
        return None
    dummy_atoms = [atom for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]
    if len(dummy_atoms) != 1 or dummy_atoms[0].GetDegree() != 1:
        return None
    editable = Chem.RWMol(mol)
    carbon = editable.GetAtomWithIdx(dummy_atoms[0].GetIdx())
    carbon.SetAtomicNum(6)
    carbon.SetNoImplicit(True)
    for _ in range(3):
        deuterium = Chem.Atom(1)
        deuterium.SetIsotope(2)
        d_idx = editable.AddAtom(deuterium)
        editable.AddBond(carbon.GetIdx(), d_idx, Chem.BondType.SINGLE)
    restored = editable.GetMol()
    try:
        Chem.SanitizeMol(restored)
        return Chem.MolToSmiles(restored, isomericSmiles=True)
    except Exception:
        return None


def _restore_singleton_terminal_amine_wildcard(smiles: Optional[str], item: dict) -> Optional[str]:
    """Restore a terminal amino group when singleton-claim evidence proves it.

    OCSR can read a terminal ``NH2`` label as an attached wildcard
    atom. Only apply this correction for claim/formula singleton bindings whose
    OCR chemical name explicitly contains amino/amine evidence, and only when
    there is exactly one terminal dummy atom.
    """
    if not smiles:
        return None
    if str(item.get("binding_rule") or "") != "singleton_claim_formula_structure":
        return None
    evidence = " ".join(
        str(item.get(key) or "")
        for key in ("singleton_chemical_name", "chemical_name", "notes", "evidence_reasons")
    )
    if not re.search(r"amino|amine|NH2", evidence, re.IGNORECASE):
        return None
    try:
        from rdkit import Chem
    except ImportError:
        return None
    mol = Chem.MolFromSmiles(str(smiles))
    if mol is None:
        return None
    dummy_atoms = [atom for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]
    if len(dummy_atoms) != 1 or dummy_atoms[0].GetDegree() != 1:
        return None
    editable = Chem.RWMol(mol)
    nitrogen = editable.GetAtomWithIdx(dummy_atoms[0].GetIdx())
    nitrogen.SetAtomicNum(7)
    nitrogen.SetFormalCharge(0)
    nitrogen.SetNoImplicit(False)
    restored = editable.GetMol()
    try:
        Chem.SanitizeMol(restored)
        return Chem.MolToSmiles(restored, isomericSmiles=True)
    except Exception:
        return None


def _invert_chiral_tags(smiles: str) -> Optional[str]:
    """Return the enantiomeric SMILES by flipping all assigned chiral atoms."""
    if not smiles:
        return None
    try:
        from rdkit import Chem
    except ImportError:
        return None

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    flipped = 0
    for atom in mol.GetAtoms():
        tag = atom.GetChiralTag()
        if tag == Chem.ChiralType.CHI_TETRAHEDRAL_CW:
            atom.SetChiralTag(Chem.ChiralType.CHI_TETRAHEDRAL_CCW)
            flipped += 1
        elif tag == Chem.ChiralType.CHI_TETRAHEDRAL_CCW:
            atom.SetChiralTag(Chem.ChiralType.CHI_TETRAHEDRAL_CW)
            flipped += 1

    if flipped == 0:
        return None
    return Chem.MolToSmiles(mol, isomericSmiles=True)


def _same_stereoless_smiles(a: str, b: str) -> bool:
    try:
        from rdkit import Chem
    except ImportError:
        return False
    ma = Chem.MolFromSmiles(a or "")
    mb = Chem.MolFromSmiles(b or "")
    if ma is None or mb is None:
        return False
    return Chem.MolToSmiles(ma, isomericSmiles=False) == Chem.MolToSmiles(mb, isomericSmiles=False)


def _apply_qc_to_result(result: dict, smiles: str, note: str) -> None:
    qc_result = qc_smiles(smiles)
    if not qc_result.get("rdkit_valid"):
        return
    result["raw_smiles"] = smiles
    result["canonical_smiles"] = qc_result["canonical_smiles"]
    result["inchikey"] = qc_result["inchikey"]
    result["mol_formula"] = qc_result["mol_formula"]
    result["mol_weight"] = qc_result["mol_weight"]
    result["heavy_atom_count"] = qc_result["heavy_atom_count"]
    result["ring_count"] = qc_result["ring_count"]
    result["chiral_centers"] = qc_result["chiral_centers"]
    result["rdkit_valid"] = True
    result["OCSR_quality_flag"] = note
    result["stereo_correction"] = note
    if qc_result.get("suspicious_elements"):
        result["suspicious_elements"] = qc_result["suspicious_elements"]
    else:
        result.pop("suspicious_elements", None)


def _normalise_enantiomer_pairs(results: List[dict]) -> List[dict]:
    """Ensure N-1/N-2 pairs are not emitted as identical stereoisomers.

    OCSR engines often read both enantiomer drawings as the same wedge
    direction. When a pair has the same formula and same stereoless graph, keep
    N-1 as read and flip assigned chiral tags in N-2 if the pair is identical.
    """
    by_id = {r.get("cpd_id"): r for r in results}
    bases = sorted({
        m.group(1)
        for r in results
        for m in [re.match(r"^Compound\s+([1-9]\d*)-[12]$", str(r.get("cpd_id", "")))]
        if m
    }, key=int)

    for base in bases:
        left = by_id.get(f"Compound {base}-1")
        right = by_id.get(f"Compound {base}-2")
        if not left or not right:
            continue
        ls = left.get("canonical_smiles") or left.get("raw_smiles") or ""
        rs = right.get("canonical_smiles") or right.get("raw_smiles") or ""
        if not ls or not rs:
            continue
        if left.get("mol_formula") and right.get("mol_formula") and left["mol_formula"] != right["mol_formula"]:
            continue
        if not _same_stereoless_smiles(ls, rs):
            continue
        if ls == rs or left.get("inchikey") == right.get("inchikey"):
            flipped = _invert_chiral_tags(rs)
            if flipped and flipped != rs:
                _apply_qc_to_result(
                    right,
                    flipped,
                    "stereo_pair_inverted_from_compound_%s-1" % base,
                )
    return results


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
                f"Image file not found: {ocsr_image_path}" if ocsr_image_path else "No image_path"
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
            except Exception:
                working_image = ocsr_image_path

        try:
            image_hash = compute_image_sha256(ocsr_image_path)
            result["image_hash"] = image_hash
        except Exception as e:
            result["OCSR_status"] = "image_missing"
            result["OCSR_failure_reason"] = f"Cannot compute image hash: {e}"
            return {"item": item, "result": result, "ready": False}

        return {
            "item": item,
            "result": result,
            "ready": True,
            "image_hash": image_hash,
            "working_image": working_image,
            "ocsr_image_path": ocsr_image_path,
        }

    def convert_one(self, item: dict, preprocess_dir: str = "", prepared: Optional[dict] = None) -> dict:
        """Convert one binding item to a SMILES result.

        Args:
            item: A binding dict with at least:
                - cpd (str): Compound ID
                - image_path (str): Path to structure image
                - page_no (int): Page number
                - structure_id (str): Structure identifier
                - structure_index (int): Structure index on page
            preprocess_dir: Directory for preprocessed images.

        Returns:
            Comprehensive result dict with SMILES, QC, and OCSR metadata.
        """
        structure_index = item.get("structure_index", 0)
        prepared = prepared or self._prepare_input(item, preprocess_dir=preprocess_dir)
        result = dict(prepared.get("result", {}))
        if not prepared.get("ready"):
            return result
        image_hash = prepared["image_hash"]
        working_image = prepared["working_image"]

        # Try engines in order
        engine_attempts = []
        best_result = None

        for engine_name in self.all_engine_names:
            engine = self.engines.get(engine_name)
            if engine is None:
                attempt = {
                    "engine": engine_name,
                    "status": "unavailable",
                    "quality_flag": "empty_prediction",
                    "error": f"Engine '{engine_name}' not registered",
                }
                engine_attempts.append(attempt)
                continue

            # Check cache first
            if self.cache:
                cached = self.cache.get_cached_result(image_hash, engine_name)
                if cached is not None:
                    if not str(cached.get("raw_smiles") or "").strip():
                        engine_attempts.append({
                            "engine": engine_name,
                            "status": cached.get("status", "cached_empty"),
                            "quality_flag": cached.get("quality_flag", "empty_prediction"),
                            "error": cached.get("error"),
                            "from_cache": True,
                            "ignored_cached_empty": True,
                        })
                        cached = None
                if cached is not None:
                    cached_raw_smiles, cached_qc, cached_dummy_cleanup = _qc_ocr_smiles(
                        cached.get("raw_smiles")
                    )
                    cached_restored_cd3 = None
                    if cached_qc.get("quality_flag") == "markush_or_query":
                        cached_restored_cd3 = _restore_cd3_wildcard(cached_raw_smiles, item)
                        if cached_restored_cd3:
                            cached_raw_smiles, cached_qc, _unused_cleanup = _qc_ocr_smiles(
                                cached_restored_cd3
                            )
                        if cached_qc.get("quality_flag") == "markush_or_query":
                            cached_restored_amine = _restore_singleton_terminal_amine_wildcard(cached_raw_smiles, item)
                            if cached_restored_amine:
                                cached_raw_smiles, cached_qc, _unused_cleanup = _qc_ocr_smiles(
                                    cached_restored_amine
                                )
                                cached["restored_terminal_amine"] = True
                    if cached_dummy_cleanup and _is_clean_rdkit_result(cached_qc):
                        cached = {
                            **cached,
                            "raw_smiles": cached_raw_smiles,
                            "rdkit_valid": cached_qc.get("rdkit_valid"),
                            "canonical_smiles": cached_qc.get("canonical_smiles"),
                            "inchikey": cached_qc.get("inchikey"),
                            "mol_formula": cached_qc.get("mol_formula"),
                            "mol_weight": cached_qc.get("mol_weight"),
                            "heavy_atom_count": cached_qc.get("heavy_atom_count", 0),
                            "ring_count": cached_qc.get("ring_count", 0),
                            "chiral_centers": cached_qc.get("chiral_centers", 0),
                            "quality_flag": cached_qc.get("quality_flag"),
                            "detached_dummy_cleanup": True,
                        }
                    if cached_restored_cd3 and _is_clean_rdkit_result(cached_qc):
                        cached = {
                            **cached,
                            "raw_smiles": cached_raw_smiles,
                            "rdkit_valid": cached_qc.get("rdkit_valid"),
                            "canonical_smiles": cached_qc.get("canonical_smiles"),
                            "inchikey": cached_qc.get("inchikey"),
                            "mol_formula": cached_qc.get("mol_formula"),
                            "mol_weight": cached_qc.get("mol_weight"),
                            "heavy_atom_count": cached_qc.get("heavy_atom_count", 0),
                            "ring_count": cached_qc.get("ring_count", 0),
                            "chiral_centers": cached_qc.get("chiral_centers", 0),
                            "quality_flag": cached_qc.get("quality_flag"),
                            "restored_isotope_label": "CD3",
                        }
                    # Re-evaluate every historical cache entry with current QC
                    # rules so a previously accepted plausible-looking OCR
                    # error cannot bypass stricter releases.
                    cached = {
                        **cached,
                        "raw_smiles": cached_raw_smiles,
                        "rdkit_valid": cached_qc.get("rdkit_valid"),
                        "canonical_smiles": cached_qc.get("canonical_smiles"),
                        "inchikey": cached_qc.get("inchikey"),
                        "mol_formula": cached_qc.get("mol_formula"),
                        "mol_weight": cached_qc.get("mol_weight"),
                        "heavy_atom_count": cached_qc.get("heavy_atom_count", 0),
                        "ring_count": cached_qc.get("ring_count", 0),
                        "chiral_centers": cached_qc.get("chiral_centers", 0),
                        "quality_flag": cached_qc.get("quality_flag"),
                        "suspicious_elements": cached_qc.get("suspicious_elements", []),
                    }
                    attempt = {
                        "engine": engine_name,
                        "status": cached.get("status", "cached"),
                        "quality_flag": cached.get("quality_flag", ""),
                        "error": cached.get("error"),
                        "from_cache": True,
                    }
                    if cached.get("suspicious_elements"):
                        attempt["suspicious_elements"] = cached.get("suspicious_elements")
                    if cached_qc.get("ocr_repair"):
                        attempt["ocr_repair"] = cached_qc.get("ocr_repair")
                        attempt["engine_raw_smiles"] = cached_qc.get("engine_raw_smiles")
                    if cached.get("detached_dummy_cleanup"):
                        attempt["detached_dummy_cleanup"] = True
                    if cached.get("restored_isotope_label"):
                        attempt["restored_isotope_label"] = cached.get("restored_isotope_label")
                    if cached.get("restored_terminal_amine"):
                        attempt["restored_terminal_amine"] = True
                    engine_attempts.append(attempt)

                    cached_clean = (
                        cached.get("rdkit_valid")
                        and cached.get("quality_flag") == "ok"
                    )
                    cached_query_baseline = (
                        result.get("raw_smiles")
                        if best_result == "partial_query"
                        and result.get("OCSR_quality_flag") in {"markush_or_query", "suspicious_element"}
                        else None
                    )
                    if (
                        cached_clean
                        and cached_query_baseline
                        and not _review_fallback_is_graph_compatible(
                            cached_query_baseline,
                            cached.get("raw_smiles"),
                        )
                    ):
                        attempt["rejected_query_fallback"] = "product graph differs from query candidate"
                        continue
                    if cached_clean:
                        # Cache hit with a clean valid SMILES - use it.
                        best_result = cached
                        result["raw_smiles"] = cached.get("raw_smiles")
                        result["canonical_smiles"] = cached.get("canonical_smiles")
                        result["inchikey"] = cached.get("inchikey")
                        result["mol_formula"] = cached.get("mol_formula")
                        result["mol_weight"] = cached.get("mol_weight")
                        result["heavy_atom_count"] = cached.get("heavy_atom_count", 0)
                        result["ring_count"] = cached.get("ring_count", 0)
                        result["chiral_centers"] = cached.get("chiral_centers", 0)
                        result["rdkit_valid"] = True
                        result["OCSR_engine"] = engine_name
                        result["OCSR_status"] = "success"
                        result["OCSR_quality_flag"] = cached.get("quality_flag", "ok")
                        result["OCSR_failure_reason"] = None
                        if cached_qc.get("ocr_repair"):
                            result["OCSR_repair_note"] = cached_qc.get("ocr_repair")
                            result["engine_raw_smiles"] = cached_qc.get("engine_raw_smiles")
                        result.pop("suspicious_elements", None)
                        break
                    else:
                        # Accuracy first: cached non-clean outputs are only
                        # diagnostics.  They must never block a fresh DECIMER
                        # attempt because engine config, GPU/CPU mode, QC
                        # rules, or crop selection may have changed.
                        attempt["ignored_cached_non_clean"] = True

            # Run engine prediction
            try:
                pred_result = engine.predict(working_image, timeout=self.timeout)
            except Exception as e:
                pred_result = {
                    "engine": engine_name,
                    "status": "failed",
                    "raw_smiles": None,
                    "molblock": None,
                    "confidence": None,
                    "error": str(e),
                    "elapsed_sec": 0.0,
                }

            # Apply RDKit QC
            engine_raw_smiles = pred_result.get("raw_smiles")
            raw_smiles, qc_result, detached_dummy_cleanup = _qc_ocr_smiles(engine_raw_smiles)
            restored_cd3_smiles = None
            restored_terminal_amine_smiles = None
            if qc_result.get("quality_flag") == "markush_or_query":
                restored_cd3_smiles = _restore_cd3_wildcard(raw_smiles, item)
                if restored_cd3_smiles:
                    raw_smiles, qc_result, _unused_cleanup = _qc_ocr_smiles(restored_cd3_smiles)
                if qc_result.get("quality_flag") == "markush_or_query":
                    restored_terminal_amine_smiles = _restore_singleton_terminal_amine_wildcard(raw_smiles, item)
                    if restored_terminal_amine_smiles:
                        raw_smiles, qc_result, _unused_cleanup = _qc_ocr_smiles(restored_terminal_amine_smiles)

            attempt = {
                "engine": engine_name,
                "status": pred_result.get("status", "unknown"),
                "quality_flag": qc_result["quality_flag"],
                "error": pred_result.get("error"),
                "raw_smiles": raw_smiles,
                "elapsed_sec": pred_result.get("elapsed_sec", 0.0),
                "device_used": pred_result.get("device_used"),
                "device_warning": pred_result.get("device_warning"),
            }
            if qc_result.get("suspicious_elements"):
                attempt["suspicious_elements"] = qc_result["suspicious_elements"]
            if qc_result.get("ocr_repair"):
                attempt["ocr_repair"] = qc_result.get("ocr_repair")
                attempt["engine_raw_smiles"] = qc_result.get("engine_raw_smiles") or engine_raw_smiles
            if detached_dummy_cleanup:
                attempt["engine_raw_smiles"] = engine_raw_smiles
                attempt["detached_dummy_cleanup"] = True
            if restored_cd3_smiles:
                attempt["restored_isotope_label"] = "CD3"
                attempt["engine_raw_smiles"] = engine_raw_smiles
            if restored_terminal_amine_smiles:
                attempt["restored_terminal_amine"] = True
                attempt["engine_raw_smiles"] = engine_raw_smiles
            engine_attempts.append(attempt)

            # Save to cache
            if self.cache:
                cache_data = {
                    "raw_smiles": raw_smiles,
                    "molblock": pred_result.get("molblock"),
                    "rdkit_valid": qc_result["rdkit_valid"],
                    "canonical_smiles": qc_result["canonical_smiles"],
                    "inchikey": qc_result["inchikey"],
                    "mol_formula": qc_result["mol_formula"],
                    "mol_weight": qc_result["mol_weight"],
                    "quality_flag": qc_result["quality_flag"],
                    "status": pred_result.get("status", "unknown"),
                    "error": pred_result.get("error"),
                    "model_version": pred_result.get("device_used"),
                }
                self.cache.save_result(image_hash, engine_name, cache_data)

            # Check if this result is usable
            if pred_result.get("status") == "success" and raw_smiles:
                review_baseline = (
                    result.get("raw_smiles")
                    if best_result == "partial_query"
                    and result.get("OCSR_quality_flag") in {"markush_or_query", "suspicious_element"}
                    else None
                )
                incompatible_review_fallback = bool(
                    review_baseline
                    and _is_clean_rdkit_result(qc_result)
                    and not _review_fallback_is_graph_compatible(review_baseline, raw_smiles)
                )
                if incompatible_review_fallback:
                    attempt["rejected_review_fallback"] = "product core differs from review candidate"
                    continue
                result["raw_smiles"] = raw_smiles
                result["canonical_smiles"] = qc_result["canonical_smiles"]
                result["inchikey"] = qc_result["inchikey"]
                result["mol_formula"] = qc_result["mol_formula"]
                result["mol_weight"] = qc_result["mol_weight"]
                result["heavy_atom_count"] = qc_result["heavy_atom_count"]
                result["ring_count"] = qc_result["ring_count"]
                result["chiral_centers"] = qc_result["chiral_centers"]
                result["rdkit_valid"] = qc_result["rdkit_valid"]
                result["OCSR_engine"] = engine_name
                result["OCSR_quality_flag"] = qc_result["quality_flag"]
                if qc_result.get("suspicious_elements"):
                    result["suspicious_elements"] = qc_result["suspicious_elements"]
                else:
                    result.pop("suspicious_elements", None)
                if qc_result.get("ocr_repair"):
                    result["OCSR_repair_note"] = qc_result.get("ocr_repair")
                    result["engine_raw_smiles"] = qc_result.get("engine_raw_smiles") or engine_raw_smiles

                if _is_clean_rdkit_result(qc_result):
                    # Best possible outcome - stop here.
                    result["OCSR_status"] = "success"
                    result["OCSR_failure_reason"] = None
                    best_result = True
                    break
                elif qc_result["quality_flag"] in {"markush_or_query", "suspicious_element"}:
                    # Query atoms and improbable element reads are not a
                    # deliverable final-product SMILES. Keep the candidate for
                    # review while trying fallback engines.
                    result["OCSR_status"] = "success"
                    best_result = "partial_query"
                    continue
                else:
                    # Got SMILES but RDKit invalid - record but try fallback
                    result["OCSR_status"] = "invalid_smiles"
                    result["OCSR_failure_reason"] = (
                        f"Engine {engine_name} produced SMILES but RDKit validation failed: "
                        f"{qc_result['quality_flag']}"
                    )
                    best_result = "partial"
            elif pred_result.get("status") == "timeout":
                if result["OCSR_status"] in ("not_processed", "engine_unavailable"):
                    result["OCSR_status"] = "engine_timeout"
                    result["OCSR_failure_reason"] = (
                        f"Engine {engine_name} timed out after {self.timeout}s"
                    )
            elif pred_result.get("status") == "unavailable":
                if result["OCSR_status"] == "not_processed":
                    result["OCSR_status"] = "engine_unavailable"
                    result["OCSR_failure_reason"] = (
                        f"Engine {engine_name} unavailable: {pred_result.get('error', '')}"
                    )

        # If no engine succeeded
        if best_result is None:
            if result["OCSR_status"] == "not_processed":
                result["OCSR_status"] = "all_engines_failed"
                result["OCSR_failure_reason"] = "All engines failed or unavailable"
        elif best_result == "partial":
            # We have a SMILES but it's not RDKit valid
            pass  # status already set to "invalid_smiles"

        result["engine_attempts"] = engine_attempts
        return result

    def convert_batch(
        self,
        items: List[dict],
        preprocess_dir: str = "",
        only_bound: bool = True,
        limit: int = 0,
        jobs: int = 1,
    ) -> List[dict]:
        """Batch-convert binding items to SMILES results.

        Args:
            items: List of binding dictionaries.
            preprocess_dir: Directory for preprocessed images.
            only_bound: If True, only process items with bind_status=bound
                       (or items without bind_status field, which are assumed bound).
            limit: If > 0, only process this many items (for testing).

        Returns:
            List of SMILES result dicts.
        """
        # Filter items
        filtered = []
        for item in items:
            # Check bind_status
            bind_status = item.get("bind_status", "bound")  # Default to bound
            if only_bound and bind_status != "bound":
                continue
            filtered.append(item)

        if limit > 0:
            filtered = filtered[:limit]

        jobs = max(1, int(jobs or 1))
        results = []
        t_batch_start = time.time()
        if jobs > 1:
            print(f"  Parallel OCSR workers: {jobs}")
            with ThreadPoolExecutor(max_workers=jobs) as executor:
                future_map = {
                    executor.submit(self.convert_one, item, preprocess_dir): (i, item)
                    for i, item in enumerate(filtered)
                }
                ordered = [None] * len(filtered)
                completed = 0
                for future in as_completed(future_map):
                    i, item = future_map[future]
                    cpd_id = item.get("cpd", f"item_{i}")
                    try:
                        result = future.result()
                    except Exception as e:
                        result = {
                            "patent_id": item.get("patent_id", "WO2026067249"),
                            "page_no": item.get("page_no", 0),
                            "cpd_id": cpd_id,
                            "structure_id": item.get("structure_id", ""),
                            "structure_image": item.get("image_path", ""),
                            "raw_smiles": None,
                            "canonical_smiles": None,
                            "rdkit_valid": False,
                            "OCSR_engine": None,
                            "OCSR_status": "failed",
                            "OCSR_quality_flag": "exception",
                            "OCSR_failure_reason": str(e),
                            "engine_attempts": [],
                        }
                    ordered[i] = result
                    completed += 1
                    status = result.get("OCSR_status", "?")
                    engine = result.get("OCSR_engine", "-")
                    total_elapsed = time.time() - t_batch_start
                    print(f"  [{completed}/{len(filtered)}] {cpd_id}: {status} "
                          f"engine={engine} (total {total_elapsed:.0f}s)")
                return _normalise_enantiomer_pairs([r for r in ordered if r is not None])

        for i, item in enumerate(filtered):
            cpd_id = item.get("cpd", f"item_{i}")
            t0 = time.time()
            result = self.convert_one(item, preprocess_dir=preprocess_dir)
            dt = time.time() - t0
            results.append(result)

            # Progress logging — helps diagnose which image hangs
            status = result.get("OCSR_status", "?")
            engine = result.get("OCSR_engine", "-")
            if (i + 1) % 10 == 0 or dt > 30 or status not in ("success", "not_processed"):
                total_elapsed = time.time() - t_batch_start
                print(f"  [{i+1}/{len(filtered)}] {cpd_id}: {status} "
                      f"engine={engine} {dt:.1f}s (total {total_elapsed:.0f}s)")

        return _normalise_enantiomer_pairs(results)
