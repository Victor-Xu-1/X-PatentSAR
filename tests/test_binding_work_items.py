"""Only actual completed loop bodies can advance source-work observations."""

import unittest

from patent_sar_extractor.core.binding_progress import observed_items


class BindingWorkItemTests(unittest.TestCase):
    def test_disabled_observer_returns_the_identical_input_without_copying(self):
        items = [object(), object()]
        self.assertIs(observed_items("caption_sources", items), items)

    def test_begin_and_counts_follow_body_completion_not_yield_or_clock(self):
        events = []
        items = [object(), object()]
        work = observed_items(
            "caption_sources", items, lambda *event: events.append(event)
        )
        self.assertEqual(events, [("caption_sources", 0, 2)])
        iterator = iter(work)
        self.assertIs(next(iterator), items[0])
        self.assertEqual(events[-1], ("caption_sources", 0, 2))
        self.assertIs(next(iterator), items[1])
        self.assertEqual(events[-1], ("caption_sources", 1, 2))
        with self.assertRaises(StopIteration):
            next(iterator)
        self.assertEqual(events[-1], ("caption_sources", 2, 2))

    def test_failure_and_early_close_do_not_complete_the_current_item(self):
        events = []
        work = iter(
            observed_items(
                "heading_sources", [1, 2, 3], lambda *event: events.append(event)
            )
        )
        with self.assertRaisesRegex(RuntimeError, "controlled source failure"):
            for item in work:
                if item == 2:
                    raise RuntimeError("controlled source failure")
        work.close()
        self.assertEqual(events, [("heading_sources", 0, 3), ("heading_sources", 1, 3)])

    def test_break_empty_work_and_observer_errors_are_not_fabricated_success(self):
        events = []
        work = iter(
            observed_items(
                "visible_captions", [1, 2], lambda *event: events.append(event)
            )
        )
        for _item in work:
            break
        work.close()
        self.assertEqual(events, [("visible_captions", 0, 2)])
        self.assertEqual(
            list(
                observed_items(
                    "heading_sources", [], lambda *event: events.append(event)
                )
            ),
            [],
        )
        self.assertEqual(events[-1], ("heading_sources", 0, 0))

        def failed_observer(*_event):
            raise OSError("controlled progress write failure")

        with self.assertRaisesRegex(OSError, "controlled progress write failure"):
            observed_items("heading_sources", [1], failed_observer)


if __name__ == "__main__":
    unittest.main()
