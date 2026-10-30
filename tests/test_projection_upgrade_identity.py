"""Only unchanged presentation rebuilds can retain a manual source basis."""

import copy
import json
import unittest

from test_web_support import WebFixture

from patent_sar_extractor.web.pdf import copy_original
from patent_sar_extractor.web.processes import runtime_identity
from patent_sar_extractor.web.service import WorkspaceService


class ProjectionUpgradeIdentityTests(WebFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.service = WorkspaceService(self.state)
        self.project = self.service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "control.pdf", None
        )
        self.store = self.service.store
        self.run_root = str(self.root / "controlled-projection")
        with self.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET run_root=? WHERE id=?",
                (self.run_root, self.project.id),
            )
        self.snapshot = {
            "is_historical": False,
            "read_model_identity": runtime_identity(),
            "raw_projection_layout": "previous-layout",
            "correction_projection_id": "a" * 32,
            "acceptance": {"state": "needs_review"},
        }
        self.rows = [
            {
                "dto": {"id": identity, "source": {"page": index + 1}},
                "image_path": f"images/{index}.png",
                "geometry_space": "rendered",
            }
            for index, identity in enumerate(("original-A", "original-B"))
        ]
        self.publish(self.snapshot, self.rows)

    def publish(self, snapshot, rows, *, upgrade=False):
        project = self.store.project(self.project.id)
        return self.store.snapshot(
            self.project.id,
            snapshot,
            rows,
            expected_run_root=self.run_root,
            expected_sha256=project["sha256"],
            presentation_upgrade=upgrade,
        )

    def current(self):
        return json.loads(self.store.project(self.project.id)["snapshot"])

    def candidate(self):
        return {
            **copy.deepcopy(self.snapshot),
            "raw_projection_layout": "current-layout",
            "historical_source_review_version": 1,
            "correction_projection_id": "b" * 32,
        }

    def test_complete_unchanged_current_rows_keep_the_existing_basis(self):
        candidate, rows = self.candidate(), copy.deepcopy(self.rows)
        rows[0]["dto"] = dict(reversed(list(rows[0]["dto"].items())))
        self.assertTrue(self.publish(candidate, rows, upgrade=True))
        self.assertEqual(self.current()["correction_projection_id"], "a" * 32)
        self.assertEqual(candidate["correction_projection_id"], "b" * 32)
        self.assertEqual(self.current()["raw_projection_layout"], "current-layout")

    def test_row_content_owner_order_and_source_identity_changes_do_not_rebase(self):
        for change in (
            "payload",
            "row_id",
            "order",
            "image",
            "geometry",
            "missing",
            "extra",
            "history",
            "acceptance",
            "runtime",
            "missing_basis",
            "malformed_basis",
        ):
            with self.subTest(change=change):
                previous = copy.deepcopy(self.snapshot)
                candidate, rows = self.candidate(), copy.deepcopy(self.rows)
                if change == "payload":
                    rows[0]["dto"]["source"]["page"] = 99
                elif change == "row_id":
                    rows[0]["dto"]["id"] = "other-original"
                elif change == "order":
                    rows.reverse()
                elif change == "image":
                    rows[0]["image_path"] = "images/another.png"
                elif change == "geometry":
                    rows[0]["geometry_space"] = "unrotated"
                elif change == "missing":
                    rows.pop()
                elif change == "extra":
                    rows.append({**rows[0], "dto": {"id": "other-original"}})
                elif change == "history":
                    candidate["is_historical"] = True
                elif change == "acceptance":
                    candidate["acceptance"] = {"state": "failed"}
                elif change == "runtime":
                    candidate["read_model_identity"]["ruleset"]["version"] = "other"
                elif change == "missing_basis":
                    previous.pop("correction_projection_id")
                else:
                    previous["correction_projection_id"] = "not-a-source-identity"
                self.publish(previous, self.rows)
                self.assertTrue(self.publish(candidate, rows, upgrade=True))
                self.assertEqual(self.current()["correction_projection_id"], "b" * 32)

    def test_explicit_refresh_still_invalidates_the_old_basis(self):
        candidate = self.candidate()
        self.assertTrue(self.publish(candidate, self.rows))
        self.assertEqual(self.current()["correction_projection_id"], "b" * 32)

    def test_publication_uses_the_latest_committed_basis_not_an_earlier_read(self):
        candidate = self.candidate()
        newer = {**self.snapshot, "correction_projection_id": "c" * 32}
        self.publish(newer, self.rows)
        self.assertTrue(self.publish(candidate, self.rows, upgrade=True))
        self.assertEqual(self.current()["correction_projection_id"], "c" * 32)

    def test_changed_run_cannot_publish_or_restore_a_prior_source_basis(self):
        before = self.current()
        with self.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET run_root=? WHERE id=?",
                (str(self.root / "new-attempt"), self.project.id),
            )
        self.assertFalse(self.publish(self.candidate(), self.rows, upgrade=True))
        self.assertEqual(self.current(), before)


if __name__ == "__main__":
    unittest.main()
