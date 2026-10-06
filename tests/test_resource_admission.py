"""Bounded measured admission; waiting is not an inference failure or retry."""

import unittest


class ResourceAdmissionTests(unittest.TestCase):
    def test_available_memory_never_waits(self):
        from patent_sar_extractor.resource_admission import wait_for_memory

        observations = []
        wait_for_memory(3072, available=lambda: 4096, publish=observations.append)
        self.assertEqual(observations, [])

    def test_shortage_publishes_real_wait_then_clears(self):
        from patent_sar_extractor.resource_admission import wait_for_memory

        values = iter([1024, 4096])
        observed = []
        wait_for_memory(
            3072,
            available=lambda: next(values),
            publish=observed.append,
            pause=lambda _: None,
        )
        self.assertEqual(observed[0]["available_mb"], 1024)
        self.assertEqual(observed[0]["required_mb"], 3072)
        self.assertIsNone(observed[-1])

    def test_exhausted_wait_is_bounded_and_never_loads_a_model(self):
        from patent_sar_extractor.resource_admission import (
            ResourceAdmissionError,
            wait_for_memory,
        )

        observed = []
        ticks = iter([0, 0, 2])
        with self.assertRaises(ResourceAdmissionError):
            wait_for_memory(
                3072,
                timeout=1,
                available=lambda: 0,
                publish=observed.append,
                pause=lambda _: None,
                clock=lambda: next(ticks),
            )
        self.assertIsNone(observed[-1])
