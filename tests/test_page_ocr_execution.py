"""Real bounded thread execution with no model, provider or private patent."""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from patent_sar_extractor.core import page_ocr_execution as execution


class PageOCRExecutionTests(unittest.TestCase):
    def test_executor_has_at_most_one_pending_source_per_worker(self):
        ready, release = threading.Event(), threading.Event()
        lock = threading.Lock()
        submitted, started, observed, errors = [], [], [], []

        class OwnedPool(ThreadPoolExecutor):
            def submit(self, function, index):
                submitted.append(index)
                return super().submit(function, index)

        def source(index):
            with lock:
                started.append(index)
                if len(started) == 2:
                    ready.set()
            if not release.wait(2):
                raise RuntimeError("Controlled source deadline")
            return index, f"Original page {index}", []

        def consume():
            try:
                observed.extend(execution.parallel_pages(list(range(20)), source, 2))
            except RuntimeError as error:
                errors.append(error)

        with patch.object(execution, "ThreadPoolExecutor", OwnedPool):
            thread = threading.Thread(target=consume)
            thread.start()
            try:
                self.assertTrue(ready.wait(2))
                self.assertEqual(submitted, [0, 1])
            finally:
                release.set()
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(sorted(value[0] for value in observed), list(range(20)))

    def test_source_failure_stops_new_requests_and_never_synthesizes_a_page(self):
        visited, results = [], []

        def source(index):
            visited.append(index)
            if index == 0:
                raise RuntimeError("Controlled unavailable original page")
            return index, f"Original page {index}", []

        with self.assertRaises(execution.PageObservationError):
            results.extend(execution.parallel_pages(list(range(20)), source, 2))
        self.assertTrue(set(visited) <= {0, 1})
        self.assertTrue(all(value[0] == 1 for value in results))

    def test_owner_and_coordinate_shapes_are_not_coerced(self):
        for value in (
            (True, "text", []),
            (1, "foreign", []),
            (0, 11, []),
            (0, "text", [{"text": "11", "y0": True}]),
            (0, "text", [{"text": "11", "bbox": [0, 0, float("inf"), 3]}]),
        ):
            with (
                self.subTest(value=value),
                self.assertRaises(execution.PageObservationError),
            ):
                execution.page_observation(0, value)
