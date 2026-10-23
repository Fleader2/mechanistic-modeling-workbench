import type {
  AddArmRequest,
  AddExperimentRequest,
  AddParameterRoleRequest,
  AddVariableBindingRequest,
  AliasMappingDetail,
  AliasMappingRevisionSummary,
  BoundaryPortItem,
  CalibrationJobDetail,
  CalibrationJobRevisionDetail,
  CalibrationJobRevisionSummary,
  CalibrationJobSummary,
  CalibrationReviewResult,
  CompleteReviewRequest,
  DeclareModelRelationshipRequest,
  EditModuleSetDraftMemberRequest,
  HierarchicalRunSummary,
  ModelDetail,
  ModelLineage,
  ModelListItem,
  ModelRelationshipItem,
  ModuleSetDraftDetail,
  ModuleSetDraftValidationFindingItem,
  ModuleSetDraftValidationResult,
  ModuleSetMemberReviewDetail,
  ModuleSetSimulationRunItem,
  ModuleSetSummary,
  ModuleSetVersionDetail,
  ProjectDetail,
  ProjectListItem,
  SaveAliasMappingRequest,
  SaveModuleSetDraftRequest,
  ScenarioEvaluationRunItem,
  SetExperimentMappingRequest,
  SetExperimentObjectiveWeightingRequest,
  SetExperimentOutputWeightingRequest,
  SetExperimentRoleRequest,
  SubmitBoundaryDecisionRequest,
  SubmitModuleSetSimulationRequest,
  SubmitScenarioEvaluationRequest,
  SubprojectDetail,
  SubprojectListItem,
  TimeSeriesDatasetDetail,
  TimeSeriesDatasetListItem,
  TimeSeriesWorkbookPreview,
} from "../types";

const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

/** Mirrors app/schemas/common.py::ErrorResponse. */
interface ApiErrorBody {
  detail: {
    code: string;
    message: string;
    context?: unknown;
  };
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly context: Record<string, unknown> | null;

  constructor(
    status: number,
    code: string,
    message: string,
    context: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
    this.context = context;
  }
}

async function request<T>(
  path: string,
  init?: { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown },
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: init?.method ?? "GET",
      headers: init?.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiRequestError(0, "NETWORK_ERROR", "Could not reach the Workbench API.");
  }

  if (!response.ok) {
    const body: ApiErrorBody | null = await response.json().catch(() => null);
    throw new ApiRequestError(
      response.status,
      body?.detail?.code ?? "HTTP_ERROR",
      body?.detail?.message ?? `Request failed with status ${response.status}.`,
      (body?.detail?.context as Record<string, unknown> | undefined) ?? null,
    );
  }

  return (await response.json()) as T;
}

/** Like ``request``, but sends ``formData`` as a real multipart body instead of JSON --
 * never sets its own Content-Type header, since the browser must set the multipart boundary
 * itself (time-series dataset workbook upload: preview/save). */
async function requestFormData<T>(path: string, formData: FormData): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { method: "POST", body: formData });
  } catch {
    throw new ApiRequestError(0, "NETWORK_ERROR", "Could not reach the Workbench API.");
  }

  if (!response.ok) {
    const body: ApiErrorBody | null = await response.json().catch(() => null);
    throw new ApiRequestError(
      response.status,
      body?.detail?.code ?? "HTTP_ERROR",
      body?.detail?.message ?? `Request failed with status ${response.status}.`,
      (body?.detail?.context as Record<string, unknown> | undefined) ?? null,
    );
  }

  return (await response.json()) as T;
}

/** Fetches the blank template workbook as a ``Blob``, for the caller to trigger a browser
 * download from (``URL.createObjectURL`` + a synthetic anchor click) -- the one response
 * shape ``request``/``requestFormData`` don't cover. */
async function requestBlob(path: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new ApiRequestError(0, "NETWORK_ERROR", "Could not reach the Workbench API.");
  }
  if (!response.ok) {
    const body: ApiErrorBody | null = await response.json().catch(() => null);
    throw new ApiRequestError(
      response.status,
      body?.detail?.code ?? "HTTP_ERROR",
      body?.detail?.message ?? `Request failed with status ${response.status}.`,
      (body?.detail?.context as Record<string, unknown> | undefined) ?? null,
    );
  }
  return await response.blob();
}

export function listProjects(): Promise<ProjectListItem[]> {
  return request<ProjectListItem[]>("/api/v1/projects");
}

export function getProject(projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/v1/projects/${encodeURIComponent(projectId)}`);
}

export function getProjectSubprojects(projectId: string): Promise<SubprojectListItem[]> {
  return request<SubprojectListItem[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/subprojects`,
  );
}

export function getModelingStudy(projectId: string, studyId: string): Promise<SubprojectDetail> {
  return request<SubprojectDetail>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/subprojects/${encodeURIComponent(studyId)}`,
  );
}

export function getModelingStudyModels(
  projectId: string,
  studyId: string,
): Promise<ModelListItem[]> {
  return request<ModelListItem[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/subprojects/${encodeURIComponent(
      studyId,
    )}/models`,
  );
}

function modelPath(projectId: string, studyId: string, modelId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/subprojects/${encodeURIComponent(
    studyId,
  )}/models/${encodeURIComponent(modelId)}`;
}

export function getModel(projectId: string, studyId: string, modelId: string): Promise<ModelDetail> {
  return request<ModelDetail>(modelPath(projectId, studyId, modelId));
}

export function getModelLineage(
  projectId: string,
  studyId: string,
  modelId: string,
): Promise<ModelLineage> {
  return request<ModelLineage>(`${modelPath(projectId, studyId, modelId)}/lineage`);
}

function studyPath(projectId: string, studyId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/subprojects/${encodeURIComponent(
    studyId,
  )}`;
}

export function listDraftableHierarchicalRuns(
  projectId: string,
  studyId: string,
): Promise<HierarchicalRunSummary[]> {
  return request<HierarchicalRunSummary[]>(`${studyPath(projectId, studyId)}/hierarchical-runs`);
}

export function createModuleSetDraft(
  projectId: string,
  studyId: string,
  runRecordId: string,
): Promise<ModuleSetDraftDetail> {
  return request<ModuleSetDraftDetail>(`${studyPath(projectId, studyId)}/module-set-drafts`, {
    method: "POST",
    body: { run_record_id: runRecordId },
  });
}

export function getModuleSetDraft(
  projectId: string,
  studyId: string,
  draftId: string,
): Promise<ModuleSetDraftDetail> {
  return request<ModuleSetDraftDetail>(
    `${studyPath(projectId, studyId)}/module-set-drafts/${encodeURIComponent(draftId)}`,
  );
}

export function discardModuleSetDraft(
  projectId: string,
  studyId: string,
  draftId: string,
): Promise<ModuleSetDraftDetail> {
  return request<ModuleSetDraftDetail>(
    `${studyPath(projectId, studyId)}/module-set-drafts/${encodeURIComponent(draftId)}/discard`,
    { method: "POST" },
  );
}

export function saveModuleSetDraft(
  projectId: string,
  studyId: string,
  draftId: string,
  request_body: SaveModuleSetDraftRequest,
): Promise<ModuleSetVersionDetail> {
  return request<ModuleSetVersionDetail>(
    `${studyPath(projectId, studyId)}/module-set-drafts/${encodeURIComponent(draftId)}/save`,
    { method: "POST", body: request_body },
  );
}

export function editModuleSetDraftMember(
  projectId: string,
  studyId: string,
  draftId: string,
  memberId: string,
  body: EditModuleSetDraftMemberRequest,
): Promise<ModuleSetDraftValidationResult> {
  return request<ModuleSetDraftValidationResult>(
    `${studyPath(projectId, studyId)}/module-set-drafts/${encodeURIComponent(
      draftId,
    )}/members/${encodeURIComponent(memberId)}`,
    { method: "PATCH", body },
  );
}

export function getModuleSetDraftValidation(
  projectId: string,
  studyId: string,
  draftId: string,
): Promise<ModuleSetDraftValidationFindingItem[]> {
  return request<ModuleSetDraftValidationFindingItem[]>(
    `${studyPath(projectId, studyId)}/module-set-drafts/${encodeURIComponent(draftId)}/validation`,
  );
}

export function getDraftMemberBoundaryPorts(
  projectId: string,
  studyId: string,
  draftId: string,
  memberId: string,
): Promise<BoundaryPortItem[]> {
  return request<BoundaryPortItem[]>(
    `${studyPath(projectId, studyId)}/module-set-drafts/${encodeURIComponent(
      draftId,
    )}/members/${encodeURIComponent(memberId)}/boundary-ports`,
  );
}

export function listModuleSets(projectId: string, studyId: string): Promise<ModuleSetSummary[]> {
  return request<ModuleSetSummary[]>(`${studyPath(projectId, studyId)}/module-sets`);
}

export function getModuleSetVersion(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
): Promise<ModuleSetVersionDetail> {
  return request<ModuleSetVersionDetail>(
    `${studyPath(projectId, studyId)}/module-sets/${encodeURIComponent(
      moduleSetId,
    )}/versions/${encodeURIComponent(version)}`,
  );
}

export function createModuleSetEditDraft(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
): Promise<ModuleSetDraftDetail> {
  return request<ModuleSetDraftDetail>(
    `${studyPath(projectId, studyId)}/module-sets/${encodeURIComponent(
      moduleSetId,
    )}/versions/${encodeURIComponent(version)}/edit`,
    { method: "POST" },
  );
}

export function getVersionMemberBoundaryPorts(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
  memberId: string,
): Promise<BoundaryPortItem[]> {
  return request<BoundaryPortItem[]>(
    `${studyPath(projectId, studyId)}/module-sets/${encodeURIComponent(
      moduleSetId,
    )}/versions/${encodeURIComponent(version)}/members/${encodeURIComponent(
      memberId,
    )}/boundary-ports`,
  );
}

// --- Module-Set Edited-Module Materialization increment, Phase B (docs/24) ---

function moduleSetMemberPath(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
  memberId: string,
): string {
  return `${studyPath(projectId, studyId)}/module-sets/${encodeURIComponent(
    moduleSetId,
  )}/versions/${encodeURIComponent(version)}/members/${encodeURIComponent(memberId)}`;
}

export function deriveModuleSetMemberBoundaryReview(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
  memberId: string,
): Promise<ModuleSetMemberReviewDetail> {
  return request<ModuleSetMemberReviewDetail>(
    `${moduleSetMemberPath(projectId, studyId, moduleSetId, version, memberId)}/boundary-review/derive`,
    { method: "POST" },
  );
}

export function getModuleSetMemberBoundaryReview(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
  memberId: string,
): Promise<ModuleSetMemberReviewDetail> {
  return request<ModuleSetMemberReviewDetail>(
    `${moduleSetMemberPath(projectId, studyId, moduleSetId, version, memberId)}/boundary-review`,
  );
}

export function submitModuleSetMemberBoundaryDecision(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
  memberId: string,
  portId: string,
  body: SubmitBoundaryDecisionRequest,
): Promise<ModuleSetMemberReviewDetail> {
  return request<ModuleSetMemberReviewDetail>(
    `${moduleSetMemberPath(
      projectId,
      studyId,
      moduleSetId,
      version,
      memberId,
    )}/boundary-review/ports/${encodeURIComponent(portId)}/decision`,
    { method: "POST", body },
  );
}

export function submitModuleSetMemberSimulation(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
  memberId: string,
  body: SubmitModuleSetSimulationRequest,
): Promise<ModuleSetSimulationRunItem> {
  return request<ModuleSetSimulationRunItem>(
    `${moduleSetMemberPath(projectId, studyId, moduleSetId, version, memberId)}/simulations`,
    { method: "POST", body },
  );
}

export function listModuleSetMemberSimulations(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
  memberId: string,
): Promise<ModuleSetSimulationRunItem[]> {
  return request<ModuleSetSimulationRunItem[]>(
    `${moduleSetMemberPath(projectId, studyId, moduleSetId, version, memberId)}/simulations`,
  );
}

export function getModuleSetMemberSimulation(
  projectId: string,
  studyId: string,
  moduleSetId: string,
  version: string,
  memberId: string,
  runId: string,
): Promise<ModuleSetSimulationRunItem> {
  return request<ModuleSetSimulationRunItem>(
    `${moduleSetMemberPath(
      projectId,
      studyId,
      moduleSetId,
      version,
      memberId,
    )}/simulations/${encodeURIComponent(runId)}`,
  );
}

function timeSeriesDatasetsPath(projectId: string, studyId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/subprojects/${encodeURIComponent(
    studyId,
  )}/datasets/time-series`;
}

export async function downloadTimeSeriesDatasetTemplate(
  projectId: string,
  studyId: string,
): Promise<Blob> {
  return requestBlob(`${timeSeriesDatasetsPath(projectId, studyId)}/template`);
}

export function previewTimeSeriesDataset(
  projectId: string,
  studyId: string,
  file: File,
): Promise<TimeSeriesWorkbookPreview> {
  const formData = new FormData();
  formData.append("file", file);
  return requestFormData<TimeSeriesWorkbookPreview>(
    `${timeSeriesDatasetsPath(projectId, studyId)}/preview`,
    formData,
  );
}

export function saveTimeSeriesDataset(
  projectId: string,
  studyId: string,
  file: File,
  savedBy?: string,
): Promise<TimeSeriesDatasetDetail> {
  const formData = new FormData();
  formData.append("file", file);
  if (savedBy) {
    formData.append("saved_by", savedBy);
  }
  return requestFormData<TimeSeriesDatasetDetail>(
    timeSeriesDatasetsPath(projectId, studyId),
    formData,
  );
}

export function listTimeSeriesDatasets(
  projectId: string,
  studyId: string,
): Promise<TimeSeriesDatasetListItem[]> {
  return request<TimeSeriesDatasetListItem[]>(timeSeriesDatasetsPath(projectId, studyId));
}

export function getTimeSeriesDataset(
  projectId: string,
  studyId: string,
  datasetId: string,
): Promise<TimeSeriesDatasetDetail> {
  return request<TimeSeriesDatasetDetail>(
    `${timeSeriesDatasetsPath(projectId, studyId)}/${encodeURIComponent(datasetId)}`,
  );
}

function aliasMappingPath(
  projectId: string,
  studyId: string,
  datasetId: string,
  modelId: string,
): string {
  return `${timeSeriesDatasetsPath(projectId, studyId)}/${encodeURIComponent(
    datasetId,
  )}/alias-mapping/${encodeURIComponent(modelId)}`;
}

export function getCurrentAliasMapping(
  projectId: string,
  studyId: string,
  datasetId: string,
  modelId: string,
): Promise<AliasMappingDetail> {
  return request<AliasMappingDetail>(aliasMappingPath(projectId, studyId, datasetId, modelId));
}

export function saveAliasMapping(
  projectId: string,
  studyId: string,
  datasetId: string,
  modelId: string,
  body: SaveAliasMappingRequest,
): Promise<AliasMappingDetail> {
  return request<AliasMappingDetail>(aliasMappingPath(projectId, studyId, datasetId, modelId), {
    method: "POST",
    body,
  });
}

export function listAliasMappingRevisions(
  projectId: string,
  studyId: string,
  datasetId: string,
  modelId: string,
): Promise<AliasMappingRevisionSummary[]> {
  return request<AliasMappingRevisionSummary[]>(
    `${aliasMappingPath(projectId, studyId, datasetId, modelId)}/revisions`,
  );
}

export function getAliasMappingRevision(
  projectId: string,
  studyId: string,
  datasetId: string,
  modelId: string,
  revisionNumber: number,
): Promise<AliasMappingDetail> {
  return request<AliasMappingDetail>(
    `${aliasMappingPath(projectId, studyId, datasetId, modelId)}/revisions/${revisionNumber}`,
  );
}

// Joint Calibration Workflow, configuration-only increment. Mirrors
// app/api/v1/routes/calibration.py. See docs/29_joint_calibration_workflow_design.md and
// docs/30_joint_calibration_configuration_increment.md.

function jobsPath(projectId: string, studyId: string): string {
  return `${studyPath(projectId, studyId)}/calibration-jobs`;
}

function jobPath(projectId: string, studyId: string, jobId: string): string {
  return `${jobsPath(projectId, studyId)}/${encodeURIComponent(jobId)}`;
}

export function declareModelRelationship(
  projectId: string,
  studyId: string,
  body: DeclareModelRelationshipRequest,
): Promise<ModelRelationshipItem> {
  return request<ModelRelationshipItem>(`${studyPath(projectId, studyId)}/model-relationships`, {
    method: "POST",
    body,
  });
}

export function createCalibrationJob(
  projectId: string,
  studyId: string,
  createdBy?: string | null,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(jobsPath(projectId, studyId), {
    method: "POST",
    body: { created_by: createdBy ?? null },
  });
}

export function listCalibrationJobs(
  projectId: string,
  studyId: string,
): Promise<CalibrationJobSummary[]> {
  return request<CalibrationJobSummary[]>(jobsPath(projectId, studyId));
}

export function getCalibrationJob(
  projectId: string,
  studyId: string,
  jobId: string,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(jobPath(projectId, studyId, jobId));
}

export function listCalibrationJobModelRelationships(
  projectId: string,
  studyId: string,
  jobId: string,
): Promise<ModelRelationshipItem[]> {
  return request<ModelRelationshipItem[]>(
    `${jobPath(projectId, studyId, jobId)}/model-relationships`,
  );
}

export function addCalibrationArm(
  projectId: string,
  studyId: string,
  jobId: string,
  body: AddArmRequest,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(`${jobPath(projectId, studyId, jobId)}/arms`, {
    method: "POST",
    body,
  });
}

export function removeCalibrationArm(
  projectId: string,
  studyId: string,
  jobId: string,
  armId: string,
  expectedEditVersion: number,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/arms/${encodeURIComponent(armId)}` +
      `?expected_edit_version=${expectedEditVersion}`,
    { method: "DELETE" },
  );
}

export function addCalibrationExperiment(
  projectId: string,
  studyId: string,
  jobId: string,
  armId: string,
  body: AddExperimentRequest,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/arms/${encodeURIComponent(armId)}/experiments`,
    { method: "POST", body },
  );
}

export function removeCalibrationExperiment(
  projectId: string,
  studyId: string,
  jobId: string,
  experimentId: string,
  expectedEditVersion: number,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/experiments/${encodeURIComponent(experimentId)}` +
      `?expected_edit_version=${expectedEditVersion}`,
    { method: "DELETE" },
  );
}

export function setCalibrationExperimentMapping(
  projectId: string,
  studyId: string,
  jobId: string,
  experimentId: string,
  body: SetExperimentMappingRequest,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/experiments/${encodeURIComponent(experimentId)}/mapping`,
    { method: "PATCH", body },
  );
}

export function setCalibrationExperimentRole(
  projectId: string,
  studyId: string,
  jobId: string,
  experimentId: string,
  body: SetExperimentRoleRequest,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/experiments/${encodeURIComponent(experimentId)}/role`,
    { method: "PATCH", body },
  );
}

export function setCalibrationExperimentObjectiveWeighting(
  projectId: string,
  studyId: string,
  jobId: string,
  experimentId: string,
  body: SetExperimentObjectiveWeightingRequest,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/experiments/${encodeURIComponent(experimentId)}` +
      "/objective-weighting",
    { method: "PATCH", body },
  );
}

export function setCalibrationExperimentOutputWeighting(
  projectId: string,
  studyId: string,
  jobId: string,
  experimentId: string,
  body: SetExperimentOutputWeightingRequest,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/experiments/${encodeURIComponent(experimentId)}` +
      "/output-weightings",
    { method: "PUT", body },
  );
}

export function removeCalibrationExperimentOutputWeighting(
  projectId: string,
  studyId: string,
  jobId: string,
  weightingId: string,
  expectedEditVersion: number,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/output-weightings/${encodeURIComponent(weightingId)}` +
      `?expected_edit_version=${expectedEditVersion}`,
    { method: "DELETE" },
  );
}

export function addCalibrationVariableBinding(
  projectId: string,
  studyId: string,
  jobId: string,
  experimentId: string,
  body: AddVariableBindingRequest,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/experiments/${encodeURIComponent(experimentId)}` +
      "/variable-bindings",
    { method: "POST", body },
  );
}

export function removeCalibrationVariableBinding(
  projectId: string,
  studyId: string,
  jobId: string,
  bindingId: string,
  expectedEditVersion: number,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/variable-bindings/${encodeURIComponent(bindingId)}` +
      `?expected_edit_version=${expectedEditVersion}`,
    { method: "DELETE" },
  );
}

export function addCalibrationParameterRole(
  projectId: string,
  studyId: string,
  jobId: string,
  body: AddParameterRoleRequest,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(`${jobPath(projectId, studyId, jobId)}/parameter-roles`, {
    method: "POST",
    body,
  });
}

export function removeCalibrationParameterRole(
  projectId: string,
  studyId: string,
  jobId: string,
  roleId: string,
  expectedEditVersion: number,
): Promise<CalibrationJobDetail> {
  return request<CalibrationJobDetail>(
    `${jobPath(projectId, studyId, jobId)}/parameter-roles/${encodeURIComponent(roleId)}` +
      `?expected_edit_version=${expectedEditVersion}`,
    { method: "DELETE" },
  );
}

export function previewCalibrationReview(
  projectId: string,
  studyId: string,
  jobId: string,
): Promise<CalibrationReviewResult> {
  return request<CalibrationReviewResult>(`${jobPath(projectId, studyId, jobId)}/review`);
}

export function completeCalibrationReview(
  projectId: string,
  studyId: string,
  jobId: string,
  body: CompleteReviewRequest,
): Promise<CalibrationReviewResult> {
  return request<CalibrationReviewResult>(
    `${jobPath(projectId, studyId, jobId)}/complete-review`,
    { method: "POST", body },
  );
}

export function listCalibrationJobRevisions(
  projectId: string,
  studyId: string,
  jobId: string,
): Promise<CalibrationJobRevisionSummary[]> {
  return request<CalibrationJobRevisionSummary[]>(
    `${jobPath(projectId, studyId, jobId)}/revisions`,
  );
}

export function getCalibrationJobRevision(
  projectId: string,
  studyId: string,
  jobId: string,
  revisionNumber: number,
): Promise<CalibrationJobRevisionDetail> {
  return request<CalibrationJobRevisionDetail>(
    `${jobPath(projectId, studyId, jobId)}/revisions/${revisionNumber}`,
  );
}

// Whole-Model Experimental-Scenario Evaluation increment (docs/33). Mirrors
// app/api/v1/routes/calibration.py's own scenario-evaluation routes -- prediction only, never
// fitting.

function scenarioEvaluationsPath(
  projectId: string,
  studyId: string,
  jobId: string,
  revisionNumber: number,
  experimentId: string,
): string {
  return (
    `${jobPath(projectId, studyId, jobId)}/revisions/${revisionNumber}/experiments/` +
    `${encodeURIComponent(experimentId)}/scenario-evaluations`
  );
}

export function submitCalibrationScenarioEvaluation(
  projectId: string,
  studyId: string,
  jobId: string,
  revisionNumber: number,
  experimentId: string,
  body: SubmitScenarioEvaluationRequest,
): Promise<ScenarioEvaluationRunItem> {
  return request<ScenarioEvaluationRunItem>(
    scenarioEvaluationsPath(projectId, studyId, jobId, revisionNumber, experimentId),
    { method: "POST", body },
  );
}

export function listCalibrationScenarioEvaluations(
  projectId: string,
  studyId: string,
  jobId: string,
  revisionNumber: number,
  experimentId: string,
): Promise<ScenarioEvaluationRunItem[]> {
  return request<ScenarioEvaluationRunItem[]>(
    scenarioEvaluationsPath(projectId, studyId, jobId, revisionNumber, experimentId),
  );
}

export function getCalibrationScenarioEvaluation(
  projectId: string,
  studyId: string,
  jobId: string,
  revisionNumber: number,
  experimentId: string,
  runId: string,
): Promise<ScenarioEvaluationRunItem> {
  return request<ScenarioEvaluationRunItem>(
    `${scenarioEvaluationsPath(projectId, studyId, jobId, revisionNumber, experimentId)}/` +
      encodeURIComponent(runId),
  );
}
