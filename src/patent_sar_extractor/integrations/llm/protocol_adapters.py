"""Small wire adapters behind one policy, HTTP carrier, cache and quota.

No provider SDK, model download, tool execution or automatic protocol fallback.
Native structured fields follow the vendors' documented HTTPS APIs. Every
result still passes the exact same local evidence parser and resource bounds.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True)
class APIRequest:
    url: str
    headers: dict[str, str] = field(repr=False)
    payload: dict[str, Any] = field(repr=False)
    protocol: str


def _schema_subset(value: Any) -> Any:
    """Remove native grammar-only length constraints, not local validation.

    Anthropic documents these as unsupported by its grammar compiler. They
    remain fully enforced by parse_candidates and the consumer after response.
    """
    if isinstance(value, list):
        return [_schema_subset(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _schema_subset(item)
            for key, item in value.items()
            if key
            not in {
                "minItems",
                "maxItems",
                "minLength",
                "maxLength",
                "minimum",
                "maximum",
            }
        }
    return value


def build_request(
    config: dict[str, Any],
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, Any] | None,
) -> APIRequest:
    protocol = config.get("protocol", "openai-compatible")
    mode = config.get("response_mode", "json-schema")
    if protocol not in {"openai-compatible", "anthropic", "gemini"} or mode not in {
        "json-schema",
        "json-object",
        "prompt-only",
    }:
        raise ValueError("Unsupported LLM API protocol")
    if not isinstance(messages, list) or any(
        not isinstance(item, dict)
        or set(item) != {"role", "content"}
        or item["role"] not in {"system", "user", "assistant"}
        or not isinstance(item["content"], str)
        for item in messages
    ):
        raise ValueError("Only bounded text messages are supported")
    endpoint = config["endpoint"].rstrip("/")
    key = config["api_key"]
    schema = (
        response_format.get("json_schema", {}).get("schema")
        if response_format
        else None
    )
    headers = {"Content-Type": "application/json"}
    system = "\n".join(item["content"] for item in messages if item["role"] == "system")
    ordinary = [dict(item) for item in messages if item["role"] != "system"]
    if protocol == "openai-compatible":
        payload: dict[str, Any] = {
            "model": model,
            "messages": [dict(item) for item in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema:
            if mode == "json-schema":
                payload["response_format"] = response_format
            else:
                payload["messages"].insert(
                    0,
                    {
                        "role": "system",
                        "content": "Return strict JSON only conforming to this schema: "
                        + json.dumps(schema, separators=(",", ":")),
                    },
                )
                if mode == "json-object":
                    payload["response_format"] = {"type": "json_object"}
        headers["Authorization"] = f"Bearer {key}"
        return APIRequest(endpoint + "/chat/completions", headers, payload, protocol)
    if protocol == "anthropic":
        payload = {
            "model": model,
            "messages": ordinary,
            "system": system,
            "max_tokens": max_tokens,
        }
        if schema:
            payload["output_config"] = {
                "format": {"type": "json_schema", "schema": _schema_subset(schema)}
            }
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        return APIRequest(endpoint + "/messages", headers, payload, protocol)
    model = model.removeprefix("models/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", model):
        raise ValueError("Gemini model must be a model name, not a URL or path")
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in ordinary
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "candidateCount": 1,
        },
    }
    if schema:
        payload["generationConfig"]["responseFormat"] = {
            "text": {"mimeType": "APPLICATION_JSON", "schema": schema}
        }
    headers["x-goog-api-key"] = key
    return APIRequest(
        endpoint + f"/models/{quote(model, safe='')}:generateContent",
        headers,
        payload,
        protocol,
    )


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("API content must be plain text")
    return value


def response_text(packet: dict[str, Any], protocol: str) -> str:
    if protocol == "openai-compatible":
        choices = packet["choices"]
        if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
            raise ValueError("LLM structured response was not complete")
        message = choices[0]["message"]
        if (
            message.get("refusal")
            or message.get("tool_calls")
            or message.get("function_call")
        ):
            raise ValueError("LLM refused the request")
        return _text(message["content"])
    if protocol == "anthropic":
        if packet.get("stop_reason") != "end_turn":
            raise ValueError("Anthropic structured response was not complete")
        parts = packet["content"]
        if len(parts) != 1 or parts[0].get("type") != "text":
            raise ValueError("Unexpected Anthropic content; no tools are executed")
        return _text(parts[0]["text"])
    if protocol == "gemini":
        candidates = packet["candidates"]
        if len(candidates) != 1 or candidates[0].get("finishReason") != "STOP":
            raise ValueError("Gemini structured response was not complete")
        parts = candidates[0]["content"]["parts"]
        if any(set(item) != {"text"} for item in parts) or not parts:
            raise ValueError("Unexpected Gemini tool/thinking/media output")
        return "".join(_text(item["text"]) for item in parts)
    raise ValueError("Unsupported API response protocol")
