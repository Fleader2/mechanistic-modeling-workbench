import type { ProjectListItem } from "../types";
import { formatProjectType } from "../format";
import { navigate } from "../lib/router";
import { RouterLink } from "./RouterLink";

interface ProjectsTableProps {
  projects: ProjectListItem[];
  selectedId: string | null;
  onSelect: (project: ProjectListItem) => void;
}

/** The "01 — All Projects" table (Figma node 46:112).
 *
 * Row click (anywhere except the title link) selects a project (populates
 * the preview panel below). The title itself is a real, accessible link to
 * "02 — Current Project"; double-clicking the row also opens it, matching
 * the screen's own copy ("Double-click its name to open it.").
 */
export function ProjectsTable({ projects, selectedId, onSelect }: ProjectsTableProps) {
  return (
    <table className="projects-table">
      <thead>
        <tr>
          <th scope="col">Project</th>
          <th scope="col">Mode</th>
          <th scope="col">Organism / system</th>
          <th scope="col">Studies</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((project) => (
          <tr
            key={project.id}
            className={project.id === selectedId ? "selected" : undefined}
            onClick={() => onSelect(project)}
            onDoubleClick={() => navigate(`/projects/${project.id}`)}
            aria-selected={project.id === selectedId}
          >
            <td>
              <RouterLink to={`/projects/${project.id}`} className="project-link">
                {project.title}
              </RouterLink>
            </td>
            <td>{formatProjectType(project.project_type)}</td>
            <td className={project.biological_context_summary ? undefined : "not-captured"}>
              {project.biological_context_summary ?? "Not captured"}
            </td>
            <td>{project.study_count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
