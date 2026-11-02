"""Database-level protection of Intellect guardrails (triggers).

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import install_protection_triggers
    install_protection_triggers(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for t in ("trg_protected_rule_no_update", "trg_protected_rule_no_delete", "trg_protected_condition_guard"):
            op.execute(f"DROP TRIGGER IF EXISTS {t}")
    else:
        op.execute("DROP TRIGGER IF EXISTS trg_protected_rule ON intellect_rules")
        op.execute("DROP TRIGGER IF EXISTS trg_protected_condition ON intellect_rule_conditions")
        op.execute("DROP FUNCTION IF EXISTS x_protect_rule()")
        op.execute("DROP FUNCTION IF EXISTS x_protect_condition()")
