"""Shared constants for the time-series dataset workbook: sheet names, the ``Metadata`` tab's
own scalar-field layout, the ``Data`` tab's structural (non-measurement) column names, and the
missing/unknown/not-applicable token vocabulary. The single source of truth both
``app.time_series.template`` (writes a blank workbook matching this exact layout) and
``app.time_series.parser`` (reads one back) import from, so the two can never silently drift
apart from each other.

See ``docs/25_time_series_dataset_import_increment.md`` for the full contract write-up.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bumped only if this workbook layout itself changes shape in a later increment. Written into
#: every generated template's own "Template version" row, and read back (non-blocking finding
#: if missing/unrecognized -- this version is not itself a reason to refuse an import, since
#: v1 is the only version that has ever existed).
TEMPLATE_VERSION = "1.0"

METADATA_SHEET_NAME = "Metadata"
DATA_SHEET_NAME = "Data"

#: The ``Data`` tab's own non-measurement, structural columns -- matched case-insensitively,
#: trimmed. Every other Data-tab header is a user-defined measurement column, preserved
#: verbatim (task instructions: "preserve original measurement-column names exactly"). Per
#: task instructions ("sample ID, condition ID, biological/technical replicate identifiers
#: *where applicable*"), every one of these except ``time`` may be entirely absent from a
#: given workbook's own Data tab -- never fabricated if the scientist's own data has no such
#: axis.
TIME_COLUMN = "time"
SAMPLE_ID_COLUMN = "sample_id"
CONDITION_ID_COLUMN = "condition_id"
BIOLOGICAL_REPLICATE_COLUMN = "biological_replicate"
TECHNICAL_REPLICATE_COLUMN = "technical_replicate"

STRUCTURAL_DATA_COLUMNS = (
    SAMPLE_ID_COLUMN,
    CONDITION_ID_COLUMN,
    BIOLOGICAL_REPLICATE_COLUMN,
    TECHNICAL_REPLICATE_COLUMN,
    TIME_COLUMN,
)

#: Cell text (case-insensitive, trimmed) recognized as "explicitly recorded as not applicable"
#: -- never collapsed into ``MISSING`` (task instructions: "distinguish missing, unknown, and
#: not-applicable values").
NOT_APPLICABLE_TOKENS = frozenset({"na", "n/a", "not applicable"})
#: Cell text (case-insensitive, trimmed) recognized as "explicitly recorded as unknown."
UNKNOWN_TOKENS = frozenset({"unknown", "unk"})


@dataclass(frozen=True, slots=True)
class MetadataField:
    """One row of the ``Metadata`` tab's own scalar-field block. ``key`` is this field's stable
    identifier (used in persistence/API/findings); ``label`` is the exact text written into the
    template's own column A (matched back, case-insensitively and trimmed, by the parser);
    ``guidance`` is written into the template's own column C, for a human filling it in, and is
    never parsed back -- informational only.
    """

    key: str
    label: str
    required: bool
    guidance: str


#: Order matters -- this is the exact row order the template writes and a human reads, top to
#: bottom. ``template_version`` is first and is the one field this increment ever treats as
#: load-bearing for anything beyond disclosure (a non-blocking finding, never a reason to
#: refuse the import -- see module docstring).
METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField("template_version", "Template version", True, "Required. Do not edit."),
    MetadataField("dataset_name", "Dataset name", True, "Required."),
    MetadataField(
        "experimental_date",
        "Experimental date",
        True,
        "Required. Use whatever format you actually have; leave blank rather than guess.",
    ),
    MetadataField("organism", "Organism", True, "Required."),
    MetadataField("cell_type", "Cell type", False, "Optional."),
    MetadataField("strain", "Strain", False, "Optional."),
    MetadataField("experiment_type", "Experiment type", True, "Required."),
    MetadataField("measurement_type", "Measurement type", True, "Required."),
    MetadataField("scientific_objective", "Scientific objective", True, "Required."),
    MetadataField(
        "conditions_treatments",
        "Conditions / treatments summary",
        False,
        "Optional free text. Use the Condition / treatment legend table below for a "
        "per-condition-id description.",
    ),
    MetadataField("assay", "Assay", True, "Required."),
    MetadataField(
        "provenance",
        "Provenance",
        True,
        "Required. E.g. lab, instrument, collected by, source file.",
    ),
    MetadataField(
        "processing_normalization",
        "Processing / normalization",
        True,
        'Required. State "raw / unprocessed" explicitly if no processing was applied -- do '
        "not leave blank to mean that.",
    ),
    MetadataField(
        "time_unit",
        "Time unit",
        True,
        "Required if the Data tab's Time column has any values (e.g. minutes, hours, "
        "seconds).",
    ),
)

#: Marker text written into column A, on its own row, immediately before each sub-table --
#: matched by the parser to find where that sub-table starts (never by a fixed row number, so
#: an extra blank row never breaks parsing).
MEASUREMENT_COLUMNS_SECTION_MARKER = "## Measurement column definitions"
CONDITION_LEGEND_SECTION_MARKER = "## Condition / treatment legend"

MEASUREMENT_COLUMNS_HEADER = (
    "Column name (must match a Data tab column exactly)",
    "Unit",
    "Description",
)
CONDITION_LEGEND_HEADER = ("Condition ID", "Description")

__all__ = [
    "BIOLOGICAL_REPLICATE_COLUMN",
    "CONDITION_ID_COLUMN",
    "CONDITION_LEGEND_HEADER",
    "CONDITION_LEGEND_SECTION_MARKER",
    "DATA_SHEET_NAME",
    "MEASUREMENT_COLUMNS_HEADER",
    "MEASUREMENT_COLUMNS_SECTION_MARKER",
    "METADATA_FIELDS",
    "METADATA_SHEET_NAME",
    "NOT_APPLICABLE_TOKENS",
    "SAMPLE_ID_COLUMN",
    "STRUCTURAL_DATA_COLUMNS",
    "TECHNICAL_REPLICATE_COLUMN",
    "TEMPLATE_VERSION",
    "TIME_COLUMN",
    "UNKNOWN_TOKENS",
    "MetadataField",
]
