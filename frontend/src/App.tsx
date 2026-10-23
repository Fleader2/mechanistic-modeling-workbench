import { useCallback, useState } from "react";
import { useRoute } from "./lib/router";
import type { ProjectDetail, SubprojectDetail } from "./types";
import { ProjectsListScreen } from "./components/ProjectsListScreen";
import { ProjectDetailScreen } from "./components/ProjectDetailScreen";
import { StudyDetailScreen } from "./components/StudyDetailScreen";
import { ModelOverviewScreen } from "./components/ModelOverviewScreen";
import { ModuleSetsListScreen } from "./components/ModuleSetsListScreen";
import { ModuleSetDraftScreen } from "./components/ModuleSetDraftScreen";
import { ModuleSetVersionScreen } from "./components/ModuleSetVersionScreen";
import { ModuleSetMemberExecutionScreen } from "./components/ModuleSetMemberExecutionScreen";
import { TimeSeriesDatasetsListScreen } from "./components/TimeSeriesDatasetsListScreen";
import { TimeSeriesDatasetDetailScreen } from "./components/TimeSeriesDatasetDetailScreen";
import { AliasMappingScreen } from "./components/AliasMappingScreen";
import { CalibrationJobsListScreen } from "./components/CalibrationJobsListScreen";
import { CalibrationJobScreen } from "./components/CalibrationJobScreen";
import { Sidebar } from "./components/Sidebar";

/** App shell: persistent header + left sidebar, matching the Figma file's
 * chrome. Routes between "01 — All Projects," "02 — Current Project,"
 * "03 — Modeling Study," "05 — Model Overview," and the module-set
 * draft/save/catalog screens (see src/lib/router.ts) -- every other
 * section of the Figma file remains out of scope. */
export function App() {
  const route = useRoute();
  // Lifted out of every detail screen so the sidebar's "PROJECT MODE" and
  // "Current study" sections (siblings, not descendants, of any of them)
  // can show them.
  const [sidebarProject, setSidebarProject] = useState<ProjectDetail | null>(null);
  const [sidebarStudy, setSidebarStudy] = useState<SubprojectDetail | null>(null);
  const handleProjectChange = useCallback((project: ProjectDetail | null) => {
    setSidebarProject(project);
  }, []);
  const handleStudyChange = useCallback((study: SubprojectDetail | null) => {
    setSidebarStudy(study);
  }, []);
  const studyScopedScreens: Array<typeof route.screen> = [
    "project-detail",
    "study-detail",
    "model-detail",
    "module-sets",
    "module-set-draft",
    "module-set-version",
    "module-set-member-execution",
    "time-series-datasets",
    "time-series-dataset-detail",
    "dataset-model-alias-mapping",
    "calibration-jobs",
    "calibration-job-detail",
  ];
  const showProjectMode = studyScopedScreens.includes(route.screen);
  const showStudyScope = route.screen !== "projects" && route.screen !== "project-detail";

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
          {route.screen === "module-sets" && (
            <ModuleSetsListScreen
              projectId={route.projectId}
              studyId={route.studyId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
          {route.screen === "module-set-draft" && (
            <ModuleSetDraftScreen
              projectId={route.projectId}
              studyId={route.studyId}
              draftId={route.draftId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
          {route.screen === "module-set-version" && (
            <ModuleSetVersionScreen
              projectId={route.projectId}
              studyId={route.studyId}
              moduleSetId={route.moduleSetId}
              version={route.version}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
          {route.screen === "module-set-member-execution" && (
            <ModuleSetMemberExecutionScreen
              projectId={route.projectId}
              studyId={route.studyId}
              moduleSetId={route.moduleSetId}
              version={route.version}
              memberId={route.memberId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
          {route.screen === "time-series-datasets" && (
            <TimeSeriesDatasetsListScreen
              projectId={route.projectId}
              studyId={route.studyId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
          {route.screen === "time-series-dataset-detail" && (
            <TimeSeriesDatasetDetailScreen
              projectId={route.projectId}
              studyId={route.studyId}
              datasetId={route.datasetId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
          {route.screen === "dataset-model-alias-mapping" && (
            <AliasMappingScreen
              projectId={route.projectId}
              studyId={route.studyId}
              datasetId={route.datasetId}
              modelId={route.modelId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
          {route.screen === "calibration-jobs" && (
            <CalibrationJobsListScreen
              projectId={route.projectId}
              studyId={route.studyId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
          {route.screen === "calibration-job-detail" && (
            <CalibrationJobScreen
              projectId={route.projectId}
              studyId={route.studyId}
              jobId={route.jobId}
              onProjectChange={handleProjectChange}
              onStudyChange={handleStudyChange}
            />
          )}
        </main>
      </div>
    </div>
  );
}
