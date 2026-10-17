"""One owner's independent raw observations, separate from its saved projection."""

from dataclasses import dataclass, field

from patent_sar_extractor.contracts import (
    SMILES_SCHEMA,
    SMILES_SCHEMA_VERSION,
    schema_ref,
)

from .errors import WebError


@dataclass
class SourceCompletion:
    compound_id: str
    binding: dict
    crop_sha256: str
    primary: dict | None = None
    reprints: list[dict] = field(default_factory=list)
    prior_status: str = "unavailable"

    @property
    def sources(self) -> list[dict]:
        return [self.binding, *self.binding.get("additional_sources", [])]

    @property
    def records(self) -> list[dict]:
        return [self.primary, *self.reprints] if self.primary is not None else []

    def append(self, record: dict) -> None:
        if not isinstance(record, dict):
            raise WebError(
                502,
                "invalid_recognition",
                "Source recognition did not return an observation object.",
            )
        if self.primary is None:
            self.primary = record
        else:
            self.reprints.append(record)

    def packet(self) -> dict:
        if self.primary is None:
            raise ValueError("There is no original observation to checkpoint")
        return {
            **self.primary,
            "source_schema": schema_ref(SMILES_SCHEMA, SMILES_SCHEMA_VERSION),
            "reprint_records": [dict(record) for record in self.reprints],
        }
