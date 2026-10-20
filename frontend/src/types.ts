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
