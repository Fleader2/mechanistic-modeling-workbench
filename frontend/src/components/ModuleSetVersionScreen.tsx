import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  createModuleSetEditDraft,
  getModelingStudy,
  getModuleSetVersion,
  getProject,
  getVersionMemberBoundaryPorts,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { formatModuleSetOriginMethod } from "../format";
import { navigate } from "../lib/router";
import type { ModuleSetVersionDetail, ProjectDetail, SubprojectDetail } from "../types";
import { RouterLink } from "./RouterLink";
import { ModuleHierarchyTable } from "./ModuleHierarchyTable";

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

type VersionState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; version: ModuleSetVersionDetail };

interface ModuleSetVersionScreenProps {
  projectId: string;
  studyId: string;
  moduleSetId: string;
  version: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

/** Reopening one saved, immutable `ModuleSetVersion` (Figma's own "Module set saved" screen,
 * node `112:766`, which this read-only view is the "come back later" counterpart of). Always
 * read-only -- there is no edit, re-save, or delete action anywhere on this screen
 * (`docs/20` §4, rule 6; `docs/21_module_set_first_increment.md`). */
export function ModuleSetVersionScreen({
  projectId,
  studyId,
  moduleSetId,
  version,
  onProjectChange,
  onStudyChange,
}: ModuleSetVersionScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studyState, setStudyState] = useState<StudyState>({ status: "loading" });
  const [versionState, setVersionState] = useState<VersionState>({ status: "loading" });
  const [editError, setEditError] = useState<string | null>(null);
  const [creatingEditDraft, setCreatingEditDraft] = useState(false);

  function handleCreateEditDraft() {
    setEditError(null);
    setCreatingEditDraft(true);
    createModuleSetEditDraft(projectId, studyId, moduleSetId, version)
      .then((draft) => {
        navigate(`/projects/${projectId}/studies/${studyId}/module-set-drafts/${draft.id}`);
      })
      .catch((error: unknown) => {
        setCreatingEditDraft(false);
        setEditError(error instanceof ApiRequestError ? error.message : "An unexpected error occurred.");
      });
  }
  const guard = useRef(createStaleGuard<string>()).current;

  useEffect(() => {
    const key = `${projectId}/${studyId}/${moduleSetId}/${version}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
    setVersionState({ status: "loading" });
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

            return getModuleSetVersion(projectId, studyId, moduleSetId, version)
              .then((versionDetail) => {
                if (guard.isCurrent(key)) {
                  setVersionState({ status: "ready", version: versionDetail });
                }
              })
              .catch((error: unknown) => {
                if (!guard.isCurrent(key)) return;
                if (error instanceof ApiRequestError && error.status === 404) {
                  setVersionState({ status: "not-found" });
                } else {
                  const message =
                    error instanceof ApiRequestError
                      ? error.message
                      : "An unexpected error occurred.";
                  setVersionState({ status: "error", message });
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
    // `guard`, `onProjectChange`, `onStudyChange` intentionally omitted -- see
    // StudyDetailScreen's identical effect for why.
  }, [projectId, studyId, moduleSetId, version]);

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
  const moduleSetsUrl = `/projects/${projectId}/studies/${studyId}/module-sets`;

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
        <RouterLink to={moduleSetsUrl} className="back-link">
          Back to All modules
        </RouterLink>
      </div>
    );
  }
  const { version: versionDetail } = versionState;

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}/studies/${studyId}`}>{study.title}</RouterLink> /{" "}
        <RouterLink to={moduleSetsUrl}>All modules</RouterLink> /{" "}
        {versionDetail.module_set_stable_identifier} v{versionDetail.version}
      </p>
      <h1>
        {versionDetail.module_set_name} · v{versionDetail.version}
      </h1>
      <p className="screen-subtitle">
        {versionDetail.module_set_stable_identifier} · {formatModuleSetOriginMethod(versionDetail.origin_method)}
      </p>
      <p className="not-available-note">
        Saved after explicit confirmation. The source set and its previous versions remain
        unchanged. Each module belongs to this set identity and version.
      </p>

      <section className="card" aria-label="Version information">
        <h2>Version information</h2>
        <p>
          <strong>Version note:</strong>{" "}
          <span className={versionDetail.version_note ? undefined : "not-captured"}>
            {versionDetail.version_note ?? "Not captured"}
          </span>
        </p>
        <p>
          <strong>Saved by:</strong>{" "}
          <span className={versionDetail.saved_by ? undefined : "not-captured"}>
            {versionDetail.saved_by ?? "Not captured"}
          </span>
        </p>
        <p>
          <strong>Saved at:</strong> {new Date(versionDetail.saved_at).toLocaleString()}
        </p>
        {editError && (
          <p className="status-message error" role="alert">
            Couldn&apos;t start editing: {editError}
          </p>
        )}
        <button type="button" onClick={handleCreateEditDraft} disabled={creatingEditDraft}>
          {creatingEditDraft ? "Starting edit…" : "Edit this version"}
        </button>
      </section>

      <section className="card" aria-label="Modules">
        <h2>Modules ({versionDetail.members.length})</h2>
        <ModuleHierarchyTable
          members={versionDetail.members}
          fetchBoundaryPorts={(memberId) =>
            getVersionMemberBoundaryPorts(projectId, studyId, moduleSetId, version, memberId)
          }
          executionLinkFor={(memberId) =>
            `/projects/${projectId}/studies/${studyId}/module-sets/${moduleSetId}/versions/${version}/members/${memberId}/execution`
          }
        />
      </section>
    </div>
  );
}
