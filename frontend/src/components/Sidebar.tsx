import type { Route } from "../lib/router";
import type { ProjectDetail, SubprojectDetail } from "../types";
import { formatProjectType, NOT_CAPTURED } from "../format";
import { RouterLink } from "./RouterLink";

interface SidebarProps {
  route: Route;
  /** The loaded project, for the "PROJECT MODE" section -- `null` while a
   * project-detail, study-detail, or model-detail page is loading/erroring,
   * and whenever `route` is "projects". */
  project: ProjectDetail | null;
  /** The loaded study, for the "Current study" label (Figma node 46:314) --
   * `null` while a study-detail or model-detail page is loading/erroring,
   * and whenever `route` is "projects" or "project-detail". */
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
 * precedent.
 *
 * On a model's own overview ("05 — Model Overview", node 46:564), "Study
 * overview" becomes a real link back (not active -- there is no model-list
 * screen between it and this page) and the same four items stay disabled.
 * Figma's own prototype instead highlights "All models" as the active
 * section for a model page -- a deliberate deviation here, since that
 * presumes the "All models" list screen exists as a real navigational
 * step above the model, which this increment does not build; marking an
 * unbuilt, disabled destination "active" would be confusing, not helpful.
 * See docs/19_model_overview_increment.md.
 *
 * All three detail routes show the open project's own mode.
 */
export function Sidebar({ route, project, study }: SidebarProps) {
  const onProjectDetail = route.screen === "project-detail";
  const onStudyDetail = route.screen === "study-detail";
  const onModelDetail = route.screen === "model-detail";
  const studyScoped = onStudyDetail || onModelDetail;
  const projectId = studyScoped ? route.projectId : null;
  const studyId = onModelDetail ? route.studyId : null;

  return (
    <nav className="app-sidebar" aria-label="Workbench navigation">
      <span className="sidebar-section-label">Workbench</span>

      {onProjectDetail || studyScoped ? (
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

      {studyScoped && (
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
          {onStudyDetail ? (
            <span className="sidebar-nav-item active" aria-current="page">
              Study overview
            </span>
          ) : (
            <RouterLink to={`/projects/${projectId}/studies/${studyId}`} className="sidebar-nav-item">
              Study overview
            </RouterLink>
          )}
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

      {(onProjectDetail || studyScoped) && project && (
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
