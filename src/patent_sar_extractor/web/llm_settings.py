"""Hot API-only configuration, revisioned saves and one consented nonce probe."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Literal, cast, get_args

from patent_sar_extractor import paths
from patent_sar_extractor.integrations.llm.api_failures import (
    APIProblem,
    evidence_problem,
)
from patent_sar_extractor.integrations.llm.client import llm_chat
from patent_sar_extractor.integrations.llm.config import EvidenceResolutionConfig
from patent_sar_extractor.integrations.llm.credential_authorization import (
    dispatch_authorization,
    renew_authorization,
)
from patent_sar_extractor.integrations.llm.evidence_resolution import EvidenceCallBudget
from patent_sar_extractor.integrations.llm.job_health import (
    BLOCKED_REASONS,
    clear_state,
    read_state,
)
from patent_sar_extractor.integrations.llm.private_state import read_budget

from .errors import WebError
from .llm_models import (
    MAX_REVISION,
    TEST_REASONS,
    LLMSettings,
    LLMSettingsRequest,
    LLMTestRequest,
    LLMTestResult,
    SettingsSnapshot,
    nonce_probe,
    settings_view,
    unavailable_settings,
    validate_endpoint,
    validate_test_settings,
)
from .llm_settings_storage import (
    LOCAL_NAME,
    LLMSettingsStorage,
    environment_overrides,
    policy_from_config,
    unavailable,
)


class LLMSettingsService:
    def __init__(self, config_dir: Path | None = None) -> None:
        # Construction and GET must never initialize state, an installer or LLM.
        self.config_dir = config_dir
        self._test_lock = threading.Lock()

    def _storage(self) -> LLMSettingsStorage:
        if self.config_dir is not None:
            return LLMSettingsStorage(self.config_dir)
        directory = paths.operator_config_dir()
        raw = os.environ.get("PATENTSAR_CONFIG_DIR", "").strip()
        if raw:
            original = Path(raw).expanduser().absolute()
        else:
            xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
            original = (
                Path(xdg).expanduser().absolute() if xdg else Path.home() / ".config"
            ) / "patent-sar-extractor"
        if original != directory:
            raise unavailable()  # Resolving a configured symlink cannot confer ownership.
        return LLMSettingsStorage(directory)

    def _snapshot(
        self, storage: LLMSettingsStorage, directory: int | None = None
    ) -> SettingsSnapshot:
        configured = paths.config_files("llm.yaml")
        # Synthetic constructors never read the real operator's overrides.
        sources = (configured[0],) if self.config_dir is not None else configured
        sources = tuple(
            dict.fromkeys(
                (
                    *sources,
                    storage.config_dir / "llm.yaml",
                    storage.config_dir / LOCAL_NAME,
                )
            )
        )
        merged, local, token = storage.load(sources, directory=directory)
        env = environment_overrides()
        policy = policy_from_config(merged, env)
        try:
            if policy.endpoint:
                policy = replace(policy, endpoint=validate_endpoint(policy.endpoint))
        except ValueError:
            pass  # GET presents an explicit invalid-provider state, never the raw URL.
        view = settings_view(policy, local, locked=bool(env))
        if "api_settings" in local and not env:
            policy = replace(
                policy, authorization_file=str(storage.config_dir / LOCAL_NAME)
            )
        fingerprint = hashlib.sha256(
            (token + json.dumps(env, sort_keys=True)).encode()
        ).hexdigest()
        return SettingsSnapshot(view, policy, local, fingerprint)

    def get_settings(self) -> LLMSettings:
        try:
            return self._snapshot(self._storage()).view
        except (WebError, OSError, ValueError, TypeError, RecursionError):
            return unavailable_settings()

    def policy(self) -> EvidenceResolutionConfig:
        """Capture the same effective configuration, validating before queue use."""
        try:
            snapshot = self._snapshot(self._storage())
            policy = snapshot.policy
            if policy.endpoint:
                validate_endpoint(policy.endpoint)
            policy.validate()
            return policy
        except (WebError, OSError, ValueError, TypeError, RecursionError):
            raise unavailable() from None

    @staticmethod
    def _revision(snapshot: SettingsSnapshot, expected: int) -> None:
        if snapshot.view.revision != expected:
            raise WebError(
                409,
                "llm_settings_conflict",
                "Settings changed; reload before retrying.",
            )

    def save_settings(self, body: LLMSettingsRequest) -> LLMSettings:
        if environment_overrides():
            raise WebError(
                409,
                "llm_settings_locked",
                "Explicit operator environment overrides prevent editing saved LLM settings.",
            )
        try:
            storage = self._storage()
            # Check stale requests without creating even a configuration directory.
            self._revision(self._snapshot(storage), body.expected_revision)
            with storage.transaction() as directory:
                current = self._snapshot(storage, directory)
                self._revision(current, body.expected_revision)
                if not current.view.editable:
                    raise WebError(
                        409,
                        "llm_settings_locked",
                        "Operator overrides prevent editing saved LLM settings.",
                    )
                endpoint = validate_endpoint(body.endpoint) if body.endpoint else ""
                changed = (endpoint, body.model, body.protocol) != (
                    current.policy.endpoint,
                    current.policy.model,
                    current.policy.protocol,
                )
                key = current.policy.api_key if body.api_key is None else body.api_key
                if changed and current.policy.api_key and body.api_key is None:
                    raise WebError(
                        422,
                        "llm_key_replacement_required",
                        "Changing endpoint, model or protocol requires key re-entry or explicit clearing.",
                    )
                policy = replace(
                    current.policy,
                    endpoint=endpoint,
                    model=body.model,
                    protocol=body.protocol,
                    response_mode=body.response_mode,
                    api_key=key,
                    mode=body.mode,
                    data_consent=body.data_consent,
                )
                if policy.mode != "off" and (
                    not policy.data_consent or not all((endpoint, policy.model, key))
                ):
                    raise WebError(
                        422,
                        "llm_settings_incomplete",
                        "Enabled LLM use requires an external provider, model, key and explicit data consent.",
                    )
                policy.validate()
                if current.view.revision == MAX_REVISION:
                    raise WebError(
                        409,
                        "llm_settings_conflict",
                        "Settings revision limit reached; no settings were changed.",
                    )
                storage.publish(
                    directory, current.local, policy, current.view.revision + 1
                )
            return self.get_settings()
        except (OSError, TypeError, RecursionError):
            raise unavailable() from None
        except ValueError:
            raise WebError(
                422,
                "llm_settings_invalid",
                "LLM provider or policy fields are invalid; existing settings were preserved.",
            ) from None

    @staticmethod
    def _probe(
        policy: EvidenceResolutionConfig,
    ) -> tuple[Literal["passed", "failed"], TEST_REASONS]:
        nonce = secrets.token_hex(16)
        failures: list[APIProblem] = []
        try:
            messages, schema = nonce_probe(nonce, policy.model, policy.max_input_chars)
        except ValueError:
            return "failed", "input_budget"
        try:
            content = llm_chat(
                messages,
                config=asdict(policy),
                model=policy.model,
                timeout=min(policy.timeout, 30),
                max_retries=0,
                max_tokens=128,
                max_response_chars=2048,
                max_request_chars=policy.max_input_chars,
                cache=False,
                response_format=schema,
                on_failure=failures.append,
                dispatch_guard=partial(dispatch_authorization, policy)
                if policy.authorization_file
                else None,
            )
        except (
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            RecursionError,
            MemoryError,
        ):
            # Untrusted provider exceptions never cross the API/log boundary.
            return "failed", "transport_unavailable"
        if not content:
            latest = evidence_problem(failures[-1]) if failures else None
            reason = latest.reason if latest is not None else "transport_unavailable"
            return "failed", cast(TEST_REASONS, reason) if reason in get_args(
                TEST_REASONS
            ) else "transport_unavailable"
        try:
            if not isinstance(content, str) or len(content) > 2048:
                raise ValueError("Invalid test response")
            if json.loads(content, object_pairs_hook=list) != [("nonce", nonce)]:
                raise ValueError("Nonce mismatch or extra/duplicate fields")
        except (ValueError, TypeError, RecursionError):
            return "failed", "invalid_response"
        return "passed", "nonce_verified"

    def test_connection(self, body: LLMTestRequest) -> LLMTestResult:
        if body.consent is not True:
            raise WebError(
                422,
                "llm_test_consent_required",
                "Explicit charged-test consent is required.",
            )
        if not self._test_lock.acquire(blocking=False):
            raise WebError(
                409,
                "llm_test_busy",
                "A synthetic connection test is already active; no request was replayed.",
            )
        try:
            storage = self._storage()
            current = self._snapshot(storage)
            self._revision(current, body.expected_revision)
            validate_test_settings(current.view)
            current.policy.validate()
            status, reason = self._probe(current.policy)
            result = LLMTestResult(
                status=status,
                reason=reason,
                settings_revision=current.view.revision,
                checked_at=datetime.now(UTC).isoformat(),
            )
            # No lock spans network I/O: settings may change or be switched OFF.
            if not current.view.editable:
                return result  # Environment values have no durable YAML revision.
            with storage.transaction() as directory:
                latest = self._snapshot(storage, directory)
                if (
                    latest.fingerprint != current.fingerprint
                    or not latest.view.editable
                ):
                    return result.model_copy(
                        update={"status": "failed", "reason": "settings_changed"}
                    )
                data = deepcopy(latest.local)
                data["api_settings"] = {
                    **data.get("api_settings", {}),
                    "revision": latest.view.revision,
                    "last_test": result.model_dump(),
                }
                storage.replace(directory, data, expected=latest.local)
            return result
        except (OSError, ValueError, TypeError, RecursionError):
            raise unavailable() from None
        finally:
            self._test_lock.release()

    def renew_job(self, context, expected_revision: int) -> None:
        """No API request, job start, snapshot rewrite, quota reset or key echo."""
        if environment_overrides():
            raise WebError(
                409,
                "llm_settings_locked",
                "Operator profiles cannot be renewed in the browser.",
            )
        budget = EvidenceCallBudget(
            context.job_id, context.policy.max_calls, ledger=context.ledger
        )
        if not budget.acquire():
            raise WebError(
                409,
                "llm_job_busy",
                "A task API request is active; authorization was not changed.",
            )
        try:
            storage = self._storage()
            with storage.transaction() as directory:
                health = read_state(context.ledger, context.job_id)
                if health and health["reason"] in BLOCKED_REASONS - {
                    "authentication_failed"
                }:
                    raise WebError(
                        409,
                        "llm_recovery_blocked",
                        "A non-authentication safety fault cannot be cleared by credential renewal.",
                    )
                if (
                    read_budget(
                        context.ledger, context.job_id, context.policy.max_calls
                    )
                    >= context.policy.max_calls
                ):
                    raise WebError(
                        409,
                        "llm_renewal_unavailable",
                        "The task's retained API quota is exhausted.",
                    )
                current = self._snapshot(storage, directory)
                self._revision(current, expected_revision)
                validate_test_settings(current.view)
                renew_authorization(context, current.policy, current.view.revision)
                if health and health["reason"] == "authentication_failed":
                    clear_state(context.ledger, context.job_id)
        except (OSError, TypeError, RecursionError):
            raise unavailable() from None
        except ValueError:
            raise WebError(
                409,
                "llm_profile_changed",
                "Only credentials for the same saved API profile can be renewed; create a new task for a semantic change.",
            ) from None
        finally:
            budget.release()
