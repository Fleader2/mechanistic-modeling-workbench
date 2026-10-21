import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  getModelingStudy,
  getModelingStudyModels,
  getProject,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { formatTaskType } from "../format";
import type { ModelListItem, ProjectDetail, SubprojectDetail } from "../types";
import { RouterLink } from "./RouterLink";
import { StudyInformationCard } from "./StudyInformationCard";
import { ModelsTable } from "./ModelsTable";

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

type ModelsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; models: ModelListItem[] };

interface StudyDetailScreenProps {
  projectId: string;
  studyId: string;
  /** Reports the owning project (for the sidebar's "PROJECT MODE" section,
   * same mechanism `ProjectDetailScreen` already uses), or `null` while
   * loading, on error/not-found, or once this screen unmounts. */
  onProjectChange: (project: ProjectDetail | null) => void;
  /** Reports the loaded study (for the sidebar's "Current study" label,
   * Figma's own node 46:314), or `null` while loading, on error/not-found,
   * or once this screen unmounts. */
  onStudyChange: (study: SubprojectDetail | null) => void;
}

/** The "03 — Modeling Study" screen (Figma node 46:314, file
 * 4tLH4HX0rdgPxjpNB1aJOW).
 *
 * In scope: the owning project's identity (for the breadcrumb and sidebar),
 * the study's own persisted metadata, its models, and opening a model (see
 * docs/19_model_overview_increment.md). Out of scope (disabled, never
 * silently dropped): editing the study, creating a new model. See
 * docs/18_modeling_study_increment.md.
 *
 * Fetches the project first (so an unknown/mismatched project never fires
 * the study request at all, and so the breadcrumb/sidebar always have a
 * real project title even on a direct link), then the study -- scoped to
 * that project id, so a study id that exists but belongs to a *different*
 * project is indistinguishable from one that does not exist at all, never
 * a cross-project leak -- then, only on the study's own success, its
 * models. Reuses the identical `createStaleGuard` pattern
 * `ProjectDetailScreen` already established, keyed here by the combined
 * `projectId`/`studyId` pair so navigating directly between two different
 * studies (same project or not) is protected against a slower, earlier
 * response overwriting a faster, later one.
 */
export function StudyDetailScreen({
  projectId,
  studyId,
  onProjectChange,
  onStudyChange,
}: StudyDetailScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studyState, setStudyState] = useState<StudyState>({ status: "loading" });
  const [modelsState, setModelsState] = useState<ModelsState>({ status: "loading" });
  const guard = useRef(createStaleGuard<string>()).current;

  useEffect(() => {
    const key = `${projectId}/${studyId}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
    setModelsState({ status: "loading" });
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

            return getModelingStudyModels(projectId, studyId)
              .then((models) => {
                if (!guard.isCurrent(key)) return;
                setModelsState({ status: "ready", models });
              })
              .catch((error: unknown) => {
                if (!guard.isCurrent(key)) return;
                const message =
                  error instanceof ApiRequestError
                    ? error.message
                    : "An unexpected error occurred.";
                setModelsState({ status: "error", message });
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
    // `guard`, `onProjectChange`, and `onStudyChange` are intentionally
    // omitted: `guard` is a stable ref, and the two callbacks must be
    // stable (wrapped in useCallback by the caller) -- see
    // ProjectDetailScreen's identical effect for why.
  }, [projectId, studyId]);

  if (projectState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="status-message">Loading project…</p>
      </div>
    );
  }

  if (projectState.status === "not-found") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          This project could not be found.
        </p>
        <RouterLink to="/projects" className="back-link">
          Back to All Projects
        </RouterLink>
      </div>
    );
  }

  if (projectState.status === "error") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          Couldn&apos;t load this project: {projectState.message}
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

  if (studyState.status === "not-found") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          This Modeling Study could not be found.
        </p>
        <RouterLink to={`/projects/${projectId}`} className="back-link">
          Back to {project.title}
        </RouterLink>
      </div>
    );
  }

  if (studyState.status === "error") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          Couldn&apos;t load this Modeling Study: {studyState.message}
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
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> / {study.title}
      </p>
      <h1>{study.title}</h1>
      <p className="screen-subtitle">Modeling Study · {formatTaskType(study.task_type)}</p>

      <StudyInformationCard study={study} />

      <section className="card models-card" aria-label="Models">
        <h2>Models</h2>

        {modelsState.status === "loading" && <p className="status-message">Loading models…</p>}
        {modelsState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t load models: {modelsState.message}
          </p>
        )}
        {modelsState.status === "ready" && modelsState.models.length === 0 && (
          <p className="status-message">No models yet.</p>
        )}
        {modelsState.status === "ready" && modelsState.models.length > 0 && (
          <ModelsTable projectId={projectId} studyId={studyId} models={modelsState.models} />
        )}

        <button type="button" className="primary-button" disabled title="Not available yet">
          New Model
        </button>
      </section>
    </div>
  );
}
