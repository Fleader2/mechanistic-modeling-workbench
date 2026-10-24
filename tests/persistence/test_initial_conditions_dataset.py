"""Tests for ``app.persistence.initial_conditions_dataset``."""

from __future__ import annotations

import json

import pytest

from app.initial_conditions.parser import InitialConditionsWorkbookMalformedError
from app.persistence.initial_conditions_dataset import (
    get_initial_conditions_dataset,
    list_initial_conditions_datasets_for_subproject,
    persist_initial_conditions_dataset,
)
from app.persistence.types import PersistenceAction
from tests.initial_conditions_helpers import (
    blank_template_bytes,
    fixture_workbook_bytes,
    populate_data_tab,
)
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.database


class TestPersistInitialConditionsDataset:
    def test_creates_a_new_dataset_with_every_row_and_column_preserved(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)

        result = persist_initial_conditions_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="egfr_ras_abundance.xlsx",
            workbook_bytes=fixture_workbook_bytes(),
            saved_by="test-scientist",
        )
        assert result.action is PersistenceAction.CREATED

        dataset = get_initial_conditions_dataset(db_session, result.entity_id)
        assert dataset is not None
        assert len(dataset.rows) == 4
        assert {c.column_name for c in dataset.measurement_columns} == {"Abundance"}
        assert dataset.saved_by == "test-scientist"
        assert dataset.organism is None  # honestly left blank, never fabricated

        egfr_row = next(r for r in dataset.rows if r.target_name == "EGFR")
        measurements = json.loads(egfr_row.measurements)
        assert measurements["Abundance"] == {"status": "MEASURED", "value": 208.0, "raw": "208"}

    def test_re_saving_byte_identical_content_reuses_the_existing_dataset(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        data = fixture_workbook_bytes()

        first = persist_initial_conditions_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="egfr_ras_abundance.xlsx",
            workbook_bytes=data,
        )
        second = persist_initial_conditions_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="egfr_ras_abundance.xlsx",
            workbook_bytes=data,
        )
        assert second.action is PersistenceAction.REUSED_EXISTING
        assert second.entity_id == first.entity_id

    def test_a_duplicate_target_name_is_disclosed_but_not_blocking(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        data = populate_data_tab(
            blank_template_bytes(),
            headers=("target_name", "Abundance"),
            rows=(("SOS1", 5), ("SOS1", 4)),
        )
        result = persist_initial_conditions_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="dup.xlsx",
            workbook_bytes=data,
        )
        assert result.action is PersistenceAction.CREATED
        dataset = get_initial_conditions_dataset(db_session, result.entity_id)
        findings = json.loads(dataset.validation_findings)
        assert any(f["code"] == "DUPLICATE_TARGET_NAME" for f in findings)
        assert len(dataset.rows) == 2  # both rows kept, never merged

    def test_a_missing_target_name_column_is_malformed(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        data = populate_data_tab(
            blank_template_bytes(),
            headers=("Species", "Abundance"),
            rows=(("EGFR", 208),),
        )
        with pytest.raises(InitialConditionsWorkbookMalformedError):
            persist_initial_conditions_dataset(
                session=db_session,
                project_id=project_id,
                subproject_id=subproject_id,
                original_filename="bad.xlsx",
                workbook_bytes=data,
            )

    def test_list_returns_newest_first_scoped_to_one_subproject(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        other_subproject_id = make_subproject_id(db_session, project_id=project_id)

        persist_initial_conditions_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=other_subproject_id,
            original_filename="other.xlsx",
            workbook_bytes=fixture_workbook_bytes({"Dataset name": "other"}),
        )
        persist_initial_conditions_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="mine.xlsx",
            workbook_bytes=fixture_workbook_bytes({"Dataset name": "mine"}),
        )
        datasets = list_initial_conditions_datasets_for_subproject(db_session, subproject_id)
        assert [d.dataset_name for d in datasets] == ["mine"]
