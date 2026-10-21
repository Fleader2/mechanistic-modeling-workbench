import type { ProjectDetail } from "../types";
import { formatProjectType } from "../format";
import { MetadataField } from "./MetadataField";

interface ProjectInformationCardProps {
  project: ProjectDetail;
}

/** The "Project information" card on "02 — Current Project" (Figma node
 * 46:203). Shows the identical field set as the "01 — All Projects" preview
 * panel (ProjectPreviewPanel) -- see docs/16_projects_api_first_increment.md
 * for which fields have a real backing column today. "Edit project" is a
 * creation/editing action, out of scope for this increment -- disabled,
 * never silently dropped.
 */
export function ProjectInformationCard({ project }: ProjectInformationCardProps) {
  return (
    <section className="card info-card" aria-label="Project information">
      <h2>Project information</h2>
      <div className="metadata-field-grid">
        <MetadataField label="Investigator" value={null} />
        <MetadataField label="Start date" value={null} />
        <MetadataField label="Project mode" value={formatProjectType(project.project_type)} />
        <MetadataField label="Organism / strain" value={project.strain_genotype_notes} />
        <MetadataField label="Scope / condition" value={null} />
        <MetadataField label="Knowledge sources" value={null} />
      </div>
      <MetadataField label="Objective" value={null} />
      <div className="info-card-actions">
        <button type="button" className="secondary-button" disabled title="Not available yet">
          Edit project
        </button>
      </div>
    </section>
  );
}
