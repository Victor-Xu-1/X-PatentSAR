"""Redacted API-only LLM settings and the existing bounded disclosure policy."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, StrictBool, StrictStr, field_validator

from patent_sar_extractor.integrations.llm.config import EvidenceResolutionConfig

from .dto import DTO
from .errors import WebError

Mode = Literal["off", "on-error", "quality"]
Protocol = Literal["openai-compatible", "anthropic", "gemini"]
ResponseMode = Literal["json-schema", "json-object", "prompt-only"]
SettingsStatus = Literal["disabled", "incomplete", "ready"]
MAX_REVISION = 2**53 - 1
TEST_REASONS = Literal[
    "nonce_verified",
    "invalid_response",
    "transport_unavailable",
    "settings_changed",
    "input_budget",
    "authentication_failed",
    "rate_limited",
    "provider_unavailable",
    "timeout",
    "cancelled",
    "cache_unavailable",
    "unsafe_cache",
]
BOUND_NAMES = (
    "max_calls",
    "timeout",
    "retries",
    "max_input_chars",
    "max_output_chars",
    "max_tokens",
)


def validate_endpoint(endpoint: str) -> str:
    # The integration owner supplies this single no-DNS external-host authority.
    from patent_sar_extractor.integrations.llm.external_api import (
        validate_external_endpoint,
    )

    return validate_external_endpoint(endpoint)


def safe_text(value: Any, limit: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Invalid provider field")
    return value.strip()


def nonce_probe(
    nonce: str, model: str, max_input_chars: int
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """A synthetic strict echo request, with no patent or credential content."""
    messages = [
        {
            "role": "system",
            "content": "Synthetic test: return only the supplied nonce as JSON.",
        },
        {"role": "user", "content": json.dumps({"nonce": nonce})},
    ]
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "patentsar_connectivity",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"nonce": {"type": "string", "enum": [nonce]}},
                "required": ["nonce"],
                "additionalProperties": False,
            },
        },
    }
    payload = {
        "messages": messages,
        "response_format": schema,
        "model": model,
        "max_tokens": 128,
        "temperature": 0.0,
    }
    if len(json.dumps(payload, ensure_ascii=False)) > max_input_chars:
        raise ValueError("Synthetic test exceeds the input budget")
    return messages, schema


class LLMSettingsRequest(DTO):
    expected_revision: int = Field(ge=0, le=MAX_REVISION, strict=True)
    endpoint: StrictStr = Field(max_length=2048)
    model: StrictStr = Field(max_length=128)
    protocol: Protocol = "openai-compatible"
    response_mode: ResponseMode = "json-schema"
    mode: Mode
    data_consent: StrictBool
    api_key: StrictStr | None = Field(
        default=None, max_length=4096, repr=False, exclude=True
    )

    @field_validator("endpoint", "model")
    @classmethod
    def provider_text(cls, value: str) -> str:
        return safe_text(value, 2048)

    @field_validator("api_key")
    @classmethod
    def explicit_key(cls, value: str | None) -> str:
        if value is None or (value and value != safe_text(value, 4096)):
            raise ValueError("An explicitly supplied API key must be a valid string")
        return value


class LLMTestRequest(DTO):
    expected_revision: int = Field(ge=0, le=MAX_REVISION, strict=True)
    consent: StrictBool

    @field_validator("consent")
    @classmethod
    def charged_test_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "Explicit consent to one charged synthetic test is required"
            )
        return value


class LLMReauthorizeRequest(DTO):
    """Explicit local credential use, not consent to another API/model call."""

    expected_revision: int = Field(ge=0, le=MAX_REVISION, strict=True)
    consent: StrictBool

    @field_validator("consent")
    @classmethod
    def renewal_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "Explicit consent to renew this task's API authorization is required"
            )
        return value


class LLMRecovery(DTO):
    status: Literal[
        "disabled", "ready", "blocked", "cooldown", "exhausted", "unavailable"
    ]
    reason: str | None = Field(default=None, max_length=64)
    remaining_calls: int | None = Field(default=None, ge=0, le=8, strict=True)
    retry_after_seconds: float | None = Field(default=None, ge=0, le=45, strict=True)
    can_reauthorize: StrictBool = False


class LLMLimits(DTO):
    max_calls: int
    timeout_seconds: int
    max_input_chars: int
    max_output_chars: int
    max_tokens: int

    @classmethod
    def from_policy(cls, policy: EvidenceResolutionConfig) -> LLMLimits:
        return cls(
            timeout_seconds=policy.timeout,
            **{
                key: getattr(policy, key)
                for key in BOUND_NAMES
                if key not in {"timeout", "retries"}
            },
        )


class LLMTestResult(DTO):
    status: Literal["passed", "failed"]
    reason: TEST_REASONS
    settings_revision: int = Field(ge=0, le=MAX_REVISION, strict=True)
    checked_at: StrictStr = Field(max_length=64)

    @field_validator("checked_at")
    @classmethod
    def timestamp(cls, value: str) -> str:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Test time must include a timezone")
        return value


class LLMSettings(DTO):
    revision: int = Field(ge=0, le=MAX_REVISION, strict=True)
    endpoint: str
    model: str
    protocol: Protocol = "openai-compatible"
    response_mode: ResponseMode = "json-schema"
    mode: Mode
    data_consent: bool
    key_configured: bool
    editable: bool
    status: SettingsStatus
    reason: str | None
    limits: LLMLimits
    last_test: LLMTestResult | None


@dataclass(frozen=True)
class SettingsSnapshot:
    view: LLMSettings
    policy: EvidenceResolutionConfig = field(repr=False)
    local: dict[str, Any] = field(repr=False)
    fingerprint: str = field(repr=False)


def unavailable_settings() -> LLMSettings:
    return LLMSettings(
        revision=0,
        endpoint="",
        model="",
        mode="off",
        data_consent=False,
        key_configured=False,
        editable=False,
        status="incomplete",
        reason="configuration_unavailable",
        limits=LLMLimits.from_policy(EvidenceResolutionConfig()),
        last_test=None,
    )


def validate_test_settings(view: LLMSettings) -> None:
    if view.mode == "off":
        raise WebError(
            409, "llm_test_disabled", "LLM mode is OFF; no network test was authorized."
        )
    if not view.data_consent:
        raise WebError(
            422,
            "llm_test_consent_required",
            "LLM data consent is required before testing.",
        )
    if view.status != "ready":
        raise WebError(
            422,
            "llm_test_incomplete",
            "Complete external API settings are required before testing.",
        )


def settings_view(
    policy: EvidenceResolutionConfig, local: dict[str, Any], *, locked: bool
) -> LLMSettings:
    metadata = local.get("api_settings", {})
    if not isinstance(metadata, dict):
        raise TypeError("Invalid settings metadata")
    revision = metadata.get("revision", 0)
    if type(revision) is not int or not 0 <= revision <= MAX_REVISION:
        raise ValueError("Invalid settings revision")
    # Validate every bound even OFF, but incomplete providers remain repairable.
    EvidenceResolutionConfig(
        mode="off",
        data_consent=policy.data_consent,
        protocol=policy.protocol,
        response_mode=policy.response_mode,
        **{key: getattr(policy, key) for key in BOUND_NAMES},
    ).validate()
    if policy.mode not in {"off", "on-error", "quality"}:
        raise ValueError("Invalid LLM mode")
    endpoint, reason = "", None
    try:
        endpoint = validate_endpoint(policy.endpoint) if policy.endpoint else ""
        policy.validate()
    except (ValueError, TypeError):
        reason = "invalid_provider"
    complete = bool(endpoint and policy.model and policy.api_key)
    status: SettingsStatus = "disabled" if policy.mode == "off" else "incomplete"
    if policy.mode == "off":
        reason = reason or "off"
    elif not policy.data_consent:
        reason = reason or "data_consent_required"
    elif not complete:
        reason = reason or "provider_incomplete"
    elif reason is None:
        status = "ready"
    last_test = metadata.get("last_test")
    result = LLMTestResult.model_validate(last_test) if last_test is not None else None
    if result is not None and (result.settings_revision != revision or locked):
        result = None
    return LLMSettings(
        revision=revision,
        endpoint=endpoint,
        model=policy.model,
        protocol=policy.protocol,
        response_mode=policy.response_mode,
        mode=policy.mode,
        data_consent=policy.data_consent,
        key_configured=bool(policy.api_key),
        editable=not locked,
        status=status,
        reason="environment_override" if locked else reason,
        limits=LLMLimits.from_policy(policy),
        last_test=result,
    )
