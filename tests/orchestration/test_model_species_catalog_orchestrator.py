"""Tests for the Model-Species Catalog Prerequisite increment's own orchestration layer --
mirroring ``tests/orchestration/test_module_set_execution_orchestrator.py``'s own established
convention: the harness client is mocked via ``monkeypatch`` here (fast, no real subprocess);
real, end-to-end subprocess behavior (including a genuine Antimony/RoadRunner load) is proven
once, separately, at the Harness repository's own test level
(``agent-integration-harness/tests/harness/test_workbench_model_antimony_verification_contract
.py``) and again by ``tests/orchestration/test_end_to_end_persistence.py``'s own real
``real_run_id`` fixture, which exercises this exact orchestrator through a real whole-model
build.
"""

from __future__ import annotations

import json

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts.model_antimony_verification import ModelAntimonyVerificationResult
from app.models.enums import (
    ModelSourceType,
    ModelSpeciesCatalogStatus,
    ModelSpeciesKind,
    ProjectType,
    RunStage,
    SubprojectTaskType,
)
from app.orchestration import model_species_catalog_orchestrator
from app.persistence.model import persist_model
from app.persistence.model_species_catalog import get_model_species_catalog
from app.persistence.project import persist_project
from app.persistence.run_record import create_run_record
from app.persistence.subproject import persist_subproject
from tests.persistence.conftest import make_model_id, make_subproject_id

_ANTIMONY_TEXT = "model m\n  species S1\nend\n"


def _agent2_assembly(
    *,
    antimony_text: str | None = _ANTIMONY_TEXT,
    species: list[dict] | None = None,
    compartments: list[dict] | None = None,
    symbol_map_species: dict[str, str] | None = None,
) -> dict:
    data: dict = {}
    if antimony_text is not None:
        data["antimony_text"] = antimony_text
    data["species"] = (
        species
        if species is not None
        else [
            {"species_id": "compound-S1::in::c1", "name": "S1", "compartment_id": "c1"},
        ]
    )
    data["compartments"] = (
        compartments if compartments is not None else [{"compartment_id": "c1", "name": "cyto"}]
    )
    data["antimony_symbol_map"] = {
        "species": (
            symbol_map_species
            if symbol_map_species is not None
            else {"compound-S1::in::c1": "s_S1_cyto"}
        )
    }
    return data


def _write_assembly(tmp_path, assembly: dict) -> str:
    path = tmp_path / "agent2_assembly.json"
    path.write_text(json.dumps(assembly))
    return str(path)


def _run_record_id(db_session, *, model_id) -> str:
    run = create_run_record(
        subproject_id=make_subproject_id(db_session),
        stage=RunStage.HARNESS,
        session=db_session,
        model_id=model_id,
    )
    db_session.flush()
    return run.id


def _fake_invoke(
    *, load_succeeded=True, load_message=None, floating=("s_S1_cyto",), boundary=()
):
    def _invoke(request):
        return (
            ModelAntimonyVerificationResult(
                contract_version=request.contract_version,
                run_id=request.run_id,
                status="SUCCEEDED",
                load_succeeded=load_succeeded,
                load_message=load_message,
                floating_species_ids=tuple(floating),
                boundary_species_ids=tuple(boundary),
                compartment_ids=("c_cyto",),
                antimony_version="3.2.0",
                roadrunner_version="2.10.0",
                started_at="t0",
                completed_at="t1",
                error=None,
                summary="verified",
            ),
            None,
        )

    return _invoke


class TestCaptureModelSpeciesCatalog:
    def test_a_successful_capture_persists_a_verified_species_and_compartment(
        self, db_session, monkeypatch, tmp_path
    ):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        monkeypatch.setattr(
            model_species_catalog_orchestrator, "invoke_model_antimony_verification", _fake_invoke()
        )
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "save_model_antimony_text",
            lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
        )
        path = _write_assembly(tmp_path, _agent2_assembly())

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )

        assert catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
        assert catalog.unavailable_reason is None
        assert catalog.source_antimony_artifact_reference == "artifacts/models/fake.antimony"
        assert len(catalog.species) == 1
        sp = catalog.species[0]
        assert sp.antimony_species_id == "s_S1_cyto"
        assert sp.canonical_species_id == "compound-S1::in::c1"
        assert sp.compartment_id == "c1"
        assert sp.compartment_name == "cyto"
        assert sp.kind is ModelSpeciesKind.FLOATING
        assert sp.unit is None
        assert len(catalog.compartments) == 1
        assert catalog.compartments[0].species_count == 1

    def test_a_boundary_species_is_captured_with_the_right_kind(
        self, db_session, monkeypatch, tmp_path
    ):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "invoke_model_antimony_verification",
            _fake_invoke(floating=(), boundary=("s_S1_cyto",)),
        )
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "save_model_antimony_text",
            lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
        )
        path = _write_assembly(tmp_path, _agent2_assembly())

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        assert catalog.species[0].kind is ModelSpeciesKind.BOUNDARY

    def test_missing_antimony_text_is_unavailable(self, db_session, monkeypatch, tmp_path):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        path = _write_assembly(tmp_path, _agent2_assembly(antimony_text=None))

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        assert catalog.status is ModelSpeciesCatalogStatus.UNAVAILABLE
        assert "antimony_text" in catalog.unavailable_reason

    def test_a_missing_output_file_is_unavailable_never_an_exception(self, db_session):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session,
            model_id=model_id,
            run_record_id=run_record_id,
            agent2_assembly_path="/nonexistent/agent2_assembly.json",
        )
        assert catalog.status is ModelSpeciesCatalogStatus.UNAVAILABLE

    def test_a_harness_client_error_is_unavailable(self, db_session, monkeypatch, tmp_path):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)

        class _Err:
            code = "HARNESS_SUBPROCESS_TIMEOUT"
            message = "timed out"

        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "invoke_model_antimony_verification",
            lambda request: (None, _Err()),
        )
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "save_model_antimony_text",
            lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
        )
        path = _write_assembly(tmp_path, _agent2_assembly())

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        assert catalog.status is ModelSpeciesCatalogStatus.UNAVAILABLE
        assert "HARNESS_SUBPROCESS_TIMEOUT" in catalog.unavailable_reason

    def test_a_real_load_failure_is_unavailable_never_a_valid_empty_catalog(
        self, db_session, monkeypatch, tmp_path
    ):
        """load_succeeded=False means nothing real exists to catalog at all -- this must never
        be confused with a genuinely empty-but-valid model."""
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "invoke_model_antimony_verification",
            _fake_invoke(load_succeeded=False, load_message="Antimony compilation failed: bad"),
        )
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "save_model_antimony_text",
            lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
        )
        path = _write_assembly(tmp_path, _agent2_assembly())

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        assert catalog.status is ModelSpeciesCatalogStatus.UNAVAILABLE
        assert "bad" in catalog.unavailable_reason

    def test_a_structural_species_not_surviving_into_the_real_model_is_disclosed_not_dropped(
        self, db_session, monkeypatch, tmp_path
    ):
        """The one fact this whole increment exists to get right: a canonical species with a
        symbol_map entry that does not actually load for real is reported, never silently
        included as if it were real, and never silently discarded with no trace."""
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "invoke_model_antimony_verification",
            _fake_invoke(floating=()),  # s_S1_cyto never actually loaded for real
        )
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "save_model_antimony_text",
            lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
        )
        path = _write_assembly(tmp_path, _agent2_assembly())

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        assert catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
        assert catalog.species == []
        assert json.loads(catalog.unresolved_canonical_species_ids) == ["compound-S1::in::c1"]

    def test_a_structural_species_with_no_symbol_map_entry_at_all_is_disclosed(
        self, db_session, monkeypatch, tmp_path
    ):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "invoke_model_antimony_verification",
            _fake_invoke(),
        )
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "save_model_antimony_text",
            lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
        )
        path = _write_assembly(tmp_path, _agent2_assembly(symbol_map_species={}))

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        assert catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
        assert catalog.species == []
        assert json.loads(catalog.unmapped_canonical_species_ids) == ["compound-S1::in::c1"]

    def test_a_species_declaring_an_unknown_compartment_is_unavailable(
        self, db_session, monkeypatch, tmp_path
    ):
        """Defensive validation of a referential-integrity anomaly Agent 2 itself should
        already prevent -- never silently proceeded past if it somehow occurs anyway."""
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "invoke_model_antimony_verification",
            _fake_invoke(),
        )
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "save_model_antimony_text",
            lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
        )
        path = _write_assembly(tmp_path, _agent2_assembly(compartments=[]))

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        assert catalog.status is ModelSpeciesCatalogStatus.UNAVAILABLE
        assert "compartment" in catalog.unavailable_reason.lower()

    def test_two_canonical_species_mapped_to_the_same_antimony_id_is_unavailable(
        self, db_session, monkeypatch, tmp_path
    ):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "invoke_model_antimony_verification",
            _fake_invoke(floating=("s_dup",)),
        )
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "save_model_antimony_text",
            lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
        )
        path = _write_assembly(
            tmp_path,
            _agent2_assembly(
                species=[
                    {"species_id": "compound-A::in::c1", "name": "A", "compartment_id": "c1"},
                    {"species_id": "compound-B::in::c1", "name": "B", "compartment_id": "c1"},
                ],
                symbol_map_species={
                    "compound-A::in::c1": "s_dup",
                    "compound-B::in::c1": "s_dup",
                },
            ),
        )

        catalog = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        assert catalog.status is ModelSpeciesCatalogStatus.UNAVAILABLE
        assert "s_dup" in catalog.unavailable_reason

    def test_a_second_call_for_the_same_model_reuses_the_existing_catalog_without_reinvoking(
        self, db_session, monkeypatch, tmp_path
    ):
        model_id = make_model_id(db_session)
        run_record_id = _run_record_id(db_session, model_id=model_id)
        calls = {"count": 0}

        def _counting_invoke(request):
            calls["count"] += 1
            return _fake_invoke()(request)

        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "invoke_model_antimony_verification",
            _counting_invoke,
        )
        monkeypatch.setattr(
            model_species_catalog_orchestrator,
            "save_model_antimony_text",
            lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
        )
        path = _write_assembly(tmp_path, _agent2_assembly())

        first = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        second = model_species_catalog_orchestrator.capture_model_species_catalog(
            db_session, model_id=model_id, run_record_id=run_record_id, agent2_assembly_path=path
        )
        assert first.id == second.id
        assert calls["count"] == 1

    def test_get_model_species_catalog_returns_none_when_never_captured(self, db_session):
        model_id = make_model_id(db_session)
        assert get_model_species_catalog(db_session, model_id) is None


class TestCaptureSurvivesAnIndependentSession:
    """``capture_model_species_catalog`` already commits internally -- this proves that
    commit is real and durable, not an artifact of a shared, rolled-back test transaction:
    every assertion here queries through a brand-new ``Session``, opened after the capturing
    session has fully closed, mirroring ``tests/orchestration/test_module_set_run_recovery.py``
    's own established discipline exactly."""

    def test_an_available_catalog_is_visible_from_a_second_independent_session(
        self, migrated_engine: Engine, monkeypatch, tmp_path
    ) -> None:
        capturing_session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            project_id = persist_project(
                stable_identifier=f"PRJ-catalog-durability-{tmp_path.name}",
                title="catalog durability project",
                project_type=ProjectType.MICROBIAL_METABOLISM,
                session=capturing_session,
            ).entity_id
            subproject_id = persist_subproject(
                project_id=project_id,
                title="catalog durability study",
                task_type=SubprojectTaskType.BUILD_MODEL,
                session=capturing_session,
            ).entity_id
            model_id = persist_model(
                subproject_id=subproject_id,
                stable_identifier=f"MOD-catalog-durability-{tmp_path.name}",
                name="catalog durability model",
                source_type=ModelSourceType.GENERATED,
                session=capturing_session,
            ).entity_id
            run_record_id = _run_record_id(capturing_session, model_id=model_id)
            capturing_session.commit()

            monkeypatch.setattr(
                model_species_catalog_orchestrator,
                "invoke_model_antimony_verification",
                _fake_invoke(),
            )
            monkeypatch.setattr(
                model_species_catalog_orchestrator,
                "save_model_antimony_text",
                lambda text: ("artifacts/models/fake.antimony", "deadbeef"),
            )
            path = _write_assembly(tmp_path, _agent2_assembly())
            model_species_catalog_orchestrator.capture_model_species_catalog(
                capturing_session,
                model_id=model_id,
                run_record_id=run_record_id,
                agent2_assembly_path=path,
            )
        finally:
            capturing_session.close()

        # A brand-new session, opened after the capturing one is fully closed -- an
        # uncommitted write would be invisible here even though it was visible to the
        # capturing session's own identity map.
        verifying_session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            catalog = get_model_species_catalog(verifying_session, model_id)
            assert catalog is not None
            assert catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
            assert len(catalog.species) == 1
            assert catalog.species[0].antimony_species_id == "s_S1_cyto"
            assert catalog.species[0].kind is ModelSpeciesKind.FLOATING
        finally:
            verifying_session.close()
