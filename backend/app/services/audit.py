from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from ..models import AuditLog, User

SENSITIVE_KEYS = {"password", "secret", "api_key", "token", "credential", "key"}


def _scrub(d):
    if isinstance(d, dict):
        return {k: ("[redacted]" if any(s in k.lower() for s in SENSITIVE_KEYS) else _scrub(v)) for k, v in d.items()}
    if isinstance(d, list):
        return [_scrub(x) for x in d]
    return d


def audit(db: Session, *, actor: User | None, category: str, action: str, target_type: str = "",
          target_id: str = "", outcome: str = "success", detail: dict | None = None,
          request: Request | None = None) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, actor_email=actor.email if actor else "",
                    category=category, action=action, target_type=target_type, target_id=str(target_id or ""),
                    outcome=outcome, detail=_scrub(detail or {}),
                    ip=(request.client.host if request and request.client else "")))
