import type {
  ModelModuleExecutionStatus,
  ModelSourceType,
  ModelStatus,
  ModuleBoundaryResolutionStatus,
  ModuleBoundaryTreatmentType,
  ModulePortDirection,
  ModuleSetDraftStatus,
  ModuleSetOriginMethod,
  ProjectType,
  ReadinessFindingCode,
  RunStatus,
  SubprojectTaskType,
  WorkflowLifecycleStatus,
} from "./types";

const PROJECT_TYPE_LABELS: Record<ProjectType, string> = {
  MICROBIAL_METABOLISM: "Microbial Metabolism",
  REGULATORY_NETWORK: "Regulatory Networks",
};

export function formatProjectType(projectType: ProjectType): string {
  return PROJECT_TYPE_LABELS[projectType];
}

const TASK_TYPE_LABELS: Record<SubprojectTaskType, string> = {
  BUILD_MODEL: "Build model",
  IMPORT_MODEL: "Import model",
  TEST_MODEL: "Test model",
  CALIBRATE_MODEL: "Calibrate model",
  EXTEND_MODEL: "Extend model",
};

export function formatTaskType(taskType: SubprojectTaskType): string {
  return TASK_TYPE_LABELS[taskType];
}

const WORKFLOW_STATUS_LABELS: Record<WorkflowLifecycleStatus, string> = {
  ACTIVE: "Active",
  COMPLETED: "Completed",
  ON_HOLD: "On hold",
  ARCHIVED: "Archived",
};

export function formatWorkflowStatus(status: WorkflowLifecycleStatus): string {
  return WORKFLOW_STATUS_LABELS[status];
}

const MODEL_STATUS_LABELS: Record<ModelStatus, string> = {
  DRAFT: "Draft",
  ACTIVE: "Active",
  SUPERSEDED: "Superseded",
  ARCHIVED: "Archived",
};

export function formatModelStatus(status: ModelStatus): string {
  return MODEL_STATUS_LABELS[status];
}

const MODEL_SOURCE_TYPE_LABELS: Record<ModelSourceType, string> = {
  GENERATED: "Generated",
  IMPORTED: "Imported",
  DERIVED: "Derived",
};

export function formatModelSourceType(sourceType: ModelSourceType): string {
  return MODEL_SOURCE_TYPE_LABELS[sourceType];
}

const MODULE_SET_ORIGIN_METHOD_LABELS: Record<ModuleSetOriginMethod, string> = {
  AUTOMATED: "Automated",
  MANUAL: "Manual",
  MIXED_EDITED: "Mixed (edited)",
};

export function formatModuleSetOriginMethod(origin: ModuleSetOriginMethod): string {
  return MODULE_SET_ORIGIN_METHOD_LABELS[origin];
}

const MODULE_SET_DRAFT_STATUS_LABELS: Record<ModuleSetDraftStatus, string> = {
  OPEN: "Open",
  DISCARDED: "Discarded",
  SAVED: "Saved",
};

export function formatModuleSetDraftStatus(status: ModuleSetDraftStatus): string {
  return MODULE_SET_DRAFT_STATUS_LABELS[status];
}

const EXECUTION_STATUS_LABELS: Record<ModelModuleExecutionStatus, string> = {
  VIEW_ONLY: "View only",
  REQUIRES_BOUNDARY_REVIEW: "Requires boundary review",
  SIMULATION_READY: "Simulation ready",
};

export function formatExecutionStatus(status: ModelModuleExecutionStatus): string {
  return EXECUTION_STATUS_LABELS[status];
}

const PORT_DIRECTION_LABELS: Record<ModulePortDirection, string> = {
  INPUT: "Input",
  OUTPUT: "Output",
  INPUT_OUTPUT: "Input / output",
};

export function formatPortDirection(direction: ModulePortDirection): string {
  return PORT_DIRECTION_LABELS[direction];
}

const BOUNDARY_TREATMENT_TYPE_LABELS: Record<ModuleBoundaryTreatmentType, string> = {
  EXTERNALLY_CONTROLLED: "Externally controlled",
  PRESCRIBED_INPUT: "Prescribed input",
  DYNAMIC_COUPLING: "Dynamic coupling",
  UNRESOLVED: "Unresolved",
};

export function formatBoundaryTreatmentType(treatment: ModuleBoundaryTreatmentType): string {
  return BOUNDARY_TREATMENT_TYPE_LABELS[treatment];
}

const BOUNDARY_RESOLUTION_STATUS_LABELS: Record<ModuleBoundaryResolutionStatus, string> = {
  PENDING_REVIEW: "Pending review",
  RESOLVED: "Resolved",
};

export function formatBoundaryResolutionStatus(status: ModuleBoundaryResolutionStatus): string {
  return BOUNDARY_RESOLUTION_STATUS_LABELS[status];
}

/** The honest placeholder for a Figma field slot with no backend counterpart,
 * or a real column that happens to be null for this project. Never invented. */
export const NOT_CAPTURED = "Not captured";

const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  PENDING: "Pending",
  RUNNING: "Running",
  REQUIRES_USER_REVIEW: "Requires user review",
  SUCCEEDED: "Succeeded",
  FAILED: "Failed",
};

export function formatRunStatus(status: RunStatus): string {
  return RUN_STATUS_LABELS[status];
}

const READINESS_FINDING_LABELS: Record<ReadinessFindingCode, string> = {
  UNRESOLVED_BOUNDARY_PORT: "An unresolved boundary port remains",
  NO_BOUNDARY_PORTS_DERIVED: "No boundary ports have been derived yet",
};

export function formatReadinessFindingCode(code: ReadinessFindingCode): string {
  return READINESS_FINDING_LABELS[code];
}

/** Every continuous/measured value shown on screen (observed/predicted values, parameter
 * bounds and fixed values, sigma/weight values, dataset sample values, curator-decided initial
 * values) -- never a count, id, index, or revision number, which stay plain integers. Rounds to
 * 3 significant figures and renders in scientific notation (e.g. `16.361616600246265` ->
 * `"1.64e1"`). A non-numeric string (or a null/undefined the caller has not already guarded) is
 * returned unchanged -- this never corrupts a value it cannot safely parse as a number. */
export function formatScientific(value: number | string | null | undefined): string {
  if (value === null || value === undefined) {
    return "";
  }
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }
  if (numeric === 0) {
    return "0e0";
  }
  return numeric.toExponential(2).replace("e+", "e");
}

/** The exact, unrounded counterpart to `formatScientific` -- the full-precision value that
 * display rounds away, with no label of its own (for an inspection view, e.g. an SVG `<title>`
 * tooltip, that already supplies its own context/wording). A numeric-string API field (Decimal
 * as string) is returned exactly as given, never reformatted through a binary float -- the
 * identical "preserve original data" discipline `formatScientific` itself follows. Returns
 * `undefined` (never a rendered "null"/"undefined" string) for a missing value. Display only --
 * never fed back into a calculation. */
export function fullPrecisionValue(value: number | string | null | undefined): string | undefined {
  if (value === null || value === undefined) {
    return undefined;
  }
  return String(value);
}

/** `fullPrecisionValue`, labeled for direct use as a bare `title={...}` attribute (which
 * supplies no context of its own) -- e.g. `<td title={fullPrecisionTitle(x)}>`. */
export function fullPrecisionTitle(value: number | string | null | undefined): string | undefined {
  const full = fullPrecisionValue(value);
  return full === undefined ? undefined : `Full precision: ${full}`;
}
