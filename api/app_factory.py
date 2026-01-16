"""FastAPI application factory and middleware setup."""

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agentic_models.router import AgentRouter
from main_configs import (
    CORS_ALLOW_CREDENTIALS,
    CORS_ALLOW_HEADERS,
    CORS_ALLOW_METHODS,
    CORS_ALLOW_ORIGINS,
    MAIN_APP_DESCRIPTION,
    MAIN_APP_TITLE,
    MAIN_APP_VERSION,
)

logger = logging.getLogger("LEO Activation API")


def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI application.

    Includes:
    - CORS middleware
    - Static files and templates
    - Health check endpoint
    - Root endpoint
    - Agent router setup
    - API routes

    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title=MAIN_APP_TITLE,
        description=MAIN_APP_DESCRIPTION,
        version=MAIN_APP_VERSION,
    )

    # --------------------
    # CORS Middleware
    # --------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        allow_credentials=CORS_ALLOW_CREDENTIALS,
        allow_methods=CORS_ALLOW_METHODS,
        allow_headers=CORS_ALLOW_HEADERS,
    )

    # --------------------
    # Static Files & Templates
    # --------------------
    base_dir = Path(__file__).resolve().parent.parent
    resources_dir = base_dir / "agentic_resources"
    templates_dir = resources_dir / "templates"

    if resources_dir.exists():
        app.mount(
            "/resources",
            StaticFiles(directory=resources_dir),
            name="resources",
        )

    if templates_dir.exists():
        app.state.templates = Jinja2Templates(directory=templates_dir)
    else:
        app.state.templates = None

    # --------------------
    # Health Check
    # --------------------
    @app.get("/ping")
    def ping():
        """Health check endpoint."""
        return {"status": "ok"}

    # --------------------
    # Root Endpoint
    # --------------------
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """Root endpoint - returns test template or simple HTML."""
        if not request.app.state.templates:
            API_HEAD = "<h1>LEO Activation API</h1>"
            return HTMLResponse(API_HEAD, status_code=200)

        ts = int(time.time())
        return request.app.state.templates.TemplateResponse(
            "test.html",
            {"request": request, "timestamp": ts},
        )

    # --------------------
    # Agent Router Setup
    # --------------------
    agent_router = AgentRouter(mode="auto")
    app.state.agent_router = agent_router

    # --------------------
    # API Routes
    # --------------------
    from api.handlers import create_api_router

    api_router = create_api_router(agent_router)
    app.include_router(api_router)

    return app
