import type {
  ModelSourceType,
  ModelStatus,
  ProjectType,
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

/** The honest placeholder for a Figma field slot with no backend counterpart,
 * or a real column that happens to be null for this project. Never invented. */
export const NOT_CAPTURED = "Not captured";
