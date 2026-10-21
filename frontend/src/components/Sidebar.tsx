import type { Route } from "../lib/router";
import type { ProjectDetail } from "../types";
import { formatProjectType, NOT_CAPTURED } from "../format";
import { RouterLink } from "./RouterLink";

interface SidebarProps {
  route: Route;
  /** The loaded project, for the "PROJECT MODE" section -- `null` while a
   * project-detail page is loading/erroring, and whenever `route` is not
   * "project-detail". */
  project: ProjectDetail | null;
}

/** The persistent left sidebar ("Context navigation" in Figma). On the "01
 * — All Projects" screen it shows only "All Projects"; once a project is
 * open ("02 — Current Project", node 46:203) it also shows "Current
 * Project" (active) and "Modeling Studies" (a separate, not-yet-built
 * screen -- disabled, never silently dropped) plus the open project's own
 * mode.
 */
export function Sidebar({ route, project }: SidebarProps) {
  const onProjectDetail = route.screen === "project-detail";

  return (
    <nav className="app-sidebar" aria-label="Workbench navigation">
      <span className="sidebar-section-label">Workbench</span>

      {onProjectDetail ? (
        <RouterLink to="/projects" className="sidebar-nav-item">
          All Projects
        </RouterLink>
      ) : (
        <span className="sidebar-nav-item active" aria-current="page">
          All Projects
        </span>
      )}

      {onProjectDetail && (
        <>
          <span className="sidebar-nav-item active" aria-current="page">
            Current Project
          </span>
          <span
            className="sidebar-nav-item disabled"
            aria-disabled="true"
            title="Not available in this increment"
          >
            Modeling Studies
          </span>
        </>
      )}

      {onProjectDetail && project && (
        <div className="sidebar-project-mode">
          <span className="sidebar-section-label">Project mode</span>
          <span className="sidebar-project-mode-value">
            {formatProjectType(project.project_type)}
          </span>
          <span
            className={
              project.biological_context_summary
                ? "sidebar-project-mode-context"
                : "sidebar-project-mode-context not-captured"
            }
          >
            {project.biological_context_summary ?? NOT_CAPTURED}
          </span>
        </div>
      )}
    </nav>
  );
}
