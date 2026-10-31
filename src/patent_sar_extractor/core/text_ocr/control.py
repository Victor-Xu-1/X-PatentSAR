"""Finite worker control only; model readiness is never a text observation."""

WORKER_PROTOCOL_VERSION = 2
STARTUP_SECONDS = 60
_PREPARED_FIELDS = {
    "status",
    "id",
    "image_sha256",
    "pixel_sha256",
    "model_fingerprint",
}


def worker_ready_matches(reply, identity):
    return (
        isinstance(reply, dict)
        and set(reply) == {"status", "protocol_version", "identity"}
        and reply["status"] == "worker_ready"
        and type(reply["protocol_version"]) is int
        and reply["protocol_version"] == WORKER_PROTOCOL_VERSION
        and reply["identity"] == identity
    )


def control_packet(operation, request):
    if type(operation) is not str or operation not in {"prepare", "observe"}:
        raise ValueError("Unknown auxiliary text OCR operation")
    if not isinstance(request, dict):
        raise TypeError("Auxiliary text OCR requires an owned row request")
    return {"operation": operation, "request": dict(request)}


def parse_control(packet):
    if (
        not isinstance(packet, dict)
        or set(packet) != {"operation", "request"}
        or control_packet(packet["operation"], packet["request"]) != packet
    ):
        raise ValueError("Invalid auxiliary text OCR control packet")
    return packet["operation"], packet["request"]


def prepared_reply(request):
    return {
        "status": "model_ready",
        **{key: request[key] for key in _PREPARED_FIELDS - {"status"}},
    }


def validate_prepared(reply, request):
    if (
        not isinstance(reply, dict)
        or set(reply) != _PREPARED_FIELDS
        or reply != prepared_reply(request)
    ):
        raise ValueError("Auxiliary text OCR model preparation differs from its row")
    return dict(reply)
