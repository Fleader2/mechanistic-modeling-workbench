import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  downloadTimeSeriesDatasetTemplate,
  getModelingStudy,
  getProject,
  listTimeSeriesDatasets,
  previewTimeSeriesDataset,
  saveTimeSeriesDataset,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { NOT_CAPTURED, formatScientific, fullPrecisionTitle } from "../format";
import { RouterLink } from "./RouterLink";
import type {
  ProjectDetail,
  SubprojectDetail,
  TimeSeriesDatasetDetail,
  TimeSeriesDatasetListItem,
  TimeSeriesWorkbookPreview,
} from "../types";

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

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: TimeSeriesDatasetListItem[] };

type PreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "malformed"; findings: { code: string; severity: string; message: string }[] }
  | { status: "error"; message: string }
  | { status: "ready"; file: File; preview: TimeSeriesWorkbookPreview };

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "error"; message: string }
  | { status: "saved"; dataset: TimeSeriesDatasetDetail };

interface TimeSeriesDatasetsListScreenProps {
  projectId: string;
  studyId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

/** "All datasets" (Downloadable Two-Tab Excel Template increment) -- the Sidebar's own
 * "All datasets" item, disabled since the Module-Set increment, finally made real here,
 * mirroring that increment's own "All modules" precedent exactly (see Sidebar.tsx).
 *
 * Template download -> file picker -> preview/validation -> explicit save -> reopen, entirely
 * on one screen; see docs/25_time_series_dataset_import_increment.md. Uploading/saving never
 * requires a model or Antimony species name -- nothing on this screen references either.
 */
export function TimeSeriesDatasetsListScreen({
  projectId,
  studyId,
  onProjectChange,
  onStudyChange,
}: TimeSeriesDatasetsListScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studyState, setStudyState] = useState<StudyState>({ status: "loading" });
  const [listState, setListState] = useState<ListState>({ status: "loading" });
  const [previewState, setPreviewState] = useState<PreviewState>({ status: "idle" });
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  const [savedBy, setSavedBy] = useState("");
  const [templateError, setTemplateError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const guard = useRef(createStaleGuard<string>()).current;

  function loadList() {
    setListState({ status: "loading" });
    listTimeSeriesDatasets(projectId, studyId)
      .then((items) => setListState({ status: "ready", items }))
      .catch((error: unknown) => {
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setListState({ status: "error", message });
      });
  }

  useEffect(() => {
    const key = `${projectId}/${studyId}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
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
          loadList();
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
    // `guard`, `onProjectChange`, `onStudyChange` intentionally omitted -- matches every other
    // screen's identical effect.
  }, [projectId, studyId]);

  async function handleDownloadTemplate() {
    setTemplateError(null);
    try {
      const blob = await downloadTimeSeriesDatasetTemplate(projectId, studyId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "time_series_dataset_template.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error: unknown) {
      setTemplateError(
        error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
      );
    }
  }

  function handleFileChosen(file: File) {
    setSaveState({ status: "idle" });
    setPreviewState({ status: "loading" });
    previewTimeSeriesDataset(projectId, studyId, file)
      .then((preview) => setPreviewState({ status: "ready", file, preview }))
      .catch((error: unknown) => {
        if (error instanceof ApiRequestError && error.status === 422) {
          const findings =
            (error.context?.findings as
              | { code: string; severity: string; message: string }[]
              | undefined) ?? [];
          setPreviewState({ status: "malformed", findings });
        } else {
          const message =
            error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
          setPreviewState({ status: "error", message });
        }
      });
  }

  function handleSave() {
    if (previewState.status !== "ready") return;
    setSaveState({ status: "saving" });
    saveTimeSeriesDataset(projectId, studyId, previewState.file, savedBy || undefined)
      .then((dataset) => {
        setSaveState({ status: "saved", dataset });
        setPreviewState({ status: "idle" });
        setSavedBy("");
        if (fileInputRef.current) fileInputRef.current.value = "";
        loadList();
      })
      .catch((error: unknown) => {
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setSaveState({ status: "error", message });
      });
  }

  function handleChooseDifferentFile() {
    setPreviewState({ status: "idle" });
    setSaveState({ status: "idle" });
    if (fileInputRef.current) fileInputRef.current.value = "";
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
  const { project } = projectState;

  if (studyState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="breadcrumb">
          <RouterLink to="/projects">Projects</RouterLink> /{" "}
          <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink>
        </p>
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

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}/studies/${studyId}`}>{study.title}</RouterLink> /
        All datasets
      </p>
      <h1>All datasets</h1>
      <p className="screen-subtitle">
        {study.title} · Time-series experimental datasets, imported from a two-tab Excel
        workbook.
      </p>

      <section className="card" aria-label="Upload a dataset">
        <h2>Upload a dataset</h2>
        <p>
          <button type="button" className="secondary-button" onClick={handleDownloadTemplate}>
            Download template
          </button>
        </p>
        {templateError && (
          <p className="status-message error" role="alert">
            Couldn&apos;t download the template: {templateError}
          </p>
        )}

        <p>
          <label htmlFor="time-series-file-input">Workbook file (.xlsx)</label>
          <br />
          <input
            id="time-series-file-input"
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handleFileChosen(file);
            }}
          />
        </p>

        {previewState.status === "loading" && (
          <p className="status-message">Parsing workbook…</p>
        )}
        {previewState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t parse this workbook: {previewState.message}
          </p>
        )}
        {previewState.status === "malformed" && (
          <div className="status-message error" role="alert">
            <p>This workbook could not be imported:</p>
            <ul>
              {previewState.findings.map((finding, index) => (
                <li key={index}>{finding.message}</li>
              ))}
            </ul>
          </div>
        )}

        {previewState.status === "ready" && (
          <div className="time-series-preview">
            <h3>Preview: {previewState.preview.effective_dataset_name}</h3>

            <table className="time-series-metadata-table">
              <tbody>
                {Object.entries(previewState.preview.metadata)
                  .filter(([key]) => key !== "template_version")
                  .map(([key, value]) => (
                    <tr key={key}>
                      <th scope="row">{key.replace(/_/g, " ")}</th>
                      <td className={value ? undefined : "not-captured"}>
                        {value ?? NOT_CAPTURED}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>

            {previewState.preview.findings.length > 0 && (
              <>
                <h4>Validation findings ({previewState.preview.findings.length})</h4>
                <p className="screen-subtitle">
                  None of these block saving -- an incomplete scientific record is still a real,
                  honestly-disclosed one.
                </p>
                <ul className="time-series-findings-list">
                  {previewState.preview.findings.map((finding, index) => (
                    <li key={index}>{finding.message}</li>
                  ))}
                </ul>
              </>
            )}

            <h4>Data ({previewState.preview.rows.length} rows)</h4>
            <table className="time-series-data-table">
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  {previewState.preview.measurement_columns.map((column) => (
                    <th scope="col" key={column.column_name}>
                      {column.column_name}
                      {column.unit ? ` (${column.unit})` : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewState.preview.rows.map((row) => (
                  <tr key={row.row_index}>
                    <td title={row.time_value !== null ? fullPrecisionTitle(row.time_value) : undefined}>
                      {row.time_value !== null
                        ? formatScientific(row.time_value)
                        : (row.time_raw ?? NOT_CAPTURED)}
                    </td>
                    {previewState.preview.measurement_columns.map((column) => {
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
                            : measurement.status}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>

            <p>
              <label htmlFor="time-series-saved-by">Saved by (optional)</label>
              <br />
              <input
                id="time-series-saved-by"
                type="text"
                value={savedBy}
                onChange={(event) => setSavedBy(event.target.value)}
              />
            </p>

            {saveState.status === "error" && (
              <p className="status-message error" role="alert">
                Couldn&apos;t save this dataset: {saveState.message}
              </p>
            )}

            <button
              type="button"
              className="primary-button"
              disabled={saveState.status === "saving"}
              onClick={handleSave}
            >
              {saveState.status === "saving" ? "Saving…" : "Save dataset"}
            </button>{" "}
            <button type="button" className="secondary-button" onClick={handleChooseDifferentFile}>
              Choose a different file
            </button>
          </div>
        )}

        {saveState.status === "saved" && (
          <p className="status-message">
            Saved.{" "}
            <RouterLink
              to={`/projects/${projectId}/studies/${studyId}/datasets/time-series/${saveState.dataset.id}`}
            >
              View {saveState.dataset.content.effective_dataset_name}
            </RouterLink>
          </p>
        )}
      </section>

      <section className="card" aria-label="Saved datasets">
        <h2>Saved datasets</h2>
        {listState.status === "loading" && <p className="status-message">Loading datasets…</p>}
        {listState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t load datasets: {listState.message}
          </p>
        )}
        {listState.status === "ready" && listState.items.length === 0 && (
          <p className="status-message">No datasets saved yet.</p>
        )}
        {listState.status === "ready" && listState.items.length > 0 && (
          <table className="module-sets-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Measurement type</th>
                <th scope="col">Organism</th>
                <th scope="col">Rows</th>
                <th scope="col">Columns</th>
                <th scope="col">Findings</th>
                <th scope="col">Saved</th>
              </tr>
            </thead>
            <tbody>
              {listState.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <RouterLink
                      to={`/projects/${projectId}/studies/${studyId}/datasets/time-series/${item.id}`}
                      className="project-link"
                    >
                      {item.name}
                    </RouterLink>
                  </td>
                  <td className={item.measurement_type ? undefined : "not-captured"}>
                    {item.measurement_type ?? NOT_CAPTURED}
                  </td>
                  <td className={item.organism ? undefined : "not-captured"}>
                    {item.organism ?? NOT_CAPTURED}
                  </td>
                  <td>{item.row_count}</td>
                  <td>{item.measurement_column_count}</td>
                  <td>{item.unresolved_finding_count}</td>
                  <td>{new Date(item.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
