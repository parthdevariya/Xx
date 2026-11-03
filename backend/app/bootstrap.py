"""Start-up: migrate, seed, create the bootstrap super administrator."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from .config import get_settings
from .db import get_engine, session_scope
from .models import Role, User
from .security import hash_password, validate_password_strength

log = logging.getLogger("x.bootstrap")
BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


def ensure_admin() -> None:
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    problem = validate_password_strength(s.bootstrap_admin_password)
    if problem:
        log.error("X_BOOTSTRAP_ADMIN_PASSWORD rejected: %s", problem)
        return
    with session_scope() as db:
        if db.scalar(select(User).where(User.email == s.bootstrap_admin_email.lower())):
            return
        role = db.scalar(select(Role).where(Role.code == "super_admin"))
        db.add(User(email=s.bootstrap_admin_email.lower(), display_name="Super Administrator",
                    password_hash=hash_password(s.bootstrap_admin_password), role_id=role.id))
        log.info("bootstrap super administrator created: %s", s.bootstrap_admin_email)


def bootstrap(migrate: bool = True) -> None:
    problems = get_settings().validate_for_production()
    if problems:
        raise RuntimeError("unsafe production configuration:\n  - " + "\n  - ".join(problems))
    print("[x.bootstrap] configuration ok; connecting to the database", flush=True)
    from sqlalchemy import text
    with get_engine().connect() as conn:
        conn.execute(text("select 1"))
    print(f"[x.bootstrap] database reachable ({get_engine().dialect.name})", flush=True)
    if migrate:
        print("[x.bootstrap] running migrations", flush=True)
        run_migrations()
        print("[x.bootstrap] migrations complete", flush=True)
    from .seed import seed_all
    print("[x.bootstrap] seeding (framework, providers, scenarios)", flush=True)
    with session_scope() as db:
        seed_all(db)
    print("[x.bootstrap] seed complete", flush=True)
    ensure_admin()
    print("[x.bootstrap] ready", flush=True)
