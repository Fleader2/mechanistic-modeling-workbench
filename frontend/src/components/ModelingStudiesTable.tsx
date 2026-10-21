import type { SubprojectListItem } from "../types";
import { NOT_CAPTURED } from "../format";
import { navigate } from "../lib/router";
import { RouterLink } from "./RouterLink";

interface ModelingStudiesTableProps {
  projectId: string;
  studies: SubprojectListItem[];
}

/** The "Modeling Studies" table on "02 — Current Project" (Figma node
 * 46:203). "Study" is now a real, accessible link to "03 — Modeling Study"
 * (`docs/18_modeling_study_increment.md`) -- opening a study is in scope as
 * of this increment, matching the identical row-click/title-link/
 * double-click pattern `ProjectsTable` already established for opening a
 * project.
 */
export function ModelingStudiesTable({ projectId, studies }: ModelingStudiesTableProps) {
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
          <tr
            key={study.id}
            onDoubleClick={() => navigate(`/projects/${projectId}/studies/${study.id}`)}
          >
            <td>
              <RouterLink to={`/projects/${projectId}/studies/${study.id}`} className="project-link">
                {study.title}
              </RouterLink>
            </td>
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
