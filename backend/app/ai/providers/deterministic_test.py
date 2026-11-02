"""Deterministic test provider.

Used by the automated test suite and, when an administrator explicitly activates it, for offline
walkthroughs. It makes no judgment: every response is fixed, and every Completion it returns carries
provider_kind="deterministic_test", which the orchestrator turns into result_source="test" and the UI
labels "Test provider — not a real model".

Tests can register responders per purpose prefix to script specific behaviour.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from .base import Completion, CompletionRequest, ProviderConfig

Responder = Callable[[CompletionRequest], dict | str]
_RESPONDERS: dict[str, Responder] = {}
TEST_NOTE = "[TEST PROVIDER — deterministic placeholder, not model output]"


def register_responder(purpose_prefix: str, fn: Responder) -> None:
    _RESPONDERS[purpose_prefix] = fn


def clear_responders() -> None:
    _RESPONDERS.clear()


def _default_for(req: CompletionRequest) -> dict | str:
    hints = req.hints or {}
    p = req.purpose
    if p.startswith("intellect.stage"):
        return {
            "rule_assessments": [
                {"rule": code, "applies": False, "reason": f"{TEST_NOTE} no judgment made"}
                for code in hints.get("rule_codes", [])
            ],
            "output": f"{TEST_NOTE} stage {hints.get('stage_label', '')} output.",
            "conflicts": [],
            "preset": {"register": "neutral", "pace": "steady", "intensity": "low", "rule_ids": []}
            if hints.get("mode") == "select_preset" else None,
        }
    if p.startswith("intellect.guardrail_audit"):
        return {"checks": [{"rule": c, "breached": False, "note": TEST_NOTE} for c in hints.get("rule_codes", [])]}
    if p.startswith("intake"):
        return {"category": "general", "objectives": [], "constraints": [], "required_outputs": [],
                "missing_information": [], "complexity": "low", "summary": TEST_NOTE,
                "solver_template": "", "template_data": {}}
    if req.json_schema is not None:
        return _from_schema(req.json_schema)
    return f"{TEST_NOTE} response to: {req.messages[-1].content[:120]}"


def _from_schema(schema: dict):
    t = schema.get("type")
    if t == "object":
        return {k: _from_schema(v) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return []
    if t == "string":
        return TEST_NOTE
    if t in ("number", "integer"):
        return 0
    if t == "boolean":
        return False
    if isinstance(t, list):
        return None
    return None


class DeterministicTestAdapter:
    kind = "deterministic_test"

    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    def list_models(self) -> list[str]:
        return ["x-test-deterministic"]

    def complete(self, req: CompletionRequest) -> Completion:
        responder = next((fn for prefix, fn in sorted(_RESPONDERS.items(), key=lambda kv: -len(kv[0]))
                          if req.purpose.startswith(prefix)), None)
        out = responder(req) if responder else _default_for(req)
        if isinstance(out, dict):
            text = json.dumps(out)
            data = out if req.json_schema is not None else None
        else:
            text, data = out, None
        n_in = sum(len(m.content) for m in req.messages) // 4
        return Completion(text=text, model=req.model or "x-test-deterministic", provider_kind=self.kind,
                          input_tokens=n_in, output_tokens=len(text) // 4, latency_ms=0.0,
                          stop_reason="end_turn", data=data)
