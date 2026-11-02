"""Deterministic conflict resolution under the source-defined hierarchy.

    1 hard limits and always-on guardrails   (protected rules)
    2 truth (RL, IE)
    3 ethics (MC, judged by VL)
    4 judgment (VL, with inputs from TP, UL, FD)
    5 clarity (CB)
    6 comfort and delivery (HM, EFV, settings)

A rule's tier is 1 if it is protected, otherwise its layer's tier. Higher tier (lower number) wins;
within a tier the lower P number wins; an exact tie is left to the judgment stage (VL).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import IntellectRule

HARD_LIMIT_NOTE = "Moral Compass Hard Limits are never weighed against anything."


@dataclass
class Resolution:
    winner: str
    hierarchy_step: str
    decision: str
    tie: bool = False


def effective_tier(rule: IntellectRule) -> int:
    return 1 if rule.is_protected else rule.layer.tier


def _tier_label(hierarchy: list[dict], tier: int) -> str:
    item = next((h for h in hierarchy if h["rank"] == tier), None)
    return f"rank {tier}: {item['raw']}" if item else f"rank {tier}"


def resolve(rules: list[IntellectRule], hierarchy: list[dict], hard_limits: set[str] | None = None) -> Resolution:
    if len(rules) < 2:
        raise ValueError("a conflict needs at least two rules")
    hard_limits = hard_limits or set()
    ranked = sorted(rules, key=lambda r: (effective_tier(r), r.priority))
    best, second = ranked[0], ranked[1]
    t_best, t_second = effective_tier(best), effective_tier(second)
    losers = ", ".join(r.rule_code for r in ranked[1:])
    if t_best < t_second:
        step = _tier_label(hierarchy, t_best)
        note = f" {HARD_LIMIT_NOTE}" if best.rule_code in hard_limits else ""
        return Resolution(best.rule_code, step,
                          f"{best.rule_code} ({_tier_label(hierarchy, t_best)}) outranks {losers} "
                          f"({_tier_label(hierarchy, t_second)}).{note}")
    if best.priority < second.priority:
        return Resolution(best.rule_code, f"{_tier_label(hierarchy, t_best)}; then priority",
                          f"Same hierarchy rank; {best.rule_code} (P{best.priority}) applies before {losers} "
                          f"(P{second.priority}).")
    return Resolution(best.rule_code if best.layer.code == "VL" else "VL",
                      f"{_tier_label(hierarchy, t_best)}; equal priority",
                      f"{best.rule_code} and {losers} share rank and priority P{best.priority}; the judgment "
                      "stage (VL) weighs them, and HM/EFV may change only how the result is said.", tie=True)
