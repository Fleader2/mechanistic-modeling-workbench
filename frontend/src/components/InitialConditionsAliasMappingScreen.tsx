import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  getInitialConditionsAliasMappingRevision,
  getCurrentInitialConditionsAliasMapping,
  getInitialConditionsDataset,
  getModel,
  getModelingStudy,
  getProject,
  listInitialConditionsAliasMappingRevisions,
  saveInitialConditionsAliasMapping,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { NOT_CAPTURED, formatScientific } from "../format";
import { RouterLink } from "./RouterLink";
import type {
  AliasMappingAssignmentStatus,
  InitialConditionsAliasMappingDetail,
  InitialConditionsAliasMappingRevisionSummary,
  InitialConditionsAliasMappingTargetKind,
  InitialConditionsDatasetDetail,
  ModelDetail,
  ProjectDetail,
  SaveInitialConditionsAliasMappingAssignmentRequest,
  SubprojectDetail,
} from "../types";

type LoadState<T> =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; value: T };

interface InitialConditionsAliasMappingScreenProps {
  projectId: string;
  studyId: string;
  datasetId: string;
  modelId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

interface DraftAssignment {
  status: AliasMappingAssignmentStatus;
  target_kind: InitialConditionsAliasMappingTargetKind | null;
  target_id: string | null;
}

function draftFromMapping(
  mapping: InitialConditionsAliasMappingDetail,
): Record<string, DraftAssignment> {
  const byTarget: Record<string, DraftAssignment> = {};
  for (const target of mapping.targets) {
    byTarget[target.target_name] = { status: "UNRESOLVED", target_kind: null, target_id: null };
  }
  for (const assignment of mapping.assignments) {
    byTarget[assignment.target_name] = {
      status: assignment.status,
      target_kind: assignment.target_kind,
      target_id: assignment.target_id,
    };
  }
  return byTarget;
}

/** Initial-Conditions Dataset Import increment (docs/36): assign each distinct target_name
 * (a row value, never a column header -- this dataset is long-format) to a real Antimony
 * species or independent parameter for one specific model, or explicitly skip it. Mirrors
 * AliasMappingScreen exactly in spirit -- every save creates a new, immutable revision; source
 * data is never touched by anything on this screen -- with two real differences: the picker
 * offers both a species catalog and a parameter catalog, and a target's own kind must be
 * chosen explicitly before its id can be chosen.
 */
export function InitialConditionsAliasMappingScreen({
  projectId,
  studyId,
  datasetId,
  modelId,
  onProjectChange,
  onStudyChange,
}: InitialConditionsAliasMappingScreenProps) {
  const [projectState, setProjectState] = useState<LoadState<ProjectDetail>>({
    status: "loading",
  });
  const [studyState, setStudyState] = useState<LoadState<SubprojectDetail>>({
    status: "loading",
  });
  const [datasetState, setDatasetState] = useState<LoadState<InitialConditionsDatasetDetail>>({
    status: "loading",
  });
  const [modelState, setModelState] = useState<LoadState<ModelDetail>>({ status: "loading" });
  const [mappingState, setMappingState] = useState<LoadState<InitialConditionsAliasMappingDetail>>(
    { status: "loading" },
  );
  const [revisions, setRevisions] = useState<InitialConditionsAliasMappingRevisionSummary[]>([]);
  const [draft, setDraft] = useState<Record<string, DraftAssignment>>({});
  const [savedBy, setSavedBy] = useState("");
  const [saveState, setSaveState] = useState<
    { status: "idle" } | { status: "saving" } | { status: "error"; message: string }
  >({ status: "idle" });
  const [viewingRevision, setViewingRevision] =
    useState<InitialConditionsAliasMappingDetail | null>(null);
  const guard = useRef(createStaleGuard<string>()).current;

  function loadCurrentMapping(key: string) {
    getCurrentInitialConditionsAliasMapping(projectId, studyId, datasetId, modelId)
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
    listInitialConditionsAliasMappingRevisions(projectId, studyId, datasetId, modelId)
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

          getInitialConditionsDataset(projectId, studyId, datasetId)
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
    const assignments: SaveInitialConditionsAliasMappingAssignmentRequest[] = Object.entries(
      draft,
    ).map(([targetName, assignment]) => ({
      target_name: targetName,
      status: assignment.status,
      target_kind: assignment.status === "ASSIGNED" ? assignment.target_kind : null,
      target_id: assignment.status === "ASSIGNED" ? assignment.target_id : null,
    }));
    saveInitialConditionsAliasMapping(projectId, studyId, datasetId, modelId, {
      expected_revision_number: mappingState.value.revision_number,
      assignments,
      saved_by: savedBy || undefined,
    })
      .then((mapping) => {
        setSaveState({ status: "idle" });
        setMappingState({ status: "ready", value: mapping });
        setDraft(draftFromMapping(mapping));
        listInitialConditionsAliasMappingRevisions(projectId, studyId, datasetId, modelId).then(
          setRevisions,
        );
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
    getInitialConditionsAliasMappingRevision(
      projectId,
      studyId,
      datasetId,
      modelId,
      revisionNumber,
    ).then(setViewingRevision);
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
  const datasetUrl = `/projects/${projectId}/studies/${studyId}/datasets/initial-conditions/${datasetId}`;

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
  const speciesAvailable = mapping.model_species_catalog_status === "AVAILABLE";
  const parametersAvailable = mapping.model_parameter_catalog_status === "AVAILABLE";
  const anyCatalogAvailable = speciesAvailable || parametersAvailable;
  const usedTargets = new Set(
    Object.values(draft)
      .filter((a) => a.status === "ASSIGNED" && a.target_kind && a.target_id)
      .map((a) => `${a.target_kind}:${a.target_id}`),
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
        Assign each distinct target to an exact Antimony species or independent parameter, or
        explicitly skip it. Source names and measurements are never changed by anything on this
        screen.
      </p>

      {!anyCatalogAvailable && (
        <section className="card" aria-label="No catalog available">
          <p className="status-message error" role="alert">
            Neither a species catalog nor a parameter catalog is available for this model --
            neither was ever captured during a real model build. No mapping can be validated or
            saved against this model until a real build succeeds.
          </p>
        </section>
      )}

      {anyCatalogAvailable && (
        <section className="card" aria-label="Target assignments">
          <h2>Target assignments (revision {mapping.revision_number})</h2>
          <p className="status-message">
            {speciesAvailable && parametersAvailable
              ? "Both a species catalog and a parameter catalog are available for this model."
              : speciesAvailable
                ? "Only a species catalog is available for this model -- a target can only be assigned to a species."
                : "Only a parameter catalog is available for this model -- a target can only be assigned to a parameter."}
          </p>
          <table className="module-sets-table">
            <thead>
              <tr>
                <th scope="col">Target</th>
                <th scope="col">Unit</th>
                <th scope="col">Sample values</th>
                <th scope="col">Decision</th>
                <th scope="col">Kind</th>
                <th scope="col">Target id</th>
                <th scope="col">Unit finding</th>
              </tr>
            </thead>
            <tbody>
              {mapping.targets.map((target) => {
                const assignment = draft[target.target_name];
                const savedAssignment = mapping.assignments.find(
                  (a) => a.target_name === target.target_name,
                );
                return (
                  <tr key={target.target_name}>
                    <td>{target.target_name}</td>
                    <td className={target.unit ? undefined : "not-captured"}>
                      {target.unit ?? NOT_CAPTURED}
                    </td>
                    <td title={`Full precision: ${target.sample_values.join(", ")}`}>
                      {target.sample_values.map((v) => formatScientific(v)).join(", ")}
                    </td>
                    <td>
                      <select
                        aria-label={`Decision for ${target.target_name}`}
                        value={assignment?.status ?? "UNRESOLVED"}
                        onChange={(event) =>
                          setDraft((prev) => ({
                            ...prev,
                            [target.target_name]: {
                              status: event.target.value as AliasMappingAssignmentStatus,
                              target_kind:
                                event.target.value === "ASSIGNED"
                                  ? prev[target.target_name]?.target_kind ?? null
                                  : null,
                              target_id:
                                event.target.value === "ASSIGNED"
                                  ? prev[target.target_name]?.target_id ?? null
                                  : null,
                            },
                          }))
                        }
                      >
                        <option value="UNRESOLVED">Unresolved</option>
                        <option value="ASSIGNED">Assign</option>
                        <option value="SKIPPED">Skip (no model home)</option>
                      </select>
                    </td>
                    <td>
                      {assignment?.status === "ASSIGNED" && (
                        <select
                          aria-label={`Kind for ${target.target_name}`}
                          value={assignment.target_kind ?? ""}
                          onChange={(event) =>
                            setDraft((prev) => ({
                              ...prev,
                              [target.target_name]: {
                                status: "ASSIGNED",
                                target_kind:
                                  (event.target.value as InitialConditionsAliasMappingTargetKind) ||
                                  null,
                                target_id: null,
                              },
                            }))
                          }
                        >
                          <option value="">Choose…</option>
                          {speciesAvailable && <option value="SPECIES">Species</option>}
                          {parametersAvailable && <option value="PARAMETER">Parameter</option>}
                        </select>
                      )}
                    </td>
                    <td>
                      {assignment?.status === "ASSIGNED" && assignment.target_kind === "SPECIES" && (
                        <select
                          aria-label={`Target species for ${target.target_name}`}
                          value={assignment.target_id ?? ""}
                          onChange={(event) =>
                            setDraft((prev) => ({
                              ...prev,
                              [target.target_name]: {
                                status: "ASSIGNED",
                                target_kind: "SPECIES",
                                target_id: event.target.value || null,
                              },
                            }))
                          }
                        >
                          <option value="">Choose a species…</option>
                          {mapping.available_species.map((species) => {
                            const key = `SPECIES:${species.antimony_species_id}`;
                            const alreadyUsedElsewhere =
                              usedTargets.has(key) &&
                              assignment.target_id !== species.antimony_species_id;
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
                      {assignment?.status === "ASSIGNED" && assignment.target_kind === "PARAMETER" && (
                        <select
                          aria-label={`Target parameter for ${target.target_name}`}
                          value={assignment.target_id ?? ""}
                          onChange={(event) =>
                            setDraft((prev) => ({
                              ...prev,
                              [target.target_name]: {
                                status: "ASSIGNED",
                                target_kind: "PARAMETER",
                                target_id: event.target.value || null,
                              },
                            }))
                          }
                        >
                          <option value="">Choose a parameter…</option>
                          {mapping.available_parameters.map((parameter) => {
                            const key = `PARAMETER:${parameter.antimony_parameter_id}`;
                            const alreadyUsedElsewhere =
                              usedTargets.has(key) &&
                              assignment.target_id !== parameter.antimony_parameter_id;
                            return (
                              <option
                                key={parameter.antimony_parameter_id}
                                value={parameter.antimony_parameter_id}
                                disabled={alreadyUsedElsewhere}
                              >
                                {parameter.antimony_parameter_id}
                                {parameter.display_name ? ` (${parameter.display_name})` : ""}
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
            <label htmlFor="ic-alias-mapping-saved-by">Saved by (optional)</label>
            <br />
            <input
              id="ic-alias-mapping-saved-by"
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
                  <th scope="col">Target</th>
                  <th scope="col">Status</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Target id</th>
                </tr>
              </thead>
              <tbody>
                {viewingRevision.assignments.map((assignment) => (
                  <tr key={assignment.target_name}>
                    <td>{assignment.target_name}</td>
                    <td>{assignment.status}</td>
                    <td className={assignment.target_kind ? undefined : "not-captured"}>
                      {assignment.target_kind ?? NOT_CAPTURED}
                    </td>
                    <td className={assignment.target_id ? undefined : "not-captured"}>
                      {assignment.target_id ?? NOT_CAPTURED}
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
