"""Tests for ``app.persistence.unit_resolution``."""

from __future__ import annotations

import pytest

from app.models.unit_resolution import UnitResolution
from app.persistence.unit_resolution import get_unit_resolution, resolve_and_persist_unit

pytestmark = pytest.mark.database


def test_missing_unit_is_never_persisted(db_session):
    result = resolve_and_persist_unit(db_session, None)
    assert result["parse_status"] == "MISSING"
    assert db_session.query(UnitResolution).count() == 0


def test_blank_unit_is_never_persisted(db_session):
    result = resolve_and_persist_unit(db_session, "   ")
    assert result["parse_status"] == "MISSING"
    assert db_session.query(UnitResolution).count() == 0


def test_parsed_unit_is_persisted(db_session):
    result = resolve_and_persist_unit(db_session, "mM")
    assert result["parse_status"] == "PARSED"
    assert result["normalized_unit"] == "mM"
    row = get_unit_resolution(db_session, "mM")
    assert row is not None
    assert row.source_unit_string == "mM"
    assert row.normalized_unit == "mM"


def test_malformed_unit_is_persisted(db_session):
    result = resolve_and_persist_unit(db_session, "not_a_real_unit_xyz")
    assert result["parse_status"] == "MALFORMED"
    assert result["normalized_unit"] is None
    row = get_unit_resolution(db_session, "not_a_real_unit_xyz")
    assert row is not None
    assert row.parse_status.value == "MALFORMED"


def test_resolving_the_same_string_twice_is_idempotent_not_duplicated(db_session):
    resolve_and_persist_unit(db_session, "mmol/L")
    resolve_and_persist_unit(db_session, "mmol/L")
    rows = (
        db_session.query(UnitResolution).filter(UnitResolution.source_unit_string == "mmol/L").all()
    )
    assert len(rows) == 1


def test_unknown_unit_lookup_returns_none(db_session):
    assert get_unit_resolution(db_session, "never-resolved-string") is None


def test_fresh_session_reload_reads_back_persisted_resolution(db_session):
    resolve_and_persist_unit(db_session, "per_sec")
    db_session.expire_all()

    row = get_unit_resolution(db_session, "per_sec")
    assert row is not None
    assert row.normalized_unit == "per_sec"
    assert row.dimensionality == "1 / [time]"
