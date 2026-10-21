import type { ModelListItem } from "../types";
import { formatModelStatus, NOT_CAPTURED } from "../format";
import { navigate } from "../lib/router";
import { RouterLink } from "./RouterLink";

interface ModelsTableProps {
  projectId: string;
  studyId: string;
  models: ModelListItem[];
}

/** The "Models" table on "03 — Modeling Study" (Figma node 46:314).
 *
 * Shows only model identity (`name`, with `stable_identifier` as a muted
 * subtitle), `version_label`, and `status` -- the columns `Model` actually
 * has. Figma's own reference also shows "Construction" (e.g. "Protein
 * abundance") and "Calibration / validation" (e.g. "WT time course / ACC1
 * perturbation", "Not assigned") columns; neither has a backing column, and
 * the increment that built this table was explicit that scientific
 * readiness, calibration/validation status, and evidence assignments are
 * never invented -- so those two columns are omitted entirely rather than
 * filled with a placeholder.
 *
 * "Model" is now a real, accessible link to "05 — Model Overview"
 * (`docs/19_model_overview_increment.md`) -- opening a model is in scope as
 * of that increment, matching the identical row-click/title-link/
 * double-click pattern `ProjectsTable`/`ModelingStudiesTable` already
 * established.
 */
export function ModelsTable({ projectId, studyId, models }: ModelsTableProps) {
  return (
    <table className="models-table">
      <thead>
        <tr>
          <th scope="col">Model</th>
          <th scope="col">Version</th>
          <th scope="col">Status</th>
        </tr>
      </thead>
      <tbody>
        {models.map((model) => (
          <tr
            key={model.id}
            onDoubleClick={() => navigate(`/projects/${projectId}/studies/${studyId}/models/${model.id}`)}
          >
            <td>
              <div className="model-identity">
                <RouterLink
                  to={`/projects/${projectId}/studies/${studyId}/models/${model.id}`}
                  className="project-link"
                >
                  {model.name}
                </RouterLink>
                <span className="model-identity-id">{model.stable_identifier}</span>
              </div>
            </td>
            <td className={model.version_label ? undefined : "not-captured"}>
              {model.version_label ?? NOT_CAPTURED}
            </td>
            <td>{formatModelStatus(model.status)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
