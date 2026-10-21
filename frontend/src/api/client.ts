import type {
  BoundaryPortItem,
  HierarchicalRunSummary,
  ModelDetail,
  ModelLineage,
  ModelListItem,
  ModuleSetDraftDetail,
  ModuleSetSummary,
  ModuleSetVersionDetail,
  ProjectDetail,
  ProjectListItem,
  SaveModuleSetDraftRequest,
  SubprojectDetail,
  SubprojectListItem,
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
  init?: { method?: "GET" | "POST"; body?: unknown },
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
