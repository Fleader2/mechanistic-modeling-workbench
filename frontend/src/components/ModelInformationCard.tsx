import type { ModelDetail } from "../types";
import { formatModelSourceType, formatModelStatus } from "../format";
import { MetadataField } from "./MetadataField";

interface ModelInformationCardProps {
  model: ModelDetail;
}

/** The "Overview" tab's own card on "05 — Model Overview" (Figma node
 * 46:564) -- named "Model information" here, not "Model overview" (Figma's
 * own card title), to avoid confusing it with the "Overview" *tab* it lives
 * under.
 *
 * Figma's own reference card shows "Scope" / "Structure" / "Parameters"
 * summary counts (e.g. "2 compartments · 18 species · 12 reactions") and a
 * "Construction: ... Calibration: ... Validation: ..." sentence -- no
 * species/reaction/parameter content, and no construction/calibration/
 * validation claim, is ever persisted for a `Model` anywhere in this
 * schema (see docs/19_model_overview_increment.md's "durability audit"),
 * so none of that is shown here. This card instead shows only the real
 * columns: `source_type`, `status`, `artifact_reference`, `notes`.
 *
 * `status` is explicitly captioned as a *recorded lifecycle* status, not a
 * scientific-readiness verdict -- Figma's own "Ready"/"Draft" labels blur
 * that distinction; this increment's own instruction is to keep it clear.
 * "Validate model" / "Export Antimony" / "Save new version" are
 * scientific-execution/export/editing actions, all out of scope --
 * disabled, never silently dropped.
 */
export function ModelInformationCard({ model }: ModelInformationCardProps) {
  return (
    <section className="card info-card" aria-label="Model information">
      <h2>Model information</h2>
      <div className="metadata-field-grid">
        <MetadataField label="Source type" value={formatModelSourceType(model.source_type)} />
        <MetadataField label="Status (recorded)" value={formatModelStatus(model.status)} />
      </div>
      <p className="status-caveat">
        "Status" reflects this model's recorded lifecycle status, not a scientific-readiness,
        calibration, or validation verdict -- none of that is tracked by this schema.
      </p>
      <MetadataField label="Artifact reference" value={model.artifact_reference} />
      <MetadataField label="Notes" value={model.notes} />
      <div className="info-card-actions">
        <button type="button" className="secondary-button" disabled title="Not available yet">
          Validate model
        </button>
        <button type="button" className="secondary-button" disabled title="Not available yet">
          Export Antimony
        </button>
        <button type="button" className="secondary-button" disabled title="Not available yet">
          Save new version
        </button>
      </div>
    </section>
  );
}
