from __future__ import annotations

import os

os.environ.setdefault("X_ENV", "test")
os.environ.setdefault("X_EMBEDDED_WORKER", "false")
os.environ.setdefault("X_SECRET_KEY", "test-secret-key-that-is-long-enough-1234567890")

import pytest  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import install_protection_triggers, make_engine, set_engine  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture()
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        install_protection_triggers(conn)
    set_engine(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture()
def seeded(db):
    from app.seed import seed_all
    seed_all(db)
    db.commit()
    return db
