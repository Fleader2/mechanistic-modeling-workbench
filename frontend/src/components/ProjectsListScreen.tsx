import { useEffect, useRef, useState } from "react";
import { ApiRequestError, getProject, listProjects } from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import type { ProjectDetail, ProjectListItem } from "../types";
import { ProjectsTable } from "./ProjectsTable";
import { ProjectPreviewPanel } from "./ProjectPreviewPanel";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; projects: ProjectListItem[] };

type DetailState =
  | { status: "none" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; project: ProjectDetail };

/** The "01 — All Projects" screen (Figma node 46:112, file 4tLH4HX0rdgPxjpNB1aJOW).
 *
 * In scope: list projects, select a row to preview its metadata.
 * Out of scope (disabled, never silently dropped): search, opening a
 * project, project creation. See docs/16_projects_api_first_increment.md.
 */
export function ProjectsListScreen() {
  const [listState, setListState] = useState<ListState>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailState, setDetailState] = useState<DetailState>({ status: "none" });
  const detailGuard = useRef(createStaleGuard<string>()).current;

  useEffect(() => {
    let cancelled = false;
    setListState({ status: "loading" });
    listProjects()
      .then((projects) => {
        if (!cancelled) setListState({ status: "ready", projects });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setListState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleSelect(project: ProjectListItem) {
    setSelectedId(project.id);
    setDetailState({ status: "loading" });
    detailGuard.start(project.id);
    getProject(project.id)
      .then((detail) => {
        if (!detailGuard.isCurrent(project.id)) return; // a later row click superseded this one
        setDetailState({ status: "ready", project: detail });
      })
      .catch((error: unknown) => {
        if (!detailGuard.isCurrent(project.id)) return;
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setDetailState({ status: "error", message });
      });
  }

  return (
    <div className="projects-screen">
      <p className="breadcrumb">Projects</p>
      <h1>Projects</h1>
      <p className="screen-subtitle">
        Select a project to preview its metadata. Double-click its name to open it.
      </p>
      <p className="not-available-note">
        Opening a project and searching projects aren&apos;t available in this increment.
      </p>

      <button type="button" className="secondary-button" disabled title="Not available yet">
        Search projects
      </button>

      {listState.status === "loading" && <p className="status-message">Loading projects…</p>}

      {listState.status === "error" && (
        <p className="status-message error" role="alert">
          Couldn&apos;t load projects: {listState.message}
        </p>
      )}

      {listState.status === "ready" && listState.projects.length === 0 && (
        <p className="status-message">No projects yet.</p>
      )}

      {listState.status === "ready" && listState.projects.length > 0 && (
        <ProjectsTable
          projects={listState.projects}
          selectedId={selectedId}
          onSelect={handleSelect}
        />
      )}

      {detailState.status === "none" && (
        <p className="status-message preview-placeholder">
          Select a project above to preview its metadata.
        </p>
      )}
      {detailState.status === "loading" && (
        <p className="status-message">Loading project details…</p>
      )}
      {detailState.status === "error" && (
        <p className="status-message error" role="alert">
          Couldn&apos;t load project details: {detailState.message}
        </p>
      )}
      {detailState.status === "ready" && <ProjectPreviewPanel project={detailState.project} />}

      <section className="create-project-panel" aria-label="Create a new project">
        <h2>Create a new project</h2>
        <label className="mode-option">
          <input type="radio" name="project-mode" disabled />
          <span>
            <strong>Microbial Metabolism</strong>
            <br />
            Pathway engineering and metabolic reconstruction
          </span>
        </label>
        <label className="mode-option">
          <input type="radio" name="project-mode" disabled />
          <span>
            <strong>Regulatory Networks</strong>
            <br />
            Signaling, disease mechanisms and drug response
          </span>
        </label>
        <p className="not-available-note">Project creation isn&apos;t available in this increment.</p>
        <button type="button" className="primary-button" disabled>
          Create Project
        </button>
      </section>
    </div>
  );
}
