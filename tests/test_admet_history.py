"""Bounded write-once ADMET history, not mutable or foreign producer evidence."""

from __future__ import annotations

import json
import unittest

from test_prediction_support import PredictionFixture, controlled_stage

from patent_sar_extractor.web.admet_history import (
    read_admet_stage,
    seal_admet_stage,
    write_admet_stage,
)
from patent_sar_extractor.web.storage import now


class ADMETHistoryTests(PredictionFixture, unittest.TestCase):
    def test_terminal_failed_stage_is_sealed_not_forever_running(self):
        row, root, _ = self.draft()
        write_admet_stage(
            root,
            row,
            controlled_stage(completed=0, status="running"),
            core_completed=False,
        )
        stamp = now()
        seal_admet_stage(self.state, root, row, "cancelled", stamp)
        terminal = {**row, "status": "cancelled", "finished_at": stamp}
        stage, _ = read_admet_stage(terminal, root, state_root=self.state)
        self.assertIsNotNone(stage)
        self.assertEqual(stage.status, "failed")
        original = (self.state / "job-history" / f"{row['id']}-admet.json").read_bytes()
        write_admet_stage(root, row, controlled_stage(), core_completed=False)
        self.assertEqual(
            read_admet_stage(terminal, root, state_root=self.state)[0], stage
        )
        self.assertEqual(
            (self.state / "job-history" / f"{row['id']}-admet.json").read_bytes(),
            original,
        )

    def test_foreign_schema_flags_extra_fields_and_noncanonical_job_ids_are_rejected(
        self,
    ):
        row, root, _ = self.draft()
        write_admet_stage(root, row, controlled_stage(), core_completed=False)
        path = root / "admet-stage.json"
        original = path.read_bytes()
        for mutation in ("schema_bool", "core", "extra", "counts", "job"):
            with self.subTest(mutation=mutation):
                packet = json.loads(original)
                if mutation == "schema_bool":
                    packet["schema"]["version"] = True
                elif mutation == "core":
                    packet["core_completed"] = True
                elif mutation == "extra":
                    packet["unreviewed"] = "field"
                elif mutation == "counts":
                    packet["stage"]["count"] = 0
                else:
                    packet["job_id"] = "../../unsafe"
                path.write_text(json.dumps(packet))
                self.assertIsNone(read_admet_stage(row, root)[0])
        with self.assertRaises((ValueError, OSError)):
            write_admet_stage(
                root,
                {**row, "id": "../../unsafe"},
                controlled_stage(),
                core_completed=False,
            )


if __name__ == "__main__":
    unittest.main()
