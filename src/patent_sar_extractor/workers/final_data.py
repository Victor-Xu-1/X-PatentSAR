"""Exact ordered source catalog and activity left join for export presentation."""

from __future__ import annotations

import json

from patent_sar_extractor.core.activity_identity import normalize_compound
from patent_sar_extractor.core.activity_join import activity_order_and_map
from patent_sar_extractor.core.formal_structure import binding_pairs, proved_catalog
from patent_sar_extractor.smiles_artifact import smiles_records


def build_smiles_maps(records):
    by_label, by_pair, by_image = {}, {}, {}
    for record in records:
        label = normalize_compound(record.get("cpd_id", ""))
        image = str(record.get("structure_id") or "")
        if (
            not label
            or not image
            or (label, image) in by_pair
            or image in by_image
            or label in by_label
        ):
            raise ValueError(
                "Recognition cannot be confidence-deduplicated or reassigned"
            )
        by_label[label] = record
        by_pair[(label, image)] = record
        by_image[image] = record
    return by_label, by_pair, by_image


def get_smiles_for_binding(
    binding, smiles_map, smiles_by_binding_key, smiles_by_structure_id=None
):
    # Only the exact label + original image pair supplies a recognition.
    del smiles_map, smiles_by_structure_id
    return smiles_by_binding_key.get(
        (
            normalize_compound(binding.get("cpd", "")),
            str(binding.get("structure_id") or ""),
        ),
        {},
    )


def load_data(bindings_path, smiles_path, activity_data=None, activity_path=None):
    with open(bindings_path, encoding="utf-8") as stream:
        payload = json.load(stream)
    bindings = payload.get("final_bindings")
    catalog = proved_catalog(payload)
    if binding_pairs(bindings) != binding_pairs(catalog):
        raise ValueError("Formal export does not cover the complete proved catalog")
    with open(smiles_path, encoding="utf-8") as stream:
        records = smiles_records(json.load(stream))
    maps = build_smiles_maps(records)
    activities = {}
    if activity_path:
        with open(activity_path, encoding="utf-8") as stream:
            activity_payload = json.load(stream)
        _, activities = activity_order_and_map(activity_payload["rows"])
    elif activity_data is not None:
        if not isinstance(activity_data, dict):
            raise ValueError("Malformed explicit activity mapping")
        activities = activity_data
    keys = list(dict.fromkeys(key for row in activities.values() for key in row))
    assays = [
        {"target": key, "test_type": "", "unit": "", "description": "", "grades": {}}
        for key in keys
    ]
    return bindings, *maps, activities, assays
