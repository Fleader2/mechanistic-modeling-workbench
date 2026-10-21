import { Fragment, useState } from "react";
import type { BoundaryPortItem, ModuleSetMemberItem } from "../types";
import {
  formatBoundaryResolutionStatus,
  formatBoundaryTreatmentType,
  formatExecutionStatus,
  formatPortDirection,
  NOT_CAPTURED,
} from "../format";

interface ModuleHierarchyTableProps {
  members: ModuleSetMemberItem[];
  fetchBoundaryPorts: (memberId: string) => Promise<BoundaryPortItem[]>;
}

type PortsState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; ports: BoundaryPortItem[] };

/** The shared "inspect hierarchy/boundaries" table for both a draft
 * (`ModuleSetDraftScreen`) and a reopened saved version
 * (`ModuleSetVersionScreen`) -- read-only in both cases.
 *
 * Hierarchy is never stored on `ModuleSetMember`/`ModuleSetDraftMember`
 * themselves (see docs/20 §6/§21): each member only carries its own
 * resolved module's `depth`/`parent_model_module_id`, so the tree shown
 * here is derived purely by indenting on `depth` and, where a member's own
 * `parent_model_module_id` matches another member's `model_module_id` in
 * this same list, implying containment -- never inferred from name (no
 * member has one; see below) or membership-overlap heuristics.
 *
 * No display name is invented: `ModelModule` has no `name` column today, so
 * each row shows its own real `module_id` (the content-addressed id the
 * harness itself assigned) instead of a fabricated label.
 */
export function ModuleHierarchyTable({ members, fetchBoundaryPorts }: ModuleHierarchyTableProps) {
  const [expandedMemberId, setExpandedMemberId] = useState<string | null>(null);
  const [portsByMember, setPortsByMember] = useState<Record<string, PortsState>>({});

  const presentModuleModuleIds = new Set(members.map((m) => m.model_module_id));
  const sorted = [...members].sort(
    (a, b) => a.depth - b.depth || a.module_id.localeCompare(b.module_id),
  );

  function toggleExpand(member: ModuleSetMemberItem) {
    if (expandedMemberId === member.id) {
      setExpandedMemberId(null);
      return;
    }
    setExpandedMemberId(member.id);
    if (!portsByMember[member.id]) {
      setPortsByMember((prev) => ({ ...prev, [member.id]: { status: "loading" } }));
      fetchBoundaryPorts(member.id)
        .then((ports) => {
          setPortsByMember((prev) => ({ ...prev, [member.id]: { status: "ready", ports } }));
        })
        .catch((error: unknown) => {
          const message = error instanceof Error ? error.message : "An unexpected error occurred.";
          setPortsByMember((prev) => ({ ...prev, [member.id]: { status: "error", message } }));
        });
    }
  }

  return (
    <table className="module-hierarchy-table">
      <thead>
        <tr>
          <th scope="col">Module</th>
          <th scope="col">Execution status</th>
          <th scope="col">Boundary ports</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((member) => {
          const parentIncluded =
            member.parent_model_module_id === null ||
            presentModuleModuleIds.has(member.parent_model_module_id);
          const portsState = portsByMember[member.id];
          return (
            <Fragment key={member.id}>
              <tr>
                <td>
                  <div
                    className="module-hierarchy-row"
                    style={{ paddingLeft: `${member.depth * 20}px` }}
                  >
                    <span className="module-identity-id">{member.module_id}</span>
                    {!parentIncluded && (
                      <span className="not-captured module-hierarchy-orphan-note">
                        (parent module not included in this set)
                      </span>
                    )}
                  </div>
                </td>
                <td>{formatExecutionStatus(member.execution_status)}</td>
                <td>
                  <button
                    type="button"
                    className="secondary-button module-hierarchy-toggle"
                    onClick={() => toggleExpand(member)}
                  >
                    {expandedMemberId === member.id ? "Hide" : "Inspect"}
                  </button>
                </td>
              </tr>
              {expandedMemberId === member.id && (
                <tr>
                  <td colSpan={3} className="module-hierarchy-ports-cell">
                    {portsState?.status === "loading" && (
                      <p className="status-message">Loading boundary ports…</p>
                    )}
                    {portsState?.status === "error" && (
                      <p className="status-message error" role="alert">
                        Couldn&apos;t load boundary ports: {portsState.message}
                      </p>
                    )}
                    {portsState?.status === "ready" && portsState.ports.length === 0 && (
                      <p className="status-message">
                        No boundary ports derived yet for this module.
                      </p>
                    )}
                    {portsState?.status === "ready" && portsState.ports.length > 0 && (
                      <table className="boundary-ports-table">
                        <thead>
                          <tr>
                            <th scope="col">Species (structural)</th>
                            <th scope="col">Direction (structural)</th>
                            <th scope="col">Treatment (decided)</th>
                            <th scope="col">Resolution</th>
                            <th scope="col">Initial value</th>
                            <th scope="col">Decided by</th>
                          </tr>
                        </thead>
                        <tbody>
                          {portsState.ports.map((port) => (
                            <tr key={port.port_id}>
                              <td>{port.species_id}</td>
                              <td>{formatPortDirection(port.direction)}</td>
                              <td>{formatBoundaryTreatmentType(port.treatment_type)}</td>
                              <td>{formatBoundaryResolutionStatus(port.resolution_status)}</td>
                              <td className={port.initial_value ? undefined : "not-captured"}>
                                {port.initial_value ?? NOT_CAPTURED}
                                {port.initial_value && port.unit ? ` ${port.unit}` : ""}
                              </td>
                              <td className={port.decided_by ? undefined : "not-captured"}>
                                {port.decided_by ?? NOT_CAPTURED}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
