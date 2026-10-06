"""Only current, live, owned resource observations may appear as waiting."""

import json
import time
from pathlib import Path

from pydantic import ValidationError

from .errors import WebError
from .files import SafeFiles
from .models import ResourceWait
from .processes import _process


def read_wait(files: SafeFiles, stage: str) -> ResourceWait | None:
    try:
        packet = json.loads(files.read("resource_wait.json", max_bytes=8192))
        if (
            not isinstance(packet, dict)
            or packet.get("schema") != {"name": "patentsar.resource-wait", "version": 1}
            or packet.get("stage") != stage
            or type(packet.get("pid")) is not int
            or type(packet.get("start_ticks")) is not int
            or type(packet.get("observed_monotonic")) not in {int, float}
            or not 0 <= time.monotonic() - packet["observed_monotonic"] <= 2
        ):
            return None
        process = _process(packet["pid"])
        if process is None or process["start_ticks"] != packet["start_ticks"]:
            return None
        # Resource writers may be isolated children; follow bounded kernel
        # ancestry back to this private attempt, never trust an arbitrary PID.
        for _ in range(16):
            if Path(process["cwd"]).resolve() == files.root.resolve():
                return ResourceWait.model_validate(packet["observation"])
            process = _process(process["ppid"])
            if process is None:
                break
    except (WebError, ValueError, TypeError, KeyError, OSError, ValidationError):
        pass  # Optional telemetry cannot imply progress or formal acceptance.
    return None
