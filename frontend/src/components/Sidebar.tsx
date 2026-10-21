import type { Route } from "../lib/router";
import type { ProjectDetail, SubprojectDetail } from "../types";
import { formatProjectType, NOT_CAPTURED } from "../format";
import { RouterLink } from "./RouterLink";

interface SidebarProps {
  route: Route;
  /** The loaded project, for the "PROJECT MODE" section -- `null` while a
   * project-detail or study-detail page is loading/erroring, and whenever
   * `route` is "projects". */
  project: ProjectDetail | null;
  /** The loaded study, for the "Current study" label (Figma node 46:314) --
   * `null` while a study-detail page is loading/erroring, and whenever
   * `route` is not "study-detail". */
  study: SubprojectDetail | null;
}

const STUDY_SCOPED_DISABLED_ITEMS = ["All models", "All datasets", "All modules", "Runs & Results"];

/** The persistent left sidebar ("Context navigation" in Figma). On the "01
 * — All Projects" screen it shows only "All Projects"; once a project is
 * open ("02 — Current Project", node 46:203) it also shows "Current
 * Project" (active) and "Modeling Studies" (a separate, not-yet-built list
 * screen -- disabled, never silently dropped); once a Modeling Study is
 * open ("03 — Modeling Study", node 46:314) it instead shows "Current
 * Project" (a real link back) and "Study overview" (active, this screen),
 * plus Figma's own "All models" / "All datasets" / "All modules" /
 * "Runs & Results" nav items -- none of those screens exist yet, so each is
 * disabled, never silently dropped, matching "Modeling Studies"'s own
 * precedent. Both project-detail and study-detail routes also show the open
 * project's own mode.
 */
export function Sidebar({ route, project, study }: SidebarProps) {
  const onProjectDetail = route.screen === "project-detail";
  const onStudyDetail = route.screen === "study-detail";
  const projectId = onStudyDetail ? route.projectId : null;

  return (
    <nav className="app-sidebar" aria-label="Workbench navigation">
      <span className="sidebar-section-label">Workbench</span>

      {onProjectDetail || onStudyDetail ? (
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

      {onStudyDetail && (
        <>
          <RouterLink to={`/projects/${projectId}`} className="sidebar-nav-item">
            Current Project
          </RouterLink>
          {study && (
            <div className="sidebar-study-scope">
              <span className="sidebar-section-label">Current study</span>
              <span className="sidebar-study-scope-value">{study.title}</span>
            </div>
          )}
          <span className="sidebar-nav-item active" aria-current="page">
            Study overview
          </span>
          {STUDY_SCOPED_DISABLED_ITEMS.map((label) => (
            <span
              key={label}
              className="sidebar-nav-item disabled"
              aria-disabled="true"
              title="Not available in this increment"
            >
              {label}
            </span>
          ))}
        </>
      )}

      {(onProjectDetail || onStudyDetail) && project && (
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
