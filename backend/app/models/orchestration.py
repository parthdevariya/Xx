from __future__ import annotations

from datetime import datetime

from sqlalchemy import (Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, utcnow

EXECUTION_STATUSES = ("planned", "queued", "running", "completed", "failed", "cancelled", "awaiting_input")


class ComputationalProblem(IdMixin, TimestampMixin, Base):
    __tablename__ = "computational_problems"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    inputs: Mapped[dict] = mapped_column(default=dict)  # structured inputs supplied by user/scenario
    attachments: Mapped[list] = mapped_column(default=list)  # [{"name","size","sha256","kind","extracted_chars"}]
    # Intake output: category, objectives, constraints, outputs, missing, complexity, template, method
    structured: Mapped[dict] = mapped_column(default=dict)


class ExecutionPlan(IdMixin, TimestampMixin, Base):
    __tablename__ = "execution_plans"
    problem_id: Mapped[str] = mapped_column(ForeignKey("computational_problems.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(24))
    steps: Mapped[list] = mapped_column(default=list)  # [{"key","engine","title","status":"planned|skipped","reason"}]
    quantum_decision: Mapped[dict] = mapped_column(default=dict)
    estimates: Mapped[dict] = mapped_column(default=dict)  # cost_usd, duration_s, ai_calls
    baselines: Mapped[list] = mapped_column(default=list)


class Execution(IdMixin, TimestampMixin, Base):
    __tablename__ = "executions"
    __table_args__ = (CheckConstraint(
        "status IN ('planned','queued','running','completed','failed','cancelled','awaiting_input')",
        name="ck_execution_status"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    problem_id: Mapped[str] = mapped_column(ForeignKey("computational_problems.id"), index=True)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("execution_plans.id", ondelete="SET NULL"))
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id", ondelete="SET NULL"), index=True)
    mode: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    framework_version_id: Mapped[str | None] = mapped_column(ForeignKey("intellect_versions.id", ondelete="SET NULL"))
    ai_provider: Mapped[str] = mapped_column(String(160), default="")
    ai_model: Mapped[str] = mapped_column(String(160), default="")
    quantum_backend: Mapped[str] = mapped_column(String(160), default="")
    algorithm: Mapped[str] = mapped_column(String(64), default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # live | cached | test — how the overall result was produced
    result_source: Mapped[str] = mapped_column(String(16), default="live")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resource_usage: Mapped[dict] = mapped_column(default=dict)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    final_output: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    event_seq: Mapped[int] = mapped_column(Integer, default=0)
    problem: Mapped[ComputationalProblem] = relationship(lazy="selectin")
    plan: Mapped[ExecutionPlan | None] = relationship(lazy="selectin")


class ExecutionEvent(IdMixin, Base):
    __tablename__ = "execution_events"
    __table_args__ = (UniqueConstraint("execution_id", "seq"),)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    engine: Mapped[str] = mapped_column(String(16), default="system")  # system|ai|intellect|quantum|classical
    type: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(default=dict)


class ExecutionArtifact(IdMixin, Base):
    __tablename__ = "execution_artifacts"
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # report_md | report_json | upload | chart_data
    name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100), default="application/json")
    content: Mapped[str] = mapped_column(Text, default="")
    storage_path: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionResult(IdMixin, Base):
    __tablename__ = "execution_results"
    __table_args__ = (CheckConstraint(
        "content_class IN ('computed','model_generated','assumption','estimate','cached','test')",
        name="ck_result_class"),)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"), index=True)
    step_key: Mapped[str] = mapped_column(String(64))
    engine: Mapped[str] = mapped_column(String(16))
    content_class: Mapped[str] = mapped_column(String(20))
    execution_class: Mapped[str] = mapped_column(String(24), default="")  # quantum provenance where relevant
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BenchmarkRun(IdMixin, Base):
    __tablename__ = "benchmark_runs"
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    input_sha256: Mapped[str] = mapped_column(String(64), default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    environment: Mapped[dict] = mapped_column(default=dict)
    methodology: Mapped[dict] = mapped_column(default=dict)
    conclusion: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[list["BenchmarkMetric"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class BenchmarkMetric(IdMixin, Base):
    __tablename__ = "benchmark_metrics"
    run_id: Mapped[str] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True)
    approach: Mapped[str] = mapped_column(String(48))
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float)
    text_value: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(24), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
