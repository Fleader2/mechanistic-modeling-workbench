"""FastAPI application factory.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.config.settings import API_V1_PREFIX, APPLICATION_NAME, get_settings
from app.schemas.common import ErrorResponse

DESCRIPTION = (
    "HTTP API over the Workbench's persistent project/workflow layer. Owns "
    "no scientific logic -- see docs/01_workbench_architecture.md."
)


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title=APPLICATION_NAME,
        version=__version__,
        description=DESCRIPTION,
        responses={
            404: {"model": ErrorResponse, "description": "Not found"},
            422: {"model": ErrorResponse, "description": "Validation error"},
            500: {"model": ErrorResponse, "description": "Internal error"},
        },
    )

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=API_V1_PREFIX)

    return app


app = create_app()
