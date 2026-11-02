"""Idempotent seed data: roles, permissions, the source Intellect framework, provider registry
entries (inactive until configured), quantum algorithms, and the scenario library."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Permission, Role

PERMISSIONS = {
    "executions.run": "Submit problems and run executions",
    "executions.read_all": "Read every user's executions",
    "scenarios.read": "Browse published scenarios",
    "scenarios.write": "Create, edit, publish and retire scenarios",
    "ai.read": "View AI providers, models and usage",
    "ai.write": "Configure AI providers, models, credentials and routing",
    "quantum.read": "View quantum providers, backends, jobs",
    "quantum.write": "Configure quantum providers, backends, algorithms, credentials",
    "intellect.read": "View frameworks, layers, rules, runs",
    "intellect.write": "Edit draft frameworks, layers and custom rules; import frameworks",
    "intellect.publish": "Approve, publish, reject and roll back framework versions",
    "intellect.test": "Use the Intellect Testing Laboratory",
    "policies.write": "Edit orchestration policies and system settings",
    "users.read": "View users",
    "users.write": "Create, edit and deactivate users and assign roles",
    "audit.read": "Read audit and security logs",
    "dashboard.read": "View the administration dashboard",
}

ROLES = {
    "super_admin": ("Super Administrator", 100, set(PERMISSIONS)),
    "admin": ("Administrator", 80, set(PERMISSIONS)),
    "researcher": ("Researcher", 50, {"executions.run", "scenarios.read", "ai.read", "quantum.read",
                                      "intellect.read", "intellect.test", "dashboard.read"}),
    "developer": ("Developer", 50, {"executions.run", "scenarios.read", "scenarios.write", "ai.read",
                                    "quantum.read", "intellect.read", "intellect.write", "intellect.test",
                                    "dashboard.read"}),
    "standard": ("Standard User", 20, {"executions.run", "scenarios.read"}),
    "read_only": ("Read-only User", 10, {"scenarios.read"}),
}
# Administrators cannot create or promote super administrators; enforced in the users API.


def seed_roles(db: Session) -> None:
    perms = {p.code: p for p in db.scalars(select(Permission))}
    for code, desc in PERMISSIONS.items():
        if code not in perms:
            perms[code] = Permission(code=code, description=desc)
            db.add(perms[code])
    db.flush()
    for code, (name, rank, granted) in ROLES.items():
        role = db.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, name=name, rank=rank)
            db.add(role)
        role.permissions = [perms[c] for c in sorted(granted)]
    db.flush()


def seed_all(db: Session) -> None:
    from .ai.seed import seed_ai
    from .intellect.frameworks import seed_source_framework
    from .quantum.seed import seed_quantum
    from .scenarios.seed import seed_scenarios

    seed_roles(db)
    seed_source_framework(db)
    seed_ai(db)
    seed_quantum(db)
    seed_scenarios(db)
    db.flush()
