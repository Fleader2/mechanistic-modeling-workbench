import type { ProjectType } from "./types";

const PROJECT_TYPE_LABELS: Record<ProjectType, string> = {
  MICROBIAL_METABOLISM: "Microbial Metabolism",
  REGULATORY_NETWORK: "Regulatory Networks",
};

export function formatProjectType(projectType: ProjectType): string {
  return PROJECT_TYPE_LABELS[projectType];
}

/** The honest placeholder for a Figma field slot with no backend counterpart,
 * or a real column that happens to be null for this project. Never invented. */
export const NOT_CAPTURED = "Not captured";
