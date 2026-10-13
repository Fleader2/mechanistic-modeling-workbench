"""Shared persistence outcome types.

A single, generic ``PersistenceAction``/``PersistenceResult`` pair serves
every entity in this schema -- there is no external-source identity
resolution happening anywhere in the Workbench (everything here is
user/workflow-authored, not resolved against an external database), so
there is no need for the richer ``NormalizationStatus`` vocabulary Agent 1
uses for its own externally-sourced entities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class PersistenceAction(StrEnum):
    """What the database actually did."""

    CREATED = "CREATED"
    REUSED_EXISTING = "REUSED_EXISTING"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    """The outcome of one persist/add call, keyed by whatever natural key
    that entity uses (named generically here as ``identity``, documented
    per-call-site).
    """

    action: PersistenceAction
    entity_id: UUID | None
    created: bool
    reused_existing: bool
    identity: str
    reason: str = ""

    def __post_init__(self) -> None:
        valid_actions = (
            PersistenceAction.CREATED,
            PersistenceAction.REUSED_EXISTING,
            PersistenceAction.FAILED,
        )
        if self.action not in valid_actions:
            raise ValueError(
                f"PersistenceResult.action must be one of {valid_actions}, got {self.action!r}"
            )
        if not isinstance(self.identity, str) or not self.identity.strip():
            raise ValueError("PersistenceResult.identity must be a non-empty string")

        if self.action is PersistenceAction.CREATED:
            if self.entity_id is None:
                raise ValueError("CREATED requires entity_id")
            if not self.created or self.reused_existing:
                raise ValueError("CREATED requires created=True, reused_existing=False")
        elif self.action is PersistenceAction.REUSED_EXISTING:
            if self.entity_id is None:
                raise ValueError("REUSED_EXISTING requires entity_id")
            if self.created or not self.reused_existing:
                raise ValueError("REUSED_EXISTING requires created=False, reused_existing=True")
        else:  # FAILED
            if self.entity_id is not None:
                raise ValueError("FAILED must not carry entity_id")
            if self.created or self.reused_existing:
                raise ValueError("FAILED requires created=False, reused_existing=False")


__all__ = ["PersistenceAction", "PersistenceResult"]
