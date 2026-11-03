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
    "swarm_config": {
        "agents": 14, "rounds": 4,
        "platforms": {"feed": True, "forum": True},
        "allowed_actions": ["CREATE_POST", "QUOTE_POST", "CREATE_COMMENT", "LIKE_POST", "DISLIKE_POST", "REPOST",
                            "FOLLOW", "MUTE", "DO_NOTHING"],
        "memory_window": 6, "visible_posts": 16, "max_entities": 16,
        "stage_models": {"graph": None, "setup": None, "round": None, "report": None, "chat": None},
        "stage_effort": {"graph": "low", "setup": "low", "round": "low", "report": "medium", "chat": "low"},
        "max_cost_usd": 2.0,
        "default_variable": "",
        "persona_guidance": "",
        "memory_backend": "internal",  # internal | zep
    },
}

ACTIONS = ["CREATE_POST", "QUOTE_POST", "CREATE_COMMENT", "LIKE_POST", "DISLIKE_POST", "REPOST", "FOLLOW", "MUTE",
           "DO_NOTHING"]
STAGES = ("graph", "setup", "round", "report", "chat")
EFFORTS = ("low", "medium", "high")


def _validate_swarm(cfg: dict) -> dict:
    out = copy.deepcopy(DEFAULTS["swarm_config"])
    for k, v in cfg.items():
        if k not in out:
            raise ValueError(f"unknown swarm setting {k!r}")
        if isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    out["agents"] = max(4, min(int(out["agents"]), 40))
    out["rounds"] = max(1, min(int(out["rounds"]), 10))
    out["memory_window"] = max(1, min(int(out["memory_window"]), 20))
    out["visible_posts"] = max(4, min(int(out["visible_posts"]), 40))
    out["max_entities"] = max(4, min(int(out["max_entities"]), 30))
    out["max_cost_usd"] = max(0.0, float(out["max_cost_usd"]))
    out["platforms"] = {"feed": bool(out["platforms"].get("feed", True)), "forum": bool(out["platforms"].get("forum", True))}
    if not any(out["platforms"].values()):
        raise ValueError("enable at least one platform")
    acts = [a for a in out["allowed_actions"] if a in ACTIONS]
    if not acts or not any(a in acts for a in ("CREATE_POST", "QUOTE_POST", "CREATE_COMMENT")):
        raise ValueError("allowed actions must include at least one writing action (post, quote or comment)")
    if "DO_NOTHING" not in acts:
        acts.append("DO_NOTHING")
    out["allowed_actions"] = acts
    out["stage_models"] = {s: (out["stage_models"].get(s) or None) for s in STAGES}
    out["stage_effort"] = {s: (out["stage_effort"].get(s) if out["stage_effort"].get(s) in EFFORTS else "low")
                           for s in STAGES}
    if out["memory_backend"] not in ("internal", "zep"):
        raise ValueError("memory_backend must be internal or zep")
    out["default_variable"] = str(out["default_variable"])[:2000]
    out["persona_guidance"] = str(out["persona_guidance"])[:2000]
    return out


def get_switches(db: Session) -> dict:
    row = db.get(SystemSetting, KEY)
    out = copy.deepcopy(DEFAULTS)
    if row and row.value:
        for k, v in row.value.items():
            if k == "swarm_config" and isinstance(v, dict):
                try:
                    out[k] = _validate_swarm(v)
                except (ValueError, TypeError):
                    out[k] = {**out[k], **v}
            elif k == "layers" and isinstance(v, dict):
                out[k] = {**out[k], **v}
            elif k in out:
                out[k] = v
    return out


def set_switches(db: Session, changes: dict, user_id: str | None) -> dict:
    current = get_switches(db)
    for k, v in changes.items():
        if k not in DEFAULTS:
            raise ValueError(f"unknown switch {k!r}")
        if k == "swarm_config":
            if not isinstance(v, dict):
                raise ValueError("swarm_config must be an object")
            current[k] = _validate_swarm({**current[k], **v})
        elif k == "layers":
            if not isinstance(v, dict):
                raise ValueError("layers must be an object")
            current[k] = {**current[k], **v}
        else:
            current[k] = bool(v)
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
