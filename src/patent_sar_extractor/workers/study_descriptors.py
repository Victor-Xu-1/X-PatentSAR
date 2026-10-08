"""One descriptor authority, explicit supplied origins, resumable row records."""

from __future__ import annotations

import math

from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.study_graphs import graph_description
from patent_sar_extractor.web.descriptor_fields import (
    DESCRIPTOR_KEYS,
    compute_descriptors,
)
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.prediction_models import METRIC_KEYS

from .study_checkpoints import BATCH_SIZE, load, progress, save


def describe(molecule: dict) -> dict:
    result = {
        "molecule_id": molecule["id"],
        "source_graph_sha256": molecule["graph_sha256"],
        "eligible": molecule["eligible"],
        "canonical_smiles": None,
        "scaffold_id": None,
        "scaffold_smiles": None,
        "properties": {
            key: molecule.get("properties", {}).get(key) for key in METRIC_KEYS
        },
        "property_origins": {
            key: molecule.get("property_origins", {}).get(key, "not_provided")
            for key in METRIC_KEYS
        },
        "predictions": dict(molecule.get("predictions", {})),
        "prediction_origin": molecule.get("prediction_origin", "not_provided"),
        "reasons": list(molecule.get("issues", [])),
    }
    if any(
        value is not None and not math.isfinite(value)
        for value in [*result["properties"].values(), *result["predictions"].values()]
    ):
        raise SARInputError("study_nonfinite_property")
    if result["prediction_origin"] == "imported":
        result["reasons"].append("imported_predictions_unverified")
    if not molecule["eligible"] or not molecule.get("molfile"):
        result["reasons"].append("source_structure_ineligible")
        return result
    try:
        description = graph_description(molecule["molfile"])
    except SARInputError as error:
        raise SARInputError("study_eligible_graph_unsupported") from error
    result.update(
        {
            key: description[key]
            for key in ("canonical_smiles", "scaffold_id", "scaffold_smiles")
        }
    )
    result["reasons"].extend(description["reasons"])
    needed = [
        key
        for key in DESCRIPTOR_KEYS
        if result["properties"][key] is None
        and result["property_origins"][key] != "manual_null"
    ]
    if needed:
        try:
            computed = {
                metric.key: metric.value
                for metric in compute_descriptors(description["canonical_smiles"])
            }
        except (WebError, ValueError, RuntimeError):
            result["reasons"].append("descriptor_out_of_domain")
        else:
            for key in needed:
                result["properties"][key] = computed[key]
                result["property_origins"][key] = "computed_rdkit"
    # LogS is only a provided actual value; never invoke or replace a model.
    if result["properties"][METRIC_KEYS[-1]] is None:
        result["reasons"].append("logs_not_provided")
    result["reasons"] = sorted(set(result["reasons"]))
    return result


def descriptor_batches(safe, identity, rows, check):
    output = []
    for start in range(0, len(rows), BATCH_SIZE):
        check()
        batch = rows[start : start + BATCH_SIZE]
        name = f"descriptors-{start // BATCH_SIZE:04d}.json"
        records = load(safe, name, identity, start, "rows")
        if records is None:
            records = []
            for molecule in batch:
                check()
                records.append(describe(molecule))
            save(safe.root, name, identity, start, "rows", records)
        elif len(records) != len(batch) or any(
            record.get("molecule_id") != row["id"]
            or record.get("source_graph_sha256") != row["graph_sha256"]
            or record.get("eligible") != row["eligible"]
            or record.get("predictions") != row["predictions"]
            or record.get("prediction_origin") != row["prediction_origin"]
            for record, row in zip(records, batch, strict=True)
        ):
            raise SARInputError("study_descriptor_checkpoint_identity")
        # Typed finite row validation also applies to cached descriptor packets.
        for record in records:
            if set(record) != {
                "molecule_id",
                "source_graph_sha256",
                "eligible",
                "canonical_smiles",
                "scaffold_id",
                "scaffold_smiles",
                "properties",
                "property_origins",
                "predictions",
                "prediction_origin",
                "reasons",
            }:
                raise SARInputError("study_descriptor_checkpoint_shape")
            if (
                not isinstance(record["properties"], dict)
                or set(record["properties"]) != set(METRIC_KEYS)
                or not isinstance(record["property_origins"], dict)
                or set(record["property_origins"]) != set(METRIC_KEYS)
                or not isinstance(record["reasons"], list)
            ):
                raise SARInputError("study_descriptor_checkpoint_shape")
        output.extend(records)
        progress(safe.root, identity, len(output), 0)
    return output
