"""Zep Cloud graph-memory integration (optional, used by Swarm Intelligence).

Endpoints follow the Zep v4 API reference (help.getzep.com/v4/sdk-reference/graph/*):
    POST   {base}/graphs                               create a standalone graph
    POST   {base}/graphs/{graph_uuid}/episodes         add an episode (data: str, type: text|json|message)
    POST   {base}/graphs/{graph_uuid}/search/edges     search facts   (?page_size=N)
    POST   {base}/graphs/{graph_uuid}/search/nodes     search entities
    DELETE {base}/graphs/{graph_uuid}                  delete (asynchronous)
    POST   {base}/graphs/list?page_size=1              cheapest authenticated read (used as health check)
Auth: "Authorization: Api-Key <project key>".

The key is stored Fernet-encrypted in system_settings and never returned by the API.
"""

from __future__ import annotations

import time

import httpx
from sqlalchemy.orm import Session

from ..models import SystemSetting, utcnow
from ..security import decrypt_secret, encrypt_secret, secret_hint

KEY = "integration.zep"
DEFAULT_BASE = "https://api.getzep.com/api/v4"
TIMEOUT = 20.0
# Test hook: an httpx transport injected by the test suite. Always None in production.
transport = None


class ZepError(RuntimeError):
    pass


def settings(db: Session) -> dict:
    row = db.get(SystemSetting, KEY)
    v = dict(row.value) if row and row.value else {}
    return {"enabled": bool(v.get("enabled", False)), "base_url": v.get("base_url") or DEFAULT_BASE,
            "configured": bool(v.get("secret_encrypted")), "hint": v.get("hint", ""),
            "status": v.get("status", "unconfigured" if not v.get("secret_encrypted") else "unknown"),
            "detail": v.get("detail", ""), "checked_at": v.get("checked_at"), "latency_ms": v.get("latency_ms")}


def save(db: Session, *, enabled: bool | None = None, base_url: str | None = None, api_key: str | None = None,
         clear_key: bool = False, user_id: str | None = None) -> dict:
    row = db.get(SystemSetting, KEY)
    if row is None:
        row = SystemSetting(key=KEY, value={}, description="Zep Cloud graph memory (Swarm Intelligence)")
        db.add(row)
    v = dict(row.value or {})
    if enabled is not None:
        v["enabled"] = bool(enabled)
    if base_url is not None:
        url = base_url.strip().rstrip("/") or DEFAULT_BASE
        if not url.startswith("https://"):
            raise ValueError("base URL must use https://")
        v["base_url"] = url
    if api_key:
        v["secret_encrypted"], v["hint"], v["status"], v["detail"] = encrypt_secret(api_key.strip()), \
            secret_hint(api_key.strip()), "unknown", ""
    if clear_key:
        for k in ("secret_encrypted", "hint"):
            v.pop(k, None)
        v["status"], v["enabled"] = "unconfigured", False
    row.value = v
    row.updated_by = user_id
    db.flush()
    return settings(db)


class ZepClient:
    def __init__(self, base_url: str, api_key: str):
        if not api_key:
            raise ZepError("Zep API key is not configured")
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(timeout=TIMEOUT, transport=transport,
                                 headers={"Authorization": f"Api-Key {api_key}", "Content-Type": "application/json"})

    def _req(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> dict:
        try:
            r = self.http.request(method, f"{self.base}{path}", json=json, params=params)
        except httpx.HTTPError as e:
            raise ZepError(f"cannot reach Zep at {self.base}: {e}") from e
        if r.status_code in (401, 403):
            raise ZepError(f"Zep rejected the API key ({r.status_code})")
        if r.status_code >= 400:
            raise ZepError(f"Zep error {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def health(self) -> dict:
        return self._req("POST", "/graphs/list", params={"page_size": 1}, json={})

    def create_graph(self, name: str, description: str = "") -> str:
        d = self._req("POST", "/graphs", json={"name": name[:120], "description": description[:500]})
        uuid = d.get("uuid") or d.get("graph_id")
        if not uuid:
            raise ZepError("Zep did not return a graph id")
        return uuid

    def add_episode(self, graph_uuid: str, data: str, *, type_: str = "text", source: str = "") -> dict:
        body = {"data": data[:9500], "type": type_}
        if source:
            body["source_description"] = source[:200]
        return self._req("POST", f"/graphs/{graph_uuid}/episodes", json=body)

    def search_edges(self, graph_uuid: str, query: str, n: int = 8) -> list[dict]:
        d = self._req("POST", f"/graphs/{graph_uuid}/search/edges", params={"page_size": n}, json={"query": query[:400]})
        return [{"fact": e.get("fact", ""), "source": e.get("source_node_name"), "target": e.get("target_node_name")}
                for e in d.get("items", [])][:n]

    def search_nodes(self, graph_uuid: str, query: str, n: int = 8) -> list[dict]:
        d = self._req("POST", f"/graphs/{graph_uuid}/search/nodes", params={"page_size": n}, json={"query": query[:400]})
        return [{"name": x.get("name", ""), "summary": x.get("summary", "")} for x in d.get("items", [])][:n]

    def delete_graph(self, graph_uuid: str) -> None:
        self._req("DELETE", f"/graphs/{graph_uuid}")


def client(db: Session) -> ZepClient | None:
    """A client only when the integration is enabled and has a key."""
    row = db.get(SystemSetting, KEY)
    v = row.value if row and row.value else {}
    if not v.get("enabled") or not v.get("secret_encrypted"):
        return None
    return ZepClient(v.get("base_url") or DEFAULT_BASE, decrypt_secret(v["secret_encrypted"]))


def health_check(db: Session) -> dict:
    row = db.get(SystemSetting, KEY)
    v = dict(row.value) if row and row.value else {}
    t0 = time.perf_counter()
    status, detail = "healthy", ""
    try:
        if not v.get("secret_encrypted"):
            raise ZepError("no API key saved")
        ZepClient(v.get("base_url") or DEFAULT_BASE, decrypt_secret(v["secret_encrypted"])).health()
    except ZepError as e:
        status, detail = ("unconfigured" if "no API key" in str(e) else "down"), str(e)
    v.update(status=status, detail=detail[:500], checked_at=utcnow().isoformat(),
             latency_ms=round((time.perf_counter() - t0) * 1000, 1) if status == "healthy" else None)
    if row is None:
        row = SystemSetting(key=KEY, value=v, description="Zep Cloud graph memory (Swarm Intelligence)")
        db.add(row)
    row.value = v
    db.flush()
    return settings(db)
