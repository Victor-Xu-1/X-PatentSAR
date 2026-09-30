"""Kernel-identity tracking of analysis-owned children only, including detached ones."""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import WebError


@dataclass(frozen=True)
class Child:
    pid: int
    parent: int
    start_ticks: int
    rss_bytes: int


def read_child(pid: int) -> Child | None:
    try:
        root = Path("/proc") / str(pid)
        if root.stat().st_uid != os.getuid():
            return None
        fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return Child(
            pid,
            int(fields[1]),
            int(fields[19]),
            int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
        )
    except (OSError, ValueError, IndexError):
        return None  # A kernel process can disappear during the read.


def alive(child: Child) -> bool:
    current = read_child(child.pid)
    return current is not None and current.start_ticks == child.start_ticks


def send(child: Child, signum: signal.Signals) -> None:
    """A pidfd prevents PID reuse between the ownership check and the signal."""
    try:
        fd = os.pidfd_open(child.pid)
    except ProcessLookupError:
        return
    try:
        if alive(child):
            signal.pidfd_send_signal(fd, signum)
    except ProcessLookupError:
        pass  # This exact owned process already exited.
    finally:
        os.close(fd)


class Children:
    def __init__(self, root: Child, max_memory_bytes: int) -> None:
        self.root = root
        self.observed: dict[int, Child] = {root.pid: root}
        self.next_observation = 0.0
        self.max_memory_bytes = max_memory_bytes

    def observe(self, *, force: bool = False) -> None:
        stamp = time.monotonic()
        if (not force and stamp < self.next_observation) or not alive(self.root):
            return
        self.next_observation = stamp + 0.1
        candidates = {}
        for item in Path("/proc").iterdir():
            if item.name.isdecimal():
                child = read_child(int(item.name))
                if child is not None:
                    candidates[child.pid] = child
                    if len(candidates) > 8192:
                        raise WebError(
                            503,
                            "analysis_process_limit",
                            "Local process inventory exceeds the analysis safety limit.",
                        )
        parents = {self.root.pid}
        for _ in range(32):
            found = {
                pid for pid, child in candidates.items() if child.parent in parents
            } - parents
            if not found:
                break
            parents.update(found)
            for pid in found:
                self.observed[pid] = candidates[pid]
            if len(self.observed) > 64:
                raise WebError(
                    503,
                    "analysis_process_limit",
                    "Analysis exceeded its owned-child limit.",
                )
        resident = sum(
            current.rss_bytes
            for child in self.observed.values()
            if (current := read_child(child.pid)) is not None
            and current.start_ticks == child.start_ticks
        )
        if resident > self.max_memory_bytes:
            raise WebError(
                503,
                "analysis_memory_limit",
                "Owned analysis exceeded its resident-memory limit and was stopped.",
            )

    def stop(self) -> None:
        targets = list(reversed(list(self.observed.values())))
        for child in targets:
            send(child, signal.SIGTERM)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and any(alive(child) for child in targets):
            time.sleep(0.02)
        for child in targets:
            send(child, signal.SIGKILL)
