// Minimal hand-rolled path router -- no router library exists in this
// project yet (see docs/16_projects_api_first_increment.md's own "no
// component library" precedent), and the four routes this app needs (the
// project list, one project's detail page, one Modeling Study's detail
// page, and one model's overview page) do not justify adding one.
// `parseRoute` is pure and framework-free specifically so it can be
// unit-tested without a DOM (see router.test.ts); `navigate`/`useRoute` are
// the thin browser-integration layer around it, verified live instead.
import { useEffect, useState } from "react";

export type Route =
  | { screen: "projects" }
  | { screen: "project-detail"; projectId: string }
  | { screen: "study-detail"; projectId: string; studyId: string }
  | { screen: "model-detail"; projectId: string; studyId: string; modelId: string };

const MODEL_DETAIL_PATH = /^\/projects\/([^/]+)\/studies\/([^/]+)\/models\/([^/]+)\/?$/;
const STUDY_DETAIL_PATH = /^\/projects\/([^/]+)\/studies\/([^/]+)\/?$/;
const PROJECT_DETAIL_PATH = /^\/projects\/([^/]+)\/?$/;

/** Parses a URL pathname into a `Route`. Any path that isn't a recognized
 * project-detail, study-detail, or model-detail path (including `/`,
 * `/projects`, and anything else unrecognized) falls back to the
 * "projects" screen -- this app has no general-purpose 404 page, only the
 * specific "unknown project id" / "unknown Modeling Study" / "unknown
 * model" states handled inside their own screens. */
export function parseRoute(pathname: string): Route {
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
