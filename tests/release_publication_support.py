"""One controlled Git/API fixture shared by release-publication regressions."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path

from tests.test_release_policy import fixture
from tools.release_github import GitHub
from tools.release_scope import SCOPE


class IncomingPullFixture:
    def pull(self):
        return {
            "number": 45,
            "state": "open",
            "merged": False,
            "base": {
                "ref": "main",
                "sha": "a" * 40,
                "repo": {"full_name": "owner/repo"},
            },
            "head": {
                "ref": "feat/version",
                "sha": "b" * 40,
                "repo": {"full_name": "owner/repo"},
            },
        }


class GitPublicationFixture(IncomingPullFixture):
    """Exercise actual Git object reads and mutation order with a controlled API."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-version-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Controlled Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", str(self.root))
        self.write(fixture())
        self.git("add", ".")
        self.git("commit", "-m", "baseline")
        self.base = self.git("rev-parse", "HEAD").strip()
        plan = {
            "schema_version": 1,
            "base_sha": self.base,
            "changed_paths": ["README.md", SCOPE],
            "python_modules": [],
            "frontend_tests": [],
            "browser_tests": [],
        }
        self.write(
            {"README.md": "controlled PR\n", SCOPE: json.dumps(plan, indent=2) + "\n"}
        )
        self.git("add", ".")
        self.git("commit", "-m", "incoming PR")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.git("update-ref", "refs/pull/45/head", self.head)
        self.git("checkout", self.base)
        self.record = self.pull()
        self.record["base"]["sha"] = self.base
        self.record["head"]["sha"] = self.head
        self.calls = []
        self.api = GitHub("owner/repo", "controlled-test-token")

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.root, text=True, stderr=subprocess.PIPE
        )

    def write(self, files):
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def answer(self, method, path, value=None):
        self.calls.append((method, path, copy.deepcopy(value)))
        if path == "/git/ref/heads/main":
            return {"object": {"sha": self.base}}
        if path == "/git/commits/" + self.head:
            return {
                "tree": {"sha": self.git("rev-parse", self.head + "^{tree}").strip()}
            }
        if path == "/git/blobs":
            import base64
            import hashlib

            data = base64.b64decode(value["content"])
            return {
                "sha": hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data
                ).hexdigest()
            }
        if path == "/git/trees":
            return {"sha": "c" * 40}
        if path == "/git/commits":
            return {"sha": "d" * 40}
        if path == "/pulls/45":
            return copy.deepcopy(self.record)
        if path.startswith("/actions/workflows/ci.yml/runs?"):
            return {"workflow_runs": [{"head_sha": self.head}]}
        return None
