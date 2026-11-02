from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import admin, ai, auth, executions, intellect, quantum, scenarios, users
from .config import get_settings

log = logging.getLogger("x.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.environment != "test":
        from .bootstrap import bootstrap
        bootstrap(migrate=True)
        if s.embedded_worker:
            from .worker import start_embedded
            start_embedded()
    yield
    if s.embedded_worker:
        from .worker import stop_embedded
        stop_embedded()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="X — Hybrid AI + Quantum + Intellect Platform", version="1.0.0", lifespan=lifespan,
                  docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.frontend_origin.split(",") if o.strip()],
                       allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["content-type", "x-csrf-token", "authorization"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Request-ID"] = request.state.request_id
        if s.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(x) for x in e.get("loc", [])[1:]), "message": e.get("msg")}
                  for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": {"message": "Invalid request", "errors": errors}})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            raise exc
        rid = getattr(request.state, "request_id", "-")
        log.exception("unhandled error %s on %s", rid, request.url.path)
        return JSONResponse(status_code=500, content={"detail": f"Internal error (reference {rid}). The error was "
                                                                "logged; please report the reference."})

    for r in (auth.router, users.router, ai.router, quantum.router, intellect.router, scenarios.router,
              executions.router, admin.router):
        app.include_router(r)

    @app.get("/health", tags=["system"])
    def health():
        return {"ok": True}

    return app


app = create_app()
