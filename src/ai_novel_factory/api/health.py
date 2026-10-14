"""Stage 9: minimal API health contract; no DB, AI, queue or publisher calls."""
from __future__ import annotations

from typing import TypedDict


class HealthResponse(TypedDict):
    status: str
    service: str
    api_version: str


def health_payload() -> HealthResponse:
    """Non-sensitive, deterministic service liveness response."""
    return {
        "status": "ok",
        "service": "ai-novel-factory",
        "api_version": "v1",
    }


def create_app():
    """Create a FastAPI application only when the optional API package exists."""
    from fastapi import FastAPI

    app = FastAPI(title="AI Novel Factory Local API", version="0.1.0")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return health_payload()

    return app
