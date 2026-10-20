import { ProjectsListScreen } from "./components/ProjectsListScreen";

/** App shell: persistent header + left sidebar, matching the Figma file's
 * chrome. Only "All Projects" exists as a real nav destination this
 * increment -- every other section of the Figma file is out of scope. */
export function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Mechanistic Modeling Workbench</span>
        <span className="app-header-meta">Local workspace · Scientist</span>
      </header>
      <div className="app-body">
        <nav className="app-sidebar" aria-label="Workbench navigation">
          <span className="sidebar-section-label">Workbench</span>
          <span className="sidebar-nav-item active" aria-current="page">
            All Projects
          </span>
        </nav>
        <main className="app-content">
          <ProjectsListScreen />
        </main>
      </div>
    </div>
  );
}
