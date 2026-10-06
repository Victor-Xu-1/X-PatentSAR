"""Page counts from saved, validated segmentation checkpoints, not time estimates."""

from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STAGE_PROGRESS_SCHEMA,
    STAGE_PROGRESS_SCHEMA_VERSION,
    schema_ref,
)


class StructureProgress:
    def __init__(self, output: str, pages: list[int]) -> None:
        if any(type(page) is not int or not 0 <= page < 1_000_000 for page in pages):
            raise ValueError(
                "Structure progress requires original integer page indices"
            )
        if len(set(pages)) != len(pages):
            raise ValueError("Structure progress cannot double-count requested pages")
        self.path = Path(output) / "progress.json"
        self.expected = frozenset(pages)
        self.completed: set[int] = set()
        self.cached: set[int] = set()
        self._write()

    def saved(self, pages: list[int], *, cached: bool = False) -> None:
        if type(cached) is not bool or any(type(page) is not int for page in pages):
            raise ValueError("Structure progress page observations are invalid")
        observed = set(pages)
        if not observed <= self.expected:
            raise ValueError("Structure progress cannot introduce foreign pages")
        fresh = observed - self.completed
        self.completed.update(fresh)
        if cached:
            self.cached.update(fresh)
        if fresh:
            self._write()

    def _write(self) -> None:
        write_json_atomic(
            self.path,
            {
                "schema": schema_ref(
                    STAGE_PROGRESS_SCHEMA, STAGE_PROGRESS_SCHEMA_VERSION
                ),
                "stage": "structures",
                "completed": len(self.completed),
                "total": len(self.expected),
                "cache_hits": len(self.cached),
                # Successful saved checkpoints, not failed SDK attempts/chemistry QA.
                "failures": 0,
                "device": None,
                "peak_rss_mb": None,
            },
        )
