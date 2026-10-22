"""Grouping a time-series workbook's own measurement columns into default display panels by
declared-unit compatibility, for the Read-Only Dataset Inspection and Time-Series Plotting
increment (``docs/28_dataset_inspection_and_time_series_plotting_increment.md``).

Reuses ``app.units.compare_units`` -- the project's one source of truth for unit comparison --
rather than any bespoke string matching (task instructions: "use existing units machinery").
Two columns are only ever placed on the same default panel when doing so requires no implicit
rescaling of either one's own real values: either their declared unit strings are identical
after trimming/case-folding (including both being left undeclared, which groups into one
shared "unit not declared" panel -- the common case, never treated as a reason to assume
compatibility with anything *else*), or ``compare_units`` reports them ``COMPATIBLE`` with a
conversion factor of exactly ``1.0`` (a genuine spelling alias for the identical physical
unit, e.g. two ways of writing the same thing). Any other relationship -- incompatible
dimensionality, a parse failure on either side, one side declared and the other not, or a
*compatible-but-rescaled* unit pair (``mM`` vs. ``uM``) -- keeps the two columns on separate
panels by default, since combining them on one shared axis would otherwise require a silent,
undisclosed rescale (task instructions: "never ... convert units").
"""

from __future__ import annotations

from app.units import UnitComparisonStatus, compare_units


def _share_panel(unit_a: str | None, unit_b: str | None) -> bool:
    normalized_a = (unit_a or "").strip().lower()
    normalized_b = (unit_b or "").strip().lower()
    if normalized_a == normalized_b:
        # Covers both "identical declared string" and "both left undeclared" -- the latter is
        # deliberately treated as one shared bucket, never fragmented per-column, since there
        # is no positive evidence any two undeclared-unit columns are actually incompatible.
        return True
    if not normalized_a or not normalized_b:
        # One side declared, the other not -- never assumed compatible with a genuinely
        # unknown unit.
        return False
    comparison = compare_units(unit_a, unit_b)
    if comparison["status"] != UnitComparisonStatus.COMPATIBLE.value:
        return False
    factor = comparison["conversion_factor"]
    return factor is not None and abs(factor - 1.0) < 1e-9


def group_columns_into_panels(columns: list[tuple[str, str | None]]) -> list[list[str]]:
    """``columns`` as ``(column_name, unit)`` pairs, in display order. Returns groups of
    column names (each group in display order; groups themselves in first-appearance order),
    with each column name appearing in exactly one group."""
    #: Each entry is ``(representative_unit, column_names)`` -- the representative is simply
    #: the first column's own unit, never recomputed as the group grows.
    groups: list[tuple[str | None, list[str]]] = []
    for column_name, unit in columns:
        placed = False
        for representative_unit, group in groups:
            if _share_panel(representative_unit, unit):
                group.append(column_name)
                placed = True
                break
        if not placed:
            groups.append((unit, [column_name]))
    return [group for _, group in groups]


__all__ = ["group_columns_into_panels"]
