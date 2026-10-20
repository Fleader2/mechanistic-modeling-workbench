import type { ProjectDetail } from "../types";
import { formatProjectType, NOT_CAPTURED } from "../format";

interface PreviewFieldProps {
  label: string;
  value: string | null;
}

function PreviewField({ label, value }: PreviewFieldProps) {
  return (
    <div className="preview-field">
      <span className="preview-field-label">{label}</span>
      <span className={value ? "preview-field-value" : "preview-field-value not-captured"}>
        {value ?? NOT_CAPTURED}
      </span>
    </div>
  );
}

interface ProjectPreviewPanelProps {
  project: ProjectDetail;
}

/** The row-selection preview panel on "01 — All Projects" (Figma node 46:112).
 *
 * Figma's panel shows seven fields: Investigator, Start date, Project mode,
 * Organism / strain, Scope / condition, Knowledge sources, Objective.
 * ``Project`` (app/models/project.py) has a real column for only one of
 * those (project_type). The rest render the explicit "Not captured"
 * placeholder rather than a fabricated value -- in particular, `created_at`
 * is deliberately never shown as "Start date": it records when the
 * Workbench row was created, not when the scientific study began.
 */
export function ProjectPreviewPanel({ project }: ProjectPreviewPanelProps) {
  return (
    <section className="preview-panel" aria-label="Selected project metadata">
      <h2 className="preview-panel-title">
        Selected project · {project.title} · {project.stable_identifier}
      </h2>
      <div className="preview-field-grid">
        <PreviewField label="Investigator" value={null} />
        <PreviewField label="Start date" value={null} />
        <PreviewField label="Project mode" value={formatProjectType(project.project_type)} />
        <PreviewField label="Organism / strain" value={project.strain_genotype_notes} />
        <PreviewField label="Scope / condition" value={null} />
        <PreviewField label="Knowledge sources" value={null} />
      </div>
      <PreviewField label="Objective" value={null} />
    </section>
  );
}
