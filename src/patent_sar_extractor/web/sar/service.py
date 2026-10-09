"""Independent SAR dataset/region use cases shared by routes and owned jobs."""

from __future__ import annotations

import uuid

from ...core.sar.drawing import draw_structure
from ...core.sar.matching import validate_region
from ..analysis_lease import analysis_lease
from ..errors import WebError
from ..service import WorkspaceService
from ..storage import now
from .assets import SARAssets, digest
from .csv_inputs import mapped_inputs
from .dataset_store import Datasets
from .models import (
    CSVMapping,
    Dataset,
    DatasetList,
    MoleculeDrawing,
    ProjectSnapshot,
    Region,
    RegionRequest,
)
from .project_inputs import project_inputs, project_revision
from .store import SARStore
from .uploads import Uploads


class SARService:
    def __init__(self, workspace: WorkspaceService):
        self.workspace = workspace
        self.store = SARStore(workspace.store.root)
        self.assets = SARAssets(workspace.store.root)
        self.datasets = Datasets(self.store)
        self.uploads = Uploads(self.store, self.assets)

    def dataset(self, identifier: str) -> Dataset:
        value = self.datasets.get(identifier)
        if value.source_project_id:
            try:
                value.stale = project_revision(
                    self.workspace,
                    value.source_project_id,
                    include_research=(
                        self.datasets.source_revision(identifier) or ""
                    ).startswith("research2:"),
                ) != self.datasets.source_revision(identifier)
            except WebError:
                value.stale = True
        return value

    def list(self) -> DatasetList:
        values = self.datasets.list()
        values.items = [self.dataset(item.id) for item in values.items]
        return values

    def current(self, identifier: str, revision: int | None = None) -> Dataset:
        value = self.dataset(identifier)
        if value.stale or (revision is not None and value.revision != revision):
            raise WebError(
                409,
                "sar_dataset_stale",
                "Source data changed; create a new snapshot before analysing it.",
            )
        return value

    def from_csv(self, request: CSVMapping) -> Dataset:
        fields = request.model_dump(exclude={"request_id"})
        # New neutral optional roles do not change an already-published nonce's
        # meaning. Nonempty mappings remain part of its exact identity.
        for key in ("source_page_column", "property_columns", "prediction_columns"):
            if not fields[key]:
                fields.pop(key)
        request_hash = digest(fields)
        existing = self.datasets.existing(request.request_id, request_hash)
        if existing:
            return self.dataset(existing.id)
        data, source_hash = self.uploads.read(request.token)
        with analysis_lease(self.workspace.store.root):
            molecules, metrics, input_count = mapped_inputs(data, request)
            dataset = Dataset(
                id=uuid.uuid4().hex,
                title=request.title,
                source_kind="csv",
                source_sha256=source_hash,
                row_count=len(molecules),
                input_row_count=input_count,
                eligible_count=sum(item.eligible for item in molecules),
                issue_count=sum(bool(item.issues) for item in molecules),
                metrics=metrics,
                created_at=now(),
            )
            dataset = self.datasets.publish(
                dataset, molecules, request.request_id, request_hash
            )
            self.uploads.used(request.token)
            return dataset

    def from_project(self, request: ProjectSnapshot) -> Dataset:
        request_hash = digest(request.model_dump(exclude={"request_id"}))
        existing = self.datasets.existing(request.request_id, request_hash)
        if existing:
            return self.dataset(existing.id)
        with analysis_lease(self.workspace.store.root):
            (
                molecules,
                metrics,
                source_revision,
                source_title,
                document_hash,
                source_acceptance,
                source_page_count,
            ) = project_inputs(self.workspace, request.project_id)
            dataset = Dataset(
                id=uuid.uuid4().hex,
                title=request.title or source_title,
                source_kind="project",
                source_project_id=request.project_id,
                source_document_sha256=document_hash,
                source_acceptance=source_acceptance,
                source_page_count=source_page_count,
                source_sha256=digest(
                    [source_revision, [item.model_dump() for item in molecules]]
                ),
                row_count=len(molecules),
                input_row_count=len(molecules),
                eligible_count=sum(item.eligible for item in molecules),
                issue_count=sum(bool(item.issues) for item in molecules),
                metrics=metrics,
                created_at=now(),
            )
            return self.datasets.publish(
                dataset, molecules, request.request_id, request_hash, source_revision
            )

    def drawing(self, identifier: str, molecule_id: str) -> MoleculeDrawing:
        molecule = self.datasets.molecule(identifier, molecule_id)
        if not molecule.eligible or not molecule.molfile:
            raise WebError(
                422,
                "sar_structure_unavailable",
                "This structure needs verification before region selection.",
            )
        try:
            drawing = draw_structure(molecule.molfile)
        except ValueError as error:
            raise WebError(
                422,
                "sar_structure_unavailable",
                "Molecular drawing could not be verified.",
            ) from error
        return MoleculeDrawing(molecule=molecule, **drawing)

    def save_region(self, identifier: str, request: RegionRequest) -> Region:
        dataset = self.current(identifier, request.expected_dataset_revision)
        molecule = self.datasets.molecule(identifier, request.molecule_id)
        if (
            not molecule.eligible
            or not molecule.molfile
            or molecule.graph_sha256 != request.expected_graph_sha256
        ):
            raise WebError(
                409,
                "sar_graph_changed",
                "Region must refer to the exact eligible snapshot graph.",
            )
        try:
            if request.kind == "core":
                from ...core.sar.molecules import read_molfile
                from ...core.sar.regions import attachment_groups
                from ...core.sar.study_cores import compile_core

                compile_core(molecule.molfile, request.atom_indices)
                groups = attachment_groups(
                    read_molfile(molecule.molfile), frozenset(request.atom_indices)
                )
                attachments = sum(
                    len(key) * len(values) for key, values in groups.items()
                )
            else:
                attachments = validate_region(molecule.molfile, request.atom_indices)
        except ValueError as error:
            raise WebError(
                422,
                "sar_region_invalid",
                "Select one connected variable region with a nonempty fixed background.",
            ) from error
        region_id = digest(
            [
                identifier,
                molecule.id,
                dataset.revision,
                molecule.graph_sha256,
                sorted(request.atom_indices),
                request.name,
                request.kind,
            ]
        )[:32]
        return self.datasets.save_region(
            Region(
                id=region_id,
                dataset_id=identifier,
                molecule_id=molecule.id,
                dataset_revision=dataset.revision,
                graph_sha256=molecule.graph_sha256,
                atom_indices=sorted(request.atom_indices),
                attachment_count=attachments,
                created_at=now(),
                name=request.name,
                kind=request.kind,
            )
        )
