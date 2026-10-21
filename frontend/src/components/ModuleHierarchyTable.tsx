import { Fragment, useRef, useState } from "react";
import type { BoundaryPortItem, ModuleSetDraftValidationFindingItem, ModuleSetMemberItem } from "../types";
import {
  formatBoundaryResolutionStatus,
  formatBoundaryTreatmentType,
  formatExecutionStatus,
  formatPortDirection,
  NOT_CAPTURED,
} from "../format";
import { ApiRequestError } from "../api/client";

interface ModuleHierarchyTableProps {
  members: ModuleSetMemberItem[];
  fetchBoundaryPorts: (memberId: string) => Promise<BoundaryPortItem[]>;
  /** Manual-Editing increment (docs/23): when present, renders rename controls and
   * per-reaction "move to a sibling" controls. Omitted entirely on the read-only reopened
   * version screen. */
  editable?: {
    findings: ModuleSetDraftValidationFindingItem[];
    onRename: (memberId: string, displayName: string) => void;
    onMoveReaction: (reactionId: string, toMemberId: string) => void;
  };
}

type PortsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "invalidated" }
  | { status: "ready"; ports: BoundaryPortItem[] };

/** The shared "inspect hierarchy/boundaries" table for a draft (`ModuleSetDraftScreen`,
 * possibly editable) and a reopened saved version (`ModuleSetVersionScreen`, always
 * read-only).
 *
 * Hierarchy is never stored on `ModuleSetMember`/`ModuleSetDraftMember` themselves (see
 * docs/20 §6/§21): each member only carries its own resolved module's
 * `depth`/`parent_model_module_id`, so the tree shown here is derived purely by indenting on
 * `depth` and, where a member's own `parent_model_module_id` matches another member's
 * `model_module_id` in this same list, implying containment. A reaction may only ever be
 * moved to a *sibling* (same `parent_model_module_id`) -- the server enforces this too
 * (docs/23's "hierarchy rule"); the move control here only ever offers siblings in the first
 * place, so an attempted out-of-group move is never even presentable, not merely rejected.
 *
 * `display_name` falls back to the real `module_id` (the content-addressed id the harness
 * itself assigned) until the first rename -- never an invented label.
 */
export function ModuleHierarchyTable({
  members,
  fetchBoundaryPorts,
  editable,
}: ModuleHierarchyTableProps) {
  const [expandedMemberId, setExpandedMemberId] = useState<string | null>(null);
  const [portsByMember, setPortsByMember] = useState<Record<string, PortsState>>({});
  const renameInputs = useRef<Record<string, HTMLInputElement | null>>({});

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
          if (error instanceof ApiRequestError && error.status === 409) {
            setPortsByMember((prev) => ({ ...prev, [member.id]: { status: "invalidated" } }));
            return;
          }
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
          <th scope="col">Reactions</th>
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
          const siblings = sorted.filter(
            (m) => m.id !== member.id && m.parent_model_module_id === member.parent_model_module_id,
          );
          const emptyModuleFinding = editable?.findings.find(
            (f) => f.code === "EMPTY_MODULE" && f.member_id === member.id,
          );
          return (
            <Fragment key={member.id}>
              <tr>
                <td>
                  <div
                    className="module-hierarchy-row"
                    style={{ paddingLeft: `${member.depth * 20}px` }}
                  >
                    {editable ? (
                      <>
                        <input
                          type="text"
                          className="module-rename-input"
                          defaultValue={member.display_name ?? ""}
                          placeholder={member.module_id}
                          ref={(el) => {
                            renameInputs.current[member.id] = el;
                          }}
                        />
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => {
                            const value = renameInputs.current[member.id]?.value.trim();
                            if (value) editable.onRename(member.id, value);
                          }}
                        >
                          Rename
                        </button>
                      </>
                    ) : (
                      <span className="module-identity-id">
                        {member.display_name ?? member.module_id}
                      </span>
                    )}
                    {!parentIncluded && (
                      <span className="not-captured module-hierarchy-orphan-note">
                        (parent module not included in this set)
                      </span>
                    )}
                    {member.membership_edited && (
                      <span className="module-edited-badge">edited</span>
                    )}
                  </div>
                </td>
                <td>
                  <div className="module-hierarchy-reactions">
                    {member.reaction_component_ids.length === 0 && (
                      <span className="not-captured">none</span>
                    )}
                    {member.reaction_component_ids.map((rid) => (
                      <span key={rid} className="reaction-chip">
                        {rid}
                        {editable && siblings.length > 0 && (
                          <select
                            aria-label={`Move reaction ${rid} to a sibling module`}
                            value=""
                            onChange={(event) => {
                              const target = event.currentTarget.value;
                              if (target) editable.onMoveReaction(rid, target);
                              event.currentTarget.value = "";
                            }}
                          >
                            <option value="">Move to…</option>
                            {siblings.map((sibling) => (
                              <option key={sibling.id} value={sibling.id}>
                                {sibling.display_name ?? sibling.module_id}
                              </option>
                            ))}
                          </select>
                        )}
                      </span>
                    ))}
                    {emptyModuleFinding && (
                      <p className="status-message error" role="alert">
                        {emptyModuleFinding.message}
                      </p>
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
                  <td colSpan={4} className="module-hierarchy-ports-cell">
                    {portsState?.status === "loading" && (
                      <p className="status-message">Loading boundary ports…</p>
                    )}
                    {portsState?.status === "invalidated" && (
                      <p className="status-message error" role="alert">
                        This module&apos;s reaction membership has been edited. Its boundary
                        ports were derived for its original membership and can&apos;t be shown
                        as still valid -- re-deriving them is not automated in this increment.
                      </p>
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
