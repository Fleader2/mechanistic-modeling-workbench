import { useCallback, useState } from "react";
import { useRoute } from "./lib/router";
import type { ProjectDetail, SubprojectDetail } from "./types";
import { ProjectsListScreen } from "./components/ProjectsListScreen";
import { ProjectDetailScreen } from "./components/ProjectDetailScreen";
import { StudyDetailScreen } from "./components/StudyDetailScreen";
import { ModelOverviewScreen } from "./components/ModelOverviewScreen";
import { Sidebar } from "./components/Sidebar";

/** App shell: persistent header + left sidebar, matching the Figma file's
 * chrome. Routes between "01 — All Projects," "02 — Current Project,"
 * "03 — Modeling Study," and "05 — Model Overview" (see src/lib/router.ts)
 * -- every other section of the Figma file remains out of scope. */
export function App() {
  const route = useRoute();
  // Lifted out of ProjectDetailScreen/StudyDetailScreen/ModelOverviewScreen
  // so the sidebar's "PROJECT MODE" and "Current study" sections (siblings,
  // not descendants, of any of those screens) can show them.
  const [sidebarProject, setSidebarProject] = useState<ProjectDetail | null>(null);
  const [sidebarStudy, setSidebarStudy] = useState<SubprojectDetail | null>(null);
  const handleProjectChange = useCallback((project: ProjectDetail | null) => {
    setSidebarProject(project);
  }, []);
  const handleStudyChange = useCallback((study: SubprojectDetail | null) => {
    setSidebarStudy(study);
  }, []);
  const showProjectMode =
    route.screen === "project-detail" || route.screen === "study-detail" || route.screen === "model-detail";
  const showStudyScope = route.screen === "study-detail" || route.screen === "model-detail";

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Mechanistic Modeling Workbench</span>
        <span className="app-header-meta">Local workspace · Scientist</span>
      </header>
      <div className="app-body">
        <Sidebar
          route={route}
          project={showProjectMode ? sidebarProject : null}
          study={showStudyScope ? sidebarStudy : null}
        />
        <main className="app-content">
          {route.screen === "projects" && <ProjectsListScreen />}
          {route.screen === "project-detail" && (
            <ProjectDetailScreen projectId={route.projectId} onProjectChange={handleProjectChange} />
          )}
          {route.screen === "study-detail" && (
            <StudyDetailScreen
              projectId={route.projectId}
              studyId={route.studyId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
          {route.screen === "model-detail" && (
            <ModelOverviewScreen
              projectId={route.projectId}
              studyId={route.studyId}
              modelId={route.modelId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
        </main>
      </div>
    </div>
  );
}
