import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  deriveModuleSetMemberBoundaryReview,
  getModelingStudy,
  getModuleSetMemberBoundaryReview,
  getModuleSetMemberSimulation,
  getModuleSetVersion,
  getProject,
  listModuleSetMemberSimulations,
  submitModuleSetMemberBoundaryDecision,
  submitModuleSetMemberSimulation,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import {
  formatBoundaryResolutionStatus,
  formatBoundaryTreatmentType,
  formatPortDirection,
  formatReadinessFindingCode,
  formatRunStatus,
  NOT_CAPTURED,
} from "../format";
import type {
  ModuleBoundaryTreatmentType,
  ModuleSetMemberBoundaryPortItem,
  ModuleSetMemberReviewDetail,
  ModuleSetSimulationRunItem,
  ModuleSetVersionDetail,
  ProjectDetail,
  SubprojectDetail,
} from "../types";
import { RouterLink } from "./RouterLink";

type LoadState<T> =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; value: T };

interface ModuleSetMemberExecutionScreenProps {
  projectId: string;
  studyId: string;
  moduleSetId: string;
  version: string;
  memberId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

const ACTIVE_RUN_POLL_INTERVAL_MS = 3000;

/** Boundary review, readiness, and simulation for one saved module-set version's own
 * member -- the Module-Set Edited-Module Materialization increment, Phase B
 * (docs/24_module_set_execution_increment.md). There is no Figma screen for this anywhere
 * in the design file (confirmed by a full search during this increment's own planning) --
 * this layout is a from-scratch, functional design, following this codebase's existing
 * component/CSS conventions rather than any design reference. */
export function ModuleSetMemberExecutionScreen({
  projectId,
  studyId,
  moduleSetId,
  version,
  memberId,
  onProjectChange,
  onStudyChange,
}: ModuleSetMemberExecutionScreenProps) {
  const [projectState, setProjectState] = useState<LoadState<ProjectDetail>>({
    status: "loading",
  });
  const [studyState, setStudyState] = useState<LoadState<SubprojectDetail>>({
    status: "loading",
  });
  const [versionState, setVersionState] = useState<LoadState<ModuleSetVersionDetail>>({
    status: "loading",
  });
  const [reviewState, setReviewState] = useState<LoadState<ModuleSetMemberReviewDetail>>({
    status: "loading",
  });
  const [runsState, setRunsState] = useState<LoadState<ModuleSetSimulationRunItem[]>>({
    status: "loading",
  });

  const [deriving, setDeriving] = useState(false);
  const [deriveError, setDeriveError] = useState<string | null>(null);
  const [decidingPortId, setDecidingPortId] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [submittingSimulation, setSubmittingSimulation] = useState(false);
  const [simulationError, setSimulationError] = useState<string | null>(null);
  const [simulationErrorFindings, setSimulationErrorFindings] = useState<string[] | null>(null);
  const [savedByInput, setSavedByInput] = useState("");

  const guard = useRef(createStaleGuard<string>()).current;

  function reloadReview() {
    getModuleSetMemberBoundaryReview(projectId, studyId, moduleSetId, version, memberId)
      .then((review) => setReviewState({ status: "ready", value: review }))
      .catch((error: unknown) => {
        const message = error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setReviewState({ status: "error", message });
      });
  }

  function reloadRuns() {
    listModuleSetMemberSimulations(projectId, studyId, moduleSetId, version, memberId)
      .then((runs) => setRunsState({ status: "ready", value: runs }))
      .catch((error: unknown) => {
        const message = error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setRunsState({ status: "error", message });
      });
  }

  useEffect(() => {
    const key = `${projectId}/${studyId}/${moduleSetId}/${version}/${memberId}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
    setVersionState({ status: "loading" });
    setReviewState({ status: "loading" });
    setRunsState({ status: "loading" });
    onProjectChange(null);
    onStudyChange(null);

    getProject(projectId)
      .then((project) => {
        if (!guard.isCurrent(key)) return;
        setProjectState({ status: "ready", value: project });
        onProjectChange(project);
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        if (error instanceof ApiRequestError && error.status === 404) {
          setProjectState({ status: "not-found" });
        } else {
          setProjectState({
            status: "error",
            message: error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
          });
        }
      });

    getModelingStudy(projectId, studyId)
      .then((study) => {
        if (!guard.isCurrent(key)) return;
        setStudyState({ status: "ready", value: study });
        onStudyChange(study);
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        if (error instanceof ApiRequestError && error.status === 404) {
          setStudyState({ status: "not-found" });
        } else {
          setStudyState({
            status: "error",
            message: error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
          });
        }
      });

    getModuleSetVersion(projectId, studyId, moduleSetId, version)
      .then((versionDetail) => {
        if (!guard.isCurrent(key)) return;
        setVersionState({ status: "ready", value: versionDetail });
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        if (error instanceof ApiRequestError && error.status === 404) {
          setVersionState({ status: "not-found" });
        } else {
          setVersionState({
            status: "error",
            message: error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
          });
        }
      });

    getModuleSetMemberBoundaryReview(projectId, studyId, moduleSetId, version, memberId)
      .then((review) => {
        if (guard.isCurrent(key)) setReviewState({ status: "ready", value: review });
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        if (error instanceof ApiRequestError && error.status === 404) {
          setReviewState({ status: "not-found" });
        } else {
          setReviewState({
            status: "error",
            message: error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
          });
        }
      });

    listModuleSetMemberSimulations(projectId, studyId, moduleSetId, version, memberId)
      .then((runs) => {
        if (guard.isCurrent(key)) setRunsState({ status: "ready", value: runs });
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        setRunsState({
          status: "error",
          message: error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
        });
      });

    return () => {
      onProjectChange(null);
      onStudyChange(null);
    };
    // `guard`, `onProjectChange`, `onStudyChange` intentionally omitted -- see
    // StudyDetailScreen's identical effect for why.
  }, [projectId, studyId, moduleSetId, version, memberId]);

  // Poll any non-terminal run until it reaches a terminal status -- the background worker
  // (scripts/module_set_simulation_worker.py) runs out-of-process, so this is the only way
  // this screen learns a run has finished.
  useEffect(() => {
    if (runsState.status !== "ready") return;
    const activeRuns = runsState.value.filter(
      (run) => run.status === "PENDING" || run.status === "RUNNING",
    );
    if (activeRuns.length === 0) return;

    const interval = window.setInterval(() => {
      Promise.all(
        activeRuns.map((run) =>
          getModuleSetMemberSimulation(projectId, studyId, moduleSetId, version, memberId, run.id),
        ),
      )
        .then((refreshed) => {
          setRunsState((prev) => {
            if (prev.status !== "ready") return prev;
            const byId = new Map(refreshed.map((run) => [run.id, run]));
            return {
              status: "ready",
              value: prev.value.map((run) => byId.get(run.id) ?? run),
            };
          });
        })
        .catch(() => {
          // A transient poll failure is not surfaced as a page-level error -- the next
          // poll, or a manual reload, will simply try again.
        });
    }, ACTIVE_RUN_POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [runsState, projectId, studyId, moduleSetId, version, memberId]);

  function handleDerive() {
    setDeriveError(null);
    setDeriving(true);
    deriveModuleSetMemberBoundaryReview(projectId, studyId, moduleSetId, version, memberId)
      .then((review) => {
        setReviewState({ status: "ready", value: review });
      })
      .catch((error: unknown) => {
        setDeriveError(error instanceof ApiRequestError ? error.message : "An unexpected error occurred.");
      })
      .finally(() => setDeriving(false));
  }

  function handleDecide(
    port: ModuleSetMemberBoundaryPortItem,
    treatmentType: ModuleBoundaryTreatmentType,
    initialValue: string,
    unit: string,
    decidedBy: string,
  ) {
    if (reviewState.status !== "ready") return;
    setDecisionError(null);
    setDecidingPortId(port.id);
    submitModuleSetMemberBoundaryDecision(projectId, studyId, moduleSetId, version, memberId, port.id, {
      expected_review_version: reviewState.value.review_version,
      treatment_type: treatmentType,
      initial_value: initialValue.trim() === "" ? undefined : initialValue.trim(),
      unit: unit.trim() === "" ? undefined : unit.trim(),
      decided_by: decidedBy.trim() === "" ? undefined : decidedBy.trim(),
    })
      .then((review) => setReviewState({ status: "ready", value: review }))
      .catch((error: unknown) => {
        if (error instanceof ApiRequestError && error.status === 409) {
          setDecisionError(
            "This review changed since it was loaded (someone or something else acted on it " +
              "first). Reloading the current state.",
          );
          reloadReview();
          return;
        }
        setDecisionError(
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
        );
      })
      .finally(() => setDecidingPortId(null));
  }

  function handleSubmitSimulation() {
    if (reviewState.status !== "ready") return;
    setSimulationError(null);
    setSimulationErrorFindings(null);
    setSubmittingSimulation(true);
    submitModuleSetMemberSimulation(projectId, studyId, moduleSetId, version, memberId, {
      expected_review_version: reviewState.value.review_version,
      saved_by: savedByInput.trim() === "" ? undefined : savedByInput.trim(),
    })
      .then(() => {
        reloadRuns();
      })
      .catch((error: unknown) => {
        if (error instanceof ApiRequestError && error.status === 409) {
          setSimulationError(
            typeof error.context?.existing_run_id === "string"
              ? "This module already has an active simulation run in progress."
              : "This review changed since it was loaded. Reloading the current state.",
          );
          reloadReview();
          reloadRuns();
          return;
        }
        if (error instanceof ApiRequestError && error.status === 422) {
          setSimulationError("This module is not ready to simulate yet.");
          const findings = error.context?.findings;
          if (Array.isArray(findings)) {
            setSimulationErrorFindings(
              findings
                .map((f) => (typeof f === "object" && f && "message" in f ? String(f.message) : null))
                .filter((m): m is string => m !== null),
            );
          }
          return;
        }
        setSimulationError(
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
        );
      })
      .finally(() => setSubmittingSimulation(false));
  }

  if (projectState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="status-message">Loading project…</p>
      </div>
    );
  }
  if (projectState.status === "not-found" || projectState.status === "error") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          {projectState.status === "not-found"
            ? "This project could not be found."
            : `Couldn't load this project: ${projectState.message}`}
        </p>
        <RouterLink to="/projects" className="back-link">
          Back to All Projects
        </RouterLink>
      </div>
    );
  }
  const project = projectState.value;

  if (studyState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="status-message">Loading Modeling Study…</p>
      </div>
    );
  }
  if (studyState.status === "not-found" || studyState.status === "error") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          {studyState.status === "not-found"
            ? "This Modeling Study could not be found."
            : `Couldn't load this Modeling Study: ${studyState.message}`}
        </p>
        <RouterLink to={`/projects/${projectId}`} className="back-link">
          Back to {project.title}
        </RouterLink>
      </div>
    );
  }
  const study = studyState.value;
  const versionUrl = `/projects/${projectId}/studies/${studyId}/module-sets/${moduleSetId}/versions/${version}`;

  if (versionState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="status-message">Loading module set…</p>
      </div>
    );
  }
  if (versionState.status === "not-found" || versionState.status === "error") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          {versionState.status === "not-found"
            ? "This module-set version could not be found."
            : `Couldn't load this module-set version: ${versionState.message}`}
        </p>
        <RouterLink to={`/projects/${projectId}/studies/${studyId}/module-sets`} className="back-link">
          Back to All modules
        </RouterLink>
      </div>
    );
  }
  const versionDetail = versionState.value;
  const member = versionDetail.members.find((m) => m.id === memberId);
  if (!member) {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          This module does not belong to this saved version.
        </p>
        <RouterLink to={versionUrl} className="back-link">
          Back to {versionDetail.module_set_name}
        </RouterLink>
      </div>
    );
  }

  const ready = reviewState.status === "ready" && reviewState.value.ready;

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}/studies/${studyId}`}>{study.title}</RouterLink> /{" "}
        <RouterLink to={versionUrl}>
          {versionDetail.module_set_name} · v{versionDetail.version}
        </RouterLink>{" "}
        / {member.display_name ?? member.module_id}
      </p>
      <h1>Boundary review &amp; simulation</h1>
      <p className="screen-subtitle">{member.display_name ?? member.module_id}</p>
      <p className="not-available-note">
        Simulation output for this module's own current, saved reaction selection -- never
        calibration or validation. Readiness here means Agent 2 has enough resolved structural
        information to build a standalone artifact; it does not by itself prove whole-model
        coverage or biological validity.
      </p>

      <section className="card" aria-label="Boundary review">
        <h2>Boundary review</h2>
        {deriveError && (
          <p className="status-message error" role="alert">
            Couldn&apos;t derive boundary candidates: {deriveError}
          </p>
        )}
        {decisionError && (
          <p className="status-message error" role="alert">
            {decisionError}
          </p>
        )}
        <button type="button" onClick={handleDerive} disabled={deriving}>
          {deriving ? "Deriving…" : "Derive boundary candidates"}
        </button>

        {reviewState.status === "loading" && (
          <p className="status-message">Loading boundary review…</p>
        )}
        {reviewState.status === "not-found" && (
          <p className="status-message error" role="alert">
            This module&apos;s boundary review could not be found.
          </p>
        )}
        {reviewState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t load this module&apos;s boundary review: {reviewState.message}
          </p>
        )}
        {reviewState.status === "ready" && (
          <>
            <div
              className={`status-message ${ready ? "" : "error"}`}
              role={ready ? undefined : "alert"}
            >
              {ready
                ? "Ready to simulate."
                : "Not ready to simulate:"}
            </div>
            {!ready && (
              <ul>
                {reviewState.value.findings.map((finding, index) => (
                  <li key={index}>
                    {formatReadinessFindingCode(finding.code)}
                    {finding.species_id ? ` (${finding.species_id})` : ""} -- {finding.message}
                  </li>
                ))}
              </ul>
            )}

            {reviewState.value.ports.length === 0 ? (
              <p className="status-message">No boundary ports derived yet for this module.</p>
            ) : (
              <table className="boundary-ports-table">
                <thead>
                  <tr>
                    <th scope="col">Species (structural)</th>
                    <th scope="col">Direction (structural)</th>
                    <th scope="col">Treatment</th>
                    <th scope="col">Resolution</th>
                    <th scope="col">Initial value</th>
                    <th scope="col">Decided by</th>
                    <th scope="col">Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {reviewState.value.ports.map((port) => (
                    <BoundaryPortDecisionRow
                      key={port.id}
                      port={port}
                      submitting={decidingPortId === port.id}
                      onDecide={handleDecide}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </section>

      <section className="card" aria-label="Simulation">
        <h2>Simulation</h2>
        {simulationError && (
          <p className="status-message error" role="alert">
            {simulationError}
            {simulationErrorFindings && simulationErrorFindings.length > 0 && (
              <ul>
                {simulationErrorFindings.map((message, index) => (
                  <li key={index}>{message}</li>
                ))}
              </ul>
            )}
          </p>
        )}
        <label>
          Saved by (optional){" "}
          <input
            type="text"
            value={savedByInput}
            onChange={(event) => setSavedByInput(event.currentTarget.value)}
          />
        </label>{" "}
        <button type="button" onClick={handleSubmitSimulation} disabled={!ready || submittingSimulation}>
          {submittingSimulation ? "Submitting…" : "Submit simulation"}
        </button>

        <h3>Runs</h3>
        {runsState.status === "loading" && <p className="status-message">Loading runs…</p>}
        {runsState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t load simulation runs: {runsState.message}
          </p>
        )}
        {runsState.status === "ready" && runsState.value.length === 0 && (
          <p className="status-message">No simulations submitted yet for this module.</p>
        )}
        {runsState.status === "ready" && runsState.value.length > 0 && (
          <ul className="module-set-simulation-run-list">
            {runsState.value.map((run) => (
              <SimulationRunCard key={run.id} run={run} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

interface BoundaryPortDecisionRowProps {
  port: ModuleSetMemberBoundaryPortItem;
  submitting: boolean;
  onDecide: (
    port: ModuleSetMemberBoundaryPortItem,
    treatmentType: ModuleBoundaryTreatmentType,
    initialValue: string,
    unit: string,
    decidedBy: string,
  ) => void;
}

function BoundaryPortDecisionRow({ port, submitting, onDecide }: BoundaryPortDecisionRowProps) {
  const [treatmentType, setTreatmentType] = useState<ModuleBoundaryTreatmentType>(
    port.treatment_type === "UNRESOLVED" ? "EXTERNALLY_CONTROLLED" : port.treatment_type,
  );
  const [initialValue, setInitialValue] = useState(port.initial_value ?? "");
  const [unit, setUnit] = useState(port.unit ?? "");
  const [decidedBy, setDecidedBy] = useState(port.decided_by ?? "");

  return (
    <tr>
      <td>{port.species_id}</td>
      <td>{formatPortDirection(port.direction)}</td>
      <td>{formatBoundaryTreatmentType(port.treatment_type)}</td>
      <td>{formatBoundaryResolutionStatus(port.resolution_status)}</td>
      <td className={port.initial_value ? undefined : "not-captured"}>
        {port.initial_value ?? NOT_CAPTURED}
        {port.initial_value && port.unit ? ` ${port.unit}` : ""}
      </td>
      <td className={port.decided_by ? undefined : "not-captured"}>
        {port.decided_by ?? NOT_CAPTURED}
      </td>
      <td>
        <div className="boundary-port-decision-form">
          <select
            aria-label={`Treatment for ${port.species_id}`}
            value={treatmentType}
            onChange={(event) =>
              setTreatmentType(event.currentTarget.value as ModuleBoundaryTreatmentType)
            }
          >
            <option value="EXTERNALLY_CONTROLLED">Externally controlled</option>
            <option value="PRESCRIBED_INPUT">Prescribed input</option>
            <option value="DYNAMIC_COUPLING">Dynamic coupling</option>
          </select>
          <input
            type="text"
            aria-label={`Initial value for ${port.species_id}`}
            placeholder="Initial value"
            value={initialValue}
            onChange={(event) => setInitialValue(event.currentTarget.value)}
          />
          <input
            type="text"
            aria-label={`Unit for ${port.species_id}`}
            placeholder="Unit"
            value={unit}
            onChange={(event) => setUnit(event.currentTarget.value)}
          />
          <input
            type="text"
            aria-label={`Decided by for ${port.species_id}`}
            placeholder="Decided by"
            value={decidedBy}
            onChange={(event) => setDecidedBy(event.currentTarget.value)}
          />
          <button
            type="button"
            className="secondary-button"
            disabled={submitting}
            onClick={() => onDecide(port, treatmentType, initialValue, unit, decidedBy)}
          >
            {submitting ? "Saving…" : "Save decision"}
          </button>
        </div>
      </td>
    </tr>
  );
}

function SimulationRunCard({ run }: { run: ModuleSetSimulationRunItem }) {
  return (
    <li className="module-set-simulation-run-card">
      <p>
        <strong>Status:</strong> {formatRunStatus(run.status)}
      </p>
      <p>
        <strong>Started:</strong>{" "}
        <span className={run.started_at ? undefined : "not-captured"}>
          {run.started_at ? new Date(run.started_at).toLocaleString() : NOT_CAPTURED}
        </span>
      </p>
      <p>
        <strong>Completed:</strong>{" "}
        <span className={run.completed_at ? undefined : "not-captured"}>
          {run.completed_at ? new Date(run.completed_at).toLocaleString() : NOT_CAPTURED}
        </span>
      </p>
      {run.status === "FAILED" && (
        <p className="status-message error" role="alert">
          {run.error_summary ?? "This simulation run failed."}
        </p>
      )}
      {run.status === "SUCCEEDED" && (
        <>
          <p className="screen-subtitle">
            Simulation output (not calibration or validation).
          </p>
          <p>
            <strong>Module handoff:</strong>{" "}
            <span className={run.module_handoff_summary ? undefined : "not-captured"}>
              {run.module_handoff_summary ? JSON.stringify(run.module_handoff_summary) : NOT_CAPTURED}
            </span>
          </p>
          <p>
            <strong>Lineage:</strong>{" "}
            <span className={run.lineage ? undefined : "not-captured"}>
              {run.lineage ? JSON.stringify(run.lineage) : NOT_CAPTURED}
            </span>
          </p>
          <p>
            <strong>Agent 3 report:</strong>{" "}
            <span className={run.agent3_report ? undefined : "not-captured"}>
              {run.agent3_report ? JSON.stringify(run.agent3_report) : NOT_CAPTURED}
            </span>
          </p>
        </>
      )}
    </li>
  );
}
