"""Migration upgrade/downgrade round-trip tests."""

from __future__ import annotations

import pytest
from alembic import command

pytestmark = pytest.mark.database


def test_full_downgrade_then_upgrade_round_trip(alembic_config, migrated_engine):
    """Replaying the full migration history (downgrade to base, then upgrade
    to head) succeeds without error -- the same mechanism
    ``tests.conftest.reset_test_database`` already relies on for per-session
    test isolation.
    """
    del migrated_engine  # ensures the session fixture already migrated once
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


def test_upgrade_from_base_is_idempotent_at_head(alembic_config, migrated_engine):
    """Running ``upgrade head`` again once already at head is a safe no-op."""
    del migrated_engine
    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")
