import { useEffect, useRef, useState } from "react";
import { ApiRequestError, getProject, getProjectSubprojects } from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import type { ProjectDetail, SubprojectListItem } from "../types";
import { RouterLink } from "./RouterLink";
import { ProjectInformationCard } from "./ProjectInformationCard";
import { ModelingStudiesTable } from "./ModelingStudiesTable";

type ProjectState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; project: ProjectDetail };

type StudiesState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; studies: SubprojectListItem[] };

interface ProjectDetailScreenProps {
  projectId: string;
  /** Reports the loaded project (for the sidebar's "PROJECT MODE" section,
   * which lives outside this component), or `null` while loading, on
   * error/not-found, or once this screen unmounts. */
  onProjectChange: (project: ProjectDetail | null) => void;
}

/** The "02 — Current Project" screen (Figma node 46:203, file
 * 4tLH4HX0rdgPxjpNB1aJOW).
 *
 * In scope: project metadata, its Modeling Studies with per-study model/
 * dataset counts. Out of scope (disabled, never silently dropped): editing
 * the project, opening a Modeling Study, creating a new one. See
 * docs/17_current_project_increment.md.
 */
export function ProjectDetailScreen({ projectId, onProjectChange }: ProjectDetailScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studiesState, setStudiesState] = useState<StudiesState>({ status: "loading" });
  const guard = useRef(createStaleGuard<string>()).current;

  useEffect(() => {
    guard.start(projectId);
    setProjectState({ status: "loading" });
    setStudiesState({ status: "loading" });
    onProjectChange(null);

    getProject(projectId)
      .then((project) => {
        if (!guard.isCurrent(projectId)) return;
        setProjectState({ status: "ready", project });
        onProjectChange(project);

        return getProjectSubprojects(projectId)
          .then((studies) => {
            if (!guard.isCurrent(projectId)) return;
            setStudiesState({ status: "ready", studies });
          })
          .catch((error: unknown) => {
            if (!guard.isCurrent(projectId)) return;
            const message =
              error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
            setStudiesState({ status: "error", message });
          });
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(projectId)) return;
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
    };
    // `guard` and `onProjectChange` are intentionally omitted: `guard` is a
    // stable ref, and `onProjectChange` must be a stable callback (wrapped
    // in useCallback by the caller) -- re-running this effect on every
    // parent render would needlessly re-fetch.
  }, [projectId]);

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

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> / {project.title}
      </p>
      <h1>{project.title}</h1>
      <p className="screen-subtitle">
        Project {project.stable_identifier} · Double-click a Modeling Study to open it.
      </p>
      <p className="not-available-note">
        Opening a Modeling Study isn&apos;t available in this increment.
      </p>

      <ProjectInformationCard project={project} />

      <section className="card modeling-studies-card" aria-label="Modeling Studies">
        <h2>Modeling Studies</h2>

        {studiesState.status === "loading" && (
          <p className="status-message">Loading Modeling Studies…</p>
        )}
        {studiesState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t load Modeling Studies: {studiesState.message}
          </p>
        )}
        {studiesState.status === "ready" && studiesState.studies.length === 0 && (
          <p className="status-message">No Modeling Studies yet.</p>
        )}
        {studiesState.status === "ready" && studiesState.studies.length > 0 && (
          <ModelingStudiesTable studies={studiesState.studies} />
        )}

        <button type="button" className="primary-button" disabled title="Not available yet">
          New Modeling Study
        </button>
      </section>
    </div>
  );
}
