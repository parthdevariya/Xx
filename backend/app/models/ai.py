from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, utcnow


class AICapability(Base):
    __tablename__ = "ai_capabilities"
    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")


class AIProvider(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_providers"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(48))  # adapter key: anthropic | openai_compatible | deterministic_test
    base_url: Mapped[str] = mapped_column(String(400), default="")
    auth_scheme: Mapped[str] = mapped_column(String(32), default="bearer")  # bearer | x-api-key | api-key | none
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_s: Mapped[float] = mapped_column(Float, default=60.0)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)
    config: Mapped[dict] = mapped_column(default=dict)
    health_status: Mapped[str] = mapped_column(String(24), default="unknown")  # unknown|healthy|degraded|down|unconfigured
    last_latency_ms: Mapped[float | None] = mapped_column(Float)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    models: Mapped[list["AIModel"]] = relationship(back_populates="provider", cascade="all, delete-orphan",
                                                   lazy="selectin")
    credential: Mapped["AICredential | None"] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                            uselist=False)


class AIModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_models"
    __table_args__ = (UniqueConstraint("provider_id", "model_id"),)
    provider_id: Mapped[str] = mapped_column(ForeignKey("ai_providers.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(160), default="")
    capabilities: Mapped[list] = mapped_column(default=list)  # ai_capabilities codes
    modalities: Mapped[list] = mapped_column(default=lambda: ["text"])
    context_window: Mapped[int] = mapped_column(Integer, default=128000)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    input_cost_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    output_cost_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    quality_rank: Mapped[int] = mapped_column(Integer, default=50)  # 0..100, admin-set
    latency_class: Mapped[str] = mapped_column(String(16), default="medium")  # fast|medium|slow
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    provider: Mapped[AIProvider] = relationship(back_populates="models")


class AICredential(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_credentials"
    provider_id: Mapped[str] = mapped_column(ForeignKey("ai_providers.id", ondelete="CASCADE"), unique=True)
    secret_encrypted: Mapped[str] = mapped_column(Text)
    hint: Mapped[str] = mapped_column(String(32), default="")
    extra_encrypted: Mapped[str] = mapped_column(Text, default="")  # e.g. Azure deployment / org id


class AIRoutingPolicy(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_routing_policies"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # {"weights": {"quality":0.5,"cost":0.25,"latency":0.25}, "deny_providers": [], "allow_providers": [],
    #  "max_cost_per_call_usd": 0.5, "category_overrides": {"mathematical": {"min_quality": 70}}}
    rules: Mapped[dict] = mapped_column(default=dict)


class AIExecutionLog(IdMixin, Base):
    __tablename__ = "ai_execution_logs"
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id", ondelete="SET NULL"), index=True)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("ai_providers.id", ondelete="SET NULL"))
    model_id: Mapped[str] = mapped_column(String(160), default="")
    provider_kind: Mapped[str] = mapped_column(String(48), default="")
    purpose: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(16))  # ok|error|fallback
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
