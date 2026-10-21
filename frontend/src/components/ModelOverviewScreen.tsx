import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  getModel,
  getModelLineage,
  getModelingStudy,
  getProject,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { formatModelStatus } from "../format";
import type { ModelDetail, ModelLineage, ProjectDetail, SubprojectDetail } from "../types";
import { RouterLink } from "./RouterLink";
import { ModelTabs, type ModelTab } from "./ModelTabs";
import { ModelInformationCard } from "./ModelInformationCard";
import { ModelLineageCard } from "./ModelLineageCard";

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

type ModelState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; model: ModelDetail };

type LineageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; lineage: ModelLineage };

interface ModelOverviewScreenProps {
  projectId: string;
  studyId: string;
  modelId: string;
  /** Reports the owning project (for the sidebar's "PROJECT MODE" section),
   * or `null` while loading, on error/not-found, or once this screen
   * unmounts. */
  onProjectChange: (project: ProjectDetail | null) => void;
  /** Reports the owning study (for the sidebar's "Current study" label), or
   * `null` while loading, on error/not-found, or once this screen
   * unmounts. */
  onStudyChange: (study: SubprojectDetail | null) => void;
}

/** The "05 — Model Overview" screen (Figma node 46:564, file
 * 4tLH4HX0rdgPxjpNB1aJOW).
 *
 * In scope: the owning project's and study's identity (for the breadcrumb
 * and sidebar), the model's own persisted metadata ("Overview" tab), and
 * its available version lineage ("History" tab). Out of scope (disabled,
 * never silently dropped): every other Figma tab (none has durably
 * available, correctly scoped content for this increment -- see
 * docs/19_model_overview_increment.md's "durability audit"), editing,
 * exporting, validating, creating a new version. See that same doc.
 *
 * Fetches project, then study (scoped to that project), then model (scoped
 * to that study), then -- only on the model's own success -- its lineage.
 * Each step's 404 is indistinguishable from "doesn't exist," never a
 * cross-project/cross-study leak (enforced server-side; see
 * `app.api.v1.routes.projects._require_model`). Reuses the identical
 * `createStaleGuard` pattern `StudyDetailScreen` already established, keyed
 * here by the combined `projectId`/`studyId`/`modelId` triple.
 */
export function ModelOverviewScreen({
  projectId,
  studyId,
  modelId,
  onProjectChange,
  onStudyChange,
}: ModelOverviewScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studyState, setStudyState] = useState<StudyState>({ status: "loading" });
  const [modelState, setModelState] = useState<ModelState>({ status: "loading" });
  const [lineageState, setLineageState] = useState<LineageState>({ status: "loading" });
  const [activeTab, setActiveTab] = useState<ModelTab>("overview");
  const guard = useRef(createStaleGuard<string>()).current;

  useEffect(() => {
    const key = `${projectId}/${studyId}/${modelId}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
    setModelState({ status: "loading" });
    setLineageState({ status: "loading" });
    setActiveTab("overview");
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

            return getModel(projectId, studyId, modelId)
              .then((model) => {
                if (!guard.isCurrent(key)) return;
                setModelState({ status: "ready", model });

                return getModelLineage(projectId, studyId, modelId)
                  .then((lineage) => {
                    if (!guard.isCurrent(key)) return;
                    setLineageState({ status: "ready", lineage });
                  })
                  .catch((error: unknown) => {
                    if (!guard.isCurrent(key)) return;
                    const message =
                      error instanceof ApiRequestError
                        ? error.message
                        : "An unexpected error occurred.";
                    setLineageState({ status: "error", message });
                  });
              })
              .catch((error: unknown) => {
                if (!guard.isCurrent(key)) return;
                if (error instanceof ApiRequestError && error.status === 404) {
                  setModelState({ status: "not-found" });
                } else {
                  const message =
                    error instanceof ApiRequestError
                      ? error.message
                      : "An unexpected error occurred.";
                  setModelState({ status: "error", message });
                }
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
    // omitted -- see StudyDetailScreen's identical effect for why.
  }, [projectId, studyId, modelId]);

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
  const studyUrl = `/projects/${projectId}/studies/${studyId}`;

  if (modelState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="breadcrumb">
          <RouterLink to="/projects">Projects</RouterLink> /{" "}
          <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
          <RouterLink to={studyUrl}>{study.title}</RouterLink>
        </p>
        <p className="status-message">Loading model…</p>
      </div>
    );
  }

  if (modelState.status === "not-found") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          This model could not be found.
        </p>
        <RouterLink to={studyUrl} className="back-link">
          Back to {study.title}
        </RouterLink>
      </div>
    );
  }

  if (modelState.status === "error") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          Couldn&apos;t load this model: {modelState.message}
        </p>
        <RouterLink to={studyUrl} className="back-link">
          Back to {study.title}
        </RouterLink>
      </div>
    );
  }

  const { model } = modelState;

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
        <RouterLink to={studyUrl}>{study.title}</RouterLink> / {model.name}
      </p>
      <h1>{model.name}</h1>
      <p className="screen-subtitle">
        {model.stable_identifier} · {model.version_label ?? "Not captured"} ·{" "}
        {formatModelStatus(model.status)}
      </p>

      <ModelTabs activeTab={activeTab} onSelectTab={setActiveTab} />

      {activeTab === "overview" && <ModelInformationCard model={model} />}

      {activeTab === "history" && lineageState.status === "loading" && (
        <section className="card" aria-label="Version history">
          <p className="status-message">Loading version history…</p>
        </section>
      )}
      {activeTab === "history" && lineageState.status === "error" && (
        <section className="card" aria-label="Version history">
          <p className="status-message error" role="alert">
            Couldn&apos;t load version history: {lineageState.message}
          </p>
        </section>
      )}
      {activeTab === "history" && lineageState.status === "ready" && (
        <ModelLineageCard projectId={projectId} studyId={studyId} lineage={lineageState.lineage} />
      )}
    </div>
  );
}
