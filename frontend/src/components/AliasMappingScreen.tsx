import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  getAliasMappingRevision,
  getCurrentAliasMapping,
  getModel,
  getModelingStudy,
  getProject,
  getTimeSeriesDataset,
  listAliasMappingRevisions,
  saveAliasMapping,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { NOT_CAPTURED } from "../format";
import { RouterLink } from "./RouterLink";
import type {
  AliasMappingAssignmentStatus,
  AliasMappingDetail,
  AliasMappingRevisionSummary,
  ModelDetail,
  ProjectDetail,
  SaveAliasMappingAssignmentRequest,
  SubprojectDetail,
  TimeSeriesDatasetDetail,
} from "../types";

type LoadState<T> =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; value: T };

interface AliasMappingScreenProps {
  projectId: string;
  studyId: string;
  datasetId: string;
  modelId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

interface DraftAssignment {
  status: AliasMappingAssignmentStatus;
  target_antimony_species_id: string | null;
}

function draftFromMapping(mapping: AliasMappingDetail): Record<string, DraftAssignment> {
  const byColumn: Record<string, DraftAssignment> = {};
  for (const column of mapping.columns) {
    byColumn[column.column_name] = { status: "UNRESOLVED", target_antimony_species_id: null };
  }
  for (const assignment of mapping.assignments) {
    byColumn[assignment.column_name] = {
      status: assignment.status,
      target_antimony_species_id: assignment.target_antimony_species_id,
    };
  }
  return byColumn;
}

/** Model-Specific Alias Mapping increment: assign each of a saved dataset's own measurement
 * columns to an exact, real Antimony species identifier for one specific model, or explicitly
 * skip it. Every save creates a new, immutable revision; see
 * docs/27_model_specific_alias_mapping_increment.md. Source names/measurements are never
 * touched by anything on this screen -- only this (dataset, model) pair's own mapping. */
export function AliasMappingScreen({
  projectId,
  studyId,
  datasetId,
  modelId,
  onProjectChange,
  onStudyChange,
}: AliasMappingScreenProps) {
  const [projectState, setProjectState] = useState<LoadState<ProjectDetail>>({
    status: "loading",
  });
  const [studyState, setStudyState] = useState<LoadState<SubprojectDetail>>({
    status: "loading",
  });
  const [datasetState, setDatasetState] = useState<LoadState<TimeSeriesDatasetDetail>>({
    status: "loading",
  });
  const [modelState, setModelState] = useState<LoadState<ModelDetail>>({ status: "loading" });
  const [mappingState, setMappingState] = useState<LoadState<AliasMappingDetail>>({
    status: "loading",
  });
  const [revisions, setRevisions] = useState<AliasMappingRevisionSummary[]>([]);
  const [draft, setDraft] = useState<Record<string, DraftAssignment>>({});
  const [savedBy, setSavedBy] = useState("");
  const [saveState, setSaveState] = useState<
    { status: "idle" } | { status: "saving" } | { status: "error"; message: string }
  >({ status: "idle" });
  const [viewingRevision, setViewingRevision] = useState<AliasMappingDetail | null>(null);
  const guard = useRef(createStaleGuard<string>()).current;

  function loadCurrentMapping(key: string) {
    getCurrentAliasMapping(projectId, studyId, datasetId, modelId)
      .then((mapping) => {
        if (!guard.isCurrent(key)) return;
        setMappingState({ status: "ready", value: mapping });
        setDraft(draftFromMapping(mapping));
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setMappingState({ status: "error", message });
      });
    listAliasMappingRevisions(projectId, studyId, datasetId, modelId)
      .then((list) => {
        if (guard.isCurrent(key)) setRevisions(list);
      })
      .catch(() => {
        /* revision history is supplementary; its own load failure never blocks the screen */
      });
  }

  useEffect(() => {
    const key = `${projectId}/${studyId}/${datasetId}/${modelId}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
    setDatasetState({ status: "loading" });
    setModelState({ status: "loading" });
    setMappingState({ status: "loading" });
    setViewingRevision(null);
    onProjectChange(null);
    onStudyChange(null);

    getProject(projectId)
      .then((project) => {
        if (!guard.isCurrent(key)) return;
        setProjectState({ status: "ready", value: project });
        onProjectChange(project);

        return getModelingStudy(projectId, studyId).then((study) => {
          if (!guard.isCurrent(key)) return;
          setStudyState({ status: "ready", value: study });
          onStudyChange(study);

          getTimeSeriesDataset(projectId, studyId, datasetId)
            .then((dataset) => {
              if (guard.isCurrent(key)) setDatasetState({ status: "ready", value: dataset });
            })
            .catch((error: unknown) => {
              if (!guard.isCurrent(key)) return;
              setDatasetState(
                error instanceof ApiRequestError && error.status === 404
                  ? { status: "not-found" }
                  : { status: "error", message: "An unexpected error occurred." },
              );
            });

          getModel(projectId, studyId, modelId)
            .then((model) => {
              if (guard.isCurrent(key)) setModelState({ status: "ready", value: model });
            })
            .catch((error: unknown) => {
              if (!guard.isCurrent(key)) return;
              setModelState(
                error instanceof ApiRequestError && error.status === 404
                  ? { status: "not-found" }
                  : { status: "error", message: "An unexpected error occurred." },
              );
            });

          loadCurrentMapping(key);
        });
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        setProjectState(
          error instanceof ApiRequestError && error.status === 404
            ? { status: "not-found" }
            : { status: "error", message: "An unexpected error occurred." },
        );
      });

    return () => {
      onProjectChange(null);
      onStudyChange(null);
    };
  }, [projectId, studyId, datasetId, modelId]);

  function handleSave() {
    if (mappingState.status !== "ready") return;
    setSaveState({ status: "saving" });
    const assignments: SaveAliasMappingAssignmentRequest[] = Object.entries(draft).map(
      ([columnName, assignment]) => ({
        column_name: columnName,
        status: assignment.status,
        target_antimony_species_id:
          assignment.status === "ASSIGNED" ? assignment.target_antimony_species_id : null,
      }),
    );
    saveAliasMapping(projectId, studyId, datasetId, modelId, {
      expected_revision_number: mappingState.value.revision_number,
      assignments,
      saved_by: savedBy || undefined,
    })
      .then((mapping) => {
        setSaveState({ status: "idle" });
        setMappingState({ status: "ready", value: mapping });
        setDraft(draftFromMapping(mapping));
        listAliasMappingRevisions(projectId, studyId, datasetId, modelId).then(setRevisions);
      })
      .catch((error: unknown) => {
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setSaveState({ status: "error", message });
      });
  }

  function handleCancel() {
    if (mappingState.status === "ready") {
      setDraft(draftFromMapping(mappingState.value));
    }
    setSaveState({ status: "idle" });
  }

  function handleViewRevision(revisionNumber: number) {
    getAliasMappingRevision(projectId, studyId, datasetId, modelId, revisionNumber).then(
      setViewingRevision,
    );
  }

  for (const [state, label] of [
    [projectState, "project"],
    [studyState, "Modeling Study"],
    [datasetState, "dataset"],
    [modelState, "model"],
  ] as const) {
    if (state.status === "loading") {
      return (
        <div className="projects-screen">
          <p className="status-message">Loading {label}…</p>
        </div>
      );
    }
    if (state.status === "not-found" || state.status === "error") {
      return (
        <div className="projects-screen">
          <p className="status-message error" role="alert">
            {state.status === "not-found"
              ? `This ${label} could not be found.`
              : `Couldn't load this ${label}: ${state.message}`}
          </p>
          <RouterLink to="/projects" className="back-link">
            Back to All Projects
          </RouterLink>
        </div>
      );
    }
  }
  // Every state above is now narrowed to "ready" -- TypeScript needs one more check per value.
  if (
    projectState.status !== "ready" ||
    studyState.status !== "ready" ||
    datasetState.status !== "ready" ||
    modelState.status !== "ready"
  ) {
    return null;
  }
  const project = projectState.value;
  const study = studyState.value;
  const dataset = datasetState.value;
  const model = modelState.value;
  const datasetUrl = `/projects/${projectId}/studies/${studyId}/datasets/time-series/${datasetId}`;

  if (mappingState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="status-message">Loading mapping…</p>
      </div>
    );
  }
  if (mappingState.status !== "ready") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          {mappingState.status === "error"
            ? `Couldn't load this mapping: ${mappingState.message}`
            : "This mapping could not be found."}
        </p>
      </div>
    );
  }
  const mapping = mappingState.value;
  const catalogAvailable = mapping.model_species_catalog_status === "AVAILABLE";
  const usedTargets = new Set(
    Object.values(draft)
      .filter((a) => a.status === "ASSIGNED" && a.target_antimony_species_id)
      .map((a) => a.target_antimony_species_id as string),
  );

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}/studies/${studyId}`}>{study.title}</RouterLink> /{" "}
        <RouterLink to={datasetUrl}>{dataset.content.effective_dataset_name}</RouterLink> / Map to{" "}
        {model.name}
      </p>
      <h1>
        Map {dataset.content.effective_dataset_name} to {model.name}
      </h1>
      <p className="screen-subtitle">
        Assign each measurement column to an exact Antimony species, or explicitly skip it.
        Source names and measurements are never changed by anything on this screen.
      </p>

      {!catalogAvailable && (
        <section className="card" aria-label="Species catalog unavailable">
          <p className="status-message error" role="alert">
            Species catalog unavailable for this model
            {mapping.model_species_catalog_unavailable_reason
              ? `: ${mapping.model_species_catalog_unavailable_reason}`
              : " -- it was never captured during a real model build."}{" "}
            No mapping can be validated or saved against this model until a real build succeeds.
          </p>
        </section>
      )}

      {catalogAvailable && (
        <section className="card" aria-label="Column assignments">
          <h2>Column assignments (revision {mapping.revision_number})</h2>
          <p className="status-message">
            A complete mapping establishes correspondence to a species, not analysis readiness
            -- units, experimental conditions, and other required inputs may still be
            unresolved.
          </p>
          <table className="module-sets-table">
            <thead>
              <tr>
                <th scope="col">Column</th>
                <th scope="col">Unit</th>
                <th scope="col">Sample values</th>
                <th scope="col">Decision</th>
                <th scope="col">Target species</th>
                <th scope="col">Unit finding</th>
              </tr>
            </thead>
            <tbody>
              {mapping.columns.map((column) => {
                const assignment = draft[column.column_name];
                const savedAssignment = mapping.assignments.find(
                  (a) => a.column_name === column.column_name,
                );
                return (
                  <tr key={column.column_name}>
                    <td>{column.column_name}</td>
                    <td className={column.unit ? undefined : "not-captured"}>
                      {column.unit ?? NOT_CAPTURED}
                    </td>
                    <td>{column.sample_values.join(", ")}</td>
                    <td>
                      <select
                        aria-label={`Decision for ${column.column_name}`}
                        value={assignment?.status ?? "UNRESOLVED"}
                        onChange={(event) =>
                          setDraft((prev) => ({
                            ...prev,
                            [column.column_name]: {
                              status: event.target.value as AliasMappingAssignmentStatus,
                              target_antimony_species_id:
                                event.target.value === "ASSIGNED"
                                  ? prev[column.column_name]?.target_antimony_species_id ?? null
                                  : null,
                            },
                          }))
                        }
                      >
                        <option value="UNRESOLVED">Unresolved</option>
                        <option value="ASSIGNED">Assign to species</option>
                        <option value="SKIPPED">Skip (no species home)</option>
                      </select>
                    </td>
                    <td>
                      {assignment?.status === "ASSIGNED" && (
                        <select
                          aria-label={`Target species for ${column.column_name}`}
                          value={assignment.target_antimony_species_id ?? ""}
                          onChange={(event) =>
                            setDraft((prev) => ({
                              ...prev,
                              [column.column_name]: {
                                status: "ASSIGNED",
                                target_antimony_species_id: event.target.value || null,
                              },
                            }))
                          }
                        >
                          <option value="">Choose a species…</option>
                          {mapping.available_species.map((species) => {
                            const alreadyUsedElsewhere =
                              usedTargets.has(species.antimony_species_id) &&
                              assignment.target_antimony_species_id !==
                                species.antimony_species_id;
                            return (
                              <option
                                key={species.antimony_species_id}
                                value={species.antimony_species_id}
                                disabled={alreadyUsedElsewhere}
                              >
                                {species.antimony_species_id}
                                {species.compartment_name
                                  ? ` (${species.compartment_name})`
                                  : ` (${species.compartment_id})`}
                                {alreadyUsedElsewhere ? " -- already assigned" : ""}
                              </option>
                            );
                          })}
                        </select>
                      )}
                    </td>
                    <td className={savedAssignment?.unit_finding ? undefined : "not-captured"}>
                      {savedAssignment?.status === "ASSIGNED"
                        ? savedAssignment.unit_finding ?? NOT_CAPTURED
                        : NOT_CAPTURED}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <p>
            <label htmlFor="alias-mapping-saved-by">Saved by (optional)</label>
            <br />
            <input
              id="alias-mapping-saved-by"
              type="text"
              value={savedBy}
              onChange={(event) => setSavedBy(event.target.value)}
            />
          </p>

          {saveState.status === "error" && (
            <p className="status-message error" role="alert">
              Couldn&apos;t save this mapping: {saveState.message}
            </p>
          )}

          <button
            type="button"
            className="primary-button"
            disabled={saveState.status === "saving"}
            onClick={handleSave}
          >
            {saveState.status === "saving" ? "Saving…" : "Save mapping"}
          </button>{" "}
          <button type="button" className="secondary-button" onClick={handleCancel}>
            Cancel
          </button>
        </section>
      )}

      <section className="card" aria-label="Revision history">
        <h2>Revision history</h2>
        {revisions.length === 0 ? (
          <p className="status-message">No revisions saved yet.</p>
        ) : (
          <table className="module-sets-table">
            <thead>
              <tr>
                <th scope="col">Revision</th>
                <th scope="col">Assigned</th>
                <th scope="col">Skipped</th>
                <th scope="col">Unresolved</th>
                <th scope="col">Saved</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              {revisions.map((revision) => (
                <tr key={revision.revision_number}>
                  <td>{revision.revision_number}</td>
                  <td>{revision.assigned_count}</td>
                  <td>{revision.skipped_count}</td>
                  <td>{revision.unresolved_count}</td>
                  <td>
                    {new Date(revision.created_at).toLocaleString()}
                    {revision.saved_by ? ` by ${revision.saved_by}` : ""}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => handleViewRevision(revision.revision_number)}
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {viewingRevision && (
          <div className="time-series-preview">
            <h3>Revision {viewingRevision.revision_number} (read-only)</h3>
            <table className="module-sets-table">
              <thead>
                <tr>
                  <th scope="col">Column</th>
                  <th scope="col">Status</th>
                  <th scope="col">Target species</th>
                </tr>
              </thead>
              <tbody>
                {viewingRevision.assignments.map((assignment) => (
                  <tr key={assignment.column_name}>
                    <td>{assignment.column_name}</td>
                    <td>{assignment.status}</td>
                    <td className={assignment.target_antimony_species_id ? undefined : "not-captured"}>
                      {assignment.target_antimony_species_id ?? NOT_CAPTURED}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button
              type="button"
              className="secondary-button"
              onClick={() => setViewingRevision(null)}
            >
              Close
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
