import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  getModelingStudy,
  getProject,
  getTimeSeriesDataset,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { NOT_CAPTURED } from "../format";
import { RouterLink } from "./RouterLink";
import type { ProjectDetail, SubprojectDetail, TimeSeriesDatasetDetail } from "../types";

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
  const guard = useRef(createStaleGuard<string>()).current;

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

      <section className="card" aria-label="Data">
        <h2>Data ({content.rows.length} rows)</h2>
        <table className="time-series-data-table">
          <thead>
            <tr>
              <th scope="col">Time</th>
              {content.measurement_columns.map((column) => (
                <th scope="col" key={column.column_name}>
                  {column.column_name}
                  {column.unit ? ` (${column.unit})` : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {content.rows.map((row) => (
              <tr key={row.row_index}>
                <td>{row.time_value ?? row.time_raw ?? NOT_CAPTURED}</td>
                {content.measurement_columns.map((column) => {
                  const measurement = row.measurements[column.column_name];
                  return (
                    <td key={column.column_name}>
                      {measurement.status === "MEASURED" ? measurement.value : measurement.status}
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
