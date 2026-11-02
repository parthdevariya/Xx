"""AI provider registry seed. Providers are created inactive and without credentials; nothing is
reported as connected until an administrator adds a key and a health check succeeds. If
ANTHROPIC_API_KEY / OPENAI_API_KEY are present in the environment on first start, they are stored
encrypted and the provider is activated."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AICapability, AICredential, AIModel, AIProvider, AIRoutingPolicy
from ..security import encrypt_secret, secret_hint

CAPABILITIES = {
    "text_reasoning": "General reasoning over text",
    "code_generation": "Writing and explaining code",
    "mathematical_reasoning": "Mathematical and quantitative reasoning",
    "research_synthesis": "Synthesising information from supplied material",
    "structured_extraction": "Extracting structured data / JSON output",
    "classification": "Classifying inputs into categories",
    "summarization": "Summarising text",
    "planning": "Multi-step planning",
    "tool_calling": "Function / tool calling",
    "multimodal": "Image or document input",
    "rag": "Retrieval-augmented generation",
}

ALL_CAPS = list(CAPABILITIES)

# Prices are USD per million tokens as published by each vendor at seed time; admins keep them current.
PROVIDERS = [
    {
        "name": "Anthropic", "kind": "anthropic", "base_url": "", "auth_scheme": "x-api-key",
        "config": {"refusal_fallback": True}, "env_key": "anthropic_api_key",
        "models": [
            ("claude-opus-5-5", "Claude Opus 5.5", 1_000_000, 16000, 4.0, 20.0, 95, "medium"),
            ("claude-sonnet-5-5", "Claude Sonnet 5.5", 1_000_000, 16000, 2.0, 10.0, 88, "fast"),
            ("claude-haiku-5-5", "Claude Haiku 5.5", 1_000_000, 16000, 0.10, 0.50, 72, "fast"),
        ],
    },
    {
        "name": "OpenAI", "kind": "openai_compatible", "base_url": "https://api.openai.com/v1",
        "auth_scheme": "bearer", "config": {"max_tokens_field": "max_completion_tokens"},
        "env_key": "openai_api_key", "models": [],
    },
    {
        "name": "Google Gemini (OpenAI-compatible)", "kind": "openai_compatible",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "auth_scheme": "bearer",
        "config": {}, "env_key": None, "models": [],
    },
    {
        "name": "Azure OpenAI", "kind": "openai_compatible", "base_url": "", "auth_scheme": "api-key",
        "config": {"api_version": "2024-10-21"}, "env_key": None, "models": [],
    },
    {
        "name": "Ollama (local)", "kind": "openai_compatible", "base_url": "http://localhost:11434/v1",
        "auth_scheme": "none", "config": {"json_schema_support": False}, "env_key": None, "models": [],
    },
    {
        "name": "LM Studio (local)", "kind": "openai_compatible", "base_url": "http://localhost:1234/v1",
        "auth_scheme": "none", "config": {}, "env_key": None, "models": [],
    },
    {
        "name": "X Test Provider", "kind": "deterministic_test", "base_url": "", "auth_scheme": "none",
        "config": {"label": "Deterministic test provider — not a real model"}, "env_key": None,
        "models": [("x-test-deterministic", "Deterministic test model", 200_000, 8000, 0.0, 0.0, 1, "fast")],
    },
]


def seed_ai(db: Session) -> None:
    s = get_settings()
    for code, desc in CAPABILITIES.items():
        if db.get(AICapability, code) is None:
            db.add(AICapability(code=code, description=desc))
    for spec in PROVIDERS:
        p = db.scalar(select(AIProvider).where(AIProvider.name == spec["name"]))
        if p is None:
            p = AIProvider(name=spec["name"], kind=spec["kind"], base_url=spec["base_url"],
                           auth_scheme=spec["auth_scheme"], config=spec["config"], is_active=False,
                           health_status="unconfigured" if spec["kind"] != "deterministic_test" else "unknown")
            db.add(p)
            db.flush()
            for mid, name, ctx, max_out, cin, cout, q, lat in spec["models"]:
                db.add(AIModel(provider_id=p.id, model_id=mid, display_name=name, capabilities=ALL_CAPS,
                               context_window=ctx, max_output_tokens=max_out, input_cost_per_mtok=cin,
                               output_cost_per_mtok=cout, quality_rank=q, latency_class=lat))
        key = getattr(s, spec["env_key"], "") if spec.get("env_key") else ""
        if key and p.credential is None:
            db.add(AICredential(provider_id=p.id, secret_encrypted=encrypt_secret(key), hint=secret_hint(key)))
            p.is_active = True
            p.health_status = "unknown"
    if db.scalar(select(AIRoutingPolicy).where(AIRoutingPolicy.is_default.is_(True))) is None:
        db.add(AIRoutingPolicy(name="Quality first (default)", is_default=True,
                               description="Quality first, then cost and latency. Falls back down the ranking.",
                               rules={"weights": {"quality": 0.85, "cost": 0.1, "latency": 0.05},
                                      "cost_reference_usd": 0.05,
                                      "max_cost_per_call_usd": 1.0,
                                      "category_overrides": {"mathematical": {"min_quality": 80}}}))
    db.flush()
