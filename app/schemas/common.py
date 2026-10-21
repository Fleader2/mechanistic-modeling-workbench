"""Shared API schemas: the structured error envelope.

Follows the identical shape used by the sibling ``agent1-biochemical-curator``
repository (``app/schemas/common.py``): ``{"detail": {"code", "message",
"context"}}`` for every failing response, so a future shared frontend client
can treat both APIs' errors uniformly.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ErrorCode(StrEnum):
    """Machine-readable error codes.

    Only codes raised by the current implementation are defined. Codes for
    unimplemented behaviour are added by the phase that implements them.
    """

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    """Structured description of a single API failure."""

    code: ErrorCode
    message: str
    context: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Top-level error envelope returned by every failing endpoint."""

    detail: ErrorDetail


__all__ = ["ErrorCode", "ErrorDetail", "ErrorResponse"]
