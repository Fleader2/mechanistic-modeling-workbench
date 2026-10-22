"""Unit tests for ``app.time_series.panels.group_columns_into_panels``, the pure default-
display-panel grouping logic for the Read-Only Dataset Inspection and Time-Series Plotting
increment. See ``docs/28_dataset_inspection_and_time_series_plotting_increment.md``.
"""

from __future__ import annotations

from app.time_series.panels import group_columns_into_panels


def test_identical_declared_units_share_one_panel():
    groups = group_columns_into_panels([("a", "mM"), ("b", "mM"), ("c", "mM")])
    assert groups == [["a", "b", "c"]]


def test_identical_units_are_matched_case_insensitively_and_trimmed():
    groups = group_columns_into_panels([("a", "mM"), ("b", " MM "), ("c", "mm")])
    assert groups == [["a", "b", "c"]]


def test_every_column_with_no_declared_unit_shares_one_panel():
    groups = group_columns_into_panels([("a", None), ("b", ""), ("c", "   "), ("d", None)])
    assert groups == [["a", "b", "c", "d"]]


def test_a_declared_unit_never_shares_a_panel_with_an_undeclared_one():
    groups = group_columns_into_panels([("a", "mM"), ("b", None)])
    assert groups == [["a"], ["b"]]


def test_dimensionally_incompatible_units_are_kept_on_separate_panels():
    groups = group_columns_into_panels([("time_like", "s"), ("mass_like", "g")])
    assert groups == [["time_like"], ["mass_like"]]


def test_a_malformed_unit_string_never_shares_a_panel_with_a_real_one():
    groups = group_columns_into_panels([("real", "mM"), ("nonsense", "banana")])
    assert groups == [["real"], ["nonsense"]]


def test_a_unit_string_that_crashes_pints_own_tokenizer_is_still_handled_safely():
    # "not-a-real-unit!!" makes pint's own tokenizer raise a raw TypeError rather than a
    # PintError -- confirmed directly, and fixed at the source in app.units.resolve_unit_
    # string (broadened exception handling) rather than worked around here, since any caller
    # comparing a scientist's freely-typed unit string could hit it, not just this one.
    groups = group_columns_into_panels([("real", "mM"), ("nonsense", "not-a-real-unit!!")])
    assert groups == [["real"], ["nonsense"]]


def test_compatible_but_differently_scaled_units_are_kept_separate_by_default():
    # mM and uM are dimensionally compatible (both concentration) but a thousand-fold apart --
    # combining them on one shared axis without an explicit, disclosed conversion would be
    # misleading, so they are never merged by this default grouping (task instructions: "never
    # silently convert values").
    groups = group_columns_into_panels([("milli", "mM"), ("micro", "uM")])
    assert groups == [["milli"], ["micro"]]


def test_a_true_unit_alias_with_a_1x_conversion_factor_does_share_a_panel():
    # "second" and "sec" are the identical physical unit under different spellings -- no
    # rescale is ever required to combine them, so this is the one case besides literal
    # string equality where columns are grouped together.
    groups = group_columns_into_panels([("a", "second"), ("b", "sec")])
    assert groups == [["a", "b"]]


def test_display_order_is_preserved_within_and_across_groups():
    groups = group_columns_into_panels(
        [("first", "mM"), ("second", None), ("third", "mM"), ("fourth", None)]
    )
    assert groups == [["first", "third"], ["second", "fourth"]]


def test_every_column_appears_in_exactly_one_group():
    columns = [("a", "mM"), ("b", "s"), ("c", None), ("d", "mM"), ("e", "nonsense!!")]
    groups = group_columns_into_panels(columns)
    flattened = [name for group in groups for name in group]
    assert sorted(flattened) == sorted(name for name, _ in columns)
