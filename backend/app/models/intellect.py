"""Intellect Engine data model.

Protected-rule integrity is enforced in the database, not only in services:

* CHECK  ck_rule_protected_active   protected rules can never be inactive
* CHECK  ck_rule_protected_source   only source rules can be protected (custom rules can't reach tier 1)
* CHECK  ck_layer_tier              layer tiers are 2..6; tier 1 belongs to guardrails alone
* CHECK  ck_refdoc_not_executable   reference-library documents can never be executable
* TRIGGERS (see migration 0002)     reject UPDATE of protected rule content or DELETE of protected rules
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, utcnow


class IntellectFramework(IdMixin, TimestampMixin, Base):
    __tablename__ = "intellect_frameworks"
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    # A framework derived from a source pack must keep that source intact to publish.
    source_pack: Mapped[str] = mapped_column(String(80), default="")  # e.g. "x_layers_v0_3B"
    active_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("intellect_versions.id", ondelete="SET NULL", use_alter=True, name="fk_fw_active_version"))
    versions: Mapped[list["IntellectVersion"]] = relationship(
        back_populates="framework", foreign_keys="IntellectVersion.framework_id",
        cascade="all, delete-orphan", order_by="IntellectVersion.created_at")


class IntellectVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "intellect_versions"
    __table_args__ = (
        UniqueConstraint("framework_id", "label"),
        CheckConstraint("status IN ('draft','in_review','published','archived','rejected')", name="ck_version_status"),
    )
    framework_id: Mapped[str] = mapped_column(ForeignKey("intellect_frameworks.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("intellect_versions.id", ondelete="SET NULL"))
    # Ordered execution sequence: [{"position":1,"layer":"CB","mode":"main","source_label":"CB","bound_to":null}, ...]
    pipeline: Mapped[list] = mapped_column(default=list)
    # Conflict hierarchy: [{"rank":1,"label":"...","layers":[...],"raw":"..."}, ...]
    hierarchy: Mapped[list] = mapped_column(default=list)
    hierarchy_note: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(default=dict)  # title, preamble, legend, footer, source file hash...
    notes: Mapped[str] = mapped_column(Text, default="")
    validation: Mapped[dict] = mapped_column(default=dict)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    framework: Mapped[IntellectFramework] = relationship(back_populates="versions", foreign_keys=[framework_id])
    layers: Mapped[list["IntellectLayer"]] = relationship(back_populates="version", cascade="all, delete-orphan",
                                                          order_by="IntellectLayer.position", lazy="selectin")
    rules: Mapped[list["IntellectRule"]] = relationship(back_populates="version", cascade="all, delete-orphan",
                                                        order_by="IntellectRule.position", lazy="selectin")


class IntellectLayer(IdMixin, TimestampMixin, Base):
    __tablename__ = "intellect_layers"
    __table_args__ = (
        UniqueConstraint("version_id", "code"),
        CheckConstraint("tier BETWEEN 2 AND 6", name="ck_layer_tier"),
        CheckConstraint("origin IN ('source','custom','imported')", name="ck_layer_origin"),
    )
    version_id: Mapped[str] = mapped_column(ForeignKey("intellect_versions.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(160))
    question: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tier: Mapped[int] = mapped_column(Integer)
    tier_basis: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(16), default="custom")
    enabled_by_default: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    declared_rule_count: Mapped[int | None] = mapped_column(Integer)
    source_page: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[IntellectVersion] = relationship(back_populates="layers")


class IntellectRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "intellect_rules"
    __table_args__ = (
        UniqueConstraint("version_id", "rule_code"),
        CheckConstraint("NOT is_protected OR is_active", name="ck_rule_protected_active"),
        CheckConstraint("NOT is_protected OR origin = 'source'", name="ck_rule_protected_source"),
        CheckConstraint("priority BETWEEN 1 AND 4", name="ck_rule_priority"),
        CheckConstraint("origin IN ('source','custom','imported')", name="ck_rule_origin"),
    )
    version_id: Mapped[str] = mapped_column(ForeignKey("intellect_versions.id", ondelete="CASCADE"), index=True)
    layer_id: Mapped[str] = mapped_column(ForeignKey("intellect_layers.id", ondelete="CASCADE"), index=True)
    rule_code: Mapped[str] = mapped_column(String(16))
    number: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    applies_when: Mapped[str] = mapped_column(Text, default="")
    not_when: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer)
    provenance: Mapped[str] = mapped_column(String(16), default="")
    source_marker: Mapped[str | None] = mapped_column(String(64))
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    origin: Mapped[str] = mapped_column(String(16), default="custom")
    position: Mapped[int] = mapped_column(Integer, default=0)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_sha256: Mapped[str] = mapped_column(String(64), default="")
    source_block: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[IntellectVersion] = relationship(back_populates="rules")
    layer: Mapped[IntellectLayer] = relationship(lazy="selectin")


class IntellectRuleCondition(IdMixin, TimestampMixin, Base):
    """Additional structured conditions beyond the rule's own applies_when/not_when text.

    Source conditions stay on the rule row verbatim. Rows here are admin-authored refinements
    for custom rules (e.g. restrict to a scenario category); they never alter protected rules.
    """
    __tablename__ = "intellect_rule_conditions"
    __table_args__ = (CheckConstraint("kind IN ('applies_when','not_when','scope')", name="ck_cond_kind"),)
    rule_id: Mapped[str] = mapped_column(ForeignKey("intellect_rules.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(default=dict)


class IntellectDependency(IdMixin, Base):
    __tablename__ = "intellect_dependencies"
    __table_args__ = (UniqueConstraint("rule_id", "depends_on_code", "kind"),)
    version_id: Mapped[str] = mapped_column(ForeignKey("intellect_versions.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("intellect_rules.id", ondelete="CASCADE"), index=True)
    depends_on_code: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(24), default="references")  # references|overrides|defers_to|custom
    origin: Mapped[str] = mapped_column(String(24), default="extracted")  # extracted from source text | admin
    context: Mapped[str] = mapped_column(Text, default="")  # the source sentence containing the reference


class IntellectGuardrail(IdMixin, Base):
    __tablename__ = "intellect_guardrails"
    __table_args__ = (UniqueConstraint("version_id", "rule_code"),)
    version_id: Mapped[str] = mapped_column(ForeignKey("intellect_versions.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("intellect_rules.id", ondelete="CASCADE"))
    rule_code: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(24))  # hard_limit | always_on
    source_basis: Mapped[str] = mapped_column(Text, default="")


class IntellectEvidence(IdMixin, Base):
    """Provenance legend codes as defined by the source (E, B, S, P, +G, G3, G2, P1-P4)."""
    __tablename__ = "intellect_evidence"
    __table_args__ = (UniqueConstraint("version_id", "code"),)
    version_id: Mapped[str] = mapped_column(ForeignKey("intellect_versions.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(16))
    meaning: Mapped[str] = mapped_column(Text)


class IntellectExecutionPolicy(IdMixin, TimestampMixin, Base):
    __tablename__ = "intellect_execution_policies"
    framework_id: Mapped[str] = mapped_column(ForeignKey("intellect_frameworks.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    layer_switches: Mapped[dict] = mapped_column(default=dict)  # {"FD": false}; protected rules ignore switches
    rule_switches: Mapped[dict] = mapped_column(default=dict)   # only non-protected rules honoured
    settings: Mapped[dict] = mapped_column(default=dict)


class IntellectTestCase(IdMixin, TimestampMixin, Base):
    __tablename__ = "intellect_test_cases"
    framework_id: Mapped[str] = mapped_column(ForeignKey("intellect_frameworks.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    layer_switches: Mapped[dict] = mapped_column(default=dict)
    # {"must_apply": ["RL-03"], "must_not_apply": [], "must_contain": [], "must_not_contain": [], "max_questions": 1}
    expected: Mapped[dict] = mapped_column(default=dict)
    origin: Mapped[str] = mapped_column(String(24), default="admin")  # admin | import_suggestion | source_library
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_run_id: Mapped[str | None] = mapped_column(String(32))
    last_outcome: Mapped[str] = mapped_column(String(16), default="never_run")  # pass|fail|error|never_run


class IntellectRun(IdMixin, Base):
    """One execution of a framework version (from an execution, the lab, or a regression run)."""
    __tablename__ = "intellect_runs"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version_id: Mapped[str] = mapped_column(ForeignKey("intellect_versions.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id", ondelete="SET NULL"), index=True)
    test_case_id: Mapped[str | None] = mapped_column(ForeignKey("intellect_test_cases.id", ondelete="SET NULL"))
    origin: Mapped[str] = mapped_column(String(16), default="execution")  # execution | lab | regression
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    prompt: Mapped[str] = mapped_column(Text, default="")
    layer_switches: Mapped[dict] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|completed|failed|unavailable
    assessment_mode: Mapped[str] = mapped_column(String(24), default="model")  # model | not_assessed | test
    final_output: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[dict] = mapped_column(default=dict)  # counts by state, guardrail audit, preset
    error: Mapped[str] = mapped_column(Text, default="")


class IntellectExecutionLog(IdMixin, Base):
    """One row per pipeline stage of a run."""
    __tablename__ = "intellect_execution_logs"
    run_id: Mapped[str] = mapped_column(ForeignKey("intellect_runs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    layer: Mapped[str] = mapped_column(String(8))
    mode: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))  # completed | skipped | failed | protected_only
    rule_states: Mapped[list] = mapped_column(default=list)  # [{"rule":"CB-01","state":"applied","reason":"..."}]
    output: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(default=dict)
    model: Mapped[str] = mapped_column(String(160), default="")
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntellectConflict(IdMixin, Base):
    __tablename__ = "intellect_conflicts"
    run_id: Mapped[str] = mapped_column(ForeignKey("intellect_runs.id", ondelete="CASCADE"), index=True)
    stage_position: Mapped[int] = mapped_column(Integer)
    rule_codes: Mapped[list] = mapped_column(default=list)
    layers: Mapped[list] = mapped_column(default=list)
    description: Mapped[str] = mapped_column(Text)
    hierarchy_step: Mapped[str] = mapped_column(Text)
    winner: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(Text)
    detected_by: Mapped[str] = mapped_column(String(16), default="model")  # model | static


class IntellectRuleHistory(IdMixin, Base):
    __tablename__ = "intellect_rule_history"
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("intellect_rules.id", ondelete="SET NULL"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("intellect_versions.id", ondelete="CASCADE"), index=True)
    rule_code: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(24))  # created|updated|activated|deactivated|deleted|imported
    before: Mapped[dict] = mapped_column(default=dict)
    after: Mapped[dict] = mapped_column(default=dict)
    changed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntellectReferenceDocument(IdMixin, TimestampMixin, Base):
    __tablename__ = "intellect_reference_documents"
    __table_args__ = (CheckConstraint("executable = false", name="ck_refdoc_not_executable"),)
    framework_id: Mapped[str] = mapped_column(ForeignKey("intellect_frameworks.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    use_for: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")  # empty until the file itself is uploaded
    executable: Mapped[bool] = mapped_column(Boolean, default=False)


class IntellectImport(IdMixin, TimestampMixin, Base):
    __tablename__ = "intellect_imports"
    framework_id: Mapped[str | None] = mapped_column(ForeignKey("intellect_frameworks.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(8))
    file_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|rejected|failed
    report: Mapped[dict] = mapped_column(default=dict)
    draft_version_id: Mapped[str | None] = mapped_column(ForeignKey("intellect_versions.id", ondelete="SET NULL"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
