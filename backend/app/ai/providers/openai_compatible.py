"""Adapter for any OpenAI-compatible Chat Completions endpoint.

Covers OpenAI, Azure OpenAI (auth_scheme="api-key", base_url = deployment URL), Google Gemini's
OpenAI-compatible endpoint, Ollama (http://localhost:11434/v1, auth none), LM Studio, vLLM,
OpenRouter, Groq, Together and similar services.
"""

from __future__ import annotations

import json
import time

import httpx

from .base import (Completion, CompletionRequest, ProviderAuthError, ProviderBadRequest, ProviderConfig,
                   ProviderError, ProviderNotConfigured, ProviderRefusal)


class OpenAICompatibleAdapter:
    kind = "openai_compatible"

    def __init__(self, cfg: ProviderConfig):
        if not cfg.base_url:
            raise ProviderNotConfigured("OpenAI-compatible provider needs a base URL")
        if cfg.auth_scheme != "none" and not cfg.api_key:
            raise ProviderNotConfigured("OpenAI-compatible provider has no API key configured")
        self.cfg = cfg

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.cfg.auth_scheme == "bearer":
            h["Authorization"] = f"Bearer {self.cfg.api_key}"
        elif self.cfg.auth_scheme == "api-key":
            h["api-key"] = self.cfg.api_key
        elif self.cfg.auth_scheme == "x-api-key":
            h["x-api-key"] = self.cfg.api_key
        return h

    def _url(self, path: str) -> str:
        base = self.cfg.base_url.rstrip("/")
        url = f"{base}/{path}"
        if self.cfg.extra.get("api_version"):  # Azure
            url += ("&" if "?" in url else "?") + f"api-version={self.cfg.extra['api_version']}"
        return url

    def list_models(self) -> list[str]:
        r = httpx.get(self._url("models"), headers=self._headers(), timeout=self.cfg.timeout_s)
        self._raise_for(r)
        return [m["id"] for m in r.json().get("data", [])]

    def _raise_for(self, r: httpx.Response) -> None:
        if r.status_code < 400:
            return
        body = r.text[:500]
        if r.status_code in (401, 403):
            raise ProviderAuthError(f"provider rejected credentials ({r.status_code}): {body}")
        if r.status_code in (400, 404, 422):
            raise ProviderBadRequest(f"provider rejected request ({r.status_code}): {body}")
        raise ProviderError(f"provider error {r.status_code}: {body}")

    def complete(self, req: CompletionRequest) -> Completion:
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages += [{"role": m.role, "content": m.content} for m in req.messages]
        body: dict = {"model": req.model, "messages": messages,
                      self.cfg.extra.get("max_tokens_field", "max_tokens"): req.max_tokens}
        if req.json_schema is not None:
            if self.cfg.extra.get("json_schema_support", True):
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "x_output", "schema": req.json_schema,
                                                           "strict": True}}
            else:
                body["response_format"] = {"type": "json_object"}
        t0 = time.perf_counter()
        try:
            r = httpx.post(self._url("chat/completions"), headers=self._headers(), json=body,
                           timeout=req.timeout_s)
        except httpx.HTTPError as e:
            raise ProviderError(f"cannot reach provider at {self.cfg.base_url}: {e}") from e
        latency = (time.perf_counter() - t0) * 1000
        self._raise_for(r)
        payload = r.json()
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        if message.get("refusal"):
            raise ProviderRefusal(f"model declined the request: {message['refusal']}")
        text = message.get("content") or ""
        data = None
        if req.json_schema is not None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise ProviderError("model returned invalid JSON") from e
        usage = payload.get("usage") or {}
        return Completion(text=text, model=payload.get("model", req.model), provider_kind=self.kind,
                          input_tokens=int(usage.get("prompt_tokens", 0)),
                          output_tokens=int(usage.get("completion_tokens", 0)), latency_ms=latency,
                          stop_reason=choice.get("finish_reason", ""), data=data,
                          request_id=r.headers.get("x-request-id", ""))
