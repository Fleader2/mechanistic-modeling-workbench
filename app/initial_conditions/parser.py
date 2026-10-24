"""Parses an initial-conditions dataset workbook (``.xlsx`` bytes) into a
``ParsedInitialConditionsWorkbook`` -- never touching a database, a model, or a real Antimony
species/parameter name (identical "a dataset must not require a model" discipline
``app.time_series.parser`` already establishes).

**Long format, not wide.** Unlike the time-series Data tab (one row per sample, one column per
measured species), this Data tab is one row per *target* (e.g. one row per protein or
metabolite) -- there is no time axis, no condition axis, and no independent-variable columns at
all (per task instructions: this dataset sets a model's *initial* species/parameter values "at
the start of an experiment," never a value that itself changes over the course of one).

Two distinct outcomes, mirroring ``app.time_series.parser`` exactly:

* **Malformed** -- the file cannot be opened at all, a required sheet is missing, the Data tab
  has no usable header row, no ``target_name`` column, zero measurement columns, or a duplicate
  column header. ``parse_initial_conditions_workbook`` raises
  ``InitialConditionsWorkbookMalformedError`` -- there is no partial result to preview or save.
* **Parseable, possibly scientifically incomplete** -- everything else becomes a non-blocking
  ``Finding``, including a duplicate ``target_name`` value across rows (never silently merged
  or averaged -- every row is kept; a duplicate target is disclosed here, and is only ever an
  actual blocking problem later, at alias-mapping/binding-resolution time, if the two rows'
  own values genuinely disagree once mapped to the identical model species/parameter -- see
  ``app.persistence.calibration_scenario_evaluation``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.initial_conditions.contract import (
    DATA_SHEET_NAME,
    MEASUREMENT_COLUMNS_SECTION_MARKER,
    MEASUREMENT_UNCERTAINTY_COLUMNS_SECTION_MARKER,
    METADATA_FIELDS,
    METADATA_SHEET_NAME,
    NOT_APPLICABLE_TOKENS,
    STRUCTURAL_DATA_COLUMNS,
    TARGET_NAME_COLUMN,
    TEMPLATE_VERSION,
    UNCERTAINTY_STATISTIC_KIND_TOKENS,
    UNKNOWN_TOKENS,
)
from app.models.enums import MeasurementValueStatus, UncertaintyStatisticKind

FindingSeverity = Literal["BLOCKING", "INFO"]


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: FindingSeverity
    message: str
    field: str | None = None
    column_name: str | None = None
    row_index: int | None = None


class InitialConditionsWorkbookMalformedError(ValueError):
    """Raised only for a structural problem that leaves nothing parseable -- never for a gap
    in the scientific content itself (see module docstring)."""

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        super().__init__("; ".join(f.message for f in findings))


@dataclass(frozen=True, slots=True)
class MeasurementValue:
    status: MeasurementValueStatus
    value: float | None
    raw: str | None


@dataclass(frozen=True, slots=True)
class MeasurementColumnDefinition:
    column_name: str
    display_order: int
    unit: str | None
    description: str | None
    declared_in_metadata: bool


@dataclass(frozen=True, slots=True)
class MeasurementUncertaintyColumnDefinition:
    column_name: str
    measurement_column_name: str
    statistic_kind: UncertaintyStatisticKind
    display_order: int
    unit: str | None
    description: str | None
    declared_in_metadata: bool = True


@dataclass(frozen=True, slots=True)
class DataRow:
    row_index: int
    #: Raw, as-uploaded target identifier -- never matched against a model here (module
    #: docstring). Preserved verbatim, including leading/trailing case, for alias mapping to
    #: later match exactly or let a scientist resolve by hand.
    target_name: str | None
    measurements: dict[str, MeasurementValue]
    measurement_uncertainty: dict[str, MeasurementValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedInitialConditionsWorkbook:
    metadata: dict[str, str | None]
    measurement_columns: list[MeasurementColumnDefinition]
    measurement_uncertainty_columns: list[MeasurementUncertaintyColumnDefinition]
    rows: list[DataRow]
    findings: list[Finding] = field(default_factory=list)


def _classify_cell_value(
    cell_value: object,
) -> tuple[MeasurementValueStatus, float | None, str | None]:
    """Identical to ``app.time_series.parser._classify_cell_value`` -- see its own docstring."""
    if cell_value is None:
        return MeasurementValueStatus.MISSING, None, None
    if isinstance(cell_value, bool):
        return MeasurementValueStatus.UNRECOGNIZED, None, str(cell_value)
    if isinstance(cell_value, int | float):
        value = float(cell_value)
        if not math.isfinite(value):
            return MeasurementValueStatus.UNRECOGNIZED, None, str(cell_value)
        return MeasurementValueStatus.MEASURED, value, str(cell_value)
    if isinstance(cell_value, str):
        text = cell_value.strip()
        if text == "":
            return MeasurementValueStatus.MISSING, None, None
        lowered = text.lower()
        if lowered in NOT_APPLICABLE_TOKENS:
            return MeasurementValueStatus.NOT_APPLICABLE, None, text
        if lowered in UNKNOWN_TOKENS:
            return MeasurementValueStatus.UNKNOWN, None, text
        try:
            value = float(text)
        except ValueError:
            return MeasurementValueStatus.UNRECOGNIZED, None, text
        if not math.isfinite(value):
            return MeasurementValueStatus.UNRECOGNIZED, None, text
        return MeasurementValueStatus.MEASURED, value, text
    return MeasurementValueStatus.UNRECOGNIZED, None, str(cell_value)


def _cell_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _find_section_start(sheet: Worksheet, marker_prefix: str) -> int | None:
    for row_index in range(1, sheet.max_row + 1):
        cell_value = sheet.cell(row=row_index, column=1).value
        if isinstance(cell_value, str) and cell_value.strip().startswith(marker_prefix):
            return row_index + 1
    return None


def _read_subtable(sheet: Worksheet, header_row: int, column_count: int) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    for row_index in range(header_row + 1, sheet.max_row + 1):
        values = [sheet.cell(row=row_index, column=c).value for c in range(1, column_count + 1)]
        if all(v is None for v in values):
            break
        rows.append(tuple(_cell_text(v) for v in values))
    return rows


def _parse_metadata_sheet(sheet: Worksheet) -> tuple[dict[str, str | None], list[Finding]]:
    findings: list[Finding] = []
    label_to_key = {f.label.strip().lower(): f for f in METADATA_FIELDS}
    found_labels: dict[str, str | None] = {}
    for row_index in range(1, sheet.max_row + 1):
        label_cell = sheet.cell(row=row_index, column=1).value
        if not isinstance(label_cell, str):
            continue
        field_def = label_to_key.get(label_cell.strip().lower())
        if field_def is None:
            continue
        found_labels[field_def.key] = _cell_text(sheet.cell(row=row_index, column=2).value)

    metadata: dict[str, str | None] = {}
    for field_def in METADATA_FIELDS:
        value = found_labels.get(field_def.key)
        metadata[field_def.key] = value
        if field_def.key == "template_version":
            if value != TEMPLATE_VERSION:
                findings.append(
                    Finding(
                        "TEMPLATE_VERSION_MISSING_OR_UNRECOGNIZED",
                        "INFO",
                        f"Template version is {value!r}, expected {TEMPLATE_VERSION!r}. "
                        "Parsed as the current version regardless.",
                        field=field_def.key,
                    )
                )
            continue
        if field_def.required and value is None:
            findings.append(
                Finding(
                    "MISSING_METADATA_FIELD",
                    "INFO",
                    f"{field_def.label!r} was left blank.",
                    field=field_def.key,
                )
            )
    return metadata, findings


def _parse_measurement_column_definitions(
    sheet: Worksheet,
) -> dict[str, tuple[str | None, str | None]]:
    declarations: dict[str, tuple[str | None, str | None]] = {}
    section_start = _find_section_start(sheet, MEASUREMENT_COLUMNS_SECTION_MARKER)
    if section_start is None:
        return declarations
    for column_name, unit, description in _read_subtable(sheet, section_start, 3):
        if column_name is not None:
            declarations[column_name] = (unit, description)
    return declarations


def _parse_measurement_uncertainty_definitions(
    sheet: Worksheet,
) -> dict[str, tuple[str | None, str | None, str | None, str | None]]:
    declarations: dict[str, tuple[str | None, str | None, str | None, str | None]] = {}
    section_start = _find_section_start(sheet, MEASUREMENT_UNCERTAINTY_COLUMNS_SECTION_MARKER)
    if section_start is None:
        return declarations
    for column_name, measurement_column_name, statistic_kind_raw, unit, description in (
        _read_subtable(sheet, section_start, 5)
    ):
        if column_name is not None:
            declarations[column_name] = (
                measurement_column_name,
                statistic_kind_raw,
                unit,
                description,
            )
    return declarations


def _parse_data_header(
    sheet: Worksheet,
) -> tuple[dict[str, int], list[tuple[int, str]], list[Finding]]:
    findings: list[Finding] = []
    header_values = list(next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ()))

    structural_by_key: dict[str, int] = {}
    measurement_columns: list[tuple[int, str]] = []
    seen_headers: dict[str, int] = {}

    for zero_based_index, raw_header in enumerate(header_values):
        column_index = zero_based_index + 1
        if raw_header is None or (isinstance(raw_header, str) and raw_header.strip() == ""):
            continue
        header_text = raw_header if isinstance(raw_header, str) else str(raw_header)
        header_text = header_text.strip()
        lowered = header_text.lower()

        structural_match = next((c for c in STRUCTURAL_DATA_COLUMNS if c == lowered), None)
        dedup_key = lowered if structural_match is not None else header_text
        if dedup_key in seen_headers:
            findings.append(
                Finding(
                    "DUPLICATE_DATA_COLUMN_HEADER",
                    "BLOCKING",
                    f"Column header {header_text!r} appears more than once in the Data tab.",
                    column_name=header_text,
                )
            )
            continue
        seen_headers[dedup_key] = column_index

        if structural_match is not None:
            structural_by_key[structural_match] = column_index
        else:
            measurement_columns.append((column_index, header_text))

    if TARGET_NAME_COLUMN not in structural_by_key:
        findings.append(
            Finding(
                "MISSING_TARGET_NAME_COLUMN",
                "BLOCKING",
                "The Data tab has no column named 'target_name' (case-insensitive).",
            )
        )
    if not measurement_columns:
        findings.append(
            Finding(
                "NO_MEASUREMENT_COLUMNS",
                "BLOCKING",
                "The Data tab has no measurement columns -- nothing to import.",
            )
        )
    return structural_by_key, measurement_columns, findings


def parse_initial_conditions_workbook(data: bytes) -> ParsedInitialConditionsWorkbook:
    """Parse ``.xlsx`` bytes into a ``ParsedInitialConditionsWorkbook``. Raises
    ``InitialConditionsWorkbookMalformedError`` (see module docstring) for a structural
    problem; every scientific-content gap instead becomes a non-blocking ``Finding``."""
    try:
        workbook = load_workbook(BytesIO(data), data_only=True, read_only=True)
    except Exception as exc:
        raise InitialConditionsWorkbookMalformedError(
            [
                Finding(
                    "WORKBOOK_UNREADABLE", "BLOCKING", f"Could not open as an .xlsx file: {exc!r}"
                )
            ]
        ) from exc

    missing_sheets = [
        name for name in (METADATA_SHEET_NAME, DATA_SHEET_NAME) if name not in workbook.sheetnames
    ]
    if missing_sheets:
        raise InitialConditionsWorkbookMalformedError(
            [
                Finding(
                    "MISSING_REQUIRED_SHEET", "BLOCKING", f"Required sheet {name!r} is missing."
                )
                for name in missing_sheets
            ]
        )

    data_sheet = workbook[DATA_SHEET_NAME]
    if data_sheet.max_row < 1 or data_sheet.max_column < 1:
        raise InitialConditionsWorkbookMalformedError(
            [Finding("DATA_SHEET_EMPTY", "BLOCKING", "The Data tab has no header row.")]
        )

    structural_by_key, measurement_column_headers, header_findings = _parse_data_header(data_sheet)
    blocking = [f for f in header_findings if f.severity == "BLOCKING"]
    if blocking:
        raise InitialConditionsWorkbookMalformedError(blocking)

    metadata_sheet = workbook[METADATA_SHEET_NAME]
    metadata, metadata_findings = _parse_metadata_sheet(metadata_sheet)
    declared_columns = _parse_measurement_column_definitions(metadata_sheet)
    declared_uncertainty_columns = _parse_measurement_uncertainty_definitions(metadata_sheet)

    findings: list[Finding] = list(metadata_findings)

    uncertainty_column_headers = [
        (index, name)
        for index, name in measurement_column_headers
        if name in declared_uncertainty_columns
    ]
    true_measurement_column_headers = [
        (index, name)
        for index, name in measurement_column_headers
        if name not in declared_uncertainty_columns
    ]

    measurement_columns: list[MeasurementColumnDefinition] = []
    declared_names_used: set[str] = set()
    for display_order, (_, column_name) in enumerate(true_measurement_column_headers):
        declaration = declared_columns.get(column_name)
        if declaration is None:
            findings.append(
                Finding(
                    "MEASUREMENT_COLUMN_UNIT_UNDECLARED",
                    "INFO",
                    f"Data column {column_name!r} has no matching entry in the Metadata "
                    "tab's measurement column definitions -- its unit is unknown.",
                    column_name=column_name,
                )
            )
            measurement_columns.append(
                MeasurementColumnDefinition(column_name, display_order, None, None, False)
            )
        else:
            declared_names_used.add(column_name)
            unit, description = declaration
            measurement_columns.append(
                MeasurementColumnDefinition(column_name, display_order, unit, description, True)
            )
    for declared_name in declared_columns:
        if declared_name not in declared_names_used:
            findings.append(
                Finding(
                    "UNDECLARED_MEASUREMENT_COLUMN_ORPHAN_DEFINITION",
                    "INFO",
                    f"The Metadata tab declares a measurement column {declared_name!r} that "
                    "does not appear in the Data tab.",
                    column_name=declared_name,
                )
            )

    true_measurement_names_present = {name for _, name in true_measurement_column_headers}
    measurement_uncertainty_columns: list[MeasurementUncertaintyColumnDefinition] = []
    uncertainty_index_to_target: dict[int, str] = {}
    targets_claimed: set[str] = set()
    uncertainty_names_present: set[str] = set()
    for display_order, (column_index, column_name) in enumerate(uncertainty_column_headers):
        uncertainty_names_present.add(column_name)
        measurement_column_name, statistic_kind_raw, unit, description = (
            declared_uncertainty_columns[column_name]
        )
        if not measurement_column_name:
            findings.append(
                Finding(
                    "MEASUREMENT_UNCERTAINTY_COLUMN_MISSING_TARGET",
                    "INFO",
                    f"Measurement-uncertainty column {column_name!r} does not name which "
                    "measurement column it describes -- its values are not used.",
                    column_name=column_name,
                )
            )
            continue
        if measurement_column_name not in true_measurement_names_present:
            findings.append(
                Finding(
                    "MEASUREMENT_UNCERTAINTY_COLUMN_TARGET_NOT_FOUND",
                    "INFO",
                    f"Measurement-uncertainty column {column_name!r} names "
                    f"{measurement_column_name!r} as the measurement column it describes, but "
                    "no such measurement column exists -- its values are not used.",
                    column_name=column_name,
                )
            )
            continue
        if measurement_column_name in targets_claimed:
            findings.append(
                Finding(
                    "DUPLICATE_MEASUREMENT_UNCERTAINTY_TARGET",
                    "INFO",
                    f"Measurement-uncertainty column {column_name!r} also names "
                    f"{measurement_column_name!r}, already described by an earlier-declared "
                    "uncertainty column -- only the first declaration is used.",
                    column_name=column_name,
                )
            )
            continue
        statistic_kind = UNCERTAINTY_STATISTIC_KIND_TOKENS.get(
            (statistic_kind_raw or "").strip().lower()
        )
        if statistic_kind is None:
            findings.append(
                Finding(
                    "MEASUREMENT_UNCERTAINTY_COLUMN_STATISTIC_KIND_UNRECOGNIZED",
                    "INFO",
                    f"Measurement-uncertainty column {column_name!r} does not declare a "
                    "recognized statistic (standard deviation / variance / standard error) "
                    "-- its values are not used.",
                    column_name=column_name,
                )
            )
            continue
        targets_claimed.add(measurement_column_name)
        uncertainty_index_to_target[column_index] = measurement_column_name
        measurement_uncertainty_columns.append(
            MeasurementUncertaintyColumnDefinition(
                column_name,
                measurement_column_name,
                statistic_kind,
                display_order,
                unit,
                description,
            )
        )
    for declared_name in declared_uncertainty_columns:
        if declared_name not in uncertainty_names_present:
            findings.append(
                Finding(
                    "ORPHAN_MEASUREMENT_UNCERTAINTY_COLUMN_DEFINITION",
                    "INFO",
                    f"The Metadata tab declares a measurement-uncertainty column "
                    f"{declared_name!r} that does not appear in the Data tab.",
                    column_name=declared_name,
                )
            )

    rows: list[DataRow] = []
    kept_row_index = 0
    target_name_first_seen_at: dict[str, int] = {}
    target_col = structural_by_key[TARGET_NAME_COLUMN]
    for sheet_row_values in data_sheet.iter_rows(min_row=2, values_only=True):
        if all(v is None for v in sheet_row_values):
            continue
        row_index = kept_row_index
        kept_row_index += 1

        target_name = _cell_text(sheet_row_values[target_col - 1])
        if target_name is None:
            findings.append(
                Finding(
                    "TARGET_NAME_MISSING",
                    "INFO",
                    "target_name is blank -- this row cannot be alias-mapped to any model "
                    "species/parameter.",
                    row_index=row_index,
                )
            )
        elif target_name in target_name_first_seen_at:
            findings.append(
                Finding(
                    "DUPLICATE_TARGET_NAME",
                    "INFO",
                    f"target_name {target_name!r} also appears at row "
                    f"{target_name_first_seen_at[target_name]} -- both rows are kept; this "
                    "only becomes a blocking problem if the two rows' own values disagree "
                    "once mapped to the identical model species/parameter.",
                    column_name=TARGET_NAME_COLUMN,
                    row_index=row_index,
                )
            )
        else:
            target_name_first_seen_at[target_name] = row_index

        measurements: dict[str, MeasurementValue] = {}
        any_measured_or_disclosed = False
        for column_index, column_name in true_measurement_column_headers:
            status, value, raw = _classify_cell_value(sheet_row_values[column_index - 1])
            measurements[column_name] = MeasurementValue(status, value, raw)
            if status != MeasurementValueStatus.MISSING:
                any_measured_or_disclosed = True
            if status == MeasurementValueStatus.UNRECOGNIZED:
                findings.append(
                    Finding(
                        "DATA_CELL_UNRECOGNIZED_VALUE",
                        "INFO",
                        f"Value {raw!r} in column {column_name!r} is not numeric and not a "
                        "recognized token.",
                        column_name=column_name,
                        row_index=row_index,
                    )
                )
        if not any_measured_or_disclosed:
            findings.append(
                Finding(
                    "DATA_ROW_ALL_MEASUREMENTS_MISSING",
                    "INFO",
                    "Every measurement column in this row is blank.",
                    row_index=row_index,
                )
            )

        measurement_uncertainty: dict[str, MeasurementValue] = {}
        for column_index, measurement_column_name in uncertainty_index_to_target.items():
            status, value, raw = _classify_cell_value(sheet_row_values[column_index - 1])
            measurement_uncertainty[measurement_column_name] = MeasurementValue(status, value, raw)
            if status == MeasurementValueStatus.UNRECOGNIZED:
                findings.append(
                    Finding(
                        "DATA_CELL_UNRECOGNIZED_VALUE",
                        "INFO",
                        f"Value {raw!r} in uncertainty column for {measurement_column_name!r} "
                        "is not numeric and not a recognized token.",
                        column_name=measurement_column_name,
                        row_index=row_index,
                    )
                )
            elif status == MeasurementValueStatus.MEASURED and value is not None and value < 0:
                findings.append(
                    Finding(
                        "NEGATIVE_UNCERTAINTY_VALUE",
                        "INFO",
                        f"Uncertainty value {raw!r} for {measurement_column_name!r} is "
                        "negative -- uncertainty is never negative; preserved as reported, "
                        "never flipped or discarded.",
                        column_name=measurement_column_name,
                        row_index=row_index,
                    )
                )

        rows.append(
            DataRow(
                row_index=row_index,
                target_name=target_name,
                measurements=measurements,
                measurement_uncertainty=measurement_uncertainty,
            )
        )

    return ParsedInitialConditionsWorkbook(
        metadata=metadata,
        measurement_columns=measurement_columns,
        measurement_uncertainty_columns=measurement_uncertainty_columns,
        rows=rows,
        findings=findings,
    )


__all__ = [
    "DataRow",
    "Finding",
    "InitialConditionsWorkbookMalformedError",
    "MeasurementColumnDefinition",
    "MeasurementUncertaintyColumnDefinition",
    "MeasurementValue",
    "ParsedInitialConditionsWorkbook",
    "parse_initial_conditions_workbook",
]
