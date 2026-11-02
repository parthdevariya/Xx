from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, utcnow


class BackgroundJob(IdMixin, Base):
    __tablename__ = "background_jobs"
    kind: Mapped[str] = mapped_column(String(48), index=True)  # execution | intellect_regression | health_sweep
    payload: Mapped[dict] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|done|failed|cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    locked_by: Mapped[str] = mapped_column(String(120), default="")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(Text, default="")
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"), index=True)


class ProviderHealth(IdMixin, Base):
    __tablename__ = "provider_health"
    provider_type: Mapped[str] = mapped_column(String(16))  # ai | quantum
    provider_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class UsageRecord(IdMixin, Base):
    __tablename__ = "usage_records"
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(32))  # ai_tokens_in | ai_tokens_out | quantum_shots | execution
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(16), default="")
    provider: Mapped[str] = mapped_column(String(120), default="")


class CostRecord(IdMixin, Base):
    __tablename__ = "cost_records"
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(16))  # ai | quantum
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(IdMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
