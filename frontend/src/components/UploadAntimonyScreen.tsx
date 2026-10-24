import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  getModelingStudy,
  getProject,
  previewModelAntimonyImport,
  saveModelAntimonyImport,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { navigate } from "../lib/router";
import { RouterLink } from "./RouterLink";
import type { AntimonyImportPreviewResponse, ModelDetail, ProjectDetail, SubprojectDetail } from "../types";

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

type PreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; file: File; preview: AntimonyImportPreviewResponse };

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "error"; message: string }
  | { status: "saved"; model: ModelDetail };

interface UploadAntimonyScreenProps {
  projectId: string;
  studyId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

/** "Upload Antimony" (Whole-Model Antimony Import increment, docs/34) -- the Study's own
 * "Models" card's "New Model" button, finally made real here. Sequential states on one
 * screen, never a separate screen per step: choose a file -> preview compilation/fidelity
 * findings -> explicitly save as a new, independent imported model -> open its overview.
 * Calibration (fitting) execution is untouched and stays unavailable regardless -- this
 * screen only ever creates a Model row; nothing here simulates or fits anything. There is no
 * Figma reference for this screen beyond the generic "New Model" button itself (confirmed by
 * a direct check of the design file during this increment) -- this layout follows
 * TimeSeriesDatasetsListScreen's own established upload/preview/save structure instead.
 */
export function UploadAntimonyScreen({
  projectId,
  studyId,
  onProjectChange,
  onStudyChange,
}: UploadAntimonyScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studyState, setStudyState] = useState<StudyState>({ status: "loading" });
  const [previewState, setPreviewState] = useState<PreviewState>({ status: "idle" });
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  const [modelName, setModelName] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [verificationNotes, setVerificationNotes] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const guard = useRef(createStaleGuard<string>()).current;

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
        return getModelingStudy(projectId, studyId)
          .then((study) => {
            if (!guard.isCurrent(key)) return;
            setStudyState({ status: "ready", study });
            onStudyChange(study);
          })
          .catch((error: unknown) => {
            if (!guard.isCurrent(key)) return;
            if (error instanceof ApiRequestError && error.status === 404) {
              setStudyState({ status: "not-found" });
            } else {
              setStudyState({
                status: "error",
                message: error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
              });
            }
          });
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        if (error instanceof ApiRequestError && error.status === 404) {
          setProjectState({ status: "not-found" });
        } else {
          setProjectState({
            status: "error",
            message: error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
          });
        }
      });

    return () => {
      onProjectChange(null);
      onStudyChange(null);
    };
    // `guard`, `onProjectChange`, `onStudyChange` intentionally omitted -- see
    // StudyDetailScreen's identical effect for why.
  }, [projectId, studyId]);

  function handleFileChosen(file: File) {
    setSaveState({ status: "idle" });
    setPreviewState({ status: "loading" });
    if (!modelName.trim()) {
      setModelName(file.name.replace(/\.(antimony|txt)$/i, ""));
    }
    previewModelAntimonyImport(projectId, studyId, file)
      .then((preview) => setPreviewState({ status: "ready", file, preview }))
      .catch((error: unknown) => {
        setPreviewState({
          status: "error",
          message: error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
        });
      });
  }

  function handleSave() {
    if (previewState.status !== "ready" || !modelName.trim()) return;
    setSaveState({ status: "saving" });
    saveModelAntimonyImport(
      projectId,
      studyId,
      previewState.file,
      modelName.trim(),
      sourceReference.trim() || undefined,
      verificationNotes.trim() || undefined,
    )
      .then((model) => {
        setSaveState({ status: "saved", model });
      })
      .catch((error: unknown) => {
        setSaveState({
          status: "error",
          message: error instanceof ApiRequestError ? error.message : "An unexpected error occurred.",
        });
      });
  }

  function handleChooseDifferentFile() {
    setPreviewState({ status: "idle" });
    setSaveState({ status: "idle" });
    setModelName("");
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
  const studyUrl = `/projects/${projectId}/studies/${studyId}`;

  if (saveState.status === "saved") {
    return (
      <div className="projects-screen">
        <p className="breadcrumb">
          <RouterLink to="/projects">Projects</RouterLink> /{" "}
          <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
          <RouterLink to={studyUrl}>{study.title}</RouterLink> / Upload Antimony
        </p>
        <h1>Model imported</h1>
        <p className="status-message">
          &quot;{saveState.model.name}&quot; was saved as a new, independent imported model.
        </p>
        <button
          type="button"
          className="primary-button"
          onClick={() => navigate(`${studyUrl}/models/${saveState.model.id}`)}
        >
          Open model overview
        </button>{" "}
        <RouterLink to={studyUrl} className="back-link">
          Back to {study.title}
        </RouterLink>
      </div>
    );
  }

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
        <RouterLink to={studyUrl}>{study.title}</RouterLink> / Upload Antimony
      </p>
      <h1>Upload Antimony</h1>
      <p className="screen-subtitle">
        Import an already-written Antimony model directly -- bypassing the usual Agent 1/Agent 2
        build. The original file is preserved byte-for-byte; nothing is silently rewritten,
        simplified, or replaced with a generated approximation.
      </p>

      <section className="card" aria-label="Choose a file">
        <h2>1. Choose a file</h2>
        <input
          ref={fileInputRef}
          type="file"
          accept=".antimony,.txt,text/plain"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) handleFileChosen(file);
          }}
        />
        {previewState.status === "loading" && (
          <p className="status-message">Compiling and auditing…</p>
        )}
        {previewState.status === "error" && (
          <p className="status-message error" role="alert">
            Couldn&apos;t preview this file: {previewState.message}
          </p>
        )}
      </section>

      {previewState.status === "ready" && (
        <section className="card" aria-label="Preview">
          <h2>2. Preview</h2>
          {previewState.preview.load_succeeded ? (
            <>
              <p className="status-message">
                Compiles and loads. {previewState.preview.floating_species_ids.length} floating
                species, {previewState.preview.boundary_species_ids.length} boundary species,{" "}
                {previewState.preview.compartment_ids.length} compartment(s),{" "}
                {previewState.preview.global_parameter_ids.length} parameter(s).
              </p>
              <p className="status-message">
                Fidelity audit:{" "}
                {previewState.preview.import_succeeded
                  ? `${previewState.preview.assignment_rule_count} assignment rule(s), ${previewState.preview.rate_rule_count} rate rule(s), ${previewState.preview.algebraic_rule_count} algebraic rule(s), ${previewState.preview.event_count} event(s).`
                  : `could not fully audit this file (${previewState.preview.import_error_kind}): ${previewState.preview.import_message}. The model is still real and executable -- only the fidelity audit itself is incomplete.`}
              </p>
            </>
          ) : (
            <p className="status-message error" role="alert">
              This file does not compile: {previewState.preview.load_message}
            </p>
          )}
        </section>
      )}

      {previewState.status === "ready" && previewState.preview.load_succeeded && (
        <section className="card" aria-label="Save">
          <h2>3. Save as a new model</h2>
          <p>
            <label>
              Model name{" "}
              <input
                type="text"
                value={modelName}
                onChange={(event) => setModelName(event.target.value)}
                required
              />
            </label>
          </p>
          <p>
            <label>
              Source / reference (optional){" "}
              <input
                type="text"
                value={sourceReference}
                onChange={(event) => setSourceReference(event.target.value)}
              />
            </label>
          </p>
          <p>
            <label>
              Verification notes (optional){" "}
              <textarea
                value={verificationNotes}
                onChange={(event) => setVerificationNotes(event.target.value)}
                rows={2}
              />
            </label>
          </p>
          <button
            type="button"
            className="primary-button"
            disabled={saveState.status === "saving" || !modelName.trim()}
            onClick={handleSave}
          >
            {saveState.status === "saving" ? "Saving…" : "Save imported model"}
          </button>{" "}
          <button type="button" className="secondary-button" onClick={handleChooseDifferentFile}>
            Choose a different file
          </button>
          {saveState.status === "error" && (
            <p className="status-message error" role="alert">
              Couldn&apos;t save this model: {saveState.message}
            </p>
          )}
        </section>
      )}

      <p>
        <RouterLink to={studyUrl} className="back-link">
          Back to {study.title}
        </RouterLink>
      </p>
    </div>
  );
}
