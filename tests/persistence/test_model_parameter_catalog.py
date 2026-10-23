"""Tests for ``app.persistence.model_parameter_catalog`` -- the docs/31 configuration-
prerequisites increment's own sibling to ``tests/persistence/test_model_species_catalog.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import ModelParameterCatalogStatus, ModelParameterKind, RunStage
from app.models.model_parameter_catalog import ModelParameterCatalog
from app.persistence.model_parameter_catalog import (
    CapturedParameter,
    get_model_parameter_catalog,
    persist_model_parameter_catalog,
)
from app.persistence.run_record import create_run_record
from app.persistence.types import PersistenceAction
from tests.persistence.conftest import make_model_id, make_subproject_id

pytestmark = pytest.mark.database


def _run_record_id(db_session, *, model_id):
    run = create_run_record(
        subproject_id=make_subproject_id(db_session),
        stage=RunStage.HARNESS,
        session=db_session,
        model_id=model_id,
    )
    db_session.flush()
    return run.id


class TestPersistModelParameterCatalog:
    def test_creates_an_available_catalog_distinguishing_independent_from_derived(
        self, db_session
    ):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)

        result = persist_model_parameter_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelParameterCatalogStatus.AVAILABLE,
            source_antimony_artifact_reference="artifacts/models/abc.antimony",
            source_antimony_checksum="abc123",
            parameters=[
                CapturedParameter(
                    antimony_parameter_id="k1",
                    canonical_parameter_id="canonical-k1",
                    display_name="k1",
                    kind=ModelParameterKind.INDEPENDENT.value,
                    unit="1/s",
                    lower_bound=Decimal("0"),
                    upper_bound=Decimal("10"),
                ),
                CapturedParameter(
                    antimony_parameter_id="Vmax",
                    canonical_parameter_id="canonical-Vmax",
                    display_name="Vmax",
                    kind=ModelParameterKind.DERIVED.value,
                ),
            ],
        )
        assert result.action is PersistenceAction.CREATED

        catalog = get_model_parameter_catalog(db_session, model_id)
        assert catalog is not None
        assert catalog.status is ModelParameterCatalogStatus.AVAILABLE
        assert len(catalog.parameters) == 2
        by_id = {p.antimony_parameter_id: p for p in catalog.parameters}
        assert by_id["k1"].kind is ModelParameterKind.INDEPENDENT
        assert by_id["k1"].lower_bound == Decimal("0")
        assert by_id["Vmax"].kind is ModelParameterKind.DERIVED

    def test_creates_an_unavailable_catalog_with_a_disclosed_reason(self, db_session):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)

        result = persist_model_parameter_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelParameterCatalogStatus.UNAVAILABLE,
            unavailable_reason="the real Antimony text did not load",
        )
        assert result.action is PersistenceAction.CREATED

        catalog = get_model_parameter_catalog(db_session, model_id)
        assert catalog.status is ModelParameterCatalogStatus.UNAVAILABLE
        assert catalog.unavailable_reason == "the real Antimony text did not load"
        assert catalog.parameters == []

    def test_unavailable_without_a_reason_is_rejected(self, db_session):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        with pytest.raises(ValueError, match="unavailable_reason"):
            persist_model_parameter_catalog(
                session=db_session,
                model_id=model_id,
                source_run_record_id=run_record_id,
                status=ModelParameterCatalogStatus.UNAVAILABLE,
            )

    def test_available_without_a_parameter_list_is_rejected(self, db_session):
        """``None`` (never attempted) and ``[]`` (verified, genuinely empty) are different
        claims -- a caller must say which one it means."""
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        with pytest.raises(ValueError, match="parameters"):
            persist_model_parameter_catalog(
                session=db_session,
                model_id=model_id,
                source_run_record_id=run_record_id,
                status=ModelParameterCatalogStatus.AVAILABLE,
            )

    def test_a_genuinely_empty_parameter_list_is_accepted_as_a_valid_available_catalog(
        self, db_session
    ):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        result = persist_model_parameter_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelParameterCatalogStatus.AVAILABLE,
            parameters=[],
        )
        assert result.action is PersistenceAction.CREATED
        catalog = get_model_parameter_catalog(db_session, model_id)
        assert catalog.status is ModelParameterCatalogStatus.AVAILABLE
        assert catalog.parameters == []

    def test_a_second_call_for_the_same_model_reuses_the_existing_row(self, db_session):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        first = persist_model_parameter_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelParameterCatalogStatus.AVAILABLE,
            parameters=[],
        )
        before_count = (
            db_session.query(ModelParameterCatalog).filter_by(model_id=model_id).count()
        )
        second = persist_model_parameter_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelParameterCatalogStatus.UNAVAILABLE,
            unavailable_reason="should never overwrite the first",
        )
        assert second.action is PersistenceAction.REUSED_EXISTING
        assert second.entity_id == first.entity_id
        assert (
            db_session.query(ModelParameterCatalog).filter_by(model_id=model_id).count()
            == before_count
        )
        catalog = get_model_parameter_catalog(db_session, model_id)
        assert catalog.status is ModelParameterCatalogStatus.AVAILABLE  # the first row, unchanged


class TestGetModelParameterCatalog:
    def test_returns_none_when_never_captured(self, db_session):
        model_id = make_model_id(db_session)
        assert get_model_parameter_catalog(db_session, model_id) is None
