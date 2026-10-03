"""Owned Linux process supervision, including observed detached descendants."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from patent_sar_extractor.contracts import (
    pipeline_contract_ref,
    product_ref,
    ruleset_ref,
)

from .errors import WebError
from .files import private_directory


@dataclass(frozen=True)
class RunSpec:
    job_id: str
    project_id: str
    pdf_path: str
    output_dir: str
    patent_id: str
    sha256: str
    allow_partial: bool = False
    advisory: bool = False
    include_intermediates: bool = False
    force: bool = False
    task_note: str = ""
    source_ocr_cache: str = ""
    include_admet: bool = False
    admet_only: bool = False
    admet_compounds: tuple[str, ...] = ()


@dataclass
class ProcessIdentity:
    pid: int
    start_ticks: int
    boot_id: str
    pgid: int
    argv: list[str]
    cwd: str
    executable: str
    descendants: list[dict[str, Any]] = field(default_factory=list)
    phase: str = "extract"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProcessRunner(Protocol):
    def start(self, spec: RunSpec) -> ProcessIdentity: ...
    def poll(self, identity: ProcessIdentity, spec: RunSpec) -> int | None: ...
    def owns(self, identity: ProcessIdentity, spec: RunSpec) -> bool: ...
    def stop(
        self, identity: ProcessIdentity, spec: RunSpec, *, grace_seconds: float = 2
    ) -> bool: ...


def runtime_identity() -> dict[str, object]:
    return {
        "product": product_ref(),
        "pipeline_contract": pipeline_contract_ref(),
        "ruleset": ruleset_ref(),
    }


def _process(pid: int) -> dict[str, Any] | None:
    try:
        root = Path("/proc") / str(pid)
        if root.stat().st_uid != os.getuid():
            return None
        fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
        return {
            "pid": pid,
            "ppid": int(fields[1]),
            "pgid": int(fields[2]),
            "start_ticks": int(fields[19]),
            "state": fields[0],
            "argv": (root / "cmdline")
            .read_bytes()
            .decode(errors="replace")
            .rstrip("\0")
            .split("\0"),
            "cwd": os.readlink(root / "cwd"),
            "executable": os.readlink(root / "exe"),
        }
    except (OSError, ValueError, IndexError):
        return None


def _same(raw: dict[str, Any] | None, saved: dict[str, Any]) -> bool:
    return bool(
        raw
        and all(
            raw.get(k) == saved.get(k)
            for k in ("pid", "pgid", "start_ticks", "argv", "cwd", "executable")
        )
    )


class SubprocessRunner:
    """Inject by subclassing command(); supervision itself always uses real processes."""

    def __init__(self) -> None:
        self._children: dict[int, subprocess.Popen[bytes]] = {}
        self._log_threads: dict[int, threading.Thread] = {}
        self.boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()

    def command(self, spec: RunSpec) -> list[str]:
        raise NotImplementedError

    def environment(self, spec: RunSpec) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "CUDA_VISIBLE_DEVICES": "-1",
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "TF_NUM_INTRAOP_THREADS": "1",
                "TF_NUM_INTEROP_THREADS": "1",
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        return env

    def start(self, spec: RunSpec) -> ProcessIdentity:
        output = private_directory(Path(spec.output_dir))
        command = self.command(spec)
        log_path = output / "web-process.log"
        fd = os.open(
            log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
        )
        try:
            child = subprocess.Popen(
                command,
                cwd=output,
                env=self.environment(spec),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except BaseException:
            os.close(fd)
            raise
        self._children[child.pid] = child
        raw = _process(child.pid)
        if raw is None:
            # Child is still our direct unreaped Popen; no arbitrary PID is signalled.
            child.terminate()
            child.wait(timeout=5)
            os.close(fd)
            raise WebError(
                500,
                "process_identity",
                "Could not establish extraction process ownership.",
            )
        identity = ProcessIdentity(
            child.pid,
            raw["start_ticks"],
            self.boot_id,
            child.pid,
            command,
            str(output),
            str(Path(command[0]).resolve()),
        )
        thread = threading.Thread(
            target=self._drain_log,
            args=(child, fd),
            daemon=True,
            name=f"patentsar-log-{spec.job_id}",
        )
        self._log_threads[child.pid] = thread
        thread.start()
        return identity

    @staticmethod
    def _drain_log(child: subprocess.Popen[bytes], fd: int) -> None:
        assert child.stdout is not None
        try:
            with os.fdopen(fd, "ab", buffering=0) as log:
                remaining = max(0, 8 * 1024 * 1024 - os.fstat(log.fileno()).st_size)
                # Buffered read(n) can wait for n bytes or EOF, hiding short
                # live installation/job logs for minutes. Drain each available
                # pipe chunk immediately while retaining the same size bound.
                while chunk := os.read(child.stdout.fileno(), 65536):
                    if remaining:
                        log.write(chunk[:remaining])
                        remaining = max(0, remaining - len(chunk))
        finally:
            child.stdout.close()

    def owns(self, identity: ProcessIdentity, spec: RunSpec) -> bool:
        return (
            identity.boot_id == self.boot_id
            and identity.pgid == identity.pid
            and identity.cwd == str(Path(spec.output_dir).resolve())
            and identity.argv == self.command(spec)
            and _same(_process(identity.pid), identity.to_dict())
        )

    def _observe(self, identity: ProcessIdentity, spec: RunSpec) -> None:
        if not self.owns(identity, spec):
            return
        # Traverse kernel parent links, not process names or TensorFlow patterns.
        parents = {}
        for entry in Path("/proc").iterdir():
            if entry.name.isdecimal():
                try:
                    if entry.stat().st_uid == os.getuid():
                        fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                        parents[int(entry.name)] = int(fields[1])
                except (OSError, ValueError, IndexError):
                    continue  # Kernel process exited during this read-only scan.
        owned = {identity.pid}
        for _ in range(64):
            found = {pid for pid, parent in parents.items() if parent in owned} - owned
            if not found:
                break
            owned.update(found)
            if len(owned) > 256:
                raise WebError(
                    500, "process_limit", "Extraction exceeded its owned process limit."
                )
        saved = {
            d["pid"]: d for d in identity.descendants if _same(_process(d["pid"]), d)
        }
        for pid in owned - {identity.pid}:
            raw = _process(pid)
            if raw:
                saved[pid] = raw
        identity.descendants = list(saved.values())

    def poll(self, identity: ProcessIdentity, spec: RunSpec) -> int | None:
        self._observe(identity, spec)
        child = self._children.get(identity.pid)
        if child is not None:
            return child.poll()
        return None if self.owns(identity, spec) else -1

    def stop(
        self, identity: ProcessIdentity, spec: RunSpec, *, grace_seconds: float = 2
    ) -> bool:
        if (
            identity.boot_id != self.boot_id
            or identity.argv != self.command(spec)
            or identity.cwd != str(Path(spec.output_dir).resolve())
        ):
            return False
        self._observe(identity, spec)
        child = self._children.get(identity.pid)
        if child is not None:
            child.poll()  # Reap only our own direct child if it already exited.
        root_owned = self.owns(identity, spec)
        root_present = _process(identity.pid) is not None
        if root_present and not root_owned:
            return False
        targets = [d for d in identity.descendants if _same(_process(d["pid"]), d)]
        # Never broaden a signal to a group unless its live leader is verified.
        if root_owned:
            try:
                os.killpg(identity.pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for target in reversed(targets):
            if _same(_process(target["pid"]), target):
                try:
                    os.kill(target["pid"], signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + min(max(grace_seconds, 0), 5)
        while time.monotonic() < deadline:
            if not self.owns(identity, spec) and not any(
                _same(_process(t["pid"]), t) for t in targets
            ):
                break
            time.sleep(0.05)
        if self.owns(identity, spec):
            try:
                os.killpg(identity.pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for target in targets:
            if _same(_process(target["pid"]), target):
                try:
                    os.kill(target["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
        child = self._children.pop(identity.pid, None)
        if child is not None:
            child.wait(timeout=5)
        thread = self._log_threads.pop(identity.pid, None)
        if thread is not None:
            thread.join(timeout=1)
        return not self.owns(identity, spec) and not any(
            _same(_process(t["pid"]), t) for t in targets
        )


class CLIProcessRunner(SubprocessRunner):
    def command(self, spec: RunSpec) -> list[str]:
        if spec.admet_only:
            return [
                sys.executable,
                "-m",
                "patent_sar_extractor.web.prediction_worker",
                "--state-dir",
                str(Path(spec.output_dir).parents[2]),
                "--job-id",
                spec.job_id,
            ]
        command = [
            sys.executable,
            "-m",
            "patent_sar_extractor",
            "run",
            "--pdf",
            spec.pdf_path,
            "--output",
            spec.output_dir,
            "--patent-id",
            spec.patent_id,
            "--gpu-mode",
            "off",
            "--locate-workers",
            "1",
            "--bind-workers",
            "1",
            "--smiles-workers",
            "1",
        ]
        if spec.allow_partial:
            command.append("--allow-partial")
        if not spec.advisory:
            command.append("--skip-advisory-qa")
        if spec.include_intermediates:
            command.append("--include-intermediates")
        if spec.force:
            command.append("--force")
        elif spec.source_ocr_cache:
            command.extend(["--reuse-ocr-cache", spec.source_ocr_cache])
        return command

    def environment(self, spec: RunSpec) -> dict[str, str]:
        env = super().environment(spec)
        from patent_sar_extractor.core.env_runner import captured_runtime_environment

        env.update(captured_runtime_environment())
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        # Advisory opt-in is explicit. There is no fallback that omits the CLI
        # opt-out flag if an old CLI rejects it; such a job genuinely fails.
        return env
