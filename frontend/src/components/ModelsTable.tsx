import type { ModelListItem } from "../types";
import { formatModelStatus, NOT_CAPTURED } from "../format";

interface ModelsTableProps {
  models: ModelListItem[];
}

/** The "Models" table on "03 — Modeling Study" (Figma node 46:314).
 *
 * Shows only model identity (`name`, with `stable_identifier` as a muted
 * subtitle), `version_label`, and `status` -- the columns `Model` actually
 * has. Figma's own reference also shows "Construction" (e.g. "Protein
 * abundance") and "Calibration / validation" (e.g. "WT time course / ACC1
 * perturbation", "Not assigned") columns; neither has a backing column, and
 * this increment's own instruction is explicit that scientific readiness,
 * calibration/validation status, and evidence assignments are never
 * invented -- so those two columns are omitted entirely rather than filled
 * with a placeholder. A model's name is deliberately plain text, not a
 * styled link -- opening a model (the "model workspace") is out of scope,
 * and a link-styled but non-functional cell would mislead a user into
 * expecting it to work, the same "disable honestly, never fake" principle
 * already established for a Modeling Study's row in the "02 — Current
 * Project" screen before this increment made that link real.
 */
export function ModelsTable({ models }: ModelsTableProps) {
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
          <tr key={model.id}>
            <td>
              <div className="model-identity">
                <span>{model.name}</span>
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
