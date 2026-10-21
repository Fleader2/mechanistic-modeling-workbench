"""Tests for ``app.persistence.time_series_dataset``."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.models.dataset_reference import DatasetReference
from app.models.time_series_dataset import TimeSeriesDataset
from app.persistence.time_series_dataset import (
    get_time_series_dataset,
    list_time_series_datasets_for_subproject,
    persist_time_series_dataset,
)
from app.persistence.types import PersistenceAction
from app.time_series.parser import WorkbookMalformedError
from tests.persistence.conftest import make_project_id, make_subproject_id
from tests.time_series_helpers import blank_template_bytes, fixture_workbook_bytes

pytestmark = pytest.mark.database


def _row_count(db_session, model) -> int:
    return db_session.execute(select(func.count()).select_from(model)).scalar_one()


class TestPersistTimeSeriesDataset:
    def test_creates_a_new_dataset_with_every_row_and_column_preserved(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)

        result = persist_time_series_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="ras_mapk.xlsx",
            workbook_bytes=fixture_workbook_bytes(),
            saved_by="test-scientist",
        )
        assert result.action is PersistenceAction.CREATED

        dataset = get_time_series_dataset(db_session, result.entity_id)
        assert dataset is not None
        assert len(dataset.rows) == 5
        assert {c.column_name for c in dataset.measurement_columns} == {
            "[aRAStot]",
            "[pMEKtot]",
            "[pYERKtot]",
            "[pTpYErk]",
            "[pBRAFtot]",
        }
        assert dataset.saved_by == "test-scientist"
        assert dataset.organism is None  # honestly left blank, never fabricated

        row_t120 = next(r for r in dataset.rows if r.time_value == 120)
        measurements = json.loads(row_t120.measurements)
        assert measurements["[pMEKtot]"] == {"status": "MEASURED", "value": 0.0, "raw": "0"}

    def test_creates_the_catalog_entry_too_and_it_is_counted_as_a_dataset(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        result = persist_time_series_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="ras_mapk.xlsx",
            workbook_bytes=fixture_workbook_bytes(),
        )
        dataset = get_time_series_dataset(db_session, result.entity_id)
        catalog_row = dataset.dataset_reference
        assert catalog_row.project_id == project_id
        assert catalog_row.subproject_id == subproject_id
        assert catalog_row.dataset_type == "time_series_experimental_observation"

    def test_blank_dataset_name_falls_back_to_the_filename_with_a_disclosed_finding(
        self, db_session
    ):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        result = persist_time_series_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="ras_mapk_observations.xlsx",
            workbook_bytes=fixture_workbook_bytes(),
        )
        dataset = get_time_series_dataset(db_session, result.entity_id)
        assert dataset.dataset_name is None  # the literal, as-uploaded value is honestly None
        assert dataset.dataset_reference.name == "ras_mapk_observations"  # the display fallback
        findings = json.loads(dataset.validation_findings)
        assert any(f["code"] == "DATASET_NAME_MISSING_USING_FILENAME" for f in findings)

    def test_resaving_byte_identical_content_for_the_same_project_reuses_the_existing_dataset(
        self, db_session
    ):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        data = fixture_workbook_bytes()

        first = persist_time_series_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="ras_mapk.xlsx",
            workbook_bytes=data,
        )
        before_dataset_count = _row_count(db_session, TimeSeriesDataset)

        second = persist_time_series_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="ras_mapk.xlsx",
            workbook_bytes=data,
        )

        assert second.action is PersistenceAction.REUSED_EXISTING
        assert second.entity_id == first.entity_id
        assert _row_count(db_session, TimeSeriesDataset) == before_dataset_count

    def test_a_malformed_workbook_persists_nothing_at_all(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        before_datasets = _row_count(db_session, TimeSeriesDataset)
        before_catalog = _row_count(db_session, DatasetReference)

        with pytest.raises(WorkbookMalformedError):
            persist_time_series_dataset(
                session=db_session,
                project_id=project_id,
                subproject_id=subproject_id,
                original_filename="blank.xlsx",
                workbook_bytes=blank_template_bytes(),  # no measurement columns -> malformed
            )

        assert _row_count(db_session, TimeSeriesDataset) == before_datasets
        assert _row_count(db_session, DatasetReference) == before_catalog


class TestListTimeSeriesDatasetsForSubproject:
    def test_scoped_to_exactly_one_subproject(self, db_session):
        project_id = make_project_id(db_session)
        subproject_a = make_subproject_id(db_session, project_id=project_id)
        subproject_b = make_subproject_id(db_session, project_id=project_id)

        persist_time_series_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_a,
            original_filename="a.xlsx",
            workbook_bytes=fixture_workbook_bytes(metadata={"Dataset name": "dataset-a"}),
        )
        persist_time_series_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_b,
            original_filename="b.xlsx",
            workbook_bytes=fixture_workbook_bytes(metadata={"Dataset name": "dataset-b"}),
        )

        listing_a = list_time_series_datasets_for_subproject(db_session, subproject_a)
        listing_b = list_time_series_datasets_for_subproject(db_session, subproject_b)
        assert [d.dataset_reference.name for d in listing_a] == ["dataset-a"]
        assert [d.dataset_reference.name for d in listing_b] == ["dataset-b"]

    def test_an_unused_subproject_returns_an_empty_list_not_an_error(self, db_session):
        subproject_id = make_subproject_id(db_session)
        assert list_time_series_datasets_for_subproject(db_session, subproject_id) == []
