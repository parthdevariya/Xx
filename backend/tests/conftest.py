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
    from sqlalchemy import update

    from app.models import Scenario
    from app.scenarios.seed import SCENARIOS
    from app.seed import seed_all
    seed_all(db)
    # The original scenarios are retired by library v2; tests still use them as stable numeric fixtures.
    db.execute(update(Scenario).where(Scenario.slug.in_([s["slug"] for s in SCENARIOS])).values(status="published"))
    db.commit()
    return db


PASSWORD = "Correct-Horse-42x"


def make_user(db, email: str, role: str):
    from sqlalchemy import select

    from app.models import Role, User
    from app.security import hash_password
    r = db.scalar(select(Role).where(Role.code == role))
    u = User(email=email, display_name=email.split("@")[0], password_hash=hash_password(PASSWORD), role_id=r.id)
    db.add(u)
    db.commit()
    return u


def enable_test_provider(db):
    from sqlalchemy import select

    from app.models import AIProvider
    p = db.scalar(select(AIProvider).where(AIProvider.kind == "deterministic_test"))
    p.is_active = True
    db.commit()
    return p


class Api:
    """TestClient wrapper that logs in and sends the CSRF header on writes."""

    def __init__(self, client):
        self.c = client

    def login(self, email, password=PASSWORD):
        r = self.c.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()

    def _h(self):
        return {"x-csrf-token": self.c.cookies.get("x_csrf", "")}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers={**self._h(), **kw.pop("headers", {})}, **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers={**self._h(), **kw.pop("headers", {})}, **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers={**self._h(), **kw.pop("headers", {})}, **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers={**self._h(), **kw.pop("headers", {})}, **kw)


@pytest.fixture()
def api(seeded):
    from fastapi.testclient import TestClient

    from app.main import create_app
    make_user(seeded, "admin@example.com", "super_admin")
    make_user(seeded, "user@example.com", "standard")
    with TestClient(create_app()) as client:
        yield Api(client)


def drain_jobs(max_jobs: int = 10):
    from app.worker import work_once
    n = 0
    while n < max_jobs and work_once():
        n += 1
    return n


@pytest.fixture(autouse=True)
def _no_network_ai(monkeypatch):
    """Any Anthropic SDK call a test did not explicitly mock fails instead of reaching the network."""
    import httpx2

    from app.ai.providers import anthropic_provider

    def refuse(request):
        raise AssertionError(f"unexpected network call to {request.url} in tests")
    monkeypatch.setattr(anthropic_provider, "http_client_factory",
                        lambda: httpx2.Client(transport=httpx2.MockTransport(refuse)))
