import type { ModelLineage, ModelListItem } from "../types";
import { formatModelStatus, NOT_CAPTURED } from "../format";
import { RouterLink } from "./RouterLink";

interface ModelLineageCardProps {
  projectId: string;
  studyId: string;
  lineage: ModelLineage;
}

function lineageLabel(item: ModelListItem): string {
  const version = item.version_label ?? NOT_CAPTURED;
  return `${item.name} (${item.stable_identifier}) · ${version} · ${formatModelStatus(item.status)}`;
}

/** The "History" tab's own honest content on "05 — Model Overview" (Figma
 * node 46:564).
 *
 * Figma's own "History" tab mock shows a fine-grained, per-parameter
 * change log -- "Version / event," "Changed by," "Change," "Evidence,"
 * with a named author ("Morgan Lee") and before/after parameter values.
 * No table anywhere in this schema records who changed what, when, with
 * what evidence, at that granularity -- this system has no user/author
 * entity at all. The only version lineage durably recorded is the
 * `parent_model_id` chain between whole `Model` rows, so that -- and
 * nothing richer -- is what this card shows; see
 * docs/19_model_overview_increment.md's "durability audit".
 *
 * A parent/child that exists but belongs to a *different* Modeling Study
 * is disclosed as existing-but-not-shown, never silently omitted (which
 * would misrepresent this model as having no lineage at all) and never
 * linked to directly (which would leak across a study boundary).
 */
export function ModelLineageCard({ projectId, studyId, lineage }: ModelLineageCardProps) {
  const hasNoLineage =
    lineage.parent === null &&
    !lineage.parent_out_of_scope &&
    lineage.children.length === 0 &&
    lineage.children_out_of_scope_count === 0;

  return (
    <section className="card" aria-label="Version history">
      <h2>Version history</h2>
      <p className="not-available-note">
        Figma's richer per-change history (author, evidence, before/after values) isn't tracked by
        this system. Only the recorded parent/child relationship between model versions is shown.
      </p>

      <div className="lineage-section">
        <span className="metadata-field-label">Earlier version</span>
        {lineage.parent && (
          <p className="lineage-item">
            <RouterLink to={`/projects/${projectId}/studies/${studyId}/models/${lineage.parent.id}`}>
              {lineageLabel(lineage.parent)}
            </RouterLink>
          </p>
        )}
        {lineage.parent_out_of_scope && (
          <p className="lineage-item not-captured">
            An earlier version exists outside this Modeling Study (not shown).
          </p>
        )}
        {!lineage.parent && !lineage.parent_out_of_scope && (
          <p className="lineage-item not-captured">No earlier version recorded.</p>
        )}
      </div>

      <div className="lineage-section">
        <span className="metadata-field-label">Later versions</span>
        {lineage.children.length === 0 && lineage.children_out_of_scope_count === 0 && (
          <p className="lineage-item not-captured">No later versions recorded.</p>
        )}
        {lineage.children.map((child) => (
          <p className="lineage-item" key={child.id}>
            <RouterLink to={`/projects/${projectId}/studies/${studyId}/models/${child.id}`}>
              {lineageLabel(child)}
            </RouterLink>
          </p>
        ))}
        {lineage.children_out_of_scope_count > 0 && (
          <p className="lineage-item not-captured">
            {lineage.children_out_of_scope_count} later version
            {lineage.children_out_of_scope_count === 1 ? "" : "s"} exist
            {lineage.children_out_of_scope_count === 1 ? "s" : ""} outside this Modeling Study (not
            shown).
          </p>
        )}
      </div>

      {hasNoLineage && (
        <p className="status-caveat">This model has no recorded earlier or later version.</p>
      )}
    </section>
  );
}
