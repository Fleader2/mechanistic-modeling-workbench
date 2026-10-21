"""Module-Set Manual Editing increment: additive columns for renaming a module and editing its
reaction membership within a draft.

See ``docs/23_module_set_manual_editing_increment.md``. Adds:

* ``module_set_draft.edit_version`` -- ``Integer NOT NULL DEFAULT 0``, an optimistic-concurrency
  token incremented by every successful member edit.
* ``module_set_draft_member.display_name`` (``Text``, nullable), ``.reaction_component_ids``
  (``Text``, nullable, JSON-encoded), and ``.original_reaction_component_ids`` (``Text``,
  nullable, JSON-encoded, immutable once set) -- the live/edited and frozen-original snapshot of
  one draft member's own reaction membership and display name.
* ``module_set_member.display_name`` / ``.reaction_component_ids`` -- the same live columns,
  carried onto a saved version's own immutable member rows (``NULL`` = "never edited," identical
  to every increment-21 row, which this migration leaves untouched).

**No column is dropped or altered, and no existing row's data changes.** Every increment-21 row
gets ``edit_version=0``/``display_name=NULL``/``reaction_component_ids=NULL`` by the server
defaults above, which is exactly the "never edited" state those rows were already honestly in.

Revision ID: 0014_module_set_editing
Revises: 0013_module_set
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_module_set_editing"
down_revision: str | None = "0013_module_set"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "module_set_draft",
        sa.Column("edit_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("module_set_draft_member", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column(
        "module_set_draft_member",
        sa.Column("reaction_component_ids", sa.Text(), nullable=True),
    )
    op.add_column(
        "module_set_draft_member",
        sa.Column("original_reaction_component_ids", sa.Text(), nullable=True),
    )
    op.add_column("module_set_member", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column(
        "module_set_member", sa.Column("reaction_component_ids", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("module_set_member", "reaction_component_ids")
    op.drop_column("module_set_member", "display_name")
    op.drop_column("module_set_draft_member", "original_reaction_component_ids")
    op.drop_column("module_set_draft_member", "reaction_component_ids")
    op.drop_column("module_set_draft_member", "display_name")
    op.drop_column("module_set_draft", "edit_version")
