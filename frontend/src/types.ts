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

// Mirrors app/schemas/module_set.py::ModuleSetMemberItem. `display_name` is
// `null` until the Manual-Editing increment's own rename edit ever touches
// it (docs/23) -- never invented otherwise. Hierarchy is derived
// client-side from parent_model_module_id.
export interface ModuleSetMemberItem {
  id: string;
  model_module_id: string;
  module_id: string;
  depth: number;
  parent_model_module_id: string | null;
  execution_status: ModelModuleExecutionStatus;
  display_name: string | null;
  reaction_component_ids: string[];
  membership_edited: boolean;
}

// Mirrors app/schemas/module_set.py::ModuleSetDraftMemberItem -- a draft
// member's own richer, editable view (docs/23).
export interface ModuleSetDraftMemberItem extends ModuleSetMemberItem {
  original_reaction_component_ids: string[];
}

// Mirrors app/schemas/module_set.py::ModuleSetDraftValidationFindingItem.
export type ModuleSetDraftValidationFindingCode = "UNASSIGNED_REACTION" | "EMPTY_MODULE";

export interface ModuleSetDraftValidationFindingItem {
  code: ModuleSetDraftValidationFindingCode;
  message: string;
  reaction_id: string | null;
  member_id: string | null;
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
  edit_version: number;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  members: ModuleSetDraftMemberItem[];
}

export interface ModuleSetDraftValidationResult {
  draft: ModuleSetDraftDetail;
  findings: ModuleSetDraftValidationFindingItem[];
}

export interface EditModuleSetDraftMemberRequest {
  expected_edit_version: number;
  display_name?: string;
  reaction_component_ids?: string[];
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

// --- Module-Set Edited-Module Materialization increment, Phase B: boundary review,
// readiness, and simulation for one saved module-set version's own member
// (docs/24_module_set_execution_increment.md). ---

export type RunStatus = "PENDING" | "RUNNING" | "REQUIRES_USER_REVIEW" | "SUCCEEDED" | "FAILED";

// Mirrors app/schemas/module_set_execution.py::ModuleSetMemberBoundaryPortItem.
// A genuinely separate, execution-scoped boundary port from `BoundaryPortItem`
// above (its own table, its own review/decision lifecycle) -- never conflated
// with the module-level `ModuleBoundaryPort` rows that table mirrors.
export interface ModuleSetMemberBoundaryPortItem {
  id: string;
  species_id: string;
  direction: ModulePortDirection;
  treatment_type: ModuleBoundaryTreatmentType;
  resolution_status: ModuleBoundaryResolutionStatus;
  initial_value: string | null;
  unit: string | null;
  decided_by: string | null;
  decided_at: string | null;
}

export type ReadinessFindingCode = "UNRESOLVED_BOUNDARY_PORT" | "NO_BOUNDARY_PORTS_DERIVED";

export interface ReadinessFindingItem {
  code: ReadinessFindingCode;
  message: string;
  species_id: string | null;
  direction: string | null;
}

// Mirrors app/schemas/module_set_execution.py::ModuleSetMemberReviewDetail.
// `ready` never claims whole-model coverage or biological validity -- only
// that every derived candidate has an explicit decision (docs/24's own
// explicit disclosure).
export interface ModuleSetMemberReviewDetail {
  id: string;
  module_set_member_id: string;
  review_version: number;
  derived_at: string | null;
  ports: ModuleSetMemberBoundaryPortItem[];
  findings: ReadinessFindingItem[];
  ready: boolean;
}

export interface SubmitBoundaryDecisionRequest {
  expected_review_version: number;
  treatment_type: ModuleBoundaryTreatmentType;
  initial_value?: string;
  unit?: string;
  decided_by?: string;
}

export interface SubmitModuleSetSimulationRequest {
  expected_review_version: number;
  saved_by?: string;
}

// Mirrors app/schemas/module_set_execution.py::ModuleSetSimulationRunItem.
// `module_handoff_summary`/`lineage`/`agent3_report` are present only once
// the run has reached a terminal status -- labeled explicitly as simulation
// output, never calibration or validation.
export interface ModuleSetSimulationRunItem {
  id: string;
  status: RunStatus;
  module_set_member_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  result_summary: string | null;
  error_summary: string | null;
  module_handoff_summary: Record<string, unknown> | null;
  lineage: Record<string, unknown> | null;
  agent3_report: Record<string, unknown> | null;
}

// Whole-Model Experimental-Scenario Evaluation increment (docs/33). Mirrors
// app/schemas/calibration_scenario_evaluation.py. Prediction only, never fitting.

export interface SubmitScenarioEvaluationRequest {
  condition_id?: string | null;
  candidate_parameter_values?: Record<string, string>;
  solver_settings?: Record<string, unknown> | null;
  saved_by?: string | null;
}

export interface ObservedVsPredictedRow {
  row_id: string;
  output_id: string;
  column_name: string | null;
  unit: string | null;
  observed: number | null;
  predicted: number;
}

export interface ScenarioEvaluationRunItem {
  id: string;
  status: RunStatus;
  calibration_experiment_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  result_summary: string | null;
  error_summary: string | null;
  evaluation_status: string | null;
  validation_errors: string[] | null;
  solver_message: string | null;
  observed_vs_predicted: ObservedVsPredictedRow[] | null;
}

// Mirrors app/schemas/time_series_dataset.py (Downloadable Two-Tab Excel Template increment).
// A "finding" is never a reason a save is blocked -- only a malformed workbook (rejected with
// a 422 before anything is saved) is. See docs/25_time_series_dataset_import_increment.md.

export type MeasurementValueStatus =
  | "MEASURED"
  | "MISSING"
  | "NOT_APPLICABLE"
  | "UNKNOWN"
  | "UNRECOGNIZED";

export interface TimeSeriesFindingItem {
  code: string;
  severity: "BLOCKING" | "INFO";
  message: string;
  field: string | null;
  column_name: string | null;
  row_index: number | null;
}

export interface TimeSeriesConditionLegendItem {
  condition_id: string;
  description: string | null;
}

export interface TimeSeriesMeasurementColumnItem {
  column_name: string;
  display_order: number;
  unit: string | null;
  description: string | null;
  declared_in_metadata: boolean;
}

export interface TimeSeriesMeasurementValueItem {
  status: MeasurementValueStatus;
  value: number | null;
  raw: string | null;
}

export interface TimeSeriesDataRowItem {
  row_index: number;
  sample_id: string | null;
  condition_id: string | null;
  biological_replicate: string | null;
  technical_replicate: string | null;
  time_status: MeasurementValueStatus;
  time_value: number | null;
  time_raw: string | null;
  measurements: Record<string, TimeSeriesMeasurementValueItem>;
}

export interface TimeSeriesUnitPanelGroup {
  column_names: string[];
  shared_unit: string | null;
}

export interface TimeSeriesWorkbookPreview {
  original_filename: string;
  effective_dataset_name: string;
  metadata: Record<string, string | null>;
  condition_legend: TimeSeriesConditionLegendItem[];
  measurement_columns: TimeSeriesMeasurementColumnItem[];
  unit_panels: TimeSeriesUnitPanelGroup[];
  rows: TimeSeriesDataRowItem[];
  findings: TimeSeriesFindingItem[];
}

export interface TimeSeriesDatasetDetail {
  id: string;
  dataset_reference_id: string;
  saved_by: string | null;
  created_at: string;
  content: TimeSeriesWorkbookPreview;
}

export interface TimeSeriesDatasetListItem {
  id: string;
  name: string;
  measurement_type: string | null;
  organism: string | null;
  row_count: number;
  measurement_column_count: number;
  unresolved_finding_count: number;
  saved_by: string | null;
  created_at: string;
}

// Mirrors app/schemas/dataset_model_alias_mapping.py (Model-Specific Alias Mapping increment).
// See docs/27_model_specific_alias_mapping_increment.md.

export type AliasMappingAssignmentStatus = "ASSIGNED" | "SKIPPED" | "UNRESOLVED";
export type AliasMappingUnitFinding = "COMPATIBLE" | "INCOMPATIBLE" | "UNKNOWN";
export type ModelSpeciesCatalogStatus = "AVAILABLE" | "UNAVAILABLE";

export interface AliasMappingSpeciesOption {
  antimony_species_id: string;
  display_name: string | null;
  compartment_id: string;
  compartment_name: string | null;
}

export interface AliasMappingColumnInfo {
  column_name: string;
  unit: string | null;
  sample_values: string[];
}

export interface AliasMappingAssignmentItem {
  column_name: string;
  status: AliasMappingAssignmentStatus;
  target_antimony_species_id: string | null;
  unit_finding: AliasMappingUnitFinding | null;
  unit_comparison_detail: Record<string, unknown> | null;
}

export interface AliasMappingRevisionSummary {
  revision_number: number;
  saved_by: string | null;
  created_at: string;
  assigned_count: number;
  skipped_count: number;
  unresolved_count: number;
}

export interface AliasMappingDetail {
  time_series_dataset_id: string;
  model_id: string;
  model_species_catalog_status: ModelSpeciesCatalogStatus | null;
  model_species_catalog_unavailable_reason: string | null;
  available_species: AliasMappingSpeciesOption[];
  columns: AliasMappingColumnInfo[];
  revision_number: number;
  saved_by: string | null;
  created_at: string | null;
  assignments: AliasMappingAssignmentItem[];
}

export interface SaveAliasMappingAssignmentRequest {
  column_name: string;
  status: AliasMappingAssignmentStatus;
  target_antimony_species_id?: string | null;
}

export interface SaveAliasMappingRequest {
  expected_revision_number: number;
  assignments: SaveAliasMappingAssignmentRequest[];
  saved_by?: string | null;
}

// Mirrors app/schemas/calibration.py (Joint Calibration Workflow, configuration-only
// increment, plus the docs/31 configuration-prerequisites revision on top of it). See
// docs/29_joint_calibration_workflow_design.md, docs/30_joint_calibration_configuration
// _increment.md, docs/31_joint_calibration_configuration_prerequisites_increment.md.

export type CalibrationJobStatus = "DRAFT" | "REVIEWED";
export type CalibrationExperimentRole = "CALIBRATION" | "HELD_OUT_VALIDATION";
// docs/32_calibration_configuration_close_out_increment.md's own minimal error/weighting
// contract supersedes the first revision's DECLARED_SIGMA (free-text-only) policy value.
export type CalibrationObjectiveWeighting = "UNWEIGHTED" | "INVERSE_VARIANCE";
export type CalibrationBindingModelMeaning =
  | "INITIAL_VALUE"
  | "PARAMETER_OVERRIDE"
  | "INTERVENTION";
export type CalibrationBindingValueSource = "CONSTANT" | "DATASET_COLUMN";
export type CalibrationUncertaintySource = "MEASURED" | "USER_ASSUMED" | "UNKNOWN";
// A standard deviation, a variance, and a standard error are not interchangeable (docs/32) --
// required wherever a real uncertainty value is captured.
export type UncertaintyStatisticKind = "STANDARD_DEVIATION" | "VARIANCE" | "STANDARD_ERROR";
export type CalibrationParameterRoleKind =
  | "MODEL_SPECIFIC"
  | "FIXED"
  | "EXACT_EQUALITY"
  | "EXACT_AFFINE_LINK"
  | "SOFT_PRIOR_LINK";
export type CalibrationFindingSeverity = "INFO" | "WARNING" | "ERROR";
export type CalibrationFindingCategory =
  | "CALIBRATION_VALIDATION_DATASET_REUSE"
  | "INCOMPATIBLE_EXPERIMENTS_MERGED"
  | "DATASET_REUSED_ACROSS_DIFFERENT_MODELS"
  | "PARAMETER_ROLE_CYCLE"
  | "UNRESOLVED_LINK_REFERENCE"
  | "AMBIGUOUS_SAME_NAME_PARAMETER"
  | "UNIT_INCOMPATIBLE_LINK"
  | "ARM_WITHOUT_MAPPED_EXPERIMENT"
  | "NO_FREE_PARAMETER_TO_FIT"
  | "INVERSE_VARIANCE_WEIGHTING_REQUIRES_KNOWN_UNCERTAINTY"
  | "OUTPUT_WEIGHT_AND_UNCERTAINTY_SCALING_BOTH_APPLY"
  | "UNWEIGHTED_POLICY_IGNORES_DECLARED_UNCERTAINTY"
  | "MEASURED_UNCERTAINTY_NOT_STRICTLY_POSITIVE";
export type ModelRelationshipKind = "VARIANT_OF" | "SHARES_STRUCTURE_WITH";

export interface VariableBindingItem {
  id: string;
  model_meaning: CalibrationBindingModelMeaning;
  target_component_id: string;
  value_source: CalibrationBindingValueSource;
  constant_value: string | null;
  constant_unit: string | null;
  source_column_name: string | null;
  source: string | null;
  // Required if and only if model_meaning === "INTERVENTION" (docs/33).
  intervention_time: string | null;
}

// docs/32's minimal error/weighting contract -- one output's own declared uncertainty source
// and relative weight.
export interface OutputWeightingItem {
  id: string;
  output_column_name: string;
  uncertainty_source: CalibrationUncertaintySource;
  assumed_sigma_value: string | null;
  assumed_sigma_unit: string | null;
  assumed_sigma_statistic_kind: UncertaintyStatisticKind | null;
  // Resolved for display regardless of source: mirrors assumed_sigma_statistic_kind for
  // USER_ASSUMED, looked up from the dataset's own declared uncertainty column for MEASURED,
  // null for UNKNOWN.
  effective_statistic_kind: UncertaintyStatisticKind | null;
  relative_output_weight: string;
  provenance_note: string | null;
}

export interface CalibrationExperimentItem {
  id: string;
  time_series_dataset_id: string;
  dataset_name: string;
  role: CalibrationExperimentRole;
  objective_weighting: CalibrationObjectiveWeighting;
  weighting_notes: string | null;
  alias_mapping_revision_id: string | null;
  alias_mapping_revision_number: number | null;
  mapping_is_stale: boolean;
  variable_bindings: VariableBindingItem[];
  // Every independent-variable column this experiment's own pinned dataset has declared --
  // what a value_source=DATASET_COLUMN binding may legally name (docs/31).
  available_dataset_columns: string[];
  // Every output (measurement column) this experiment's own pinned dataset actually has --
  // what output_column_name may legally name when declaring a weighting (docs/32).
  available_output_columns: string[];
  // The subset of available_output_columns for which the dataset itself declares a real
  // measurement-uncertainty column -- i.e. where uncertainty_source=MEASURED is legal.
  outputs_with_measured_uncertainty: string[];
  output_weightings: OutputWeightingItem[];
}

export interface CalibrationArmItem {
  id: string;
  model_id: string;
  model_name: string;
  role_label: string | null;
  sequence_index: number;
  experiments: CalibrationExperimentItem[];
}

export interface CalibrationParameterRoleItem {
  id: string;
  parameter_name: string;
  role: CalibrationParameterRoleKind;
  fixed_value: string | null;
  lower_bound: string | null;
  upper_bound: string | null;
  unit: string | null;
  reference_arm_id: string | null;
  reference_parameter_name: string | null;
  coefficient_a: string | null;
  coefficient_a_is_fixed: boolean;
  coefficient_b: string | null;
  coefficient_b_is_fixed: boolean;
  arm_ids: string[];
  // Whether parameter_name (and, for a link role, reference_parameter_name) was actually
  // confirmed against a real, AVAILABLE ModelParameterCatalog at declaration time (docs/31) --
  // false only when no such catalog existed yet; never re-evaluated against a catalog
  // captured later.
  catalog_validated: boolean;
}

export interface CalibrationJobDetail {
  id: string;
  subproject_id: string;
  status: CalibrationJobStatus;
  edit_version: number;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  updated_by: string | null;
  reviewed_at: string | null;
  arms: CalibrationArmItem[];
  parameter_roles: CalibrationParameterRoleItem[];
}

export interface CalibrationJobSummary {
  id: string;
  status: CalibrationJobStatus;
  arm_count: number;
  created_at: string;
  updated_at: string;
  created_by: string | null;
}

// An immutable, versioned snapshot of a job's complete configuration, captured each time
// "Complete review" succeeds -- a later draft edit never changes an earlier revision
// (docs/31 audit item 2).
export interface CalibrationJobRevisionSummary {
  revision_number: number;
  created_at: string;
  created_by: string | null;
  arm_count: number;
  finding_count: number;
}

export interface CalibrationJobRevisionDetail {
  revision_number: number;
  created_at: string;
  created_by: string | null;
  snapshot: Record<string, unknown>;
}

export interface CalibrationFindingItem {
  severity: CalibrationFindingSeverity;
  category: CalibrationFindingCategory;
  message: string;
  involved_arm_ids: string[];
  involved_experiment_ids: string[];
  involved_parameter_role_ids: string[];
}

export interface ExecutionCapabilityItem {
  available: boolean;
  reason: string | null;
  missing_capability: "WHOLE_MODEL_EXECUTION" | null;
}

export interface CalibrationReviewResult {
  job: CalibrationJobDetail;
  findings: CalibrationFindingItem[];
  execution_capability: ExecutionCapabilityItem;
}

export interface ModelRelationshipItem {
  id: string;
  model_id_a: string;
  model_id_b: string;
  relationship_kind: ModelRelationshipKind;
  role_label_a: string | null;
  role_label_b: string | null;
  declared_by: string | null;
  declared_at: string;
}

export interface DeclareModelRelationshipRequest {
  model_id_a: string;
  model_id_b: string;
  relationship_kind: ModelRelationshipKind;
  role_label_a?: string | null;
  role_label_b?: string | null;
  declared_by?: string | null;
}

export interface AddArmRequest {
  model_id: string;
  role_label?: string | null;
  expected_edit_version: number;
  updated_by?: string | null;
}

export interface AddExperimentRequest {
  time_series_dataset_id: string;
  role?: CalibrationExperimentRole;
  expected_edit_version: number;
  updated_by?: string | null;
}

export interface SetExperimentMappingRequest {
  alias_mapping_revision_number: number | null;
  expected_edit_version: number;
  updated_by?: string | null;
}

export interface SetExperimentRoleRequest {
  role: CalibrationExperimentRole;
  expected_edit_version: number;
  updated_by?: string | null;
}

export interface SetExperimentObjectiveWeightingRequest {
  objective_weighting: CalibrationObjectiveWeighting;
  weighting_notes?: string | null;
  expected_edit_version: number;
  updated_by?: string | null;
}

export interface SetExperimentOutputWeightingRequest {
  output_column_name: string;
  uncertainty_source: CalibrationUncertaintySource;
  assumed_sigma_value?: string | null;
  assumed_sigma_unit?: string | null;
  assumed_sigma_statistic_kind?: UncertaintyStatisticKind | null;
  relative_output_weight?: string;
  provenance_note?: string | null;
  expected_edit_version: number;
  updated_by?: string | null;
}

export interface AddVariableBindingRequest {
  model_meaning: CalibrationBindingModelMeaning;
  target_component_id: string;
  value_source: CalibrationBindingValueSource;
  constant_value?: string | null;
  constant_unit?: string | null;
  source_column_name?: string | null;
  source?: string | null;
  intervention_time?: string | null;
  expected_edit_version: number;
  updated_by?: string | null;
}

export interface AddParameterRoleRequest {
  parameter_name: string;
  role: CalibrationParameterRoleKind;
  arm_ids: string[];
  fixed_value?: string | null;
  lower_bound?: string | null;
  upper_bound?: string | null;
  unit?: string | null;
  reference_arm_id?: string | null;
  reference_parameter_name?: string | null;
  coefficient_a?: string | null;
  coefficient_a_is_fixed?: boolean;
  coefficient_b?: string | null;
  coefficient_b_is_fixed?: boolean;
  expected_edit_version: number;
  updated_by?: string | null;
}

export interface CompleteReviewRequest {
  expected_edit_version: number;
  updated_by?: string | null;
}
