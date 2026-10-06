"""Independent deterministic evidence with the same strict source/job binding."""

from typing import ClassVar

from .descriptor_fields import descriptor_epoch
from .descriptor_models import DescriptorSummary
from .molecular_observation_store import MolecularObservationStore


class DescriptorStore(MolecularObservationStore[DescriptorSummary]):
    table = "molecular_descriptors"
    packet_schema: ClassVar[dict[str, object]] = {
        "name": "patentsar.descriptor-projection",
        "version": 1,
    }
    summary_type = DescriptorSummary
    calculate_epoch = staticmethod(descriptor_epoch)
