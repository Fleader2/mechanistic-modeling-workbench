import type { MouseEvent, ReactNode } from "react";
import { navigate } from "../lib/router";

interface RouterLinkProps {
  to: string;
  className?: string;
  children: ReactNode;
}

/** A real `<a href>` -- keyboard-focusable, screen-reader-navigable, and
 * usable without JavaScript (ctrl/cmd/shift/middle-click all fall through
 * to normal browser handling) -- that performs client-side navigation only
 * for a plain, unmodified left click. Stops propagation on an intercepted
 * click so an ancestor's own click handler (e.g. a table row's
 * row-selection handler) never also fires for the identical click. */
export function RouterLink({ to, className, children }: RouterLinkProps) {
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    event.stopPropagation();
    navigate(to);
  }

  return (
    <a href={to} className={className} onClick={handleClick}>
      {children}
    </a>
  );
}
