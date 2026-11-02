"""AI Engine service: route, call, fall back, log usage and cost."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (AIExecutionLog, AIModel, AIProvider, AIRoutingPolicy, CostRecord, ProviderHealth,
                      UsageRecord, utcnow)
from ..security import decrypt_secret
from .providers import ProviderConfig, build_adapter
from .providers.base import (ChatMessage, Completion, CompletionRequest, ProviderError, ProviderNotConfigured)
from .router import RouteRequest, rank


class AIUnavailable(RuntimeError):
    """No configured, healthy model could serve the request."""

    def __init__(self, message: str, attempts: list[str] | None = None, rejected: list | None = None):
        super().__init__(message)
        self.attempts = attempts or []
        self.rejected = rejected or []


@dataclass
class AIResult:
    completion: Completion
    provider_name: str
    model_db_id: str
    cost_usd: float
    attempts: list[str] = field(default_factory=list)

    @property
    def is_test(self) -> bool:
        return self.completion.is_test


def provider_config(p: AIProvider) -> ProviderConfig:
    key = decrypt_secret(p.credential.secret_encrypted) if p.credential else ""
    return ProviderConfig(kind=p.kind, base_url=p.base_url, api_key=key, auth_scheme=p.auth_scheme,
                          timeout_s=p.timeout_s, extra=p.config or {})


def default_policy(db: Session) -> AIRoutingPolicy | None:
    return db.scalar(select(AIRoutingPolicy).where(AIRoutingPolicy.is_default.is_(True)))


def any_model_available(db: Session, allow_test: bool = False) -> bool:
    models = list(db.scalars(select(AIModel)))
    return bool(rank(models, RouteRequest(capability="", allow_test_provider=allow_test), None).candidates)


def test_provider_allowed(db: Session) -> bool:
    """The test provider serves real requests only if an admin activated it explicitly."""
    return db.scalar(select(AIProvider).where(AIProvider.kind == "deterministic_test",
                                              AIProvider.is_active.is_(True))) is not None


def complete(db: Session, *, messages: list[ChatMessage], system: str = "", route: RouteRequest | None = None,
             json_schema: dict | None = None, max_tokens: int = 4096, effort: str | None = "medium",
             purpose: str = "", execution_id: str | None = None, user_id: str | None = None,
             hints: dict | None = None, timeout_s: float = 180.0) -> AIResult:
    route = route or RouteRequest()
    if not route.allow_test_provider:
        route.allow_test_provider = test_provider_allowed(db)
    models = list(db.scalars(select(AIModel)))
    ranking = rank(models, route, default_policy(db))
    if not ranking.candidates:
        raise AIUnavailable("no AI model is configured and available for this request. Configure a provider "
                            "and credential in Admin → AI Management.", rejected=ranking.rejected)
    attempts: list[str] = []
    last_error: Exception | None = None
    for cand in ranking.candidates:
        p, m = cand.provider, cand.model
        label = f"{p.name}/{m.model_id}"
        req = CompletionRequest(messages=messages, model=m.model_id, system=system,
                                max_tokens=min(max_tokens, m.max_output_tokens), json_schema=json_schema,
                                effort=effort, purpose=purpose, hints=hints or {},
                                timeout_s=min(timeout_s, p.timeout_s * 3))
        t0 = time.perf_counter()
        try:
            adapter = build_adapter(provider_config(p))
            comp = adapter.complete(req)
        except ProviderError as e:
            attempts.append(f"{label}: {e}")
            last_error = e
            db.add(AIExecutionLog(execution_id=execution_id, provider_id=p.id, model_id=m.model_id,
                                  provider_kind=p.kind, purpose=purpose, status="error",
                                  latency_ms=(time.perf_counter() - t0) * 1000, error=str(e)[:2000]))
            if not isinstance(e, ProviderNotConfigured):
                p.last_error = str(e)[:500]
            db.flush()
            if not e.retryable:
                break
            continue
        cost = (comp.input_tokens * m.input_cost_per_mtok + comp.output_tokens * m.output_cost_per_mtok) / 1e6
        db.add(AIExecutionLog(execution_id=execution_id, provider_id=p.id, model_id=comp.model,
                              provider_kind=p.kind, purpose=purpose,
                              status="ok" if not attempts else "fallback", input_tokens=comp.input_tokens,
                              output_tokens=comp.output_tokens, cost_usd=cost, latency_ms=comp.latency_ms))
        db.add(UsageRecord(user_id=user_id, execution_id=execution_id, kind="ai_tokens_in",
                           quantity=comp.input_tokens, unit="tokens", provider=p.name))
        db.add(UsageRecord(user_id=user_id, execution_id=execution_id, kind="ai_tokens_out",
                           quantity=comp.output_tokens, unit="tokens", provider=p.name))
        if cost:
            db.add(CostRecord(execution_id=execution_id, user_id=user_id, provider=p.name, category="ai",
                              amount_usd=cost, is_estimate=True))
        p.last_latency_ms = comp.latency_ms
        db.flush()
        attempts.append(f"{label}: ok")
        return AIResult(comp, p.name, m.id, cost, attempts)
    raise AIUnavailable(f"all AI routes failed: {last_error}", attempts, ranking.rejected)


def health_check(db: Session, provider: AIProvider) -> ProviderHealth:
    """A minimal real call. Never reports healthy without a successful response."""
    t0 = time.perf_counter()
    status, detail = "healthy", ""
    model = next((m for m in provider.models if m.is_active), None)
    try:
        if model is None:
            raise ProviderNotConfigured("no active model to test")
        adapter = build_adapter(provider_config(provider))
        adapter.complete(CompletionRequest(messages=[ChatMessage("user", "Reply with OK.")], model=model.model_id,
                                           max_tokens=16, effort="low", purpose="health", timeout_s=30))
    except ProviderNotConfigured as e:
        status, detail = "unconfigured", str(e)
    except ProviderError as e:
        status, detail = "down", str(e)
    latency = (time.perf_counter() - t0) * 1000
    provider.health_status = status
    provider.last_checked_at = utcnow()
    provider.last_error = detail[:500]
    if status == "healthy":
        provider.last_latency_ms = latency
    rec = ProviderHealth(provider_type="ai", provider_id=provider.id, status=status,
                         latency_ms=latency if status == "healthy" else None, detail=detail[:1000])
    db.add(rec)
    db.flush()
    return rec
