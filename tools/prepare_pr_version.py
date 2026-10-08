"""Trusted-main automation: data-only PR version edits followed by read-only CI."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pr_version import git, require_sha, source_at
from tools.release_github import GitHub
from tools.release_scope import SCOPE, prepare_scope
from tools.version_policy import (
    AUTHORITY,
    VERSION_PATHS,
    authority_version,
    prepare_versions,
)


def open_pull(api: GitHub, event: dict) -> dict | None:
    """Resolve current server facts, not untrusted run artifacts or shell inputs."""
    inputs = event.get("inputs") or {}
    if "pr_number" in inputs:
        number = str(inputs["pr_number"])
        if re.fullmatch(r"[1-9][0-9]{0,8}", number) is None:
            raise ValueError("A positive PR number is required")
        return api.call("GET", "/pulls/" + number)
    run = event.get("workflow_run") or {}
    if run.get("event") not in {"pull_request", "workflow_dispatch"}:
        return None
    if (run.get("head_repository") or {}).get("full_name") != api.repository:
        return (
            None  # Forks retain the explicit local preparation path; never write them.
        )
    branch = run.get("head_branch")
    if not isinstance(branch, str) or len(branch) > 200:
        raise ValueError("CI run lacks a bounded source branch")
    owner = api.repository.split("/")[0]
    pulls = api.call(
        "GET",
        "/pulls?state=open&base=main&head="
        + quote(owner + ":" + branch, safe="")
        + "&per_page=2",
    )
    if not isinstance(pulls, list) or len(pulls) > 1:
        raise ValueError("CI run does not identify one open PR")
    return api.call("GET", f"/pulls/{pulls[0]['number']}") if pulls else None


def validate_pull(api: GitHub, pull: dict, base: str) -> tuple[int, str, str] | None:
    if pull.get("state") != "open" or pull.get("merged") is True:
        return None
    if (pull.get("base") or {}).get("ref") != "main":
        raise ValueError("Automatic product releases target main only")
    if (pull.get("head", {}).get("repo") or {}).get("full_name") != api.repository:
        raise ValueError(
            "Fork PRs must prepare metadata locally; no privileged fork writes"
        )
    if (pull.get("base", {}).get("repo") or {}).get("full_name") != api.repository:
        raise ValueError("PR belongs to a foreign base repository")
    number = pull.get("number")
    if type(number) is not int or not 1 <= number <= 999999999:
        raise ValueError("Invalid PR identity")
    head = require_sha(pull["head"]["sha"])
    branch = pull["head"]["ref"]
    if (
        not isinstance(branch, str)
        or re.fullmatch(r"[A-Za-z0-9_./-]{1,200}", branch) is None
        or branch == "main"
    ):
        raise ValueError("Invalid PR branch")
    if pull["base"]["sha"] != base:
        raise ValueError("Main advanced; rerun against a fresh trusted-main checkout")
    return number, head, branch


def ensure_ci(api: GitHub, head: str, branch: str, base: str) -> None:
    """Recover a missing dispatch, never loop over a known failed CI run."""
    runs = api.call(
        "GET", f"/actions/workflows/ci.yml/runs?head_sha={head}&per_page=10"
    )["workflow_runs"]
    if any(run.get("head_sha") == head for run in runs):
        return
    api.call(
        "POST",
        "/actions/workflows/ci.yml/dispatches",
        {"ref": branch, "inputs": {"base_sha": base}},
    )


def publish(api: GitHub, root: Path, pull: dict) -> None:
    base = require_sha(api.call("GET", "/git/ref/heads/main")["object"]["sha"])
    if git(root, "rev-parse", "HEAD").decode().strip() != base:
        raise ValueError("Automation must execute an exact trusted-main checkout")
    identity = validate_pull(api, pull, base)
    if identity is None:
        print("PR is closed; no release update.")
        return
    number, head, branch = identity
    git(root, "check-ref-format", "--branch", branch)
    # Fetch objects only: never checkout, import, build or execute PR source.
    git(root, "fetch", "--no-tags", "origin", f"refs/pull/{number}/head")
    if git(root, "rev-parse", "FETCH_HEAD").decode().strip() != head:
        raise ValueError("PR changed while reading; rerun from current state")
    try:
        git(root, "merge-base", "--is-ancestor", base, head)
    except subprocess.CalledProcessError:
        raise ValueError(
            "Update the PR branch to current main before preparing its version"
        ) from None
    files = {name: source_at(root, head, name) for name in VERSION_PATHS}
    changes = prepare_versions(source_at(root, base, AUTHORITY), files)
    if not changes:
        ensure_ci(api, head, branch, base)
        print(
            f"PR #{number} already prepares v{authority_version(files[AUTHORITY])}; no duplicate increment."
        )
        return
    raw_paths = git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--name-only",
        "-z",
        base,
        head,
    ).decode()
    paths = raw_paths.removesuffix("\0").split("\0") if raw_paths else []
    changes[SCOPE] = prepare_scope(
        source_at(root, head, SCOPE), base, [*paths, *changes]
    )
    parent_tree = api.call("GET", "/git/commits/" + head)["tree"]["sha"]
    entries = []
    for name, content in sorted(changes.items()):
        data = content.encode("utf-8")
        expected_blob = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        blob = api.call(
            "POST",
            "/git/blobs",
            {"content": base64.b64encode(data).decode(), "encoding": "base64"},
        )
        if blob["sha"] != expected_blob:
            raise ValueError("GitHub returned a different release blob")
        entries.append(
            {"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]}
        )
    tree = api.call("POST", "/git/trees", {"base_tree": parent_tree, "tree": entries})
    version = str(authority_version({**files, **changes}[AUTHORITY]))
    commit = api.call(
        "POST",
        "/git/commits",
        {
            "message": f"chore: prepare v{version} for PR #{number}\n\nProduct version only; scientific epochs remain independently governed.",
            "tree": tree["sha"],
            "parents": [head],
        },
    )
    revision = require_sha(commit["sha"])
    latest = api.call("GET", f"/pulls/{number}")
    if (
        validate_pull(api, latest, base) != identity
        or api.call("GET", "/git/ref/heads/main")["object"]["sha"] != base
    ):
        raise ValueError(
            "PR/main changed before publication; original branches were preserved"
        )
    path = "/git/refs/heads/" + quote(branch, safe="/")
    try:
        api.call("PATCH", path, {"sha": revision, "force": False})
    except ValueError:
        # Never blindly repeat a write with an unknown response outcome.
        observed = api.call("GET", "/git/ref/heads/" + quote(branch, safe="/"))[
            "object"
        ]["sha"]
        if observed != revision:
            raise
    ensure_ci(api, revision, branch, base)
    print(
        f"PR #{number} automatically prepared v{version} at {revision}; explicit read-only CI dispatched."
    )


def main() -> None:
    try:
        path = Path(os.environ["GITHUB_EVENT_PATH"])
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Workflow event exceeds the bounded input limit")
        event = json.loads(path.read_text(encoding="utf-8"))
        api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
        pull = open_pull(api, event)
        if pull is None:
            print("No same-repository open PR requires a release update.")
        else:
            publish(api, Path(__file__).resolve().parents[1], pull)
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        # Do not expose API responses, event bodies, credentials or PR source.
        print(
            f"Version preparation blocked: {error}. No force update or automatic retry.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
