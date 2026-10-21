import type { SubprojectListItem } from "../types";
import { NOT_CAPTURED } from "../format";

interface ModelingStudiesTableProps {
  studies: SubprojectListItem[];
}

/** The "Modeling Studies" table on "02 — Current Project" (Figma node
 * 46:203). "Study" cells are deliberately plain text, not a styled link --
 * opening a Modeling Study is out of scope for this increment (see the
 * disclosure note the parent screen renders above this table), and a
 * link-styled but non-functional cell would mislead a user into expecting
 * it to work.
 */
export function ModelingStudiesTable({ studies }: ModelingStudiesTableProps) {
  return (
    <table className="modeling-studies-table">
      <thead>
        <tr>
          <th scope="col">Study</th>
          <th scope="col">Scientific question</th>
          <th scope="col">Models</th>
          <th scope="col">Datasets</th>
        </tr>
      </thead>
      <tbody>
        {studies.map((study) => (
          <tr key={study.id}>
            <td>{study.title}</td>
            <td className={study.objective ? undefined : "not-captured"}>
              {study.objective ?? NOT_CAPTURED}
            </td>
            <td>{study.model_count}</td>
            <td>{study.dataset_count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
