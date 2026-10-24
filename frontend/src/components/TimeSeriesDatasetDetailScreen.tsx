import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  getCurrentAliasMapping,
  getModelingStudy,
  getModelingStudyModels,
  getProject,
  getTimeSeriesDataset,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { navigate } from "../lib/router";
import { distinctConditionIds } from "../lib/timeSeriesPlotData";
import { NOT_CAPTURED, formatScientific, fullPrecisionTitle } from "../format";
import { RouterLink } from "./RouterLink";
import { TimeSeriesPlot } from "./TimeSeriesPlot";
import type {
  AliasMappingDetail,
  ModelListItem,
  ProjectDetail,
  SubprojectDetail,
  TimeSeriesDatasetDetail,
} from "../types";

type AliasMappingState =
  | { status: "none" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; mapping: AliasMappingDetail };

type ProjectState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; project: ProjectDetail };

type StudyState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; study: SubprojectDetail };

type DatasetState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; dataset: TimeSeriesDatasetDetail };

interface TimeSeriesDatasetDetailScreenProps {
  projectId: string;
  studyId: string;
  datasetId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

/** Reopening one saved time-series dataset -- entirely read-only (task instructions: "read-
 * only reopening"). Every metadata field, row, and the exact validation findings as saved,
 * never re-parsed or re-derived (see docs/25_time_series_dataset_import_increment.md). */
export function TimeSeriesDatasetDetailScreen({
  projectId,
  studyId,
  datasetId,
  onProjectChange,
  onStudyChange,
}: TimeSeriesDatasetDetailScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studyState, setStudyState] = useState<StudyState>({ status: "loading" });
  const [datasetState, setDatasetState] = useState<DatasetState>({ status: "loading" });
  const [models, setModels] = useState<ModelListItem[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [aliasMappingState, setAliasMappingState] = useState<AliasMappingState>({
    status: "none",
  });
  const [selectedColumns, setSelectedColumns] = useState<Set<string>>(new Set());
  const [selectedConditions, setSelectedConditions] = useState<Set<string | null>>(new Set());
  const guard = useRef(createStaleGuard<string>()).current;
  const aliasMappingGuard = useRef(createStaleGuard<string>()).current;

  useEffect(() => {
    const key = `${projectId}/${studyId}/${datasetId}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
    setDatasetState({ status: "loading" });
    onProjectChange(null);
    onStudyChange(null);

    getProject(projectId)
      .then((project) => {
        if (!guard.isCurrent(key)) return;
        setProjectState({ status: "ready", project });
        onProjectChange(project);

        return getModelingStudy(projectId, studyId).then((study) => {
          if (!guard.isCurrent(key)) return;
          setStudyState({ status: "ready", study });
          onStudyChange(study);

          getModelingStudyModels(projectId, studyId)
            .then((list) => {
              if (guard.isCurrent(key)) setModels(list);
            })
            .catch(() => {
              /* the "map to a model" picker is a convenience; its own load failure never
               * blocks the read-only reopen screen above it */
            });

          getTimeSeriesDataset(projectId, studyId, datasetId)
            .then((dataset) => {
              if (guard.isCurrent(key)) setDatasetState({ status: "ready", dataset });
            })
            .catch((error: unknown) => {
              if (!guard.isCurrent(key)) return;
              if (error instanceof ApiRequestError && error.status === 404) {
                setDatasetState({ status: "not-found" });
              } else {
                const message =
                  error instanceof ApiRequestError
                    ? error.message
                    : "An unexpected error occurred.";
                setDatasetState({ status: "error", message });
              }
            });
        });
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        if (error instanceof ApiRequestError && error.status === 404) {
          setProjectState({ status: "not-found" });
        } else {
          const message =
            error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
          setProjectState({ status: "error", message });
        }
      });

    return () => {
      onProjectChange(null);
      onStudyChange(null);
    };
  }, [projectId, studyId, datasetId]);

  // Every measurement column and every real condition (plus the "no condition recorded"
  // bucket, if any row lacks one) start selected -- the plot/table default to showing
  // everything the dataset actually has, never a pre-narrowed subset (task instructions:
  // "never silently truncate"). Re-initialized whenever a different dataset finishes loading.
  useEffect(() => {
    if (datasetState.status !== "ready") return;
    const { rows, measurement_columns } = datasetState.dataset.content;
    setSelectedColumns(new Set(measurement_columns.map((c) => c.column_name)));
    setSelectedConditions(new Set(distinctConditionIds(rows)));
  }, [datasetState]);

  useEffect(() => {
    if (!selectedModelId) {
      setAliasMappingState({ status: "none" });
      return;
    }
    const key = `${selectedModelId}`;
    aliasMappingGuard.start(key);
    setAliasMappingState({ status: "loading" });
    getCurrentAliasMapping(projectId, studyId, datasetId, selectedModelId)
      .then((mapping) => {
        if (aliasMappingGuard.isCurrent(key)) setAliasMappingState({ status: "ready", mapping });
      })
      .catch((error: unknown) => {
        if (!aliasMappingGuard.isCurrent(key)) return;
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setAliasMappingState({ status: "error", message });
      });
  }, [projectId, studyId, datasetId, selectedModelId]);

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
  const { project } = projectState;

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
  const { study } = studyState;
  const datasetsUrl = `/projects/${projectId}/studies/${studyId}/datasets/time-series`;

  if (datasetState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="status-message">Loading dataset…</p>
      </div>
    );
  }
  if (datasetState.status === "not-found" || datasetState.status === "error") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          {datasetState.status === "not-found"
            ? "This dataset could not be found."
            : `Couldn't load this dataset: ${datasetState.message}`}
        </p>
        <RouterLink to={datasetsUrl} className="back-link">
          Back to All datasets
        </RouterLink>
      </div>
    );
  }
  const { dataset } = datasetState;
  const { content } = dataset;
  const selectedModel = models.find((m) => m.id === selectedModelId) ?? null;

  function toggleColumn(columnName: string) {
    setSelectedColumns((prev) => {
      const next = new Set(prev);
      if (next.has(columnName)) next.delete(columnName);
      else next.add(columnName);
      return next;
    });
  }
  function toggleCondition(conditionId: string | null) {
    setSelectedConditions((prev) => {
      const next = new Set(prev);
      if (next.has(conditionId)) next.delete(conditionId);
      else next.add(conditionId);
      return next;
    });
  }

  const allConditions = distinctConditionIds(content.rows);
  const filteredRows = content.rows.filter((row) => selectedConditions.has(row.condition_id));

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}/studies/${studyId}`}>{study.title}</RouterLink> /{" "}
        <RouterLink to={datasetsUrl}>All datasets</RouterLink> / {content.effective_dataset_name}
      </p>
      <h1>{content.effective_dataset_name}</h1>
      <p className="screen-subtitle">
        Saved {new Date(dataset.created_at).toLocaleString()}
        {dataset.saved_by ? ` by ${dataset.saved_by}` : ""} · read-only.
      </p>

      <section className="card" aria-label="Map to a model">
        <h2>Map to a model</h2>
        {models.length === 0 ? (
          <p className="status-message">
            No models exist in this Modeling Study yet to map against.
          </p>
        ) : (
          <p>
            <label htmlFor="alias-mapping-model-select">Model</label>
            <br />
            <select
              id="alias-mapping-model-select"
              value={selectedModelId}
              onChange={(event) => setSelectedModelId(event.target.value)}
            >
              <option value="">Choose a model…</option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name} ({model.stable_identifier})
                </option>
              ))}
            </select>{" "}
            <button
              type="button"
              className="secondary-button"
              disabled={!selectedModelId}
              onClick={() =>
                navigate(
                  `/projects/${projectId}/studies/${studyId}/datasets/time-series/${datasetId}` +
                    `/alias-mapping/${selectedModelId}`,
                )
              }
            >
              Map measurement columns
            </button>
          </p>
        )}

        {selectedModel && aliasMappingState.status === "loading" && (
          <p className="status-message">Loading this model's own alias mapping…</p>
        )}
        {selectedModel && aliasMappingState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t load the alias mapping for {selectedModel.name}:{" "}
            {aliasMappingState.message}
          </p>
        )}
        {selectedModel && aliasMappingState.status === "ready" && (
          <div className="alias-mapping-overlay">
            <p>
              Showing the mapping to <strong>{selectedModel.name}</strong> (revision{" "}
              {aliasMappingState.mapping.revision_number}) -- a separate fact from each
              column's own original name above; the plot and table below always show the
              dataset's own original values and column names regardless of this mapping.
            </p>
            {aliasMappingState.mapping.model_species_catalog_status !== "AVAILABLE" && (
              <p className="status-message error" role="alert">
                This model has no verified species catalog
                {aliasMappingState.mapping.model_species_catalog_unavailable_reason
                  ? `: ${aliasMappingState.mapping.model_species_catalog_unavailable_reason}`
                  : "."}
              </p>
            )}
            {aliasMappingState.mapping.assignments.length === 0 ? (
              <p className="status-message">No mapping has been saved for this model yet.</p>
            ) : (
              <table className="time-series-metadata-table">
                <tbody>
                  {aliasMappingState.mapping.assignments.map((assignment) => (
                    <tr key={assignment.column_name}>
                      <th scope="row">{assignment.column_name}</th>
                      <td>
                        {assignment.status === "ASSIGNED"
                          ? `-> ${assignment.target_antimony_species_id} (Antimony species id, not a display label)`
                          : assignment.status === "SKIPPED"
                            ? "Skipped -- no species home"
                            : "Unresolved"}
                        {assignment.unit_finding ? ` · unit: ${assignment.unit_finding}` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </section>

      <section className="card" aria-label="Measurement columns">
        <h2>Measurement columns</h2>
        <table className="time-series-metadata-table">
          <thead>
            <tr>
              <th scope="col">Column (original, verbatim)</th>
              <th scope="col">Unit</th>
              <th scope="col">Description</th>
              <th scope="col">Declared</th>
              <th scope="col">Default plot panel</th>
            </tr>
          </thead>
          <tbody>
            {content.measurement_columns.map((column) => {
              const panel = content.unit_panels.find((p) =>
                p.column_names.includes(column.column_name),
              );
              return (
                <tr key={column.column_name}>
                  <td>{column.column_name}</td>
                  <td className={column.unit ? undefined : "not-captured"}>
                    {column.unit ?? NOT_CAPTURED}
                  </td>
                  <td className={column.description ? undefined : "not-captured"}>
                    {column.description ?? NOT_CAPTURED}
                  </td>
                  <td>{column.declared_in_metadata ? "Yes" : "No -- unit unknown"}</td>
                  <td>
                    {panel
                      ? panel.column_names.length > 1
                        ? `Shared with ${panel.column_names
                            .filter((n) => n !== column.column_name)
                            .join(", ")}`
                        : "Own panel"
                      : NOT_CAPTURED}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="card" aria-label="Metadata">
        <h2>Metadata</h2>
        <table className="time-series-metadata-table">
          <tbody>
            {Object.entries(content.metadata)
              .filter(([key]) => key !== "template_version")
              .map(([key, value]) => (
                <tr key={key}>
                  <th scope="row">{key.replace(/_/g, " ")}</th>
                  <td className={value ? undefined : "not-captured"}>{value ?? NOT_CAPTURED}</td>
                </tr>
              ))}
          </tbody>
        </table>

        {content.condition_legend.length > 0 && (
          <>
            <h3>Condition / treatment legend</h3>
            <table className="time-series-metadata-table">
              <tbody>
                {content.condition_legend.map((entry) => (
                  <tr key={entry.condition_id}>
                    <th scope="row">{entry.condition_id}</th>
                    <td className={entry.description ? undefined : "not-captured"}>
                      {entry.description ?? NOT_CAPTURED}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <section className="card" aria-label="Validation findings">
        <h2>Validation findings ({content.findings.length})</h2>
        {content.findings.length === 0 ? (
          <p className="status-message">None.</p>
        ) : (
          <ul className="time-series-findings-list">
            {content.findings.map((finding, index) => (
              <li key={index}>{finding.message}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="card" aria-label="Time-course plot">
        <h2>Time-course plot</h2>
        <p className="screen-subtitle">
          Plots the dataset's own original measurement values under their own original column
          names. Time is always the independent variable (x-axis) and each species' own
          measured value is always the dependent variable (y-axis). Lines are grouped by
          species, condition, and -- where explicitly recorded -- biological replicate; a
          sample id alone never splits or joins a trajectory, and a technical-replicate number
          alone never establishes identity across time. With no condition or replicate
          information recorded at all, one line connects a species' own points across every
          sample id by time, as in an unstructured time course. Two or more observations
          recorded at the exact same time within one trajectory are all shown, but every
          connection touching that tie -- into it, within it, and out of it -- is left undrawn
          rather than guessed, since connecting only one specific neighbor to only one specific
          tied point would itself be an arbitrary choice this screen never makes.
        </p>

        <fieldset className="time-series-plot-controls">
          <legend>Measurement columns</legend>
          {content.measurement_columns.map((column) => (
            <label key={column.column_name} className="time-series-plot-control-item">
              <input
                type="checkbox"
                checked={selectedColumns.has(column.column_name)}
                onChange={() => toggleColumn(column.column_name)}
              />{" "}
              {column.column_name}
            </label>
          ))}
        </fieldset>

        {allConditions.length > 1 && (
          <fieldset className="time-series-plot-controls">
            <legend>Conditions</legend>
            {allConditions.map((conditionId) => (
              <label
                key={conditionId ?? "__none__"}
                className="time-series-plot-control-item"
              >
                <input
                  type="checkbox"
                  checked={selectedConditions.has(conditionId)}
                  onChange={() => toggleCondition(conditionId)}
                />{" "}
                {conditionId ?? "No condition recorded"}
              </label>
            ))}
          </fieldset>
        )}

        {content.unit_panels.map((panel) => {
          const panelColumns = content.measurement_columns.filter((c) =>
            panel.column_names.includes(c.column_name),
          );
          if (!panelColumns.some((c) => selectedColumns.has(c.column_name))) return null;
          return (
            <TimeSeriesPlot
              key={panel.column_names.join("|")}
              panelColumns={panelColumns}
              selectedColumnNames={selectedColumns}
              rows={filteredRows}
              sharedUnit={panel.shared_unit}
            />
          );
        })}
      </section>

      <section className="card" aria-label="Data">
        <h2>
          Data ({filteredRows.length} of {content.rows.length} rows shown)
        </h2>
        <p className="screen-subtitle">
          Reflects the condition selection above; every selected measurement column's own
          original value and status is shown for every selected row -- nothing plotted or
          tabulated here is ever truncated.
        </p>
        <table className="time-series-data-table">
          <thead>
            <tr>
              <th scope="col">Row</th>
              <th scope="col">Sample</th>
              <th scope="col">Condition</th>
              <th scope="col">Bio. replicate</th>
              <th scope="col">Tech. replicate</th>
              <th scope="col">Time{content.metadata.time_unit ? ` (${content.metadata.time_unit})` : " (unit not declared)"}</th>
              {content.measurement_columns
                .filter((c) => selectedColumns.has(c.column_name))
                .map((column) => (
                  <th scope="col" key={column.column_name}>
                    {column.column_name}
                    {column.unit ? ` (${column.unit})` : " (unit not declared)"}
                  </th>
                ))}
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row) => (
              <tr key={row.row_index}>
                <td>{row.row_index}</td>
                <td className={row.sample_id ? undefined : "not-captured"}>
                  {row.sample_id ?? NOT_CAPTURED}
                </td>
                <td className={row.condition_id ? undefined : "not-captured"}>
                  {row.condition_id ?? NOT_CAPTURED}
                </td>
                <td className={row.biological_replicate ? undefined : "not-captured"}>
                  {row.biological_replicate ?? NOT_CAPTURED}
                </td>
                <td className={row.technical_replicate ? undefined : "not-captured"}>
                  {row.technical_replicate ?? NOT_CAPTURED}
                </td>
                <td
                  title={
                    row.time_status === "MEASURED" ? fullPrecisionTitle(row.time_value) : undefined
                  }
                >
                  {row.time_status === "MEASURED"
                    ? formatScientific(row.time_value)
                    : `${row.time_raw ?? NOT_CAPTURED} (${row.time_status})`}
                </td>
                {content.measurement_columns
                  .filter((c) => selectedColumns.has(c.column_name))
                  .map((column) => {
                    const measurement = row.measurements[column.column_name];
                    return (
                      <td
                        key={column.column_name}
                        title={
                          measurement.status === "MEASURED"
                            ? fullPrecisionTitle(measurement.value)
                            : undefined
                        }
                      >
                        {measurement.status === "MEASURED"
                          ? formatScientific(measurement.value)
                          : `${measurement.raw ?? NOT_CAPTURED} (${measurement.status})`}
                      </td>
                    );
                  })}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
