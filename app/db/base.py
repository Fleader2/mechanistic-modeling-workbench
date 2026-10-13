"""SQLAlchemy declarative base.

A fixed naming convention is applied so that Alembic produces stable, explicit
constraint names across migrations rather than database-generated ones. This
is the identical convention used by the sibling ``agent1-biochemical-curator``
repository (``app/db/base.py``), adopted here for consistency across the
system -- not a shared import, since the Workbench never imports another
repository's runtime code (see ``docs/01_workbench_architecture.md``).
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all Workbench ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
