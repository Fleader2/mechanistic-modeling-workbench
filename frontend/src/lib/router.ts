// Minimal hand-rolled path router -- no router library exists in this
// project yet (see docs/16_projects_api_first_increment.md's own "no
// component library" precedent), and the routes this app needs do not
// justify adding one. `parseRoute` is pure and framework-free specifically
// so it can be unit-tested without a DOM (see router.test.ts);
// `navigate`/`useRoute` are the thin browser-integration layer around it,
// verified live instead.
import { useEffect, useState } from "react";

export type Route =
  | { screen: "projects" }
  | { screen: "project-detail"; projectId: string }
  | { screen: "study-detail"; projectId: string; studyId: string }
  | { screen: "model-detail"; projectId: string; studyId: string; modelId: string }
  | { screen: "module-sets"; projectId: string; studyId: string }
  | { screen: "module-set-draft"; projectId: string; studyId: string; draftId: string }
  | {
      screen: "module-set-version";
      projectId: string;
      studyId: string;
      moduleSetId: string;
      version: string;
    }
  | {
      screen: "module-set-member-execution";
      projectId: string;
      studyId: string;
      moduleSetId: string;
      version: string;
      memberId: string;
    }
  | { screen: "time-series-datasets"; projectId: string; studyId: string }
  | {
      screen: "time-series-dataset-detail";
      projectId: string;
      studyId: string;
      datasetId: string;
    };

const TIME_SERIES_DATASET_DETAIL_PATH =
  /^\/projects\/([^/]+)\/studies\/([^/]+)\/datasets\/time-series\/([^/]+)\/?$/;
const TIME_SERIES_DATASETS_PATH =
  /^\/projects\/([^/]+)\/studies\/([^/]+)\/datasets\/time-series\/?$/;
const MODULE_SET_MEMBER_EXECUTION_PATH =
  /^\/projects\/([^/]+)\/studies\/([^/]+)\/module-sets\/([^/]+)\/versions\/([^/]+)\/members\/([^/]+)\/execution\/?$/;
const MODULE_SET_VERSION_PATH =
  /^\/projects\/([^/]+)\/studies\/([^/]+)\/module-sets\/([^/]+)\/versions\/([^/]+)\/?$/;
const MODULE_SET_DRAFT_PATH =
  /^\/projects\/([^/]+)\/studies\/([^/]+)\/module-set-drafts\/([^/]+)\/?$/;
const MODULE_SETS_PATH = /^\/projects\/([^/]+)\/studies\/([^/]+)\/module-sets\/?$/;
const MODEL_DETAIL_PATH = /^\/projects\/([^/]+)\/studies\/([^/]+)\/models\/([^/]+)\/?$/;
const STUDY_DETAIL_PATH = /^\/projects\/([^/]+)\/studies\/([^/]+)\/?$/;
const PROJECT_DETAIL_PATH = /^\/projects\/([^/]+)\/?$/;

/** Parses a URL pathname into a `Route`. Any path that isn't one of the
 * recognized patterns (including `/`, `/projects`, and anything else
 * unrecognized) falls back to the "projects" screen -- this app has no
 * general-purpose 404 page, only the specific "unknown ..." states handled
 * inside their own screens. */
export function parseRoute(pathname: string): Route {
  const datasetDetailMatch = TIME_SERIES_DATASET_DETAIL_PATH.exec(pathname);
  if (datasetDetailMatch) {
    return {
      screen: "time-series-dataset-detail",
      projectId: decodeURIComponent(datasetDetailMatch[1]),
      studyId: decodeURIComponent(datasetDetailMatch[2]),
      datasetId: decodeURIComponent(datasetDetailMatch[3]),
    };
  }
  const datasetsMatch = TIME_SERIES_DATASETS_PATH.exec(pathname);
  if (datasetsMatch) {
    return {
      screen: "time-series-datasets",
      projectId: decodeURIComponent(datasetsMatch[1]),
      studyId: decodeURIComponent(datasetsMatch[2]),
    };
  }
  const executionMatch = MODULE_SET_MEMBER_EXECUTION_PATH.exec(pathname);
  if (executionMatch) {
    return {
      screen: "module-set-member-execution",
      projectId: decodeURIComponent(executionMatch[1]),
      studyId: decodeURIComponent(executionMatch[2]),
      moduleSetId: decodeURIComponent(executionMatch[3]),
      version: decodeURIComponent(executionMatch[4]),
      memberId: decodeURIComponent(executionMatch[5]),
    };
  }
  const versionMatch = MODULE_SET_VERSION_PATH.exec(pathname);
  if (versionMatch) {
    return {
      screen: "module-set-version",
      projectId: decodeURIComponent(versionMatch[1]),
      studyId: decodeURIComponent(versionMatch[2]),
      moduleSetId: decodeURIComponent(versionMatch[3]),
      version: decodeURIComponent(versionMatch[4]),
    };
  }
  const draftMatch = MODULE_SET_DRAFT_PATH.exec(pathname);
  if (draftMatch) {
    return {
      screen: "module-set-draft",
      projectId: decodeURIComponent(draftMatch[1]),
      studyId: decodeURIComponent(draftMatch[2]),
      draftId: decodeURIComponent(draftMatch[3]),
    };
  }
  const moduleSetsMatch = MODULE_SETS_PATH.exec(pathname);
  if (moduleSetsMatch) {
    return {
      screen: "module-sets",
      projectId: decodeURIComponent(moduleSetsMatch[1]),
      studyId: decodeURIComponent(moduleSetsMatch[2]),
    };
  }
  const modelMatch = MODEL_DETAIL_PATH.exec(pathname);
  if (modelMatch) {
    return {
      screen: "model-detail",
      projectId: decodeURIComponent(modelMatch[1]),
      studyId: decodeURIComponent(modelMatch[2]),
      modelId: decodeURIComponent(modelMatch[3]),
    };
  }
  const studyMatch = STUDY_DETAIL_PATH.exec(pathname);
  if (studyMatch) {
    return {
      screen: "study-detail",
      projectId: decodeURIComponent(studyMatch[1]),
      studyId: decodeURIComponent(studyMatch[2]),
    };
  }
  const projectMatch = PROJECT_DETAIL_PATH.exec(pathname);
  if (projectMatch) {
    return { screen: "project-detail", projectId: decodeURIComponent(projectMatch[1]) };
  }
  return { screen: "projects" };
}

/** Pushes a new path and notifies any mounted `useRoute` hooks.
 *
 * `history.pushState` does not itself fire `popstate` (only back/forward
 * navigation does), so a `popstate` event is dispatched manually -- the
 * standard workaround for a hand-rolled SPA router. */
export function navigate(path: string): void {
  if (path !== window.location.pathname) {
    window.history.pushState(null, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
}

/** The current route, updated on navigation and on browser back/forward. */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));

  useEffect(() => {
    function onPopState() {
      setRoute(parseRoute(window.location.pathname));
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  return route;
}
