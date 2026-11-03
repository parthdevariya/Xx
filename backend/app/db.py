from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _normalise_url(url: str) -> str:
    # Render supplies postgres://; SQLAlchemy + psycopg3 wants postgresql+psycopg://
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def make_engine(url: str) -> Engine:
    url = _normalise_url(url)
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()
        return eng
    # Fail fast instead of hanging forever if the database host is wrong or unreachable.
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10,
                         connect_args={"connect_timeout": 10})


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def set_engine(engine: Engine) -> None:
    """Used by tests to point the app at an isolated database."""
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def SessionLocal() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Database-level protection of Intellect guardrails
# ---------------------------------------------------------------------------

PROTECTED_COLUMNS = ("rule_code", "text", "applies_when", "not_when", "priority", "provenance",
                     "source_marker", "is_protected", "is_active", "layer_id", "origin", "source_sha256")

SQLITE_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_protected_rule_no_update
    BEFORE UPDATE ON intellect_rules
    FOR EACH ROW WHEN OLD.is_protected = 1 AND (
        NEW.rule_code IS NOT OLD.rule_code OR NEW.text IS NOT OLD.text OR
        NEW.applies_when IS NOT OLD.applies_when OR NEW.not_when IS NOT OLD.not_when OR
        NEW.priority IS NOT OLD.priority OR NEW.provenance IS NOT OLD.provenance OR
        NEW.source_marker IS NOT OLD.source_marker OR NEW.is_protected IS NOT OLD.is_protected OR
        NEW.is_active IS NOT OLD.is_active OR NEW.layer_id IS NOT OLD.layer_id OR
        NEW.origin IS NOT OLD.origin OR NEW.source_sha256 IS NOT OLD.source_sha256)
    BEGIN
        SELECT RAISE(ABORT, 'protected Intellect rule cannot be modified');
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_protected_rule_no_delete
    BEFORE DELETE ON intellect_rules
    FOR EACH ROW WHEN OLD.is_protected = 1
        AND (SELECT status FROM intellect_versions WHERE id = OLD.version_id) IN ('published','archived')
    BEGIN
        SELECT RAISE(ABORT, 'protected Intellect rule cannot be deleted');
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_protected_condition_guard
    BEFORE INSERT ON intellect_rule_conditions
    FOR EACH ROW WHEN (SELECT is_protected FROM intellect_rules WHERE id = NEW.rule_id) = 1
    BEGIN
        SELECT RAISE(ABORT, 'protected Intellect rule cannot receive extra conditions');
    END;
    """,
]

POSTGRES_TRIGGERS = [
    """
    CREATE OR REPLACE FUNCTION x_protect_rule() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        IF OLD.is_protected AND (SELECT status FROM intellect_versions WHERE id = OLD.version_id)
           IN ('published','archived') THEN
          RAISE EXCEPTION 'protected Intellect rule cannot be deleted';
        END IF;
        RETURN OLD;
      END IF;
      IF OLD.is_protected AND (
         NEW.rule_code IS DISTINCT FROM OLD.rule_code OR NEW.text IS DISTINCT FROM OLD.text OR
         NEW.applies_when IS DISTINCT FROM OLD.applies_when OR NEW.not_when IS DISTINCT FROM OLD.not_when OR
         NEW.priority IS DISTINCT FROM OLD.priority OR NEW.provenance IS DISTINCT FROM OLD.provenance OR
         NEW.source_marker IS DISTINCT FROM OLD.source_marker OR NEW.is_protected IS DISTINCT FROM OLD.is_protected OR
         NEW.is_active IS DISTINCT FROM OLD.is_active OR NEW.layer_id IS DISTINCT FROM OLD.layer_id OR
         NEW.origin IS DISTINCT FROM OLD.origin OR NEW.source_sha256 IS DISTINCT FROM OLD.source_sha256) THEN
        RAISE EXCEPTION 'protected Intellect rule cannot be modified';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_protected_rule ON intellect_rules;",
    """
    CREATE TRIGGER trg_protected_rule BEFORE UPDATE OR DELETE ON intellect_rules
    FOR EACH ROW EXECUTE FUNCTION x_protect_rule();
    """,
    """
    CREATE OR REPLACE FUNCTION x_protect_condition() RETURNS trigger AS $$
    BEGIN
      IF (SELECT is_protected FROM intellect_rules WHERE id = NEW.rule_id) THEN
        RAISE EXCEPTION 'protected Intellect rule cannot receive extra conditions';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_protected_condition ON intellect_rule_conditions;",
    """
    CREATE TRIGGER trg_protected_condition BEFORE INSERT ON intellect_rule_conditions
    FOR EACH ROW EXECUTE FUNCTION x_protect_condition();
    """,
]


def install_protection_triggers(conn) -> None:
    statements = SQLITE_TRIGGERS if conn.dialect.name == "sqlite" else POSTGRES_TRIGGERS
    for stmt in statements:
        conn.execute(text(stmt))
