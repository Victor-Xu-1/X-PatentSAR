"""One finite native request stream, including partial-packet idle deadlines."""

import json
import os
import selectors
import time

from patent_sar_extractor.workers.analysis_protocol import reject_constant


def request_packets(stream, *, idle_seconds=30, maximum=256):
    if (
        not 0.01 <= idle_seconds <= 30
        or type(maximum) is not int
        or not 1 <= maximum <= 256
    ):
        raise ValueError("Invalid auxiliary text OCR input limits")
    descriptor = stream.fileno()
    os.set_blocking(descriptor, False)
    buffer = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(descriptor, selectors.EVENT_READ)
        for _ in range(maximum):
            deadline = time.monotonic() + idle_seconds
            while b"\n" not in buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    if buffer:
                        raise ValueError(
                            "Auxiliary text OCR incomplete packet deadline exceeded"
                        )
                    return
                data = os.read(descriptor, 4097)
                if not data:
                    if buffer:
                        raise ValueError(
                            "Auxiliary text OCR received an incomplete packet"
                        )
                    return
                buffer.extend(data)
                if b"\n" not in buffer and len(buffer) >= 4096:
                    raise ValueError(
                        "Auxiliary text OCR input exceeds the bounded protocol"
                    )
            boundary = buffer.index(10)
            if boundary >= 4096:
                raise ValueError(
                    "Auxiliary text OCR input exceeds the bounded protocol"
                )
            packet = bytes(buffer[:boundary])
            del buffer[: boundary + 1]
            value = json.loads(packet, parse_constant=reject_constant)
            if not isinstance(value, dict):
                raise TypeError("Auxiliary text OCR requires one request object")
            yield value
