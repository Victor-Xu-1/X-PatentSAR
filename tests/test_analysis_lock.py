"""Real cross-process analysis exclusion and bounded private-lock checks."""

import os
import subprocess
import sys
import unittest

from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.analysis import AnalysisService
from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.errors import WebError


class AnalysisLockTests(PredictionFixture, unittest.TestCase):
    def test_separate_process_cannot_enter_then_lock_is_reusable(self):
        analysis = AnalysisService(
            self.state, self.service, settings=AnalysisSettings()
        )
        self.addCleanup(analysis.close)
        code = "from pathlib import Path; from patent_sar_extractor.web.service import WorkspaceService; from patent_sar_extractor.web.analysis import AnalysisService; from patent_sar_extractor.web.analysis_runtime import AnalysisSettings; from patent_sar_extractor.web.errors import WebError; import sys; s=WorkspaceService(sys.argv[1]); a=AnalysisService(s.store.root,s,settings=AnalysisSettings());\ntry:\n with a._operation(None): print('entered')\nexcept WebError as e: print(e.code)\nfinally: a.close()"
        with analysis._operation(None):
            blocked = subprocess.run(
                [sys.executable, "-c", code, str(self.state)],
                capture_output=True,
                text=True,
                timeout=8,
                check=True,
            )
        self.assertEqual(blocked.stdout.strip(), "analysis_busy")
        allowed = subprocess.run(
            [sys.executable, "-c", code, str(self.state)],
            capture_output=True,
            text=True,
            timeout=8,
            check=True,
        )
        self.assertEqual(allowed.stdout.strip(), "entered")

    def test_unsafe_lock_rejected_without_changing_permissions_or_content(self):
        analysis = AnalysisService(
            self.state, self.service, settings=AnalysisSettings()
        )
        self.addCleanup(analysis.close)
        lock = analysis.cache.root / "operation.lock"
        lock.write_bytes(b"Preserve this unknown local lock")
        os.chmod(lock, 0o644)
        with self.assertRaises(WebError) as error, analysis._operation(None):
            self.fail("Unsafe lock must not be acquired")
        self.assertEqual(error.exception.code, "analysis_lock")
        self.assertEqual(lock.read_bytes(), b"Preserve this unknown local lock")
        self.assertEqual(lock.stat().st_mode & 0o777, 0o644)
