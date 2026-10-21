import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  createModuleSetDraft,
  getModelingStudy,
  getProject,
  listDraftableHierarchicalRuns,
  listModuleSets,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { formatModuleSetOriginMethod } from "../format";
import { navigate } from "../lib/router";
import type {
  HierarchicalRunSummary,
  ModuleSetSummary,
  ProjectDetail,
  SubprojectDetail,
} from "../types";
import { RouterLink } from "./RouterLink";

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

type ListState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: T[] };

interface ModuleSetsListScreenProps {
  projectId: string;
  studyId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

/** The "06 — All Modules" screen (Figma node `60:756`), this increment's own entry point for
 * module sets: a study's own saved module sets, plus the hierarchical runs a new draft can be
 * started from (Figma's own mock has no "create module set" entry point at all -- this
 * increment adds the one it's missing, read-only browsing otherwise unchanged).
 *
 * See `docs/21_module_set_first_increment.md`. Creating a draft is the only mutation this
 * screen performs; everything else here is read-only.
 */
export function ModuleSetsListScreen({
  projectId,
  studyId,
  onProjectChange,
  onStudyChange,
}: ModuleSetsListScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studyState, setStudyState] = useState<StudyState>({ status: "loading" });
  const [setsState, setSetsState] = useState<ListState<ModuleSetSummary>>({ status: "loading" });
  const [runsState, setRunsState] = useState<ListState<HierarchicalRunSummary>>({
    status: "loading",
  });
  const [creatingRunId, setCreatingRunId] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const guard = useRef(createStaleGuard<string>()).current;

  useEffect(() => {
    const key = `${projectId}/${studyId}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
    setSetsState({ status: "loading" });
    setRunsState({ status: "loading" });
    onProjectChange(null);
    onStudyChange(null);

    getProject(projectId)
      .then((project) => {
        if (!guard.isCurrent(key)) return;
        setProjectState({ status: "ready", project });
        onProjectChange(project);

        return getModelingStudy(projectId, studyId)
          .then((study) => {
            if (!guard.isCurrent(key)) return;
            setStudyState({ status: "ready", study });
            onStudyChange(study);

            listModuleSets(projectId, studyId)
              .then((items) => {
                if (guard.isCurrent(key)) setSetsState({ status: "ready", items });
              })
              .catch((error: unknown) => {
                if (!guard.isCurrent(key)) return;
                const message =
                  error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
                setSetsState({ status: "error", message });
              });

            listDraftableHierarchicalRuns(projectId, studyId)
              .then((items) => {
                if (guard.isCurrent(key)) setRunsState({ status: "ready", items });
              })
              .catch((error: unknown) => {
                if (!guard.isCurrent(key)) return;
                const message =
                  error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
                setRunsState({ status: "error", message });
              });
          })
          .catch((error: unknown) => {
            if (!guard.isCurrent(key)) return;
            if (error instanceof ApiRequestError && error.status === 404) {
              setStudyState({ status: "not-found" });
            } else {
              const message =
                error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
              setStudyState({ status: "error", message });
            }
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
    // `guard`, `onProjectChange`, `onStudyChange` intentionally omitted -- see
    // StudyDetailScreen's identical effect for why.
  }, [projectId, studyId]);

  function handleCreateDraft(runRecordId: string) {
    setCreatingRunId(runRecordId);
    setCreateError(null);
    createModuleSetDraft(projectId, studyId, runRecordId)
      .then((draft) => {
        navigate(`/projects/${projectId}/studies/${studyId}/module-set-drafts/${draft.id}`);
      })
      .catch((error: unknown) => {
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setCreateError(message);
        setCreatingRunId(null);
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
        All modules
      </p>
      <h1>All modules</h1>
      <p className="screen-subtitle">{study.title} · Module sets grouped by model and version.</p>

      <section className="card" aria-label="Module sets">
        <h2>Module sets</h2>
        {setsState.status === "loading" && <p className="status-message">Loading module sets…</p>}
        {setsState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t load module sets: {setsState.message}
          </p>
        )}
        {setsState.status === "ready" && setsState.items.length === 0 && (
          <p className="status-message">No module sets yet.</p>
        )}
        {setsState.status === "ready" && setsState.items.length > 0 && (
          <table className="module-sets-table">
            <thead>
              <tr>
                <th scope="col">Set</th>
                <th scope="col">Name</th>
                <th scope="col">Latest version</th>
                <th scope="col">Method</th>
              </tr>
            </thead>
            <tbody>
              {setsState.items.map((set) => (
                <tr key={set.id}>
                  <td>{set.stable_identifier}</td>
                  <td>
                    {set.latest_version ? (
                      <RouterLink
                        to={`/projects/${projectId}/studies/${studyId}/module-sets/${set.id}/versions/${set.latest_version}`}
                        className="project-link"
                      >
                        {set.name}
                      </RouterLink>
                    ) : (
                      set.name
                    )}
                  </td>
                  <td>{set.latest_version ?? "—"}</td>
                  <td>
                    {set.latest_version_origin_method
                      ? formatModuleSetOriginMethod(set.latest_version_origin_method)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card" aria-label="Hierarchical runs available to draft from">
        <h2>Start a new draft</h2>
        {createError && (
          <p className="status-message error" role="alert">
            Couldn&apos;t create a draft: {createError}
          </p>
        )}
        {runsState.status === "loading" && <p className="status-message">Loading runs…</p>}
        {runsState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t load hierarchical runs: {runsState.message}
          </p>
        )}
        {runsState.status === "ready" && runsState.items.length === 0 && (
          <p className="status-message">
            No completed hierarchical runs with an associated model are available to draft from
            yet.
          </p>
        )}
        {runsState.status === "ready" && runsState.items.length > 0 && (
          <table className="module-sets-table hierarchical-runs-table">
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Modules</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              {runsState.items.map((run) => (
                <tr key={run.id}>
                  <td>{run.id}</td>
                  <td>{run.module_count}</td>
                  <td>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={creatingRunId !== null}
                      onClick={() => handleCreateDraft(run.id)}
                    >
                      {creatingRunId === run.id ? "Creating…" : "Create module set draft"}
                    </button>
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
