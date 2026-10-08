"""Pure policy/argv regressions: no project tests, models, Node or servers run."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import verification_scope as policy

with patch.dict(sys.modules, {"verification_scope": policy}):
    runner = importlib.import_module("tools.run_verification_scope")

BASE = "a" * 40
MANIFEST = ".github/verification_scope.json"


class ScopeFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-scope-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repository"
        self.root.mkdir()
        for name in (
            "README.md",
            "src/feature.py",
            "tests/test_alpha.py",
            "tests/test_beta.py",
            "tests/test_gamma.py",
            "frontend/tests/alpha.test.ts",
            "frontend/tests/beta.test.tsx",
            "frontend/tests/gamma.test.ts",
            "frontend/e2e/alpha.spec.ts",
            "frontend/e2e/beta.spec.ts",
            "frontend/e2e/gamma.spec.ts",
        ):
            self.write(name)
        self.plan = {
            "schema_version": 1,
            "base_sha": BASE,
            "changed_paths": ["src/feature.py"],
            "python_modules": ["tests.test_alpha"],
            "frontend_tests": [],
            "browser_tests": [],
        }
        self.changes = {"src/feature.py": "M"}

    def write(self, name, content=""):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def validate(self, changes=None, **updates):
        return policy.validate_scope(
            self.plan | updates,
            root=self.root,
            expected_base=BASE,
            changes=self.changes if changes is None else changes,
        )


class ScopeSchemaTests(ScopeFixture):
    def test_valid_python_only_scope(self):
        scope = self.validate()
        self.assertEqual(scope.python_modules, ("tests.test_alpha",))
        self.assertEqual(scope.changed_python, ("src/feature.py",))
        self.assertEqual(scope.frontend_tests, ())
        self.assertEqual(scope.browser_tests, ())

    def test_unknown_missing_fields_and_non_object_are_rejected(self):
        invalid = [[], None, self.plan | {"fallback": True}]
        invalid.extend(
            {key: value for key, value in self.plan.items() if key != missing}
            for missing in self.plan
        )
        for plan in invalid:
            with self.subTest(plan=plan), self.assertRaisesRegex(ValueError, "six"):
                policy.validate_scope(
                    plan,
                    root=self.root,
                    expected_base=BASE,
                    changes=self.changes,
                )

    def test_version_requires_exact_integer_one(self):
        for value in (True, False, 1.0, "1", 0, 2, None):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "integer 1"),
            ):
                self.validate(schema_version=value)

    def test_stale_and_wrong_type_manifest_base_are_rejected(self):
        for base in ("b" * 40, BASE.upper(), "HEAD", 1, None):
            with (
                self.subTest(base=base),
                self.assertRaisesRegex(ValueError, "base_sha"),
            ):
                self.validate(base_sha=base)

    def test_expected_base_must_be_safe_full_sha(self):
        for base in ("", "HEAD", "-x", "a" * 39, "a" * 41, "G" * 40):
            with self.subTest(base=base), self.assertRaisesRegex(ValueError, "Git SHA"):
                policy.validate_scope(
                    self.plan,
                    root=self.root,
                    expected_base=base,
                    changes=self.changes,
                )

    def test_list_types_elements_lengths_and_duplicates_are_rejected(self):
        for field in (
            "changed_paths",
            "python_modules",
            "frontend_tests",
            "browser_tests",
        ):
            for value in (
                None,
                {},
                "tests.test_alpha",
                [1],
                [True],
                [None],
                [[]],
                [""],
                ["a" * 241],
                ["same", "same"],
            ):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ValueError),
                ):
                    self.validate(**{field: value})

    def test_each_test_category_rejects_over_32(self):
        for field in policy.TESTS:
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "at most 32"),
            ):
                self.validate(**{field: [f"test_{index}" for index in range(33)]})

    def test_each_test_category_accepts_exactly_32(self):
        selections = {
            "python_modules": [
                f"tests.test_alpha.Case.method_{index}" for index in range(32)
            ],
            "frontend_tests": [
                f"frontend/tests/item-{index}.test.ts" for index in range(32)
            ],
            "browser_tests": [
                f"frontend/e2e/item-{index}.spec.ts" for index in range(32)
            ],
        }
        for field in ("frontend_tests", "browser_tests"):
            for name in selections[field]:
                self.write(name)
        scope = self.validate(**selections)
        for field in selections:
            self.assertEqual(len(getattr(scope, field)), 32)

    def test_changed_paths_limit_is_256(self):
        with self.assertRaisesRegex(ValueError, "at most 256"):
            self.validate(changed_paths=[f"file-{index}" for index in range(257)])

    def test_exact_changed_set_is_required_and_order_is_not(self):
        changes = self.changes | {"README.md": "M"}
        self.validate(changes=changes, changed_paths=["README.md", "src/feature.py"])
        for paths in (
            ["src/feature.py"],
            ["README.md"],
            ["src/feature.py", "tests/test_alpha.py"],
        ):
            with (
                self.subTest(paths=paths),
                self.assertRaisesRegex(ValueError, "differs from Git"),
            ):
                self.validate(changes=changes, changed_paths=paths)

    def test_python_changes_including_deletion_require_python_tests(self):
        for name, status in (("src/feature.py", "M"), ("src/deleted.py", "D")):
            with (
                self.subTest(status=status),
                self.assertRaisesRegex(ValueError, "nonempty"),
            ):
                self.validate(
                    changes={name: status}, changed_paths=[name], python_modules=[]
                )

    def test_non_python_and_empty_diffs_can_have_no_tests(self):
        self.validate(
            changes={"README.md": "M"}, changed_paths=["README.md"], python_modules=[]
        )
        self.validate(changes={}, changed_paths=[], python_modules=[])

    def test_unknown_git_status_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Unsupported Git"):
            self.validate(changes={"src/feature.py": "U"})


class ScopePathTests(ScopeFixture):
    def test_unsafe_changed_paths_are_rejected_even_when_deleted(self):
        paths = (
            "../outside.py",
            "/tmp/a.py",
            "C:/a.py",
            "src\\a.py",
            "src/../a.py",
            "src/./a.py",
            "src//a.py",
            "src/",
            "src/a*.py",
            "src/a?.py",
            "src/a[0].py",
            "src/a b.py",
            "src/a\n.py",
            "src/\x00a.py",
            "-option.py",
            "src/-option.py",
        )
        for name in paths:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsafe"):
                self.validate(changes={name: "D"}, changed_paths=[name])

    def test_missing_existing_source_and_directory_are_rejected(self):
        for name in ("src/missing.py", "src"):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "missing or not regular"),
            ):
                self.validate(changes={name: "M"}, changed_paths=[name])

    def test_deleted_python_path_is_valid_and_not_linted(self):
        changes = self.changes | {"src/deleted.py": "D"}
        scope = self.validate(changes=changes, changed_paths=list(changes))
        self.assertEqual(scope.changed_python, ("src/feature.py",))

    def test_rename_inventory_contains_both_old_and_new_names(self):
        self.write("src/renamed.py")
        changes = {"src/old.py": "D", "src/renamed.py": "A"}
        scope = self.validate(changes=changes, changed_paths=list(changes))
        self.assertEqual(scope.changed_python, ("src/renamed.py",))

    def test_source_file_and_deleted_parent_symlinks_are_rejected(self):
        (self.root / "src/link.py").symlink_to(self.root / "src/feature.py")
        (self.root / "outside").symlink_to(self.root.parent, target_is_directory=True)
        for name, status in (("src/link.py", "M"), ("outside/deleted.py", "D")):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "Symbolic link"),
            ):
                self.validate(changes={name: status}, changed_paths=[name])

    def test_symlink_root_and_test_files_are_rejected(self):
        alias = self.root.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symbolic link"):
            policy.safe_file(alias, "README.md")
        (self.root / "tests/test_link.py").symlink_to(self.root / "tests/test_alpha.py")
        with self.assertRaisesRegex(ValueError, "Symbolic link"):
            self.validate(python_modules=["tests.test_link"])

    def test_python_module_class_and_method_names(self):
        for name in (
            "tests.test_alpha",
            "tests.test_alpha.Case",
            "tests.test_alpha.Case.test_one",
        ):
            self.validate(python_modules=[name])
        for name in (
            "tests",
            "discover",
            "test_alpha",
            "tests.test_*",
            "tests.test_alpha.Case.method.extra",
            "tests.test_alpha.-option",
            "tests/test_alpha.py",
            "tests.test_alpha;exit",
            "unittest",
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsafe"):
                self.validate(python_modules=[name])

    def test_missing_test_files_fail_in_all_categories(self):
        for field, name in (
            ("python_modules", "tests.test_missing"),
            ("frontend_tests", "frontend/tests/missing.test.ts"),
            ("browser_tests", "frontend/e2e/missing.spec.ts"),
        ):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "missing"),
            ):
                self.validate(**{field: [name]})

    def test_all_test_files_cannot_be_selected_in_any_category(self):
        self.write("frontend/tests/unused.test.ts.bak")
        self.write("frontend/e2e/unused.spec.txt")
        selections = {
            "python_modules": [
                f"tests.test_{name}.Case.test_one"
                for name in ("alpha", "beta", "gamma")
            ],
            "frontend_tests": [
                "frontend/tests/alpha.test.ts",
                "frontend/tests/beta.test.tsx",
                "frontend/tests/gamma.test.ts",
            ],
            "browser_tests": [
                f"frontend/e2e/{name}.spec.ts" for name in ("alpha", "beta", "gamma")
            ],
        }
        for field, names in selections.items():
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "all existing"),
            ):
                self.validate(**{field: names})

    def test_overlapping_python_selections_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            self.validate(python_modules=["tests.test_alpha", "tests.test_alpha.Case"])

    def test_frontend_and_browser_reject_wrong_directories_and_patterns(self):
        for field, names in {
            "frontend_tests": (
                "frontend/tests",
                "frontend/**/*.test.ts",
                "frontend/e2e/alpha.spec.ts",
                "frontend/tests/alpha.test.js",
            ),
            "browser_tests": (
                "frontend/e2e",
                "frontend/e2e/*.spec.ts",
                "frontend/tests/alpha.test.ts",
                "frontend/e2e/alpha.spec.ts$",
            ),
        }.items():
            for name in names:
                with (
                    self.subTest(field=field, name=name),
                    self.assertRaises(ValueError),
                ):
                    self.validate(**{field: [name]})

    def test_vitest_substring_and_case_collisions_are_rejected(self):
        self.write("frontend/tests/alpha.test.tsx")
        self.write("frontend/tests/ALPHA.test.ts")
        with self.assertRaisesRegex(ValueError, "Ambiguous Vitest"):
            self.validate(frontend_tests=["frontend/tests/alpha.test.ts"])
        self.validate(
            frontend_tests=[
                "frontend/tests/alpha.test.ts",
                "frontend/tests/alpha.test.tsx",
                "frontend/tests/ALPHA.test.ts",
            ]
        )


class ScopeRunnerTests(ScopeFixture):
    def test_python_argv_is_explicit_and_ruff_only_sees_existing_changes(self):
        changes = self.changes | {"src/deleted.py": "D", "README.md": "M"}
        scope = self.validate(changes=changes, changed_paths=list(changes))
        commands = runner.phase_commands(scope, "python", self.root)
        self.assertEqual(
            commands,
            [
                (self.root, [sys.executable, "-m", "ruff", "check", "src/feature.py"]),
                (
                    self.root,
                    [
                        sys.executable,
                        "-m",
                        "ruff",
                        "format",
                        "--check",
                        "src/feature.py",
                    ],
                ),
                (
                    self.root,
                    [sys.executable, "-m", "unittest", "-v", "tests.test_alpha"],
                ),
            ],
        )

    def test_frontend_argv_uses_absolute_explicit_files_and_one_worker(self):
        scope = self.validate(frontend_tests=["frontend/tests/alpha.test.ts"])
        cwd, command = runner.phase_commands(scope, "frontend", self.root)[0]
        self.assertEqual(cwd, self.root / "frontend")
        self.assertEqual(
            command[1:],
            ["run", "--maxWorkers=1", str(self.root / scope.frontend_tests[0])],
        )
        self.assertTrue(command[0].endswith("node_modules/.bin/vitest"))

    def test_frontend_static_checks_only_existing_changed_ts_js_css(self):
        sources = (
            "frontend/src/changed.tsx",
            "frontend/src/changed.mjs",
            "frontend/src/changed.css",
            "frontend/e2e/changed.spec.ts",
            "frontend/src/unchanged.js",
            "frontend/data.json",
            "other.js",
        )
        for name in sources:
            self.write(name)
        changed = sources[:4] + (
            "frontend/data.json",
            "other.js",
            "frontend/deleted.ts",
        )
        changes = {name: "M" for name in changed}
        changes["frontend/deleted.ts"] = "D"
        scope = self.validate(
            changes=changes, changed_paths=list(changes), python_modules=[]
        )
        commands = runner.phase_commands(scope, "frontend", self.root)
        self.assertEqual(len(commands), 2)
        for cwd, command in commands:
            self.assertEqual(cwd, self.root / "frontend")
            self.assertNotIn("vitest", command[0])
            self.assertNotIn("playwright", command[0])
        prettier, oxlint = (command for _, command in commands)
        self.assertTrue(prettier[0].endswith("node_modules/.bin/prettier"))
        self.assertEqual(
            prettier[1:], ["--check", *[str(self.root / name) for name in sources[:4]]]
        )
        self.assertTrue(oxlint[0].endswith("node_modules/.bin/oxlint"))
        self.assertEqual(
            oxlint[1:],
            [
                "--deny-warnings",
                *[
                    str(self.root / name)
                    for name in sources[:4]
                    if not name.endswith(".css")
                ],
            ],
        )
        self.assertEqual(runner.phase_commands(scope, "browser", self.root), [])

    def test_css_only_changes_do_not_invoke_oxlint_or_test_tools(self):
        name = "frontend/src/changed.css"
        self.write(name)
        scope = self.validate(
            changes={name: "M"}, changed_paths=[name], python_modules=[]
        )
        commands = runner.phase_commands(scope, "frontend", self.root)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][1][1:], ["--check", str(self.root / name)])
        self.assertTrue(commands[0][1][0].endswith("node_modules/.bin/prettier"))

    def test_static_checks_precede_explicit_vitest_selection(self):
        name = "frontend/tests/alpha.test.ts"
        scope = self.validate(
            changes={name: "M"},
            changed_paths=[name],
            python_modules=[],
            frontend_tests=[name],
        )
        commands = runner.phase_commands(scope, "frontend", self.root)
        self.assertEqual(
            [Path(command[0]).name for _, command in commands],
            ["prettier", "oxlint", "vitest"],
        )
        self.assertEqual(
            commands[-1][1][1:], ["run", "--maxWorkers=1", str(self.root / name)]
        )

    def test_browser_argv_is_escaped_anchored_and_one_worker(self):
        scope = self.validate(browser_tests=["frontend/e2e/alpha.spec.ts"])
        cwd, command = runner.phase_commands(scope, "browser", self.root)[0]
        selected = str(self.root / scope.browser_tests[0])
        self.assertEqual(cwd, self.root / "frontend")
        self.assertEqual(command[1:3], ["test", "--workers=1"])
        self.assertEqual(command[3], "^" + re.escape(selected) + "$")
        self.assertIsNotNone(re.fullmatch(command[3], selected))
        self.assertIsNone(re.search(command[3], selected + "x"))
        self.assertIsNone(re.search(command[3], selected.replace(".spec", "Xspec")))

    def test_empty_phases_never_invoke_any_test_or_lint_tool(self):
        scope = self.validate(changes={}, changed_paths=[], python_modules=[])
        for phase in ("validate", "python", "frontend", "browser"):
            with (
                self.subTest(phase=phase),
                patch.object(runner, "load_scope", return_value=scope),
                patch.object(runner.subprocess, "run") as execute,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(runner.main(["--base", BASE, "--phase", phase]), 0)
                execute.assert_not_called()

    def test_validate_outputs_browser_count_without_running_tools(self):
        scope = self.validate()
        output = io.StringIO()
        with (
            patch.object(runner, "load_scope", return_value=scope),
            patch.object(runner.subprocess, "run") as execute,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(runner.main(["--base", BASE]), 0)
        self.assertEqual(
            output.getvalue(), "python_count=1\nfrontend_count=0\nbrowser_count=0\n"
        )
        execute.assert_not_called()

    def test_main_runs_safe_argv_and_python_environment(self):
        scope = self.validate()
        with (
            patch.object(runner, "load_scope", return_value=scope),
            patch.object(runner.subprocess, "run") as execute,
        ):
            self.assertEqual(runner.main(["--base", BASE, "--phase", "python"]), 0)
        self.assertEqual(execute.call_count, 3)
        for call in execute.call_args_list:
            self.assertIsInstance(call.args[0], list)
            self.assertNotIn("shell", call.kwargs)
            self.assertTrue(call.kwargs["check"])
            self.assertEqual(call.kwargs["timeout"], 1200)
            self.assertEqual(
                call.kwargs["env"]["PYTHONPATH"],
                os.pathsep.join(str(runner.ROOT / name) for name in ("src", "tests")),
            )

    def test_env_base_and_explicit_base_override(self):
        scope = self.validate()
        for arguments, expected in (([], "b" * 40), (["--base", BASE], BASE)):
            with (
                self.subTest(arguments=arguments),
                patch.dict(os.environ, {"PATENTSAR_CI_BASE": "b" * 40}),
                patch.object(runner, "load_scope", return_value=scope) as load,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(runner.main(arguments), 0)
                load.assert_called_once_with(runner.ROOT, MANIFEST, expected)

    def test_missing_invalid_base_and_scope_failure_never_run_tests(self):
        for arguments in ([], ["--base", "HEAD"], ["--base", BASE]):
            with (
                self.subTest(arguments=arguments),
                patch.dict(os.environ, {}, clear=True),
                patch.object(
                    runner, "load_scope", side_effect=ValueError("stale scope")
                ),
                patch.object(runner.subprocess, "run") as execute,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(runner.main(arguments), 2)
                execute.assert_not_called()

    def test_test_failure_is_nonzero_and_not_retried(self):
        scope = self.validate()
        error = subprocess.CalledProcessError(1, ["ruff"])
        with (
            patch.object(runner, "load_scope", return_value=scope),
            patch.object(runner.subprocess, "run", side_effect=error) as execute,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(runner.main(["--base", BASE, "--phase", "python"]), 2)
            self.assertEqual(execute.call_count, 1)

    def test_unknown_phase_has_no_fallback(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            runner.phase_commands(self.validate(), "all", self.root)


class ScopeGitAndManifestTests(ScopeFixture):
    def test_git_inventory_is_nul_delimited_and_renames_are_disabled(self):
        raw = (
            ":100644 000000 aaaaaaa 0000000 D\0src/old.py\0"
            ":000000 100755 0000000 bbbbbbb A\0src/new.py\0"
            ":100644 100644 aaaaaaa bbbbbbb M\0README.md\0"
        )
        with patch.object(runner, "_git", side_effect=["", "", raw]) as git:
            self.assertEqual(
                runner.git_changes(self.root, BASE),
                {"src/old.py": "D", "src/new.py": "A", "README.md": "M"},
            )
        diff = git.call_args_list[-1].args
        self.assertIn("--no-renames", diff)
        self.assertIn("--raw", diff)
        self.assertIn("--no-ext-diff", diff)
        self.assertIn("--no-textconv", diff)
        self.assertEqual(diff[-3:], (BASE, "HEAD", "--"))

    def test_empty_git_diff_is_supported(self):
        with patch.object(runner, "_git", return_value=""):
            self.assertEqual(runner.git_changes(self.root, BASE), {})

    def test_malformed_or_duplicate_git_inventory_is_rejected(self):
        for raw in (
            "M\0src/feature.py",
            "M\0",
            "M\0src/feature.py\0",
            (
                ":100644 100644 aaaaaaa bbbbbbb M\0src/feature.py\0"
                ":100644 100644 aaaaaaa bbbbbbb M\0src/feature.py\0"
            ),
        ):
            with (
                self.subTest(raw=raw),
                patch.object(runner, "_git", side_effect=["", "", raw]),
                self.assertRaises(ValueError),
            ):
                runner.git_changes(self.root, BASE)

    def test_git_modes_reject_deleted_links_and_submodules_without_disk_files(self):
        for old, new, status in (
            ("120000", "000000", "D"),
            ("160000", "000000", "D"),
            ("100644", "120000", "T"),
            ("000000", "120000", "A"),
        ):
            raw = f":{old} {new} aaaaaaa bbbbbbb {status}\0src/link.py\0"
            with (
                self.subTest(old=old, new=new),
                patch.object(runner, "_git", side_effect=["", "", raw]),
                self.assertRaisesRegex(ValueError, "non-regular"),
            ):
                runner.git_changes(self.root, BASE)

    def test_unavailable_base_fails_without_fetch_or_widening(self):
        error = subprocess.CalledProcessError(1, ["git", "cat-file"])
        with (
            patch.object(runner, "_git", side_effect=error) as git,
            self.assertRaisesRegex(ValueError, "never widened"),
        ):
            runner.git_changes(self.root, BASE)
        self.assertEqual(git.call_count, 1)

    def test_git_subprocess_is_an_argv_list_with_timeout(self):
        with patch.object(
            runner.subprocess, "check_output", return_value="result"
        ) as execute:
            self.assertEqual(runner._git(self.root, "diff", BASE, "HEAD"), "result")
        self.assertEqual(execute.call_args.args[0], ["git", "diff", BASE, "HEAD"])
        self.assertEqual(execute.call_args.kwargs["timeout"], 30)
        self.assertNotIn("shell", execute.call_args.kwargs)

    def test_manifest_must_exist_and_be_checked_in(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            runner.load_scope(self.root, MANIFEST, BASE)
        self.write(MANIFEST, json.dumps(self.plan))
        error = subprocess.CalledProcessError(1, ["git", "cat-file"])
        with (
            patch.object(runner, "_git", side_effect=error),
            self.assertRaisesRegex(ValueError, "checked in at HEAD"),
        ):
            runner.load_scope(self.root, MANIFEST, BASE)

    def test_valid_manifest_reads_explicit_git_facts(self):
        self.write(MANIFEST, json.dumps(self.plan))
        with (
            patch.object(runner, "_git", return_value="") as git,
            patch.object(runner, "git_changes", return_value=self.changes) as changes,
        ):
            scope = runner.load_scope(self.root, MANIFEST, BASE)
        self.assertEqual(scope.python_modules, ("tests.test_alpha",))
        self.assertEqual(
            git.call_args_list[0].args,
            (self.root, "cat-file", "-e", "HEAD:" + MANIFEST),
        )
        self.assertEqual(
            git.call_args_list[1].args,
            (
                self.root,
                "diff",
                "--quiet",
                "--no-ext-diff",
                "--no-textconv",
                "HEAD",
                "--",
                MANIFEST,
            ),
        )
        changes.assert_called_once_with(self.root, BASE)

    def test_modified_manifest_fails_before_reading_or_executing_plan(self):
        self.write(
            MANIFEST, json.dumps(self.plan | {"python_modules": ["tests.test_beta"]})
        )
        error = subprocess.CalledProcessError(1, ["git", "diff", "--quiet"])
        with (
            patch.object(runner, "ROOT", self.root),
            patch.object(runner, "_git", side_effect=["", error]) as git,
            patch.object(Path, "open") as read,
            patch.object(runner, "git_changes") as changes,
            patch.object(runner.subprocess, "run") as execute,
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            self.assertEqual(runner.main(["--base", BASE, "--phase", "python"]), 2)
            read.assert_not_called()
            changes.assert_not_called()
            execute.assert_not_called()
        self.assertIn("unmodified", errors.getvalue())
        self.assertEqual(
            git.call_args_list[1].args,
            (
                self.root,
                "diff",
                "--quiet",
                "--no-ext-diff",
                "--no-textconv",
                "HEAD",
                "--",
                MANIFEST,
            ),
        )

    def test_duplicate_json_fields_and_malformed_json_fail_closed(self):
        for raw in ('{"schema_version":1,"schema_version":1}', "{broken", "\ufeff{}"):
            self.write(MANIFEST, raw)
            with (
                self.subTest(raw=raw),
                patch.object(runner, "_git", return_value=""),
                self.assertRaises(ValueError),
            ):
                runner.load_scope(self.root, MANIFEST, BASE)

    def test_overlarge_manifest_is_rejected_before_parsing(self):
        self.write(MANIFEST, " " * 65537)
        with (
            patch.object(runner, "_git", return_value="") as git,
            patch.object(runner.json, "loads") as parse,
            self.assertRaisesRegex(ValueError, "64 KiB"),
        ):
            runner.load_scope(self.root, MANIFEST, BASE)
        self.assertEqual(git.call_count, 2)
        parse.assert_not_called()


class ScopeWorkflowTests(unittest.TestCase):
    def test_workflow_uses_scopes_and_preserves_build_gates(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for forbidden in (
            "unittest discover",
            "npm run test",
            "npm run e2e",
            "npm run lint",
            "npm run format:check",
            "compileall",
            "continue-on-error",
            "[skip ci]",
        ):
            self.assertNotIn(forbidden, workflow)
        for required in (
            "PATENTSAR_CI_BASE:",
            "github.event.pull_request.base.sha || github.event.before",
            "fetch-depth: 2",
            "id: scope",
            '>> "$GITHUB_OUTPUT"',
            "--phase python",
            "--phase frontend",
            "--phase browser",
            "uv sync --frozen --extra web",
            "tools/build_environment_resources.py --check",
            "npm run build",
            "tools/build_wheel.py --work-root",
            "tools/audit_wheel.py",
        ):
            self.assertIn(required, workflow)
        self.assertEqual(
            workflow.count("if: steps.scope.outputs.browser_count != '0'"), 3
        )
        self.assertRegex(
            workflow, r"(?m)^  push:\n    branches: \[main\]\n  pull_request:"
        )


if __name__ == "__main__":
    unittest.main()
