import type { SubprojectDetail } from "../types";
import { formatTaskType, formatWorkflowStatus } from "../format";
import { MetadataField } from "./MetadataField";

interface StudyInformationCardProps {
  study: SubprojectDetail;
}

/** The "Study information" card on "03 — Modeling Study" (Figma node
 * 46:314). Figma's own reference shows additional, per-project-type fields
 * here (e.g. "Biological scope" / "Conditions" / "Success criterion" for
 * one project, "Tissue / cell type" / "Condition / intervention" / "Seeds"
 * for another) -- those have no backing `Subproject` column, and unlike the
 * project-level fields `ProjectInformationCard` discloses as a fixed
 * "Not captured" set, there is no single honest fixed label to show here
 * either (which label would even apply depends on the project's domain,
 * which this schema does not record). Showing only the columns that are
 * real (`objective`, `task_type`, `status`, `notes`) is the honest choice;
 * see docs/18_modeling_study_increment.md. "Edit Study" is a
 * creation/editing action, out of scope for this increment -- disabled,
 * never silently dropped.
 */
export function StudyInformationCard({ study }: StudyInformationCardProps) {
  return (
    <section className="card info-card" aria-label="Study information">
      <h2>Study information</h2>
      <div className="metadata-field-grid">
        <MetadataField label="Task type" value={formatTaskType(study.task_type)} />
        <MetadataField label="Status" value={formatWorkflowStatus(study.status)} />
      </div>
      <MetadataField label="Objective" value={study.objective} />
      <MetadataField label="Notes" value={study.notes} />
      <div className="info-card-actions">
        <button type="button" className="secondary-button" disabled title="Not available yet">
          Edit Study
        </button>
      </div>
    </section>
  );
}
