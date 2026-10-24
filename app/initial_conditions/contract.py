"""Shared constants for the initial-conditions dataset workbook: sheet names, the ``Metadata``
tab's own scalar-field layout, the ``Data`` tab's one structural (non-measurement) column name,
and the missing/unknown/not-applicable token vocabulary.

Deliberately a *separate* contract from ``app.time_series.contract``, never a generalization of
it -- this dataset type has no time axis, no condition axis, and no independent-variable
columns at all (per task instructions: initial species/parameter abundance "at the start of an
experiment," one row per target, never a sampled-over-time series). The Data tab is long-format
(one row per target, e.g. one row per protein or metabolite), the opposite shape of the
time-series Data tab's wide format (one row per sample, one column per measured species) -- see
``app.initial_conditions.parser`` module docstring.

See ``docs/36_initial_conditions_dataset_import_increment.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import UncertaintyStatisticKind

#: Bumped only if this workbook layout itself changes shape in a later increment.
TEMPLATE_VERSION = "1.0"

METADATA_SHEET_NAME = "Metadata"
DATA_SHEET_NAME = "Data"

#: The ``Data`` tab's own one non-measurement, structural column -- matched case-insensitively,
#: trimmed. Every other Data-tab header is a user-defined measurement column (e.g. "Abundance"),
#: preserved verbatim. Unlike the time-series contract's five structural columns, this is the
#: only one: there is no sample_id, condition_id, replicate, or time axis here at all.
TARGET_NAME_COLUMN = "target_name"

STRUCTURAL_DATA_COLUMNS = (TARGET_NAME_COLUMN,)

#: Cell text (case-insensitive, trimmed) recognized as "explicitly recorded as not applicable"
#: -- identical vocabulary to ``app.time_series.contract``, never collapsed into ``MISSING``.
NOT_APPLICABLE_TOKENS = frozenset({"na", "n/a", "not applicable"})
#: Cell text (case-insensitive, trimmed) recognized as "explicitly recorded as unknown."
UNKNOWN_TOKENS = frozenset({"unknown", "unk"})

#: Identical vocabulary to ``app.time_series.contract.UNCERTAINTY_STATISTIC_KIND_TOKENS`` --
#: never inferred, never defaulted.
UNCERTAINTY_STATISTIC_KIND_TOKENS: dict[str, UncertaintyStatisticKind] = {
    "sd": UncertaintyStatisticKind.STANDARD_DEVIATION,
    "std": UncertaintyStatisticKind.STANDARD_DEVIATION,
    "stdev": UncertaintyStatisticKind.STANDARD_DEVIATION,
    "std dev": UncertaintyStatisticKind.STANDARD_DEVIATION,
    "standard deviation": UncertaintyStatisticKind.STANDARD_DEVIATION,
    "variance": UncertaintyStatisticKind.VARIANCE,
    "var": UncertaintyStatisticKind.VARIANCE,
    "se": UncertaintyStatisticKind.STANDARD_ERROR,
    "sem": UncertaintyStatisticKind.STANDARD_ERROR,
    "standard error": UncertaintyStatisticKind.STANDARD_ERROR,
    "standard error of the mean": UncertaintyStatisticKind.STANDARD_ERROR,
}


@dataclass(frozen=True, slots=True)
class MetadataField:
    key: str
    label: str
    required: bool
    guidance: str


#: Order matters -- exact row order the template writes and a human reads, top to bottom.
#: No "Time unit" field (no time axis) -- the one deliberate omission from
#: ``app.time_series.contract.METADATA_FIELDS``, otherwise identical in spirit.
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
    MetadataField(
        "cell_type",
        "Cell type",
        False,
        "Optional, but the one field that distinguishes one cell type's own initial-condition "
        "dataset from another's -- the same model can be evaluated against different cell "
        "types by pinning a different initial-conditions dataset per experiment.",
    ),
    MetadataField("strain", "Strain", False, "Optional."),
    MetadataField("experiment_type", "Experiment type", True, "Required."),
    MetadataField("measurement_type", "Measurement type", True, "Required."),
    MetadataField("scientific_objective", "Scientific objective", True, "Required."),
    MetadataField(
        "conditions_treatments",
        "Conditions / treatments summary",
        False,
        "Optional free text -- this dataset type has no per-row condition_id axis.",
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
)

#: Marker text written into column A, on its own row, immediately before each sub-table --
#: matched by the parser to find where that sub-table starts, identical discipline to
#: ``app.time_series.contract``.
MEASUREMENT_COLUMNS_SECTION_MARKER = "## Measurement column definitions"
MEASUREMENT_UNCERTAINTY_COLUMNS_SECTION_MARKER = "## Measurement uncertainty definitions"

MEASUREMENT_COLUMNS_HEADER = (
    "Column name (must match a Data tab column exactly)",
    "Unit",
    "Description",
)
MEASUREMENT_UNCERTAINTY_COLUMNS_HEADER = (
    "Uncertainty column name (must match a Data tab column exactly)",
    "Measurement column it describes (must match a measurement column name exactly)",
    "Statistic (standard deviation / variance / standard error -- required)",
    "Unit",
    "Description",
)

__all__ = [
    "DATA_SHEET_NAME",
    "MEASUREMENT_COLUMNS_HEADER",
    "MEASUREMENT_COLUMNS_SECTION_MARKER",
    "MEASUREMENT_UNCERTAINTY_COLUMNS_HEADER",
    "MEASUREMENT_UNCERTAINTY_COLUMNS_SECTION_MARKER",
    "METADATA_FIELDS",
    "METADATA_SHEET_NAME",
    "NOT_APPLICABLE_TOKENS",
    "STRUCTURAL_DATA_COLUMNS",
    "TARGET_NAME_COLUMN",
    "TEMPLATE_VERSION",
    "UNCERTAINTY_STATISTIC_KIND_TOKENS",
    "UNKNOWN_TOKENS",
    "MetadataField",
]
