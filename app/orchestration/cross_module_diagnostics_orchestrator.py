"""Cross-Module Consistency and Reconciliation Diagnostics: the service layer a caller uses to
run (or idempotently re-fetch) the consistency sweep for one hierarchy run, retrieve its
current findings, inspect their full evidence/provenance, and mark a finding reviewed.

No agent or harness call happens here (task instructions §7) -- every comparison reads only
already-persisted ``ModelModule``/``ModuleBoundaryPort``/``RunRecord``/
``ModuleExecutionSnapshot`` rows. This module never reconciles, merges, or overwrites a
conflicting value (task instructions §4) -- it only *reports* that two modules disagree,
side by side, with the exact values and their own provenance attached. A clean sweep (no
findings) is never reported as "the hierarchy is globally valid" -- it is reported only as
"no inconsistency was detected by these specific checks," which is what ``run_diagnostics``'s
own returned ``CrossModuleDiagnosticRun`` literally is: a list of findings, nothing more.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cross_module_diagnostic import CrossModuleDiagnostic, CrossModuleDiagnosticRun
from app.models.enums import RunStage, RunStatus
from app.models.model_module import ModelModule
from app.models.run_record import RunRecord
from app.persistence.cross_module_diagnostic import (
    compute_diagnostic_run_fingerprint,
    create_diagnostic_run,
    get_finding,
    get_latest_diagnostic_run,
    list_findings_for_run,
    mark_finding_reviewed,
    read_affected_model_module_ids,
    read_diagnostic_evidence,
)
from app.persistence.model_module import list_model_modules_for_run
from app.persistence.module_boundary_port import list_boundary_ports_for_module
from app.persistence.module_execution_snapshot import get_snapshot_for_run
from app.persistence.run_record import get_run_record
from app.units import UnitComparisonStatus, compare_units

#: Boundary treatments that carry a concrete, comparable value -- the identical vocabulary
#: ``app.orchestration.module_boundary_orchestrator._STANDALONE_CAPABLE_TREATMENTS`` already
#: defines, reused here (not reinvented) because it is exactly the "this port claims one
#: specific, fixed value" set.
_VALUE_BEARING_TREATMENTS = {"EXTERNALLY_CONTROLLED", "PRESCRIBED_INPUT"}

_RUN_STAGE_BY_KIND = {"CALIBRATION": RunStage.AGENT4, "VALIDATION": RunStage.AGENT5}


def _latest_run_record(
    session: Session, model_module_id: UUID, stage: RunStage
) -> RunRecord | None:
    stmt = (
        select(RunRecord)
        .where(RunRecord.model_module_id == model_module_id, RunRecord.stage == stage)
        .order_by(RunRecord.created_at.desc())
    )
    runs = list(session.scalars(stmt))
    succeeded = [r for r in runs if r.status is RunStatus.SUCCEEDED]
    return succeeded[0] if succeeded else (runs[0] if runs else None)


def _gather_module_facts(session: Session, module: ModelModule) -> dict:
    """Every already-persisted, comparable fact about one module -- boundary ports, latest
    calibration/validation outcomes, and the dataset references each used. Never re-derived
    or inferred; every field here is read verbatim from an existing row."""
    boundary_ports = [
        {
            "port_id": p.port_id,
            "species_id": p.species_id,
            "direction": p.direction.value,
            "treatment_type": p.treatment_type.value,
            "resolution_status": p.resolution_status.value,
            "initial_value": str(p.initial_value) if p.initial_value is not None else None,
            "unit": p.unit,
        }
        for p in list_boundary_ports_for_module(session, module.id)
    ]

    calibration_run = _latest_run_record(session, module.id, RunStage.AGENT4)
    calibration: dict | None = None
    if calibration_run is not None:
        calibration = {
            "run_record_id": str(calibration_run.id),
            "status": calibration_run.status.value,
            "parameter_estimates": [],
            "dataset_reference_ids": [],
        }
        if calibration_run.status is RunStatus.SUCCEEDED and calibration_run.artifact_reference:
            try:
                artifact = json.loads(calibration_run.artifact_reference)
                calibration["parameter_estimates"] = (
                    (artifact.get("agent4_report") or {}).get("calibration") or {}
                ).get("parameter_estimates", [])
            except (TypeError, json.JSONDecodeError):
                pass
        snapshot = get_snapshot_for_run(session, calibration_run.id)
        if snapshot is not None:
            payload = json.loads(snapshot.snapshot_payload)
            calibration["dataset_reference_ids"] = [
                d["dataset_reference_id"] for d in (payload.get("dataset_references") or ())
            ]
            calibration["execution_snapshot_id"] = str(snapshot.id)
            #: ``{parameter_id: unit}`` for this module's own materialized parameters, read
            #: back from the calibration snapshot's own ``parameters`` array (Agent2's own
            #: already-recorded unit metadata -- never fabricated here). Lets
            #: ``_detect_parameter_conflicts`` compare unit metadata for the identical
            #: ``target_id``/``parameter_id`` namespace a fitted estimate already uses (task
            #: instructions §3: "model parameters where unit metadata exists").
            calibration["parameter_units"] = {
                p["parameter_id"]: p.get("unit") for p in (payload.get("parameters") or ())
            }
        else:
            calibration["execution_snapshot_id"] = None
            calibration["parameter_units"] = {}

    validation_run = _latest_run_record(session, module.id, RunStage.AGENT5)
    validation: dict | None = None
    if validation_run is not None:
        validation = {
            "run_record_id": str(validation_run.id),
            "status": validation_run.status.value,
            "overall_status": None,
            "dataset_reference_ids": [],
        }
        if validation_run.status is RunStatus.SUCCEEDED and validation_run.artifact_reference:
            try:
                artifact = json.loads(validation_run.artifact_reference)
                validation["overall_status"] = (artifact.get("agent5_report") or {}).get(
                    "overall_status"
                )
            except (TypeError, json.JSONDecodeError):
                pass
        snapshot = get_snapshot_for_run(session, validation_run.id)
        if snapshot is not None:
            payload = json.loads(snapshot.snapshot_payload)
            validation["dataset_reference_ids"] = [
                d["dataset_reference_id"] for d in (payload.get("dataset_references") or ())
            ]
            validation["execution_snapshot_id"] = str(snapshot.id)
        else:
            validation["execution_snapshot_id"] = None

    return {
        "model_module_id": str(module.id),
        "module_id": module.module_id,
        "parent_model_module_id": (
            str(module.parent_model_module_id) if module.parent_model_module_id else None
        ),
        "boundary_ports": boundary_ports,
        "calibration": calibration,
        "validation": validation,
    }


def _related_pairs(modules: list[ModelModule]) -> list[tuple[ModelModule, ModelModule]]:
    """Every (sibling, sibling) and (parent, child) pair -- the only relationships a shared
    boundary species/parameter is scientifically meaningful to compare across (task
    instructions: "sibling/parent-child modules"). Each unordered pair appears exactly once."""
    by_parent: dict[str | None, list[ModelModule]] = {}
    by_id = {m.id: m for m in modules}
    for m in modules:
        by_parent.setdefault(
            str(m.parent_model_module_id) if m.parent_model_module_id else None, []
        ).append(m)

    pairs: list[tuple[ModelModule, ModelModule]] = []
    for siblings in by_parent.values():
        for i in range(len(siblings)):
            for j in range(i + 1, len(siblings)):
                pairs.append((siblings[i], siblings[j]))
    for m in modules:
        if m.parent_model_module_id is not None and m.parent_model_module_id in by_id:
            pairs.append((by_id[m.parent_model_module_id], m))
    return pairs


def _finding(
    category: str, severity: str, message: str, module_ids: list[str], evidence: dict
) -> dict:
    return {
        "category": category,
        "severity": severity,
        "message": message,
        "affected_model_module_ids": module_ids,
        "evidence_payload": evidence,
    }


def _is_parent_child(a: dict, b: dict) -> bool:
    return (
        a["model_module_id"] == b["parent_model_module_id"]
        or b["model_module_id"] == a["parent_model_module_id"]
    )


def _unit_compatibility_finding(
    unit_a: str | None,
    unit_b: str | None,
    *,
    message_prefix: str,
    module_ids: list[str],
    evidence: dict,
) -> dict | None:
    """Category 2 (``UNIT_INCOMPATIBILITY``): dimensional-compatibility check replacing bare
    string equality (task instructions §7). ``None`` if both sides lack a unit entirely (there
    is nothing to compare) or both resolve to the identical normalized unit (no disclosure
    needed).

    Severity reflects what was actually found, never a flat "units differ": a genuine
    dimensional incompatibility is ``ERROR`` (a real logical conflict, worse than the prior
    bare-string-mismatch ``WARNING``); an unparseable unit string is its own ``WARNING``
    (distinct from a confirmed incompatibility -- it is not yet known whether the units would
    even conflict); a unit recorded on only one side, or two dimensionally-equivalent but
    differently-written units (e.g. ``"mM"`` vs ``"mmol/L"``), are each ``INFO`` disclosures,
    never silently treated as either a conflict or a free conversion (task instructions §5: the
    full ``compare_units`` result, including any conversion factor, is always embedded in the
    returned finding's own evidence).
    """
    if unit_a is None and unit_b is None:
        return None
    comparison = compare_units(unit_a, unit_b)
    status = comparison["status"]
    if status == UnitComparisonStatus.MISSING.value:
        severity, detail = "INFO", "has a unit recorded on only one side"
    elif status == UnitComparisonStatus.INCOMPATIBLE.value:
        severity, detail = "ERROR", "are declared in dimensionally incompatible units"
    elif status == UnitComparisonStatus.MALFORMED.value:
        severity, detail = "WARNING", "could not be parsed as a valid unit on at least one side"
    else:
        if comparison["unit_a"]["normalized_unit"] == comparison["unit_b"]["normalized_unit"]:
            return None
        severity, detail = "INFO", "use different, but dimensionally equivalent, units"
    return _finding(
        "UNIT_INCOMPATIBILITY",
        severity,
        f"{message_prefix} {detail} ({unit_a!r} vs {unit_b!r}) -- never automatically "
        "converted or reconciled.",
        module_ids,
        {**evidence, "unit_comparison": comparison},
    )


def _detect_boundary_conflicts(a: dict, b: dict) -> list[dict]:
    """Categories 1 and 4 (and part of 7): shared boundary species across related modules,
    including unit comparisons, and insufficient-evidence disclosure when one side's own
    treatment is still unresolved."""
    findings: list[dict] = []
    category = (
        "PARENT_CHILD_BOUNDARY_INCONSISTENCY"
        if _is_parent_child(a, b)
        else "SHARED_BOUNDARY_SPECIES_CONFLICT"
    )
    ports_by_species_a: dict[str, list[dict]] = {}
    for p in a["boundary_ports"]:
        ports_by_species_a.setdefault(p["species_id"], []).append(p)

    for port_b in b["boundary_ports"]:
        for port_a in ports_by_species_a.get(port_b["species_id"], []):
            species_id = port_b["species_id"]
            module_ids = [a["model_module_id"], b["model_module_id"]]
            evidence = {
                "species_id": species_id,
                "module_a": {"module_id": a["module_id"], "port": port_a},
                "module_b": {"module_id": b["module_id"], "port": port_b},
            }

            resolved_a = port_a["resolution_status"] == "RESOLVED"
            resolved_b = port_b["resolution_status"] == "RESOLVED"
            if not (resolved_a and resolved_b):
                findings.append(
                    _finding(
                        "INSUFFICIENT_EVIDENCE_FOR_COMPARISON",
                        "UNRESOLVED",
                        f"species {species_id!r} is a shared boundary between module "
                        f"{a['module_id']!r} and {b['module_id']!r}, but at least one side's "
                        "own boundary treatment is still unresolved -- this comparison cannot "
                        "be concluded safely.",
                        module_ids,
                        evidence,
                    )
                )
                continue

            value_a, value_b = port_a["initial_value"], port_b["initial_value"]
            treatment_a, treatment_b = port_a["treatment_type"], port_b["treatment_type"]
            both_value_bearing = (
                treatment_a in _VALUE_BEARING_TREATMENTS
                and treatment_b in _VALUE_BEARING_TREATMENTS
            )
            if both_value_bearing and value_a is not None and value_b is not None:
                if Decimal(value_a) != Decimal(value_b):
                    findings.append(
                        _finding(
                            category,
                            "ERROR",
                            f"species {species_id!r} is fixed at two different values across "
                            f"module {a['module_id']!r} ({value_a}) and {b['module_id']!r} "
                            f"({value_b}).",
                            module_ids,
                            evidence,
                        )
                    )
                unit_finding = _unit_compatibility_finding(
                    port_a["unit"],
                    port_b["unit"],
                    message_prefix=(
                        f"species {species_id!r} (module {a['module_id']!r} vs {b['module_id']!r})"
                    ),
                    module_ids=module_ids,
                    evidence=evidence,
                )
                if unit_finding is not None:
                    findings.append(unit_finding)
            elif treatment_a != treatment_b:
                findings.append(
                    _finding(
                        category,
                        "WARNING",
                        f"species {species_id!r} is treated differently across module "
                        f"{a['module_id']!r} ({treatment_a}) and {b['module_id']!r} "
                        f"({treatment_b}) -- a modeling-assumption mismatch, not necessarily a "
                        "numeric conflict.",
                        module_ids,
                        evidence,
                    )
                )
    return findings


def _detect_parameter_conflicts(a: dict, b: dict) -> list[dict]:
    """Category 3: the same parameter target_id calibrated to two different values."""
    findings: list[dict] = []
    calib_a, calib_b = a["calibration"], b["calibration"]
    if calib_a is None or calib_b is None:
        return findings
    estimates_a = {e["target_id"]: e for e in calib_a.get("parameter_estimates", [])}
    estimates_b = {e["target_id"]: e for e in calib_b.get("parameter_estimates", [])}
    units_a = calib_a.get("parameter_units", {})
    units_b = calib_b.get("parameter_units", {})
    for target_id in sorted(set(estimates_a) & set(estimates_b)):
        value_a = estimates_a[target_id]["fitted_value"]
        value_b = estimates_b[target_id]["fitted_value"]
        module_ids = [a["model_module_id"], b["model_module_id"]]
        evidence = {
            "target_id": target_id,
            "module_a": {
                "module_id": a["module_id"],
                "fitted_value": value_a,
                "run_record_id": calib_a["run_record_id"],
            },
            "module_b": {
                "module_id": b["module_id"],
                "fitted_value": value_b,
                "run_record_id": calib_b["run_record_id"],
            },
        }
        if value_a != value_b:
            findings.append(
                _finding(
                    "PARAMETER_ASSUMPTION_CONFLICT",
                    "ERROR",
                    f"parameter {target_id!r} was fitted to two different values across module "
                    f"{a['module_id']!r} ({value_a}) and {b['module_id']!r} ({value_b}).",
                    module_ids,
                    evidence,
                )
            )
        unit_finding = _unit_compatibility_finding(
            units_a.get(target_id),
            units_b.get(target_id),
            message_prefix=(
                f"parameter {target_id!r} (module {a['module_id']!r} vs {b['module_id']!r})"
            ),
            module_ids=module_ids,
            evidence=evidence,
        )
        if unit_finding is not None:
            findings.append(unit_finding)
    return findings


def _detect_dataset_context_issues(a: dict, b: dict) -> list[dict]:
    """Category 5: related modules used different, unverifiable dataset contexts -- disclosed,
    never claimed compatible or incompatible."""
    findings: list[dict] = []
    for kind in ("calibration", "validation"):
        fact_a, fact_b = a[kind], b[kind]
        if fact_a is None or fact_b is None:
            continue
        ids_a = set(fact_a.get("dataset_reference_ids", []))
        ids_b = set(fact_b.get("dataset_reference_ids", []))
        if ids_a and ids_b and ids_a != ids_b:
            findings.append(
                _finding(
                    "DATASET_CONTEXT_INCOMPATIBILITY",
                    "INFO",
                    f"module {a['module_id']!r} and {b['module_id']!r} used different "
                    f"{kind} dataset references -- compatibility of their experimental "
                    "contexts cannot be automatically verified.",
                    [a["model_module_id"], b["model_module_id"]],
                    {
                        "kind": kind,
                        "module_a_dataset_ids": sorted(ids_a),
                        "module_b_dataset_ids": sorted(ids_b),
                    },
                )
            )
    return findings


def _detect_validation_outcome_conflicts(a: dict, b: dict) -> list[dict]:
    """Category 6: heterogeneous validation outcomes across related modules -- disclosed as a
    heterogeneity, never interpreted as a deeper scientific contradiction."""
    val_a, val_b = a["validation"], b["validation"]
    if val_a is None or val_b is None:
        return []
    status_a, status_b = val_a.get("overall_status"), val_b.get("overall_status")
    if status_a is None or status_b is None or status_a == status_b:
        return []
    clean = {"SUCCESS"}
    if (status_a in clean) == (status_b in clean):
        return []
    return [
        _finding(
            "CONFLICTING_CALIBRATION_OR_VALIDATION_OUTCOME",
            "WARNING",
            f"module {a['module_id']!r} ({status_a}) and {b['module_id']!r} ({status_b}) "
            "report heterogeneous validation outcomes.",
            [a["model_module_id"], b["model_module_id"]],
            {
                "module_a": {
                    "module_id": a["module_id"],
                    "overall_status": status_a,
                    "run_record_id": val_a["run_record_id"],
                },
                "module_b": {
                    "module_id": b["module_id"],
                    "overall_status": status_b,
                    "run_record_id": val_b["run_record_id"],
                },
            },
        )
    ]


def run_diagnostics(*, hierarchy_run_record_id: UUID, session: Session) -> CrossModuleDiagnosticRun:
    """Run (or idempotently return the latest existing) cross-module consistency sweep for
    every module of one hierarchy run.

    Compares every pair of *related* modules (siblings sharing a parent, and parent/child
    pairs -- task instructions: "sibling/parent-child modules") across all seven detection
    categories. Never invokes any agent or the harness (task instructions §7); never merges,
    averages, or silently resolves a detected conflict (task instructions §4).
    """
    hierarchy_run = get_run_record(session, hierarchy_run_record_id)
    if hierarchy_run is None:
        raise ValueError(f"no RunRecord with id {hierarchy_run_record_id}")

    modules = list_model_modules_for_run(session, hierarchy_run_record_id)
    facts_by_id = {m.id: _gather_module_facts(session, m) for m in modules}

    findings: list[dict] = []
    for module_a, module_b in _related_pairs(modules):
        a, b = facts_by_id[module_a.id], facts_by_id[module_b.id]
        findings += _detect_boundary_conflicts(a, b)
        findings += _detect_parameter_conflicts(a, b)
        findings += _detect_dataset_context_issues(a, b)
        findings += _detect_validation_outcome_conflicts(a, b)

    fingerprint = compute_diagnostic_run_fingerprint(
        {"modules": [facts_by_id[m.id] for m in sorted(modules, key=lambda m: str(m.id))]}
    )
    return create_diagnostic_run(
        hierarchy_run_record_id=hierarchy_run_record_id,
        input_fingerprint=fingerprint,
        findings=findings,
        session=session,
    )


def get_current_findings(
    session: Session, hierarchy_run_record_id: UUID
) -> list[CrossModuleDiagnostic]:
    """Every finding of the *latest* diagnostic run for one hierarchy run, or ``[]`` if the
    sweep has never been run. Read-only -- never runs the sweep."""
    latest = get_latest_diagnostic_run(session, hierarchy_run_record_id)
    if latest is None:
        return []
    return list_findings_for_run(session, latest.id)


def get_finding_evidence(session: Session, finding_id: UUID) -> dict:
    """One finding's own full evidence payload, plus its own ``affected_model_module_ids``.
    Raises ``ValueError`` if the finding does not exist."""
    finding = get_finding(session, finding_id)
    if finding is None:
        raise ValueError(f"no CrossModuleDiagnostic with id {finding_id}")
    return {
        "affected_model_module_ids": read_affected_model_module_ids(finding),
        "evidence": read_diagnostic_evidence(finding),
    }


def review_finding(
    *,
    finding_id: UUID,
    session: Session,
    review_note: str | None = None,
    reviewed_by: str | None = None,
) -> CrossModuleDiagnostic:
    """Mark one finding reviewed with an optional human note -- never altering the finding's
    own detection content or any source record it describes. Thin, documented re-export of
    ``app.persistence.cross_module_diagnostic.mark_finding_reviewed``."""
    return mark_finding_reviewed(
        finding_id=finding_id, session=session, review_note=review_note, reviewed_by=reviewed_by
    )


__all__ = [
    "get_current_findings",
    "get_finding_evidence",
    "review_finding",
    "run_diagnostics",
]
