"""Execution events. Every message the Command Centre shows comes from a row written here."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import Execution, ExecutionEvent


def emit(db: Session, execution: Execution, engine: str, type_: str, message: str, data: dict | None = None,
         commit: bool = True) -> ExecutionEvent:
    # Atomic increment so concurrent writers (API cancel + worker) never collide on seq.
    db.execute(update(Execution).where(Execution.id == execution.id)
               .values(event_seq=Execution.event_seq + 1))
    db.flush()
    db.refresh(execution, ["event_seq"])
    ev = ExecutionEvent(execution_id=execution.id, seq=execution.event_seq, engine=engine, type=type_,
                        message=message, data=data or {})
    db.add(ev)
    if commit:
        db.commit()
    else:
        db.flush()
    return ev


def emitter(db: Session, execution: Execution, engine: str):
    def _emit(type_: str, message: str, data: dict | None = None):
        emit(db, execution, engine, type_, message, data)
    return _emit
