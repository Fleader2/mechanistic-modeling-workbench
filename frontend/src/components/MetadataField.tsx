import { NOT_CAPTURED } from "../format";

interface MetadataFieldProps {
  label: string;
  value: string | null;
}

/** One labeled metadata value, honestly disclosing a missing value (no
 * backend column, or a real column that is null) as "Not captured" rather
 * than inventing one. Shared by the "01 — All Projects" preview panel
 * (ProjectPreviewPanel) and the "02 — Current Project" project information
 * card (ProjectInformationCard), which show the identical field set. */
export function MetadataField({ label, value }: MetadataFieldProps) {
  return (
    <div className="metadata-field">
      <span className="metadata-field-label">{label}</span>
      <span className={value ? "metadata-field-value" : "metadata-field-value not-captured"}>
        {value ?? NOT_CAPTURED}
      </span>
    </div>
  );
}
