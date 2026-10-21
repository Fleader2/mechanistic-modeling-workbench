import type {
  ModelDetail,
  ModelLineage,
  ModelListItem,
  ProjectDetail,
  ProjectListItem,
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

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string): Promise<T> {
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
