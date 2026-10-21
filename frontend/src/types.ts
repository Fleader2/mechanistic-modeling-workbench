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

export type ModelSourceType = "GENERATED" | "IMPORTED" | "DERIVED";

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

// Mirrors app/schemas/model.py::ModelDetail -- the "05 — Model Overview"
// screen. Figma's own reference also shows "Scope" / "Structure" /
// "Parameters" summary counts and a "Construction: ... Calibration: ...
// Validation: ..." sentence -- none of that has any backing column anywhere
// in this schema, and is never invented here; see
// docs/19_model_overview_increment.md.
export interface ModelDetail {
  id: string;
  subproject_id: string;
  stable_identifier: string;
  name: string;
  source_type: ModelSourceType;
  status: ModelStatus;
  artifact_reference: string | null;
  parent_model_id: string | null;
  version_label: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// Mirrors app/schemas/model.py::ModelLineage -- the "05 — Model Overview"
// screen's "History" tab. The parent_model_id chain between Model rows is
// the only version lineage this schema durably records (no fine-grained,
// per-parameter change-log table exists, unlike Figma's own richer
// "History" tab mock). A parent/child belonging to a *different* Modeling
// Study is disclosed via the two out-of-scope fields, never silently
// dropped or leaked cross-study.
export interface ModelLineage {
  parent: ModelListItem | null;
  parent_out_of_scope: boolean;
  children: ModelListItem[];
  children_out_of_scope_count: number;
}

// --- Module sets (docs/20_module_set_domain_contract.md, docs/21_module_set_first_increment.md) ---

export type ModuleSetOriginMethod = "AUTOMATED" | "MANUAL" | "MIXED_EDITED";
export type ModuleSetDraftStatus = "OPEN" | "DISCARDED" | "SAVED";
export type ModelModuleExecutionStatus = "VIEW_ONLY" | "REQUIRES_BOUNDARY_REVIEW" | "SIMULATION_READY";
export type ModulePortDirection = "INPUT" | "OUTPUT" | "INPUT_OUTPUT";
export type ModuleBoundaryTreatmentType =
  | "EXTERNALLY_CONTROLLED"
  | "PRESCRIBED_INPUT"
  | "DYNAMIC_COUPLING"
  | "UNRESOLVED";
export type ModuleBoundaryResolutionStatus = "PENDING_REVIEW" | "RESOLVED";

// Mirrors app/schemas/module_set.py::HierarchicalRunSummary -- the "pick a
// run to draft a module set from" list.
export interface HierarchicalRunSummary {
  id: string;
  model_id: string;
  created_at: string;
  module_count: number;
}

// Mirrors app/schemas/module_set.py::ModuleSetMemberItem. No `name` field --
// ModelModule has none today, and this screen never invents one (see
// docs/21). Hierarchy is derived client-side from parent_model_module_id.
export interface ModuleSetMemberItem {
  id: string;
  model_module_id: string;
  module_id: string;
  depth: number;
  parent_model_module_id: string | null;
  execution_status: ModelModuleExecutionStatus;
}

// Mirrors app/schemas/module_set.py::BoundaryPortItem -- the structural
// fact (species_id/direction) and the execution-specific decision
// (treatment_type/initial_value/unit/decided_by/decided_at) both present,
// never conflated.
export interface BoundaryPortItem {
  port_id: string;
  species_id: string;
  direction: ModulePortDirection;
  treatment_type: ModuleBoundaryTreatmentType;
  resolution_status: ModuleBoundaryResolutionStatus;
  initial_value: string | null;
  unit: string | null;
  decided_by: string | null;
  decided_at: string | null;
}

export interface ModuleSetDraftDetail {
  id: string;
  subproject_id: string;
  model_id: string;
  module_set_id: string | null;
  base_run_record_id: string | null;
  base_version_id: string | null;
  origin_method: ModuleSetOriginMethod;
  status: ModuleSetDraftStatus;
  resulting_version_id: string | null;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  members: ModuleSetMemberItem[];
}

export interface ModuleSetVersionDetail {
  id: string;
  module_set_id: string;
  module_set_stable_identifier: string;
  module_set_name: string;
  version: number;
  model_id: string;
  origin_method: ModuleSetOriginMethod;
  generation_run_record_id: string | null;
  base_version_id: string | null;
  version_note: string | null;
  saved_at: string;
  saved_by: string | null;
  members: ModuleSetMemberItem[];
}

export interface ModuleSetSummary {
  id: string;
  stable_identifier: string;
  name: string;
  created_at: string;
  latest_version: number | null;
  latest_version_saved_at: string | null;
  latest_version_origin_method: ModuleSetOriginMethod | null;
}

export interface SaveModuleSetDraftRequest {
  mode: "new_set" | "new_version";
  set_name?: string;
  existing_set_id?: string;
  version_note?: string;
  saved_by?: string;
}
