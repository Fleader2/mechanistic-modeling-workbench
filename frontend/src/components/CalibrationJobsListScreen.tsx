import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  createCalibrationJob,
  getModelingStudy,
  getProject,
  listCalibrationJobs,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { navigate } from "../lib/router";
import { RouterLink } from "./RouterLink";
import type { CalibrationJobSummary, ProjectDetail, SubprojectDetail } from "../types";

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
  | { status: "ready"; items: CalibrationJobSummary[] };

interface CalibrationJobsListScreenProps {
  projectId: string;
  studyId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

/** "All calibration jobs" -- the Joint Calibration Workflow configuration-only increment's own
 * entry point: create a new job, or reopen an existing one. See
 * docs/29_joint_calibration_workflow_design.md and
 * docs/30_joint_calibration_configuration_increment.md. Nothing on this screen executes
 * anything -- see the per-job Review & readiness screen for why. */
export function CalibrationJobsListScreen({
  projectId,
  studyId,
  onProjectChange,
  onStudyChange,
}: CalibrationJobsListScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studyState, setStudyState] = useState<StudyState>({ status: "loading" });
  const [listState, setListState] = useState<ListState>({ status: "loading" });
  const [createdBy, setCreatedBy] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const guard = useRef(createStaleGuard<string>()).current;

  function loadList() {
    setListState({ status: "loading" });
    listCalibrationJobs(projectId, studyId)
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
  }, [projectId, studyId]);

  function handleCreate() {
    setCreating(true);
    setCreateError(null);
    createCalibrationJob(projectId, studyId, createdBy || undefined)
      .then((job) => {
        navigate(`/projects/${projectId}/studies/${studyId}/calibration-jobs/${job.id}`);
      })
      .catch((error: unknown) => {
        setCreating(false);
        setCreateError(
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
        );
      });
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
        Calibration jobs
      </p>
      <h1>Calibration jobs</h1>
      <p className="screen-subtitle">
        {study.title} · Configure a calibration job for one or more whole-model versions against
        one or more datasets. Configuration only -- nothing here executes yet (see each job's
        own Review &amp; readiness screen).
      </p>

      <section className="card" aria-label="Create a calibration job">
        <h2>New calibration job</h2>
        <p>
          <label htmlFor="calibration-job-created-by">Created by (optional)</label>
          <br />
          <input
            id="calibration-job-created-by"
            type="text"
            value={createdBy}
            onChange={(event) => setCreatedBy(event.target.value)}
          />
        </p>
        {createError && (
          <p className="status-message error" role="alert">
            Couldn&apos;t create a calibration job: {createError}
          </p>
        )}
        <button
          type="button"
          className="primary-button"
          disabled={creating}
          onClick={handleCreate}
        >
          {creating ? "Creating…" : "New calibration job"}
        </button>
      </section>

      <section className="card" aria-label="Existing calibration jobs">
        <h2>Existing calibration jobs</h2>
        {listState.status === "loading" && (
          <p className="status-message">Loading calibration jobs…</p>
        )}
        {listState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t load calibration jobs: {listState.message}
          </p>
        )}
        {listState.status === "ready" && listState.items.length === 0 && (
          <p className="status-message">No calibration jobs yet.</p>
        )}
        {listState.status === "ready" && listState.items.length > 0 && (
          <table className="module-sets-table">
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Arms</th>
                <th scope="col">Created</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              {listState.items.map((item) => (
                <tr key={item.id}>
                  <td>{item.status}</td>
                  <td>{item.arm_count}</td>
                  <td>
                    {new Date(item.created_at).toLocaleString()}
                    {item.created_by ? ` by ${item.created_by}` : ""}
                  </td>
                  <td>
                    <RouterLink
                      to={`/projects/${projectId}/studies/${studyId}/calibration-jobs/${item.id}`}
                      className="project-link"
                    >
                      Open
                    </RouterLink>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
