// Mirrors app/schemas/project.py exactly. A field this UI cannot populate
// (no backend column exists) is never added here as an optional string --
// it stays absent from the type, and the component that would show it
// renders an explicit "Not captured" placeholder instead.

export type ProjectType = "MICROBIAL_METABOLISM" | "REGULATORY_NETWORK";

export type WorkflowLifecycleStatus = "ACTIVE" | "COMPLETED" | "ON_HOLD" | "ARCHIVED";

export interface ProjectListItem {
  id: string;
  stable_identifier: string;
  title: string;
  project_type: ProjectType;
  biological_context_summary: string | null;
  study_count: number;
}

export interface ProjectDetail {
  id: string;
  stable_identifier: string;
  title: string;
  description: string | null;
  project_type: ProjectType;
  agent1_organism_id: string | null;
  biological_context_summary: string | null;
  strain_genotype_notes: string | null;
  biological_process: string | null;
  disease: string | null;
  tissue: string | null;
  cell_type: string | null;
  status: WorkflowLifecycleStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export type SubprojectTaskType =
  | "BUILD_MODEL"
  | "IMPORT_MODEL"
  | "TEST_MODEL"
  | "CALIBRATE_MODEL"
  | "EXTEND_MODEL";

export type ModelStatus = "DRAFT" | "ACTIVE" | "SUPERSEDED" | "ARCHIVED";

// Mirrors app/schemas/subproject.py::SubprojectListItem -- the "Modeling
// Studies" table on the "02 — Current Project" screen.
export interface SubprojectListItem {
  id: string;
  title: string;
  objective: string | null;
  model_count: number;
  dataset_count: number;
}

// Mirrors app/schemas/subproject.py::SubprojectDetail -- the "03 — Modeling
// Study" screen. Figma's richer, per-project-type "Study information"
// fields (e.g. "Biological scope" / "Conditions" / "Success criterion" for
// one project, "Tissue / cell type" / "Condition / intervention" / "Seeds"
// for another) have no backing column and are never invented here -- see
// docs/18_modeling_study_increment.md.
export interface SubprojectDetail {
  id: string;
  project_id: string;
  title: string;
  objective: string | null;
  task_type: SubprojectTaskType;
  status: WorkflowLifecycleStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// Mirrors app/schemas/model.py::ModelListItem -- the "03 — Modeling Study"
// screen's "Models" table. Figma's "Construction" and "Calibration /
// validation" columns have no backing column and are never invented here.
export interface ModelListItem {
  id: string;
  stable_identifier: string;
  name: string;
  version_label: string | null;
  status: ModelStatus;
}
