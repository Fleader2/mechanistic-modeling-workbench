import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  discardModuleSetDraft,
  editModuleSetDraftMember,
  getDraftMemberBoundaryPorts,
  getModelingStudy,
  getModuleSetDraft,
  getModuleSetDraftValidation,
  getProject,
  listModuleSets,
  saveModuleSetDraft,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { formatModuleSetDraftStatus, formatModuleSetOriginMethod } from "../format";
import { navigate } from "../lib/router";
import type {
  ModuleSetDraftDetail,
  ModuleSetDraftValidationFindingItem,
  ModuleSetSummary,
  ProjectDetail,
  SubprojectDetail,
} from "../types";
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

type DraftState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; draft: ModuleSetDraftDetail };

interface ModuleSetDraftScreenProps {
  projectId: string;
  studyId: string;
  draftId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

type SaveForm = null | "new_set" | "new_version";

/** The "05 — Module set draft" screen (Figma node `112:672`/`112:1521`): inspect an unedited
 * draft's own hierarchy and structural/decided boundary state, then either discard it or save
 * it explicitly (as a new set, or a new version of an existing one).
 *
 * Figma's own "Save as new module set"/"Save new set version" are each a separate full-page
 * screen (`112:719`/`112:831`) with a "Confirm save"/"Cancel — return to draft" pair; this
 * increment condenses both into an inline form on this same page instead of two more screens --
 * a deliberate, disclosed simplification (`docs/21_module_set_first_increment.md`), not a
 * functional difference: the same fields (set name or existing set, version note, saved by) are
 * confirmed before the identical `save` call fires.
 */
export function ModuleSetDraftScreen({
  projectId,
  studyId,
  draftId,
  onProjectChange,
  onStudyChange,
}: ModuleSetDraftScreenProps) {
  const [projectState, setProjectState] = useState<ProjectState>({ status: "loading" });
  const [studyState, setStudyState] = useState<StudyState>({ status: "loading" });
  const [draftState, setDraftState] = useState<DraftState>({ status: "loading" });
  const [existingSets, setExistingSets] = useState<ModuleSetSummary[]>([]);
  const [saveForm, setSaveForm] = useState<SaveForm>(null);
  const [setName, setSetName] = useState("");
  const [existingSetId, setExistingSetId] = useState("");
  const [versionNote, setVersionNote] = useState("");
  const [savedBy, setSavedBy] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionInFlight, setActionInFlight] = useState(false);
  const [findings, setFindings] = useState<ModuleSetDraftValidationFindingItem[]>([]);
  const [editError, setEditError] = useState<string | null>(null);
  const guard = useRef(createStaleGuard<string>()).current;

  useEffect(() => {
    const key = `${projectId}/${studyId}/${draftId}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
    setDraftState({ status: "loading" });
    setSaveForm(null);
    setActionError(null);
    setEditError(null);
    setFindings([]);
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

            listModuleSets(projectId, studyId).then((sets) => {
              if (guard.isCurrent(key)) setExistingSets(sets);
            });

            return getModuleSetDraft(projectId, studyId, draftId)
              .then((draft) => {
                if (!guard.isCurrent(key)) return;
                setDraftState({ status: "ready", draft });
                if (draft.status === "OPEN") {
                  getModuleSetDraftValidation(projectId, studyId, draftId).then((result) => {
                    if (guard.isCurrent(key)) setFindings(result);
                  });
                }
              })
              .catch((error: unknown) => {
                if (!guard.isCurrent(key)) return;
                if (error instanceof ApiRequestError && error.status === 404) {
                  setDraftState({ status: "not-found" });
                } else {
                  const message =
                    error instanceof ApiRequestError
                      ? error.message
                      : "An unexpected error occurred.";
                  setDraftState({ status: "error", message });
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
  }, [projectId, studyId, draftId]);

  function handleDiscard() {
    setActionError(null);
    setActionInFlight(true);
    discardModuleSetDraft(projectId, studyId, draftId)
      .then(() => {
        navigate(`/projects/${projectId}/studies/${studyId}/module-sets`);
      })
      .catch((error: unknown) => {
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setActionError(message);
        setActionInFlight(false);
      });
  }

  function handleEdit(memberId: string, patch: { display_name?: string; reaction_component_ids?: string[] }) {
    if (draftState.status !== "ready") return;
    setEditError(null);
    editModuleSetDraftMember(projectId, studyId, draftId, memberId, {
      expected_edit_version: draftState.draft.edit_version,
      ...patch,
    })
      .then((result) => {
        setDraftState({ status: "ready", draft: result.draft });
        setFindings(result.findings);
      })
      .catch((error: unknown) => {
        if (error instanceof ApiRequestError && error.status === 409) {
          setEditError(
            "This draft was edited since you last loaded it — refreshing to the latest state.",
          );
          getModuleSetDraft(projectId, studyId, draftId).then((draft) => {
            setDraftState({ status: "ready", draft });
            if (draft.status === "OPEN") {
              getModuleSetDraftValidation(projectId, studyId, draftId).then(setFindings);
            }
          });
          return;
        }
        setEditError(error instanceof ApiRequestError ? error.message : "An unexpected error occurred.");
      });
  }

  function handleConfirmSave() {
    setActionError(null);
    setActionInFlight(true);
    const body =
      saveForm === "new_set"
        ? { mode: "new_set" as const, set_name: setName, version_note: versionNote || undefined, saved_by: savedBy || undefined }
        : {
            mode: "new_version" as const,
            existing_set_id: existingSetId,
            version_note: versionNote || undefined,
            saved_by: savedBy || undefined,
          };
    saveModuleSetDraft(projectId, studyId, draftId, body)
      .then((version) => {
        navigate(
          `/projects/${projectId}/studies/${studyId}/module-sets/${version.module_set_id}/versions/${version.version}`,
        );
      })
      .catch((error: unknown) => {
        const message =
          error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
        setActionError(message);
        setActionInFlight(false);
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
  const moduleSetsUrl = `/projects/${projectId}/studies/${studyId}/module-sets`;

  if (draftState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="status-message">Loading module-set draft…</p>
      </div>
    );
  }
  if (draftState.status === "not-found" || draftState.status === "error") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          {draftState.status === "not-found"
            ? "This module-set draft could not be found."
            : `Couldn't load this draft: ${draftState.message}`}
        </p>
        <RouterLink to={moduleSetsUrl} className="back-link">
          Back to All modules
        </RouterLink>
      </div>
    );
  }
  const { draft } = draftState;

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}/studies/${studyId}`}>{study.title}</RouterLink> /{" "}
        <RouterLink to={moduleSetsUrl}>All modules</RouterLink> / Module set draft
      </p>
      <h1>Module set draft</h1>
      <p className="screen-subtitle">
        {formatModuleSetOriginMethod(draft.origin_method)} · {formatModuleSetDraftStatus(draft.status)}
        {draft.base_run_record_id && ` · Based on hierarchical run ${draft.base_run_record_id}`}
      </p>
      <p className="not-available-note">
        Working draft — no new set or version created until you explicitly save. Renaming a
        module and moving a reaction to a sibling module are available below; splitting and
        merging modules aren&apos;t available in this increment.
      </p>

      <section className="card" aria-label="Draft modules">
        <h2>Modules ({draft.members.length})</h2>
        <ModuleHierarchyTable
          members={draft.members}
          fetchBoundaryPorts={(memberId) =>
            getDraftMemberBoundaryPorts(projectId, studyId, draftId, memberId)
          }
          editable={
            draft.status === "OPEN"
              ? {
                  findings,
                  onRename: (memberId, displayName) => handleEdit(memberId, { display_name: displayName }),
                  onMoveReaction: (reactionId, toMemberId) => {
                    const target = draft.members.find((m) => m.id === toMemberId);
                    if (!target) return;
                    handleEdit(toMemberId, {
                      reaction_component_ids: [...target.reaction_component_ids, reactionId],
                    });
                  },
                }
              : undefined
          }
        />
      </section>

      {editError && (
        <p className="status-message error" role="alert">
          {editError}
        </p>
      )}

      {findings.length > 0 && (
        <section className="card" aria-label="Validation findings">
          <h2>Before you can save</h2>
          <ul>
            {findings
              .filter((f) => f.code === "UNASSIGNED_REACTION")
              .map((finding) => (
                <li key={`${finding.code}-${finding.reaction_id}`} className="status-message error">
                  {finding.message}
                </li>
              ))}
          </ul>
        </section>
      )}

      {actionError && (
        <p className="status-message error" role="alert">
          {actionError}
        </p>
      )}

      {draft.status === "OPEN" && (
        <section className="card" aria-label="Explicit save choices">
          <h2>Save or discard</h2>
          <div className="info-card-actions">
            <button
              type="button"
              className="secondary-button"
              disabled={actionInFlight}
              onClick={() => setSaveForm(saveForm === "new_set" ? null : "new_set")}
            >
              Save as new module set
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={actionInFlight || existingSets.length === 0}
              title={existingSets.length === 0 ? "No existing module set in this study yet" : undefined}
              onClick={() => setSaveForm(saveForm === "new_version" ? null : "new_version")}
            >
              Save new set version
            </button>
            <button type="button" className="secondary-button" disabled={actionInFlight} onClick={handleDiscard}>
              Discard draft
            </button>
          </div>

          {saveForm === "new_set" && (
            <div className="module-set-save-form">
              <label className="module-set-save-field">
                Set name
                <input
                  type="text"
                  value={setName}
                  onChange={(e) => setSetName(e.target.value)}
                  placeholder="e.g. Expert partition"
                />
              </label>
              <label className="module-set-save-field">
                Version note (optional)
                <input type="text" value={versionNote} onChange={(e) => setVersionNote(e.target.value)} />
              </label>
              <label className="module-set-save-field">
                Saved by (optional)
                <input type="text" value={savedBy} onChange={(e) => setSavedBy(e.target.value)} />
              </label>
              <div className="info-card-actions">
                <button
                  type="button"
                  className="primary-button"
                  disabled={actionInFlight || !setName.trim() || findings.length > 0}
                  onClick={handleConfirmSave}
                >
                  Confirm save
                </button>
                <button type="button" className="secondary-button" onClick={() => setSaveForm(null)}>
                  Cancel — return to draft
                </button>
              </div>
            </div>
          )}

          {saveForm === "new_version" && (
            <div className="module-set-save-form">
              <label className="module-set-save-field">
                Existing set
                <select value={existingSetId} onChange={(e) => setExistingSetId(e.target.value)}>
                  <option value="">Select a module set…</option>
                  {existingSets.map((set) => (
                    <option key={set.id} value={set.id}>
                      {set.stable_identifier} · {set.name}
                      {set.latest_version ? ` (v${set.latest_version})` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="module-set-save-field">
                Version note (optional)
                <input type="text" value={versionNote} onChange={(e) => setVersionNote(e.target.value)} />
              </label>
              <label className="module-set-save-field">
                Saved by (optional)
                <input type="text" value={savedBy} onChange={(e) => setSavedBy(e.target.value)} />
              </label>
              <div className="info-card-actions">
                <button
                  type="button"
                  className="primary-button"
                  disabled={actionInFlight || !existingSetId || findings.length > 0}
                  onClick={handleConfirmSave}
                >
                  Confirm save
                </button>
                <button type="button" className="secondary-button" onClick={() => setSaveForm(null)}>
                  Cancel — return to draft
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {draft.status !== "OPEN" && (
        <p className="not-available-note">
          This draft is {formatModuleSetDraftStatus(draft.status).toLowerCase()} and can no longer
          be saved or discarded.
          {draft.resulting_version_id && (
            <>
              {" "}
              <RouterLink to={`${moduleSetsUrl}`}>View its saved version.</RouterLink>
            </>
          )}
        </p>
      )}
    </div>
  );
}
