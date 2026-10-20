import type { ProjectListItem } from "../types";
import { formatProjectType } from "../format";

interface ProjectsTableProps {
  projects: ProjectListItem[];
  selectedId: string | null;
  onSelect: (project: ProjectListItem) => void;
}

/** The "01 — All Projects" table (Figma node 46:112).
 *
 * Row click selects a project (populates the preview panel below). Opening
 * a project via double-click is out of this increment's scope -- see the
 * static note ProjectsListScreen renders under this table -- so no
 * double-click handler is wired here.
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
            aria-selected={project.id === selectedId}
          >
            <td>{project.title}</td>
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
