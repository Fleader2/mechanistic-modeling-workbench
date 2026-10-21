import { useCallback, useState } from "react";
import { useRoute } from "./lib/router";
import type { ProjectDetail } from "./types";
import { ProjectsListScreen } from "./components/ProjectsListScreen";
import { ProjectDetailScreen } from "./components/ProjectDetailScreen";
import { Sidebar } from "./components/Sidebar";

/** App shell: persistent header + left sidebar, matching the Figma file's
 * chrome. Routes between "01 — All Projects" and "02 — Current Project"
 * (see src/lib/router.ts) -- every other section of the Figma file remains
 * out of scope. */
export function App() {
  const route = useRoute();
  // Lifted out of ProjectDetailScreen so the sidebar's "PROJECT MODE"
  // section (a sibling, not a descendant, of that screen) can show it.
  const [sidebarProject, setSidebarProject] = useState<ProjectDetail | null>(null);
  const handleProjectChange = useCallback((project: ProjectDetail | null) => {
    setSidebarProject(project);
  }, []);

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Mechanistic Modeling Workbench</span>
        <span className="app-header-meta">Local workspace · Scientist</span>
      </header>
      <div className="app-body">
        <Sidebar route={route} project={route.screen === "project-detail" ? sidebarProject : null} />
        <main className="app-content">
          {route.screen === "projects" && <ProjectsListScreen />}
          {route.screen === "project-detail" && (
            <ProjectDetailScreen projectId={route.projectId} onProjectChange={handleProjectChange} />
          )}
        </main>
      </div>
    </div>
  );
}
