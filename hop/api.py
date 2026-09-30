"""ASGI entry point: ``uvicorn --factory hop.api:create_app``."""

from __future__ import annotations

from fastapi import FastAPI

from hop import __version__
from hop.bootstrap import App, build_app
from hop.platform.api import create_platform_app
from hop.products.opportunity_intelligence.api import build_router


def create_app(app_ctx: App | None = None) -> FastAPI:
    app_ctx = app_ctx or build_app()
    api = create_platform_app(app_ctx.platform, title="HKTDC Hidden Opportunity Discovery API", version=__version__)
    api.include_router(build_router(app_ctx))
    api.state.app_ctx = app_ctx
    return api
