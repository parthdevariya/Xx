"""Anthropic Messages API adapter (official `anthropic` SDK)."""

from __future__ import annotations

import json
import time

import anthropic

from .base import (Completion, CompletionRequest, ProviderAuthError, ProviderBadRequest, ProviderConfig,
                   ProviderError, ProviderNotConfigured, ProviderRefusal)

# Models that accept the server-side refusal fallback in its "default" form on the Claude API.
FALLBACK_CAPABLE = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models with configurable effort (output_config.effort).
EFFORT_CAPABLE_PREFIXES = ("claude-fable-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
                           "claude-opus-4-6", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-5")


class AnthropicAdapter:
    kind = "anthropic"

    def __init__(self, cfg: ProviderConfig):
        if not cfg.api_key:
            raise ProviderNotConfigured("Anthropic provider has no API key configured")
        self.cfg = cfg
        kwargs = {"api_key": cfg.api_key, "timeout": cfg.timeout_s, "max_retries": 1}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        self.client = anthropic.Anthropic(**kwargs)

    def list_models(self) -> list[str]:
        return [m.id for m in self.client.models.list()]

    def complete(self, req: CompletionRequest) -> Completion:
        params: dict = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        }
        if req.system:
            params["system"] = req.system
        output_config: dict = {}
        if req.effort and req.model.startswith(EFFORT_CAPABLE_PREFIXES):
            output_config["effort"] = req.effort
        if req.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": req.json_schema}
        if output_config:
            params["output_config"] = output_config
        extra_headers, extra_body = {}, {}
        if self.cfg.extra.get("refusal_fallback", True) and req.model in FALLBACK_CAPABLE:
            extra_headers["anthropic-beta"] = FALLBACK_BETA
            extra_body["fallbacks"] = "default"

        t0 = time.perf_counter()
        try:
            msg = self.client.with_options(timeout=req.timeout_s).messages.create(
                **params, extra_headers=extra_headers or None, extra_body=extra_body or None)
        except anthropic.AuthenticationError as e:
            raise ProviderAuthError(f"Anthropic rejected the API key: {e.message}") from e
        except anthropic.PermissionDeniedError as e:
            raise ProviderAuthError(f"Anthropic key lacks permission: {e.message}") from e
        except anthropic.NotFoundError as e:
            raise ProviderBadRequest(f"Anthropic model or endpoint not found ({req.model}): {e.message}") from e
        except anthropic.BadRequestError as e:
            raise ProviderBadRequest(f"Anthropic rejected the request: {e.message}") from e
        except anthropic.RateLimitError as e:
            raise ProviderError(f"Anthropic rate limit: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"cannot reach Anthropic: {e}") from e
        latency = (time.perf_counter() - t0) * 1000

        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderRefusal(f"model declined the request (category: {category or 'unspecified'})")
        text = "".join(b.text for b in msg.content if b.type == "text")
        data = None
        if req.json_schema is not None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise ProviderError(f"model returned invalid JSON (stop_reason={msg.stop_reason})") from e
        return Completion(text=text, model=msg.model, provider_kind=self.kind,
                          input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
                          latency_ms=latency, stop_reason=msg.stop_reason or "", data=data,
                          request_id=getattr(msg, "_request_id", "") or "")
