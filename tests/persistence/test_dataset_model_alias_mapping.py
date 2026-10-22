"""Tests for ``app.persistence.dataset_model_alias_mapping``."""

from __future__ import annotations

import json

import pytest

from app.models.enums import (
    AliasMappingAssignmentStatus,
    AliasMappingUnitFinding,
    ModelSpeciesCatalogStatus,
    RunStage,
)
from app.persistence.dataset_model_alias_mapping import (
    AssignmentInput,
    DuplicateMappingTargetError,
    InvalidMappingColumnError,
    InvalidMappingTargetError,
    MappingRevisionStaleError,
    MappingSpeciesCatalogUnavailableError,
    get_current_mapping_revision,
    get_mapping_revision,
    list_mapping_revisions,
    save_mapping_revision,
)
from app.persistence.model_species_catalog import (
    CapturedSpecies,
    get_model_species_catalog,
    persist_model_species_catalog,
)
from app.persistence.run_record import create_run_record
from app.persistence.time_series_dataset import get_time_series_dataset, persist_time_series_dataset
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id
from tests.time_series_helpers import fixture_workbook_bytes

pytestmark = pytest.mark.database

_FIXTURE_COLUMNS = ("[aRAStot]", "[pMEKtot]", "[pYERKtot]", "[pTpYErk]", "[pBRAFtot]")


def _run_record_id(db_session, *, model_id):
    run = create_run_record(
        subproject_id=make_subproject_id(db_session),
        stage=RunStage.HARNESS,
        session=db_session,
        model_id=model_id,
    )
    db_session.flush()
    return run.id


def _seed_dataset_and_available_catalog(db_session, *, species_ids: tuple[str, ...] | None = None):
    """A real, saved ``TimeSeriesDataset`` (the exact regression fixture) plus a real
    ``AVAILABLE`` ``ModelSpeciesCatalog`` (built directly via persistence, bypassing the
    harness -- the harness round trip itself is proven separately, docs/26 §9) for the same
    subproject. Returns ``(dataset, catalog)``, both read back with their own children loaded.
    """
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)

    dataset_result = persist_time_series_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="ras_mapk.xlsx",
        workbook_bytes=fixture_workbook_bytes(),
    )
    dataset = get_time_series_dataset(db_session, dataset_result.entity_id)

    if species_ids is None:
        species_ids = ("s_aRAStot", "s_pMEKtot")
    catalog_result = persist_model_species_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=_run_record_id(db_session, model_id=model_id),
        status=ModelSpeciesCatalogStatus.AVAILABLE,
        species=[
            CapturedSpecies(
                antimony_species_id=species_id,
                canonical_species_id=f"canonical-{species_id}",
                display_name=species_id,
                compartment_id="c1",
                compartment_name="cyto",
                kind="FLOATING",
            )
            for species_id in species_ids
        ],
    )
    catalog = get_model_species_catalog(db_session, model_id)
    assert catalog_result.entity_id == catalog.id
    return dataset, catalog


class TestSaveMappingRevision:
    def test_a_full_valid_assignment_set_is_saved_as_revision_one(self, db_session):
        dataset, catalog = _seed_dataset_and_available_catalog(db_session)

        revision = save_mapping_revision(
            session=db_session,
            dataset=dataset,
            model_species_catalog=catalog,
            assignments=[
                AssignmentInput(
                    column_name="[aRAStot]",
                    status=AliasMappingAssignmentStatus.ASSIGNED,
                    target_antimony_species_id="s_aRAStot",
                ),
                AssignmentInput(
                    column_name="[pMEKtot]", status=AliasMappingAssignmentStatus.SKIPPED
                ),
            ],
            expected_revision_number=0,
            saved_by="dr-test",
        )

        assert revision.revision_number == 1
        assert revision.saved_by == "dr-test"
        assert revision.model_species_catalog_id == catalog.id
        by_column = {a.column_name: a for a in revision.assignments}
        # Every measurement column gets a row -- never a sparse diff.
        assert set(by_column) == set(_FIXTURE_COLUMNS)
        assert by_column["[aRAStot]"].status is AliasMappingAssignmentStatus.ASSIGNED
        assert by_column["[aRAStot]"].target_antimony_species_id == "s_aRAStot"
        assert by_column["[pMEKtot]"].status is AliasMappingAssignmentStatus.SKIPPED
        assert by_column["[pMEKtot]"].target_antimony_species_id is None
        # Every other column defaults to UNRESOLVED, never silently omitted.
        for column_name in _FIXTURE_COLUMNS[2:]:
            assert by_column[column_name].status is AliasMappingAssignmentStatus.UNRESOLVED

    def test_an_assigned_column_gets_a_real_unit_finding(self, db_session):
        dataset, catalog = _seed_dataset_and_available_catalog(db_session)
        # The regression fixture's own columns declare no unit at all (docs/25) -- so this is
        # the real, honest UNKNOWN outcome, not a mocked one.
        revision = save_mapping_revision(
            session=db_session,
            dataset=dataset,
            model_species_catalog=catalog,
            assignments=[
                AssignmentInput(
                    column_name="[aRAStot]",
                    status=AliasMappingAssignmentStatus.ASSIGNED,
                    target_antimony_species_id="s_aRAStot",
                )
            ],
            expected_revision_number=0,
        )
        assigned = next(a for a in revision.assignments if a.column_name == "[aRAStot]")
        assert assigned.unit_finding is AliasMappingUnitFinding.UNKNOWN
        detail = json.loads(assigned.unit_comparison_detail)
        assert detail["status"] == "MISSING"

    def test_a_second_save_creates_revision_two_and_keeps_revision_one_intact(self, db_session):
        dataset, catalog = _seed_dataset_and_available_catalog(db_session)
        first = save_mapping_revision(
            session=db_session,
            dataset=dataset,
            model_species_catalog=catalog,
            assignments=[
                AssignmentInput(
                    column_name="[aRAStot]",
                    status=AliasMappingAssignmentStatus.ASSIGNED,
                    target_antimony_species_id="s_aRAStot",
                )
            ],
            expected_revision_number=0,
        )
        second = save_mapping_revision(
            session=db_session,
            dataset=dataset,
            model_species_catalog=catalog,
            assignments=[
                AssignmentInput(
                    column_name="[pMEKtot]", status=AliasMappingAssignmentStatus.SKIPPED
                )
            ],
            expected_revision_number=1,
        )
        assert second.revision_number == 2
        history = list_mapping_revisions(
            db_session, time_series_dataset_id=dataset.id, model_id=catalog.model_id
        )
        assert [r.revision_number for r in history] == [2, 1]

        reopened_first = get_mapping_revision(
            db_session,
            time_series_dataset_id=dataset.id,
            model_id=catalog.model_id,
            revision_number=1,
        )
        assert reopened_first.id == first.id
        assert next(
            a for a in reopened_first.assignments if a.column_name == "[aRAStot]"
        ).status is AliasMappingAssignmentStatus.ASSIGNED

        current = get_current_mapping_revision(
            db_session, time_series_dataset_id=dataset.id, model_id=catalog.model_id
        )
        assert current.id == second.id

    def test_a_stale_expected_revision_number_is_rejected(self, db_session):
        dataset, catalog = _seed_dataset_and_available_catalog(db_session)
        save_mapping_revision(
            session=db_session,
            dataset=dataset,
            model_species_catalog=catalog,
            assignments=[],
            expected_revision_number=0,
        )
        with pytest.raises(MappingRevisionStaleError) as exc_info:
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_species_catalog=catalog,
                assignments=[],
                expected_revision_number=0,  # stale -- revision 1 already exists
            )
        assert exc_info.value.current_revision.revision_number == 1

    def test_an_unknown_column_name_is_rejected(self, db_session):
        dataset, catalog = _seed_dataset_and_available_catalog(db_session)
        with pytest.raises(InvalidMappingColumnError) as exc_info:
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_species_catalog=catalog,
                assignments=[
                    AssignmentInput(
                        column_name="sample_id", status=AliasMappingAssignmentStatus.SKIPPED
                    )
                ],
                expected_revision_number=0,
            )
        assert exc_info.value.unknown_column_names == ["sample_id"]

    def test_an_invalid_target_species_id_is_rejected(self, db_session):
        dataset, catalog = _seed_dataset_and_available_catalog(db_session)
        with pytest.raises(InvalidMappingTargetError) as exc_info:
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_species_catalog=catalog,
                assignments=[
                    AssignmentInput(
                        column_name="[aRAStot]",
                        status=AliasMappingAssignmentStatus.ASSIGNED,
                        target_antimony_species_id="not_a_real_species",
                    )
                ],
                expected_revision_number=0,
            )
        assert exc_info.value.invalid_target_ids == ["not_a_real_species"]

    def test_two_columns_assigned_to_the_same_target_are_rejected_never_combined(
        self, db_session
    ):
        dataset, catalog = _seed_dataset_and_available_catalog(db_session)
        with pytest.raises(DuplicateMappingTargetError) as exc_info:
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_species_catalog=catalog,
                assignments=[
                    AssignmentInput(
                        column_name="[aRAStot]",
                        status=AliasMappingAssignmentStatus.ASSIGNED,
                        target_antimony_species_id="s_aRAStot",
                    ),
                    AssignmentInput(
                        column_name="[pMEKtot]",
                        status=AliasMappingAssignmentStatus.ASSIGNED,
                        target_antimony_species_id="s_aRAStot",
                    ),
                ],
                expected_revision_number=0,
            )
        assert exc_info.value.conflicts == {"s_aRAStot": ["[aRAStot]", "[pMEKtot]"]}

    def test_an_unavailable_catalog_is_rejected(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        dataset_result = persist_time_series_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="ras_mapk.xlsx",
            workbook_bytes=fixture_workbook_bytes(),
        )
        dataset = get_time_series_dataset(db_session, dataset_result.entity_id)
        persist_model_species_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=_run_record_id(db_session, model_id=model_id),
            status=ModelSpeciesCatalogStatus.UNAVAILABLE,
            unavailable_reason="the real Antimony text did not load",
        )
        catalog = get_model_species_catalog(db_session, model_id)

        with pytest.raises(MappingSpeciesCatalogUnavailableError):
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_species_catalog=catalog,
                assignments=[],
                expected_revision_number=0,
            )

    def test_saving_a_mapping_never_changes_the_dataset_own_source_data(self, db_session):
        """Task instructions: "preserve source names and measurements unchanged." """
        dataset, catalog = _seed_dataset_and_available_catalog(db_session)
        before_rows = [
            (r.row_index, r.time_value, r.measurements) for r in dataset.rows
        ]
        before_columns = [(c.column_name, c.unit) for c in dataset.measurement_columns]

        save_mapping_revision(
            session=db_session,
            dataset=dataset,
            model_species_catalog=catalog,
            assignments=[
                AssignmentInput(
                    column_name="[aRAStot]",
                    status=AliasMappingAssignmentStatus.ASSIGNED,
                    target_antimony_species_id="s_aRAStot",
                )
            ],
            expected_revision_number=0,
        )

        reloaded = get_time_series_dataset(db_session, dataset.id)
        after_rows = [
            (r.row_index, r.time_value, r.measurements) for r in reloaded.rows
        ]
        after_columns = [(c.column_name, c.unit) for c in reloaded.measurement_columns]
        assert after_rows == before_rows
        assert after_columns == before_columns


class TestGetCurrentMappingRevision:
    def test_returns_none_when_never_saved(self, db_session):
        dataset, catalog = _seed_dataset_and_available_catalog(db_session)
        assert (
            get_current_mapping_revision(
                db_session, time_series_dataset_id=dataset.id, model_id=catalog.model_id
            )
            is None
        )
