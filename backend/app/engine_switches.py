"""Master Control engine switchboard: one place that turns engines and Intellect sub-sections on or off.

Enforced in the backend (AI service, planner, Intellect pipeline, Swarm), not only in the UI.
Protected Intellect guardrails keep running even when their layer is switched off.
"""

from __future__ import annotations

import copy

from sqlalchemy.orm import Session

from .models import SystemSetting

KEY = "engine_switches"
DEFAULTS = {
    "ai": True,
    "intellect": True,
    "quantum": True,
    "swarm": False,
    "guardrail_audit": True,
    "layers": {},  # {"FD": false} — layer code → enabled
    "swarm_config": {"agents": 14, "rounds": 4},
}


def get_switches(db: Session) -> dict:
    row = db.get(SystemSetting, KEY)
    out = copy.deepcopy(DEFAULTS)
    if row and row.value:
        for k, v in row.value.items():
            if k in ("layers", "swarm_config") and isinstance(v, dict):
                out[k] = {**out[k], **v}
            elif k in out:
                out[k] = v
    return out


def set_switches(db: Session, changes: dict, user_id: str | None) -> dict:
    current = get_switches(db)
    for k, v in changes.items():
        if k not in DEFAULTS:
            raise ValueError(f"unknown switch {k!r}")
        if k in ("layers", "swarm_config"):
            if not isinstance(v, dict):
                raise ValueError(f"{k} must be an object")
            current[k] = {**current[k], **v}
        else:
            current[k] = bool(v)
    cfg = current["swarm_config"]
    cfg["agents"] = max(4, min(int(cfg.get("agents", 14)), 40))
    cfg["rounds"] = max(1, min(int(cfg.get("rounds", 4)), 10))
    row = db.get(SystemSetting, KEY)
    if row is None:
        row = SystemSetting(key=KEY, value={}, description="Master Control engine switchboard")
        db.add(row)
    row.value = current
    row.updated_by = user_id
    db.flush()
    return current


def layers_off(db: Session) -> dict:
    """Layer switches to merge into every Intellect run (only the ones switched off)."""
    return {code: False for code, on in get_switches(db)["layers"].items() if on is False}


OFF_REASON = {
    "ai": "the AI engine is switched OFF in Master Control",
    "intellect": "the Intellect engine is switched OFF in Master Control",
    "quantum": "the Quantum engine is switched OFF in Master Control",
    "swarm": "Swarm Intelligence is switched OFF in Master Control",
}
