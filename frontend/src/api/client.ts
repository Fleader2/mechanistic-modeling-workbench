import type { ProjectDetail, ProjectListItem, SubprojectListItem } from "../types";

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
