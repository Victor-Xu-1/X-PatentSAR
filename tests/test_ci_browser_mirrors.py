"""Focused pure CI mirror controls; never touch local system configuration."""

import unittest
from unittest.mock import patch

from tools.ci_browser_mirrors import official_https_mirrors, prepare


class BrowserMirrorTests(unittest.TestCase):
    def test_failed_azure_mirror_uses_official_https_without_disabling_signatures(self):
        source = "# official mirrors\nhttp://azure.archive.ubuntu.com/ubuntu/\nhttps://archive.ubuntu.com/ubuntu/\n"
        changed = official_https_mirrors(source)
        self.assertNotIn("azure.archive", changed)
        self.assertNotIn("http://", changed)
        self.assertIn("https://archive.ubuntu.com/ubuntu/", changed)
        self.assertEqual(official_https_mirrors(changed), changed)

    def test_untrusted_authenticated_query_or_oversized_lists_are_rejected(self):
        for source in (
            "https://evil.invalid/ubuntu",
            "https://user:pass@archive.ubuntu.com/ubuntu",
            "https://archive.ubuntu.com/ubuntu?x=1",
            "x" * 16385,
            "# empty",
        ):
            with self.subTest(source=source[:64]), self.assertRaises(ValueError):
                official_https_mirrors(source)

    def test_mirror_priority_metadata_keeps_required_tab_separator(self):
        source = "http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\nhttps://security.ubuntu.com/ubuntu/\tpriority:3\n"
        changed = official_https_mirrors(source)
        self.assertIn("https://archive.ubuntu.com/ubuntu/\tpriority:1", changed)
        self.assertIn("https://security.ubuntu.com/ubuntu/\tpriority:3", changed)
        self.assertNotIn("/ priority:", changed)

    def test_local_or_non_root_call_cannot_mutate_system_mirrors(self):
        with (
            patch.dict("os.environ", {"GITHUB_ACTIONS": "false"}),
            self.assertRaises(ValueError),
        ):
            prepare()
