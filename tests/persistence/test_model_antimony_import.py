"""Tests for ``app.orchestration.model_antimony_import_orchestrator`` (Whole-Model Antimony
Import increment, ``docs/34``) -- real, end-to-end: a real harness subprocess round against
real Agent 2/Agent 3 execution every time, never a mocked harness client.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.enums import ModelSourceType, ModelStatus, RunStatus
from app.models.model import Model
from app.orchestration.model_antimony_import_orchestrator import (
    AntimonyImportVerificationFailedError,
    preview_antimony_import,
    save_antimony_import,
)
from app.persistence.model_import_provenance import get_model_import_provenance
from app.persistence.model_parameter_catalog import get_model_parameter_catalog
from app.persistence.model_species_catalog import get_model_species_catalog
from app.persistence.run_record import get_run_record
from tests.persistence.conftest import make_project_id, make_subproject_id

_VALID_ANTIMONY_TEXT = """
model decay_model
  compartment C1
  C1 = 1.0
  species S1 in C1
  species S2 in C1
  S1 = 10
  S2 = 0
  R1: S1 -> S2; k1*S1
  k1 = 0.1
end
"""

#: A compartment ("unused") that compiles but has zero species -- a real, legitimate outcome,
#: confirmed against the real EGFR-Ras reference model's own "extra" compartment during this
#: increment's own live verification. Never silently omitted from the captured catalog.
_ANTIMONY_TEXT_WITH_UNUSED_COMPARTMENT = """
model probe
  compartment used, unused
  used = 1.0
  unused = 1.0
  species A in used
  A = 10
  R1: A -> ; k1 * A
  k1 = 0.1
end
"""

_ANTIMONY_TEXT_WITH_FUNCTION_DEFINITION = """
function double(x)
  x * 2
end

model has_function
  compartment C1
  C1 = 1.0
  species S1 in C1
  S1 = 10
  R1: S1 -> ; double(0.1) * S1
end
"""


class TestPreview:
    def test_preview_succeeds_for_valid_antimony(self):
        preview = preview_antimony_import(_VALID_ANTIMONY_TEXT)
        assert preview.load_succeeded is True
        assert sorted(preview.floating_species_ids) == ["S1", "S2"]
        assert preview.compartment_ids == ("C1",)
        assert preview.import_succeeded is True
        assert preview.assignment_rule_count == 0

    def test_preview_reports_malformed_antimony_honestly_never_raises(self):
        preview = preview_antimony_import("this is not valid antimony !!!")
        assert preview.load_succeeded is False
        assert preview.load_message is not None


class TestSave:
    def test_save_persists_model_catalog_and_provenance(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        db_session.commit()

        model = save_antimony_import(
            db_session,
            subproject_id=subproject_id,
            model_name="Decay test import",
            antimony_text=_VALID_ANTIMONY_TEXT,
            original_filename="decay.antimony",
            source_reference="unit test",
            verification_notes="looks right",
            created_by="tester",
        )

        assert model.source_type is ModelSourceType.IMPORTED
        assert model.status is ModelStatus.ACTIVE
        assert model.subproject_id == subproject_id

        species_catalog = get_model_species_catalog(db_session, model.id)
        assert species_catalog is not None
        assert {s.antimony_species_id for s in species_catalog.species} == {"S1", "S2"}
        assert {c.compartment_id for c in species_catalog.compartments} == {"C1"}

        parameter_catalog = get_model_parameter_catalog(db_session, model.id)
        assert parameter_catalog is not None
        assert {p.antimony_parameter_id for p in parameter_catalog.parameters} == {"k1"}

        provenance = get_model_import_provenance(db_session, model.id)
        assert provenance is not None
        assert provenance.original_filename == "decay.antimony"
        assert provenance.source_reference == "unit test"
        assert provenance.import_succeeded is True
        assert provenance.assignment_rule_count == 0

        run = get_run_record(db_session, provenance.run_record_id)
        assert run is not None
        assert run.status is RunStatus.SUCCEEDED
        assert run.model_id == model.id

    def test_a_compartment_with_zero_species_is_still_captured(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        db_session.commit()

        model = save_antimony_import(
            db_session,
            subproject_id=subproject_id,
            model_name="Unused compartment test",
            antimony_text=_ANTIMONY_TEXT_WITH_UNUSED_COMPARTMENT,
            original_filename="probe.antimony",
        )
        species_catalog = get_model_species_catalog(db_session, model.id)
        compartments_by_id = {c.compartment_id: c for c in species_catalog.compartments}
        assert set(compartments_by_id) == {"used", "unused"}
        assert compartments_by_id["unused"].species_count == 0
        assert compartments_by_id["used"].species_count == 1

    def test_malformed_antimony_is_rejected_and_no_model_is_created(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        db_session.commit()

        existing_count = db_session.execute(
            select(Model).where(Model.subproject_id == subproject_id)
        ).scalars().all()
        assert existing_count == []

        with pytest.raises(AntimonyImportVerificationFailedError):
            save_antimony_import(
                db_session,
                subproject_id=subproject_id,
                model_name="Should never exist",
                antimony_text="this is not valid antimony !!!",
                original_filename="garbage.antimony",
            )

        remaining = db_session.execute(
            select(Model).where(Model.subproject_id == subproject_id)
        ).scalars().all()
        assert remaining == []

    def test_reuploading_identical_bytes_creates_a_new_independent_model(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        db_session.commit()

        model_a = save_antimony_import(
            db_session,
            subproject_id=subproject_id,
            model_name="First upload",
            antimony_text=_VALID_ANTIMONY_TEXT,
            original_filename="decay.antimony",
        )
        model_b = save_antimony_import(
            db_session,
            subproject_id=subproject_id,
            model_name="Second upload, identical bytes",
            antimony_text=_VALID_ANTIMONY_TEXT,
            original_filename="decay.antimony",
        )
        assert model_a.id != model_b.id
        assert model_a.stable_identifier != model_b.stable_identifier

        provenance_a = get_model_import_provenance(db_session, model_a.id)
        provenance_b = get_model_import_provenance(db_session, model_b.id)
        assert provenance_a.original_checksum == provenance_b.original_checksum

    def test_an_unsupported_construct_still_saves_with_a_disclosed_audit_failure(
        self, db_session
    ):
        """Agent 3's own real executability check is the only gate -- a function call
        evaluates to a plain number at simulation time (real, executable), even though
        Agent 2's own import audit explicitly rejects function definitions. The save must
        still succeed, with the audit failure honestly disclosed, never silently hidden and
        never blocking a model that genuinely is real and executable."""
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        db_session.commit()

        model = save_antimony_import(
            db_session,
            subproject_id=subproject_id,
            model_name="Has a function definition",
            antimony_text=_ANTIMONY_TEXT_WITH_FUNCTION_DEFINITION,
            original_filename="has_function.antimony",
        )
        assert model.status is ModelStatus.ACTIVE

        provenance = get_model_import_provenance(db_session, model.id)
        assert provenance.import_succeeded is False
        assert provenance.import_error_kind == "UNSUPPORTED_CONSTRUCT"
        assert "function" in provenance.import_message.lower()

        species_catalog = get_model_species_catalog(db_session, model.id)
        assert {s.antimony_species_id for s in species_catalog.species} == {"S1"}
