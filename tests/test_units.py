"""Tests for ``app.units`` -- pure, no database dependency."""

from __future__ import annotations

import pytest

from app.units import UnitComparisonStatus, UnitParseStatus, compare_units, resolve_unit_string

pytestmark = pytest.mark.unit


def test_resolve_missing_unit_for_none():
    result = resolve_unit_string(None)
    assert result["parse_status"] == UnitParseStatus.MISSING.value
    assert result["normalized_unit"] is None
    assert result["dimensionality"] is None
    assert result["source_unit_string"] is None


def test_resolve_missing_unit_for_blank_string():
    result = resolve_unit_string("   ")
    assert result["parse_status"] == UnitParseStatus.MISSING.value


def test_resolve_parses_a_standard_concentration_unit():
    result = resolve_unit_string("mM")
    assert result["parse_status"] == UnitParseStatus.PARSED.value
    assert result["normalized_unit"] == "mM"
    assert result["dimensionality"] == "[substance] / [length] ** 3"
    assert result["source_unit_string"] == "mM"


def test_resolve_malformed_unit():
    result = resolve_unit_string("not_a_real_unit_xyz")
    assert result["parse_status"] == UnitParseStatus.MALFORMED.value
    assert result["normalized_unit"] is None
    assert result["dimensionality"] is None
    assert result["source_unit_string"] == "not_a_real_unit_xyz"


def test_resolve_classifies_unparseable_free_text_as_malformed_rather_than_raising():
    # Confirmed directly: pint's own eval-based tokenizer raises plain ``TypeError``/
    # ``AssertionError``/``ZeroDivisionError`` (never its own ``PintError`` subclass) for some
    # genuinely malformed free text a scientist might actually type -- every one of these
    # means exactly the same thing a ``PintError`` would: this string is not a real unit.
    for raw in ("not-a-real-unit!!", "()", "1/0"):
        result = resolve_unit_string(raw)
        assert result["parse_status"] == UnitParseStatus.MALFORMED.value, raw


def test_resolve_custom_agent2_rate_constant_units():
    for raw, expected_dimensionality in (
        ("per_sec", "1 / [time]"),
        ("nM_per_s", "[substance] / [length] ** 3 / [time]"),
        ("per_nMs", "[length] ** 3 / [substance] / [time]"),
    ):
        result = resolve_unit_string(raw)
        assert result["parse_status"] == UnitParseStatus.PARSED.value, raw
        assert result["dimensionality"] == expected_dimensionality, raw


def test_resolve_is_deterministic_and_idempotent():
    first = resolve_unit_string("umol/min/mg")
    second = resolve_unit_string("umol/min/mg")
    assert first == second


def test_compare_equivalent_concentration_units():
    result = compare_units("mM", "mmol/L")
    assert result["status"] == UnitComparisonStatus.COMPATIBLE.value
    assert result["conversion_factor"] == 1.0


def test_compare_equivalent_time_units():
    result = compare_units("per_sec", "1/s")
    assert result["status"] == UnitComparisonStatus.COMPATIBLE.value
    assert result["conversion_factor"] == 1.0


def test_compare_convertible_units_with_nontrivial_factor():
    result = compare_units("nM_per_s", "mM/s")
    assert result["status"] == UnitComparisonStatus.COMPATIBLE.value
    assert result["conversion_factor"] == pytest.approx(1e-6)


def test_compare_incompatible_concentration_and_time_dimensions():
    result = compare_units("mM", "s")
    assert result["status"] == UnitComparisonStatus.INCOMPATIBLE.value
    assert result["conversion_factor"] is None


def test_compare_malformed_unit_on_one_side():
    result = compare_units("mM", "not_a_real_unit_xyz")
    assert result["status"] == UnitComparisonStatus.MALFORMED.value
    assert result["conversion_factor"] is None


def test_compare_malformed_unit_on_both_sides():
    result = compare_units("garbage_one", "garbage_two")
    assert result["status"] == UnitComparisonStatus.MALFORMED.value


def test_compare_missing_unit_on_one_side():
    result = compare_units(None, "mM")
    assert result["status"] == UnitComparisonStatus.MISSING.value
    assert result["conversion_factor"] is None


def test_compare_missing_takes_precedence_over_malformed():
    result = compare_units(None, "not_a_real_unit_xyz")
    assert result["status"] == UnitComparisonStatus.MISSING.value


def test_compare_both_missing():
    result = compare_units(None, "")
    assert result["status"] == UnitComparisonStatus.MISSING.value


def test_compare_embeds_both_sides_full_resolution():
    result = compare_units("mM", "mmol/L")
    assert result["unit_a"]["source_unit_string"] == "mM"
    assert result["unit_b"]["source_unit_string"] == "mmol/L"
    assert result["unit_a"]["normalized_unit"] == "mM"
    assert result["unit_b"]["normalized_unit"] == "mmol/l"


def test_compare_identical_units_have_factor_one():
    result = compare_units("mM", "mM")
    assert result["status"] == UnitComparisonStatus.COMPATIBLE.value
    assert result["conversion_factor"] == 1.0


def test_compare_is_deterministic_and_idempotent():
    first = compare_units("umol/min", "mM/s")
    second = compare_units("umol/min", "mM/s")
    assert first == second
