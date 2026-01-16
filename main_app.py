"""
LEO Activation API - Main Application Entry Point

This module creates the FastAPI application using a modular factory pattern.
The actual application setup is delegated to the api.app_factory module,
while route handlers are in api.handlers.
"""

import logging

from api.app_factory import create_app

# ============================================================
# Logging
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LEO Activation API")


# ============================================================
# App instance (used by uvicorn & tests)
# ============================================================
app = create_app()
