// Minimal hand-rolled path router -- no router library exists in this
// project yet (see docs/16_projects_api_first_increment.md's own "no
// component library" precedent), and the two routes this app needs
// (the project list, and one project's detail page) do not justify adding
// one. `parseRoute` is pure and framework-free specifically so it can be
// unit-tested without a DOM (see router.test.ts); `navigate`/`useRoute`
// are the thin browser-integration layer around it, verified live instead.
import { useEffect, useState } from "react";

export type Route = { screen: "projects" } | { screen: "project-detail"; projectId: string };

const PROJECT_DETAIL_PATH = /^\/projects\/([^/]+)\/?$/;

/** Parses a URL pathname into a `Route`. Any path that isn't a recognized
 * project-detail path (including `/`, `/projects`, and anything else
 * unrecognized) falls back to the "projects" screen -- this app has no
 * general-purpose 404 page, only the specific "unknown project id" state
 * handled inside the project-detail screen itself. */
export function parseRoute(pathname: string): Route {
  const match = PROJECT_DETAIL_PATH.exec(pathname);
  if (match) {
    return { screen: "project-detail", projectId: decodeURIComponent(match[1]) };
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
