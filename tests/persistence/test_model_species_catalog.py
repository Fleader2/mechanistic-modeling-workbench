"""Tests for ``app.persistence.model_species_catalog``."""

from __future__ import annotations

import pytest

from app.models.enums import ModelSpeciesCatalogStatus, RunStage
from app.models.model_species_catalog import ModelSpeciesCatalog
from app.persistence.model_species_catalog import (
    CapturedCompartment,
    CapturedSpecies,
    get_model_species_catalog,
    persist_model_species_catalog,
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


class TestPersistModelSpeciesCatalog:
    def test_creates_an_available_catalog_with_species_and_compartments(self, db_session):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)

        result = persist_model_species_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelSpeciesCatalogStatus.AVAILABLE,
            source_antimony_artifact_reference="artifacts/models/abc.antimony",
            source_antimony_checksum="abc123",
            species=[
                CapturedSpecies(
                    antimony_species_id="s_S1_cyto",
                    canonical_species_id="compound-S1::in::c1",
                    display_name="S1",
                    compartment_id="c1",
                    compartment_name="cyto",
                    kind="FLOATING",
                )
            ],
            compartments=[
                CapturedCompartment(
                    compartment_id="c1", name="cyto", volume_unit="L", species_count=1
                )
            ],
        )
        assert result.action is PersistenceAction.CREATED

        catalog = get_model_species_catalog(db_session, model_id)
        assert catalog is not None
        assert catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
        assert len(catalog.species) == 1
        assert catalog.species[0].antimony_species_id == "s_S1_cyto"
        assert len(catalog.compartments) == 1

    def test_creates_an_unavailable_catalog_with_a_disclosed_reason(self, db_session):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)

        result = persist_model_species_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelSpeciesCatalogStatus.UNAVAILABLE,
            unavailable_reason="the real Antimony text did not load",
        )
        assert result.action is PersistenceAction.CREATED

        catalog = get_model_species_catalog(db_session, model_id)
        assert catalog.status is ModelSpeciesCatalogStatus.UNAVAILABLE
        assert catalog.unavailable_reason == "the real Antimony text did not load"
        assert catalog.species == []

    def test_unavailable_without_a_reason_is_rejected(self, db_session):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        with pytest.raises(ValueError, match="unavailable_reason"):
            persist_model_species_catalog(
                session=db_session,
                model_id=model_id,
                source_run_record_id=run_record_id,
                status=ModelSpeciesCatalogStatus.UNAVAILABLE,
            )

    def test_available_without_a_species_list_is_rejected(self, db_session):
        """``None`` (never attempted) and ``[]`` (verified, genuinely empty) are different
        claims -- a caller must say which one it means."""
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        with pytest.raises(ValueError, match="species"):
            persist_model_species_catalog(
                session=db_session,
                model_id=model_id,
                source_run_record_id=run_record_id,
                status=ModelSpeciesCatalogStatus.AVAILABLE,
            )

    def test_a_genuinely_empty_species_list_is_accepted_as_a_valid_available_catalog(
        self, db_session
    ):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        result = persist_model_species_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelSpeciesCatalogStatus.AVAILABLE,
            species=[],
        )
        assert result.action is PersistenceAction.CREATED
        catalog = get_model_species_catalog(db_session, model_id)
        assert catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
        assert catalog.species == []

    def test_a_second_call_for_the_same_model_reuses_the_existing_row(self, db_session):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        first = persist_model_species_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelSpeciesCatalogStatus.AVAILABLE,
            species=[],
        )
        before_count = (
            db_session.query(ModelSpeciesCatalog).filter_by(model_id=model_id).count()
        )
        second = persist_model_species_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run_record_id,
            status=ModelSpeciesCatalogStatus.UNAVAILABLE,
            unavailable_reason="should never overwrite the first",
        )
        assert second.action is PersistenceAction.REUSED_EXISTING
        assert second.entity_id == first.entity_id
        assert (
            db_session.query(ModelSpeciesCatalog).filter_by(model_id=model_id).count()
            == before_count
        )
        catalog = get_model_species_catalog(db_session, model_id)
        assert catalog.status is ModelSpeciesCatalogStatus.AVAILABLE  # the first row, unchanged


class TestGetModelSpeciesCatalog:
    def test_returns_none_when_never_captured(self, db_session):
        model_id = make_model_id(db_session)
        assert get_model_species_catalog(db_session, model_id) is None
