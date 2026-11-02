from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, utcnow

EXECUTION_CLASSES = ("hardware", "cloud_simulator", "local_simulator", "classical", "cached", "test")


class QuantumCapability(Base):
    __tablename__ = "quantum_capabilities"
    code: Mapped[str] = mapped_column(String(48), primary_key=True)  # qubo, ising, pauli_sum, oracle
    description: Mapped[str] = mapped_column(Text, default="")


class QuantumProvider(IdMixin, TimestampMixin, Base):
    __tablename__ = "quantum_providers"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    vendor: Mapped[str] = mapped_column(String(32))  # local | ibm | aws | azure | dwave | google | cudaq | pennylane
    endpoint: Mapped[str] = mapped_column(String(400), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict] = mapped_column(default=dict)
    sdk_available: Mapped[bool] = mapped_column(Boolean, default=False)
    health_status: Mapped[str] = mapped_column(String(24), default="unknown")
    health_detail: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_execution_s: Mapped[float] = mapped_column(Float, default=600.0)
    max_cost_per_job_usd: Mapped[float] = mapped_column(Float, default=0.0)
    backends: Mapped[list["QuantumBackend"]] = relationship(back_populates="provider",
                                                            cascade="all, delete-orphan", lazy="selectin")
    credential: Mapped["QuantumCredential | None"] = relationship(cascade="all, delete-orphan",
                                                                 lazy="selectin", uselist=False)


class QuantumBackend(IdMixin, TimestampMixin, Base):
    __tablename__ = "quantum_backends"
    __table_args__ = (CheckConstraint("modality IN ('gate_hardware','annealer','cloud_simulator','local_simulator','classical')",
                                      name="ck_qbackend_modality"),)
    provider_id: Mapped[str] = mapped_column(ForeignKey("quantum_providers.id", ondelete="CASCADE"), index=True)
    backend_key: Mapped[str] = mapped_column(String(120), unique=True)  # qos backend id, e.g. local.sv
    name: Mapped[str] = mapped_column(String(160))
    modality: Mapped[str] = mapped_column(String(24))
    is_hardware: Mapped[bool] = mapped_column(Boolean, default=False)
    max_qubits: Mapped[int] = mapped_column(Integer, default=0)
    supported_formulations: Mapped[list] = mapped_column(default=list)
    supported_algorithms: Mapped[list] = mapped_column(default=list)
    max_shots: Mapped[int] = mapped_column(Integer, default=100000)
    default_shots: Mapped[int] = mapped_column(Integer, default=1024)
    pricing: Mapped[dict] = mapped_column(default=dict)
    two_qubit_error: Mapped[float | None] = mapped_column(Float)
    queue_depth: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="unknown")  # online|offline|unknown|unavailable
    status_detail: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    provider: Mapped[QuantumProvider] = relationship(back_populates="backends")


class QuantumAlgorithm(IdMixin, TimestampMixin, Base):
    __tablename__ = "quantum_algorithms"
    key: Mapped[str] = mapped_column(String(64), unique=True)  # qaoa | vqe | grover | ...
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    problem_compatibility: Mapped[list] = mapped_column(default=list)
    input_schema: Mapped[dict] = mapped_column(default=dict)
    output_schema: Mapped[dict] = mapped_column(default=dict)
    backend_requirements: Mapped[dict] = mapped_column(default=dict)
    resource_requirements: Mapped[dict] = mapped_column(default=dict)
    execution_config: Mapped[dict] = mapped_column(default=dict)
    known_limitations: Mapped[list] = mapped_column(default=list)
    benchmark_methodology: Mapped[str] = mapped_column(Text, default="")
    # Admin-entered, citable evidence of benefit for a problem class and size range.
    # Empty by default: without it the selection engine never returns "quantum_recommended".
    benefit_evidence: Mapped[list] = mapped_column(default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class QuantumCredential(IdMixin, TimestampMixin, Base):
    __tablename__ = "quantum_credentials"
    provider_id: Mapped[str] = mapped_column(ForeignKey("quantum_providers.id", ondelete="CASCADE"), unique=True)
    secret_encrypted: Mapped[str] = mapped_column(Text)
    hint: Mapped[str] = mapped_column(String(32), default="")
    extra_encrypted: Mapped[str] = mapped_column(Text, default="")


class QuantumJob(IdMixin, Base):
    __tablename__ = "quantum_jobs"
    __table_args__ = (CheckConstraint(
        "execution_class IN ('hardware','cloud_simulator','local_simulator','classical','cached','test')",
        name="ck_qjob_class"),)
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id", ondelete="SET NULL"), index=True)
    backend_key: Mapped[str] = mapped_column(String(120))
    algorithm: Mapped[str] = mapped_column(String(64))
    execution_class: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|completed|failed|cancelled
    provider_job_id: Mapped[str] = mapped_column(String(200), default="")
    qubits: Mapped[int] = mapped_column(Integer, default=0)
    circuit_depth: Mapped[int] = mapped_column(Integer, default=0)
    shots: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wall_time_s: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    result: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=1)


class QuantumExecutionLog(IdMixin, Base):
    __tablename__ = "quantum_execution_logs"
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("quantum_jobs.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(12), default="info")
    message: Mapped[str] = mapped_column(Text)
