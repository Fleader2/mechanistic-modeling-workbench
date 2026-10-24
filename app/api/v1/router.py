"""Aggregated router for API version 1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import (
    calibration,
    health,
    initial_conditions_dataset,
    model_antimony_import,
    projects,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(calibration.router)
api_router.include_router(model_antimony_import.router)
api_router.include_router(initial_conditions_dataset.router)
