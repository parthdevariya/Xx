from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Base for adapter failures. `retryable` tells the router whether to try the next model."""

    retryable = True


class ProviderNotConfigured(ProviderError):
    retryable = True


class ProviderAuthError(ProviderError):
    retryable = True  # another provider may still work


class ProviderBadRequest(ProviderError):
    retryable = False


class ProviderRefusal(ProviderError):
    """The model declined the request (after any server-side fallback)."""

    retryable = False


@dataclass
class ChatMessage:
    role: str  # user | assistant
    content: str


@dataclass
class CompletionRequest:
    messages: list[ChatMessage]
    model: str
    system: str = ""
    max_tokens: int = 4096
    json_schema: dict | None = None  # request structured JSON output conforming to this schema
    effort: str | None = None        # low | medium | high | xhigh | max (providers that support it)
    timeout_s: float = 120.0
    purpose: str = ""
    hints: dict = field(default_factory=dict)  # structured context; only the test adapter reads it


@dataclass
class Completion:
    text: str
    model: str
    provider_kind: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    stop_reason: str = ""
    data: Any = None  # parsed JSON when json_schema was requested
    request_id: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def is_test(self) -> bool:
        return self.provider_kind == "deterministic_test"


@dataclass
class ProviderConfig:
    kind: str
    base_url: str = ""
    api_key: str = ""
    auth_scheme: str = "bearer"
    timeout_s: float = 60.0
    extra: dict = field(default_factory=dict)


class Adapter(Protocol):
    kind: str

    def complete(self, req: CompletionRequest) -> Completion: ...

    def list_models(self) -> list[str]: ...
