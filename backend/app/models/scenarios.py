from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin

EXECUTION_MODES = ("ai_only", "ai_intellect", "intellect_vs_ai", "classical", "quantum", "classical_quantum",
                   "ai_classical", "classical_intellect", "ai_quantum", "hybrid", "benchmark")


class ScenarioCategory(IdMixin, TimestampMixin, Base):
    __tablename__ = "scenario_categories"
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Mandatory notice shown on every scenario in this category (e.g. healthcare: not medical advice).
    notice: Mapped[str] = mapped_column(Text, default="")


class Scenario(IdMixin, TimestampMixin, Base):
    __tablename__ = "scenarios"
    __table_args__ = (CheckConstraint("status IN ('draft','published','retired')", name="ck_scenario_status"),)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("scenario_categories.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenario_versions.id", ondelete="SET NULL", use_alter=True, name="fk_scenario_current_version"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[ScenarioCategory] = relationship(lazy="selectin")
    current_version: Mapped["ScenarioVersion | None"] = relationship(foreign_keys=[current_version_id],
                                                                    lazy="selectin", post_update=True)


class ScenarioVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "scenario_versions"
    __table_args__ = (UniqueConstraint("scenario_id", "version_no"),)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    tagline: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    problem_statement: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[str] = mapped_column(Text, default="")
    demonstrates: Mapped[str] = mapped_column(Text, default="")
    # Solver binding: qos template name (tsp, knapsack, portfolio, ...) or "" for reasoning-only scenarios.
    solver_template: Mapped[str] = mapped_column(String(64), default="")
    output_structure: Mapped[dict] = mapped_column(default=dict)
    recommended_models: Mapped[list] = mapped_column(default=list)
    recommended_framework_slug: Mapped[str] = mapped_column(String(80), default="")
    quantum_eligibility: Mapped[str] = mapped_column(String(32), default="evaluate")  # evaluate|never|simulation_only
    classical_config: Mapped[dict] = mapped_column(default=dict)
    benchmark_config: Mapped[dict] = mapped_column(default=dict)
    visualizations: Mapped[list] = mapped_column(default=list)
    engines: Mapped[list] = mapped_column(default=list)  # ["ai","intellect","classical","quantum"]
    expected_output: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class ScenarioInputSchema(IdMixin, TimestampMixin, Base):
    __tablename__ = "scenario_input_schemas"
    version_id: Mapped[str] = mapped_column(ForeignKey("scenario_versions.id", ondelete="CASCADE"), unique=True)
    # Form definition: [{"key":"capacity","label":"Capacity","type":"number","required":true,"min":1,...}]
    fields: Mapped[list] = mapped_column(default=list)
    defaults: Mapped[dict] = mapped_column(default=dict)
    # Optional JSON-schema-like constraints checked server-side before execution.
    validation: Mapped[dict] = mapped_column(default=dict)


class ScenarioExecutionPolicy(IdMixin, TimestampMixin, Base):
    __tablename__ = "scenario_execution_policies"
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), unique=True)
    allowed_modes: Mapped[list] = mapped_column(default=lambda: list(EXECUTION_MODES))
    default_mode: Mapped[str] = mapped_column(String(24), default="hybrid")
    max_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    allow_quantum_hardware: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
