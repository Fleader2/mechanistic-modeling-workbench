"""Tests for ``app.persistence.initial_conditions_alias_mapping``."""

from __future__ import annotations

import pytest

from app.models.enums import (
    AliasMappingAssignmentStatus,
    InitialConditionsAliasMappingTargetKind,
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSpeciesCatalogStatus,
    RunStage,
)
from app.persistence.initial_conditions_alias_mapping import (
    AmbiguousMappingTargetError,
    AssignmentInput,
    DuplicateMappingTargetIdError,
    InvalidMappingTargetIdError,
    InvalidMappingTargetNameError,
    MappingCatalogsUnavailableError,
    MappingRevisionStaleError,
    get_current_mapping_revision,
    save_mapping_revision,
)
from app.persistence.initial_conditions_dataset import (
    get_initial_conditions_dataset,
    persist_initial_conditions_dataset,
)
from app.persistence.model_parameter_catalog import (
    CapturedParameter,
    persist_model_parameter_catalog,
)
from app.persistence.model_species_catalog import CapturedSpecies, persist_model_species_catalog
from app.persistence.run_record import create_run_record
from tests.initial_conditions_helpers import fixture_workbook_bytes
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id

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


def _seed(db_session):
    """A real, saved ``InitialConditionsDataset`` (EGFR/Grb2/SOS1/RAS) plus a real species
    catalog (EGFR, Grb2) and a real independent-parameter catalog (SOS1_rate) for the same
    model -- returns ``(dataset, model_id, species_catalog, parameter_catalog)``."""
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)

    dataset_result = persist_initial_conditions_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="abundance.xlsx",
        workbook_bytes=fixture_workbook_bytes(),
    )
    dataset = get_initial_conditions_dataset(db_session, dataset_result.entity_id)

    persist_model_species_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=_run_record_id(db_session, model_id=model_id),
        status=ModelSpeciesCatalogStatus.AVAILABLE,
        species=[
            CapturedSpecies(
                antimony_species_id=sid,
                canonical_species_id=f"canonical-{sid}",
                display_name=sid,
                compartment_id="c1",
                compartment_name="cyto",
                kind="FLOATING",
            )
            for sid in ("s_EGFR", "s_Grb2")
        ],
    )
    from app.persistence.model_species_catalog import get_model_species_catalog

    species_catalog = get_model_species_catalog(db_session, model_id)

    persist_model_parameter_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=_run_record_id(db_session, model_id=model_id),
        status=ModelParameterCatalogStatus.AVAILABLE,
        parameters=[
            CapturedParameter(
                antimony_parameter_id="SOS1_rate",
                canonical_parameter_id="canonical-SOS1_rate",
                display_name="SOS1 rate",
                kind=ModelParameterKind.INDEPENDENT.value,
                unit="1/s",
            )
        ],
    )
    from app.persistence.model_parameter_catalog import get_model_parameter_catalog

    parameter_catalog = get_model_parameter_catalog(db_session, model_id)

    return dataset, model_id, species_catalog, parameter_catalog


class TestSaveMappingRevision:
    def test_a_full_valid_mixed_species_and_parameter_assignment_is_saved(self, db_session):
        dataset, model_id, species_catalog, parameter_catalog = _seed(db_session)

        revision = save_mapping_revision(
            session=db_session,
            dataset=dataset,
            model_id=model_id,
            model_species_catalog=species_catalog,
            model_parameter_catalog=parameter_catalog,
            assignments=[
                AssignmentInput(
                    target_name="EGFR",
                    status=AliasMappingAssignmentStatus.ASSIGNED,
                    target_kind=InitialConditionsAliasMappingTargetKind.SPECIES,
                    target_id="s_EGFR",
                ),
                AssignmentInput(
                    target_name="SOS1",
                    status=AliasMappingAssignmentStatus.ASSIGNED,
                    target_kind=InitialConditionsAliasMappingTargetKind.PARAMETER,
                    target_id="SOS1_rate",
                ),
                AssignmentInput(target_name="RAS", status=AliasMappingAssignmentStatus.SKIPPED),
            ],
            expected_revision_number=0,
            saved_by="dr-test",
        )

        assert revision.revision_number == 1
        by_name = {a.target_name: a for a in revision.assignments}
        # Every distinct target_name actually in the dataset gets a row -- never a sparse diff.
        assert set(by_name) == {"EGFR", "Grb2", "SOS1", "RAS"}
        assert by_name["EGFR"].target_kind is InitialConditionsAliasMappingTargetKind.SPECIES
        assert by_name["EGFR"].target_id == "s_EGFR"
        assert by_name["SOS1"].target_kind is InitialConditionsAliasMappingTargetKind.PARAMETER
        assert by_name["SOS1"].target_id == "SOS1_rate"
        assert by_name["RAS"].status is AliasMappingAssignmentStatus.SKIPPED
        assert by_name["Grb2"].status is AliasMappingAssignmentStatus.UNRESOLVED

    def test_a_stale_expected_revision_number_is_rejected(self, db_session):
        dataset, model_id, species_catalog, parameter_catalog = _seed(db_session)
        save_mapping_revision(
            session=db_session,
            dataset=dataset,
            model_id=model_id,
            model_species_catalog=species_catalog,
            model_parameter_catalog=parameter_catalog,
            assignments=[],
            expected_revision_number=0,
        )
        with pytest.raises(MappingRevisionStaleError):
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_id=model_id,
                model_species_catalog=species_catalog,
                model_parameter_catalog=parameter_catalog,
                assignments=[],
                expected_revision_number=0,
            )

    def test_an_unknown_target_name_is_rejected(self, db_session):
        dataset, model_id, species_catalog, parameter_catalog = _seed(db_session)
        with pytest.raises(InvalidMappingTargetNameError) as exc_info:
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_id=model_id,
                model_species_catalog=species_catalog,
                model_parameter_catalog=parameter_catalog,
                assignments=[
                    AssignmentInput(
                        target_name="not_a_real_target", status=AliasMappingAssignmentStatus.SKIPPED
                    )
                ],
                expected_revision_number=0,
            )
        assert exc_info.value.unknown_target_names == ["not_a_real_target"]

    def test_an_invalid_target_id_is_rejected(self, db_session):
        dataset, model_id, species_catalog, parameter_catalog = _seed(db_session)
        with pytest.raises(InvalidMappingTargetIdError):
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_id=model_id,
                model_species_catalog=species_catalog,
                model_parameter_catalog=parameter_catalog,
                assignments=[
                    AssignmentInput(
                        target_name="EGFR",
                        status=AliasMappingAssignmentStatus.ASSIGNED,
                        target_kind=InitialConditionsAliasMappingTargetKind.SPECIES,
                        target_id="not_a_real_species",
                    )
                ],
                expected_revision_number=0,
            )

    def test_two_target_names_assigned_to_the_same_target_are_rejected(self, db_session):
        dataset, model_id, species_catalog, parameter_catalog = _seed(db_session)
        with pytest.raises(DuplicateMappingTargetIdError):
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_id=model_id,
                model_species_catalog=species_catalog,
                model_parameter_catalog=parameter_catalog,
                assignments=[
                    AssignmentInput(
                        target_name="EGFR",
                        status=AliasMappingAssignmentStatus.ASSIGNED,
                        target_kind=InitialConditionsAliasMappingTargetKind.SPECIES,
                        target_id="s_EGFR",
                    ),
                    AssignmentInput(
                        target_name="Grb2",
                        status=AliasMappingAssignmentStatus.ASSIGNED,
                        target_kind=InitialConditionsAliasMappingTargetKind.SPECIES,
                        target_id="s_EGFR",
                    ),
                ],
                expected_revision_number=0,
            )

    def test_a_target_id_real_in_both_catalogs_is_rejected_as_ambiguous(self, db_session):
        # A fresh model whose own species and parameter catalogs both happen to claim the
        # identical real id "s_EGFR" -- never silently resolved one way.
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        dataset_result = persist_initial_conditions_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="abundance.xlsx",
            workbook_bytes=fixture_workbook_bytes(),
        )
        dataset = get_initial_conditions_dataset(db_session, dataset_result.entity_id)

        from app.persistence.model_parameter_catalog import get_model_parameter_catalog
        from app.persistence.model_species_catalog import get_model_species_catalog

        persist_model_species_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=_run_record_id(db_session, model_id=model_id),
            status=ModelSpeciesCatalogStatus.AVAILABLE,
            species=[
                CapturedSpecies(
                    antimony_species_id="s_EGFR",
                    canonical_species_id="canonical-s_EGFR",
                    display_name="EGFR",
                    compartment_id="c1",
                    compartment_name="cyto",
                    kind="FLOATING",
                )
            ],
        )
        species_catalog = get_model_species_catalog(db_session, model_id)
        persist_model_parameter_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=_run_record_id(db_session, model_id=model_id),
            status=ModelParameterCatalogStatus.AVAILABLE,
            parameters=[
                CapturedParameter(
                    antimony_parameter_id="s_EGFR",
                    canonical_parameter_id="canonical-s_EGFR-as-param",
                    display_name=None,
                    kind=ModelParameterKind.INDEPENDENT.value,
                ),
            ],
        )
        parameter_catalog = get_model_parameter_catalog(db_session, model_id)
        with pytest.raises(AmbiguousMappingTargetError):
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_id=model_id,
                model_species_catalog=species_catalog,
                model_parameter_catalog=parameter_catalog,
                assignments=[
                    AssignmentInput(
                        target_name="EGFR",
                        status=AliasMappingAssignmentStatus.ASSIGNED,
                        target_kind=InitialConditionsAliasMappingTargetKind.SPECIES,
                        target_id="s_EGFR",
                    )
                ],
                expected_revision_number=0,
            )

    def test_a_derived_parameter_is_never_an_independent_target(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        dataset_result = persist_initial_conditions_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="abundance.xlsx",
            workbook_bytes=fixture_workbook_bytes(),
        )
        dataset = get_initial_conditions_dataset(db_session, dataset_result.entity_id)

        from app.persistence.model_parameter_catalog import get_model_parameter_catalog

        persist_model_parameter_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=_run_record_id(db_session, model_id=model_id),
            status=ModelParameterCatalogStatus.AVAILABLE,
            parameters=[
                CapturedParameter(
                    antimony_parameter_id="Vmax",
                    canonical_parameter_id="canonical-Vmax",
                    display_name=None,
                    kind=ModelParameterKind.DERIVED.value,
                )
            ],
        )
        parameter_catalog = get_model_parameter_catalog(db_session, model_id)
        with pytest.raises(InvalidMappingTargetIdError):
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_id=model_id,
                model_species_catalog=None,
                model_parameter_catalog=parameter_catalog,
                assignments=[
                    AssignmentInput(
                        target_name="SOS1",
                        status=AliasMappingAssignmentStatus.ASSIGNED,
                        target_kind=InitialConditionsAliasMappingTargetKind.PARAMETER,
                        target_id="Vmax",
                    )
                ],
                expected_revision_number=0,
            )

    def test_no_catalog_available_at_all_is_rejected(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        dataset_result = persist_initial_conditions_dataset(
            session=db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="abundance.xlsx",
            workbook_bytes=fixture_workbook_bytes(),
        )
        dataset = get_initial_conditions_dataset(db_session, dataset_result.entity_id)
        with pytest.raises(MappingCatalogsUnavailableError):
            save_mapping_revision(
                session=db_session,
                dataset=dataset,
                model_id=model_id,
                model_species_catalog=None,
                model_parameter_catalog=None,
                assignments=[],
                expected_revision_number=0,
            )


class TestGetCurrentMappingRevision:
    def test_returns_none_when_never_saved(self, db_session):
        dataset, model_id, _species_catalog, _parameter_catalog = _seed(db_session)
        assert (
            get_current_mapping_revision(
                db_session, initial_conditions_dataset_id=dataset.id, model_id=model_id
            )
            is None
        )
