"""Observe current sealed chunks; worker text is a wakeup, never a work receipt."""

from pathlib import Path

from .pipeline_io import _worker_output_state
from .stage_cache import _manifest_path
from .structure_cache import _load_reusable_structure_chunk


class WindowCheckpointObserver:
    """At most three owned chunk pairs; one canonical validator and no timer."""

    def __init__(self, jobs, on_saved):
        if not 1 <= len(jobs) <= 3:
            raise ValueError("Checkpoint observation requires one bounded warm window")
        self.jobs, self.on_saved = jobs, on_saved
        self.previous = {job["output"]: self._state(job) for job in jobs}
        self.observed = {}
        self.reported = set()

    @staticmethod
    def _state(job):
        path = Path(job["output"]) / "metadata.json"
        return _worker_output_state(path), _worker_output_state(
            _manifest_path(str(path))
        )

    def _read(self, job, signature):
        params = job["fingerprint"].get("params", {})
        pages = job["pages"]
        if (
            not isinstance(params, dict)
            or not isinstance(pages, list)
            or any(type(page) is not int for page in pages)
            or pages != params.get("chunk_pages")
        ):
            return None
        previous = self.previous[job["output"]]
        if any(
            current is None or current == old
            for current, old in zip(signature, previous, strict=True)
        ):
            return None
        try:
            payload = _load_reusable_structure_chunk(job["output"], job["fingerprint"])
        except (ValueError, TypeError, KeyError):
            return None  # Invalid/pending data cannot be observed as saved work.
        if payload is None or signature != self._state(job):
            return None
        return payload

    def collect(self, *, terminal=False):
        results = {}
        for job in self.jobs:
            output = job["output"]
            signature = self._state(job)
            if not terminal and self.observed.get(output) == signature:
                continue
            self.observed[output] = signature
            payload = self._read(job, signature)
            if payload is None:
                continue
            results[output] = payload
            if output not in self.reported:
                if self.on_saved is not None:
                    self.on_saved(job["pages"])
                self.reported.add(output)
        return results

    def on_line(self, _line):
        if len(self.reported) < len(self.jobs):
            self.collect()
