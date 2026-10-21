"""Shared workbook-building helpers for the Downloadable Two-Tab Excel Template increment's
own test files (``tests/unit``, ``tests/persistence``, ``tests/api``) -- never duplicated
per file.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook

from app.time_series.template import generate_template_workbook

#: The exact regression fixture supplied with this increment's own task instructions -- a
#: real RAS/MAPK phospho-time-course, units/sample identities/replicate assignments/most
#: metadata deliberately left unspecified (task instructions: "retain those gaps honestly").
#: Row 2 (t=120) has a real, reported zero for ``[pMEKtot]`` -- the "preserve reported zeros"
#: regression case.
FIXTURE_HEADERS = ("Time", "[aRAStot]", "[pMEKtot]", "[pYERKtot]", "[pTpYErk]", "[pBRAFtot]")
FIXTURE_ROWS: tuple[tuple[float, ...], ...] = (
    (0, 2.7, 5.85, 1.31, 2.76, 13.95),
    (120, 11.22, 0, 4.72, 9.43, 12.39),
    (240, 21.89, 43.31, 28.45, 54.07, 9.83),
    (480, 21.22, 58.01, 36.68, 66.44, 9.2),
    (720, 18.09, 41.86, 29.54, 54.34, 9.04),
)


def blank_template_bytes() -> bytes:
    return generate_template_workbook()


def populate_data_tab(
    template_bytes: bytes,
    *,
    headers: tuple[str, ...],
    rows: tuple[tuple, ...],
    metadata: dict[str, str] | None = None,
) -> bytes:
    """Starting from a real template's own bytes, overwrite the Data tab's header row with
    ``headers`` and append ``rows`` beneath it, and set any ``metadata`` scalar field (by its
    exact template label) on the Metadata tab. Every field not named in ``metadata`` is left
    exactly as the blank template already has it -- an honest, disclosed gap, never
    fabricated."""
    workbook = load_workbook(BytesIO(template_bytes))
    data_sheet = workbook["Data"]
    for col, value in enumerate(headers, start=1):
        data_sheet.cell(row=1, column=col, value=value)
    for col in range(len(headers) + 1, data_sheet.max_column + 1):
        # openpyxl's cell(..., value=None) is a no-op, not a clear -- direct attribute
        # assignment is the only way to actually blank out a cell that already has a value.
        data_sheet.cell(row=1, column=col).value = None
    for row_offset, row_values in enumerate(rows, start=2):
        for col, value in enumerate(row_values, start=1):
            data_sheet.cell(row=row_offset, column=col, value=value)

    if metadata:
        metadata_sheet = workbook["Metadata"]
        for row_index in range(1, metadata_sheet.max_row + 1):
            label = metadata_sheet.cell(row=row_index, column=1).value
            if label in metadata:
                metadata_sheet.cell(row=row_index, column=2, value=metadata[label])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def fixture_workbook_bytes(metadata: dict[str, str] | None = None) -> bytes:
    """The supplied regression fixture, populated into a real template -- Metadata left blank
    except whatever ``metadata`` overrides explicitly (default: nothing, matching the task's
    own "retain those gaps honestly" instruction for this specific fixture)."""
    return populate_data_tab(
        blank_template_bytes(), headers=FIXTURE_HEADERS, rows=FIXTURE_ROWS, metadata=metadata
    )


__all__ = [
    "FIXTURE_HEADERS",
    "FIXTURE_ROWS",
    "blank_template_bytes",
    "fixture_workbook_bytes",
    "populate_data_tab",
]
