"""Model routing: rank active models for a request under the active routing policy."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import AIModel, AIProvider, AIRoutingPolicy

LATENCY_SCORE = {"fast": 1.0, "medium": 0.6, "slow": 0.25}
DEFAULT_WEIGHTS = {"quality": 0.85, "cost": 0.1, "latency": 0.05}
COST_REFERENCE_USD = 0.05  # a call costing this much scores 0.5 on cost; free scores 1.0


@dataclass
class RouteRequest:
    capability: str = "text_reasoning"
    category: str = ""
    est_input_tokens: int = 2000
    est_output_tokens: int = 1500
    min_quality: int = 0
    max_cost_usd: float | None = None
    prefer: str = ""  # "" | quality | cost | latency
    pinned_model_id: str | None = None  # AIModel.id forced by caller/scenario
    allow_test_provider: bool = False


@dataclass
class RouteCandidate:
    model: AIModel
    provider: AIProvider
    score: float
    est_cost_usd: float
    reason: str


@dataclass
class RouteResult:
    candidates: list[RouteCandidate]
    rejected: list[tuple[str, str]] = field(default_factory=list)


def estimate_cost(m: AIModel, tokens_in: int, tokens_out: int) -> float:
    return (tokens_in * m.input_cost_per_mtok + tokens_out * m.output_cost_per_mtok) / 1_000_000


def rank(models: list[AIModel], req: RouteRequest, policy: AIRoutingPolicy | None) -> RouteResult:
    rules = (policy.rules if policy else {}) or {}
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(rules.get("weights", {}))
    if req.prefer in weights:
        weights[req.prefer] += 0.4
    allow = set(rules.get("allow_providers", []))
    deny = set(rules.get("deny_providers", []))
    override = rules.get("category_overrides", {}).get(req.category, {})
    min_quality = max(req.min_quality, int(override.get("min_quality", 0)))
    max_cost = req.max_cost_usd if req.max_cost_usd is not None else rules.get("max_cost_per_call_usd")

    rejected: list[tuple[str, str]] = []
    viable: list[tuple[AIModel, float]] = []
    for m in models:
        p = m.provider
        label = f"{p.name}/{m.model_id}"
        if req.pinned_model_id and m.id != req.pinned_model_id:
            continue
        if not p.is_active or not m.is_active:
            rejected.append((label, "inactive"))
            continue
        if p.kind == "deterministic_test" and not req.allow_test_provider:
            rejected.append((label, "test provider not allowed for this request"))
            continue
        if p.kind != "deterministic_test" and p.credential is None and p.auth_scheme != "none":
            rejected.append((label, "no credential configured"))
            continue
        if p.health_status == "down":
            rejected.append((label, f"provider health: down ({p.last_error[:80]})"))
            continue
        if allow and p.name not in allow:
            rejected.append((label, "not in policy allow-list"))
            continue
        if p.name in deny:
            rejected.append((label, "in policy deny-list"))
            continue
        if req.capability and m.capabilities and req.capability not in m.capabilities:
            rejected.append((label, f"lacks capability {req.capability}"))
            continue
        if m.context_window < req.est_input_tokens + req.est_output_tokens:
            rejected.append((label, "context window too small"))
            continue
        if m.quality_rank < min_quality:
            rejected.append((label, f"quality {m.quality_rank} below required {min_quality}"))
            continue
        cost = estimate_cost(m, req.est_input_tokens, req.est_output_tokens)
        if max_cost is not None and max_cost > 0 and cost > max_cost:
            rejected.append((label, f"estimated ${cost:.4f} exceeds per-call limit ${max_cost:.4f}"))
            continue
        viable.append((m, cost))

    if not viable:
        return RouteResult([], rejected)
    ref = float(rules.get("cost_reference_usd", COST_REFERENCE_USD)) or COST_REFERENCE_USD
    cands = []
    for m, cost in viable:
        q = m.quality_rank / 100
        c = 1 / (1 + cost / ref)
        lat = LATENCY_SCORE.get(m.latency_class, 0.5)
        score = weights["quality"] * q + weights["cost"] * c + weights["latency"] * lat
        cands.append(RouteCandidate(m, m.provider, round(score, 4), cost,
                                    f"quality {m.quality_rank}, est ${cost:.4f}, latency {m.latency_class}"))
    cands.sort(key=lambda x: -x.score)
    return RouteResult(cands, rejected)
