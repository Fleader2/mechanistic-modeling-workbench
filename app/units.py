"""Structured unit semantics: a single, project-owned ``pint.UnitRegistry`` plus two pure,
deterministic functions (``resolve_unit_string``, ``compare_units``) that replace fragile
unit-string equality with real dimensional analysis (Structured Units and Dimensional-
Consistency Validation increment).

See ``docs/14_structured_units.md``.

## Library choice

``pint`` (task instructions §1: "preferably using a well-supported units library rather than
custom dimensional algebra") -- confirmed, by direct testing against this Workbench's own real
unit vocabulary (not hypothetical units), to correctly parse and compare every standard
concentration/time/mass/temperature unit already in use by Agent1/Agent2
(``"mM"``, ``"mmol/L"``, ``"1/s"``, ``"umol/min"``, ``"umol/min/mg"``, ``"°C"``, ...).

## Custom unit definitions -- not invented, taught

Four real, already-emitted unit strings are not in pint's own default registry. Confirmed by
direct inspection of the upstream agents' own source (never assumed):

* ``per_sec`` -- Agent2's own ``CANONICAL_UNIT_PER_SEC``
  (``agent2-antimony-builder/app/agent2/parameters/reconstruction.py``), a first-order rate
  constant, physically ``1/second``.
* ``nM_per_s`` -- Agent2's own ``CANONICAL_UNIT_NM_PER_S``, a rate of concentration change,
  physically ``nanomole/liter/second``.
* ``per_nMs`` -- Agent2's own ``CANONICAL_UNIT_PER_NMS``, a second-order rate constant,
  physically ``1/(nanomole/liter * second)``.
* ``cell`` -- from Agent1's own ``"molecules/cell"`` unit string -- a count of cells. Given its
  own new base dimension (``[cell_count]``), deliberately *not* unified with ``[substance]``
  (pint's own default registry already treats ``"molecules"``/``"molecule"`` as the builtin
  ``particle`` unit, dimension ``[substance]`` -- a copy-number ratio like "molecules/cell" is
  not the same physical quantity as a molar amount, so it must not become dimensionally
  comparable to one by accident).

Task instructions §9 ("do not invent missing units"): each definition above is a real,
already-well-defined physical unit (or, for ``cell``, a real counting unit) that Agent1/Agent2
already emit today -- this module only teaches pint their existing meaning, it does not assign
a meaning no one asked for.
"""

from __future__ import annotations

from enum import StrEnum

import pint

_registry = pint.UnitRegistry()
_registry.define("cell = [cell_count]")
_registry.define("per_sec = 1 / second")
_registry.define("nM_per_s = nanomole / liter / second")
_registry.define("per_nMs = 1 / (nanomole / liter * second)")


class UnitParseStatus(StrEnum):
    """Whether one raw unit string could be resolved against the registry (``resolve_unit
    _string``'s own return value) -- the Workbench's own copy of a vocabulary also mapped to a
    real DB column (``app.models.unit_resolution.UnitResolution.parse_status``).

    ``MISSING`` is deliberately distinct from ``MALFORMED``: a ``None``/empty string is *absent*
    information (never fabricated -- task instructions §9), while a non-empty string pint
    cannot parse is a genuine parse failure worth flagging as such.
    """

    PARSED = "PARSED"
    MALFORMED = "MALFORMED"
    MISSING = "MISSING"


class UnitComparisonStatus(StrEnum):
    """The outcome of comparing two raw unit strings (``compare_units``'s own return value).

    Deliberately a *plain* enum, not a mapped DB column type (unlike ``UnitParseStatus``): a
    comparison is never itself persisted in its own table -- every caller that needs to record
    one (a cross-module diagnostic's own evidence, a pre-flight rejection message) already has
    an existing JSON payload column to embed the full ``compare_units`` result into, so a
    dedicated comparison-history table would be unused ceremony, not a real requirement (task
    instructions §5 only asks that a conversion be *recorded*, not that it be in its own table).

    A 1:1 mapping onto task instructions §4's own four detection cases:
    ``COMPATIBLE`` -- equivalent or convertible units (same dimensionality; a conversion_factor,
    possibly ``1.0``, is always reported alongside -- never a silent conversion, task
    instructions §5).
    ``INCOMPATIBLE`` -- both units parse, but their dimensionalities genuinely differ.
    ``MALFORMED`` -- at least one side fails to parse at all.
    ``MISSING`` -- at least one side is ``None``/empty -- never fabricated as any other status.
    """

    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    MALFORMED = "MALFORMED"
    MISSING = "MISSING"


def _is_present(raw: str | None) -> bool:
    return raw is not None and raw.strip() != ""


def resolve_unit_string(raw: str | None) -> dict:
    """Resolve one raw unit string into its structured representation -- a pure, deterministic
    function of ``raw`` alone (task instructions §10: "keep unit normalization deterministic
    and idempotent").

    Returns a dict with keys ``source_unit_string`` (``raw``, preserved verbatim -- task
    instructions §2), ``normalized_unit`` (pint's own short pretty-printed form, e.g.
    ``"mM"``/``"s"``, or ``None`` if unresolvable), ``dimensionality`` (pint's own
    dimensionality string, e.g. ``"[substance] / [length] ** 3"``, or ``None`` if
    unresolvable), and ``parse_status`` (a ``UnitParseStatus`` value).

    A ``None`` or blank/whitespace-only string is classified ``MISSING`` -- never fabricated as
    a guessed unit (task instructions §9). A non-empty string pint's registry (including this
    module's own additional definitions) cannot parse is classified ``MALFORMED``.
    """
    if not _is_present(raw):
        return {
            "source_unit_string": raw,
            "normalized_unit": None,
            "dimensionality": None,
            "parse_status": UnitParseStatus.MISSING.value,
        }

    assert raw is not None
    try:
        unit = _registry.parse_units(raw.strip())
    except Exception:
        # Deliberately broad: pint's own eval-based tokenizer can raise far more than its own
        # ``PintError`` hierarchy on genuinely malformed free text a scientist actually typed
        # (confirmed directly -- e.g. ``TypeError``, ``AssertionError``, ``ZeroDivisionError``
        # for different kinds of unparseable input) -- every one of them means exactly the
        # same thing here: this string is not a real unit, which is already ``MALFORMED``'s
        # own documented meaning. Narrowing this to ``pint.errors.PintError`` alone would let
        # an arbitrary free-text unit string crash every caller instead of disclosing a
        # finding (confirmed by the Read-Only Dataset Inspection and Time-Series Plotting
        # increment's own default-panel grouping, the first caller to compare *every*
        # measurement column's own freely-typed unit string, not just a pre-validated one).
        return {
            "source_unit_string": raw,
            "normalized_unit": None,
            "dimensionality": None,
            "parse_status": UnitParseStatus.MALFORMED.value,
        }

    return {
        "source_unit_string": raw,
        "normalized_unit": f"{unit:~P}",
        "dimensionality": str(unit.dimensionality),
        "parse_status": UnitParseStatus.PARSED.value,
    }


def compare_units(unit_a: str | None, unit_b: str | None) -> dict:
    """Compare two raw unit strings for dimensional compatibility -- the replacement for bare
    string equality (task instructions §7).

    Returns a dict with keys ``status`` (a ``UnitComparisonStatus`` value), ``conversion
    _factor`` (a ``float``, set only when ``status == "COMPATIBLE"`` -- the factor to multiply
    a quantity in ``unit_a`` by to obtain the equivalent quantity in ``unit_b``; ``1.0`` for
    literally identical units, never omitted or silently applied elsewhere -- task instructions
    §5), and ``unit_a``/``unit_b`` (each side's own full ``resolve_unit_string`` result, so a
    caller can always see exactly what was compared).

    Status precedence when both sides have issues: ``MISSING`` is reported if either side is
    missing (regardless of the other side's own status), then ``MALFORMED`` if either side
    fails to parse, then a genuine dimensionality comparison.
    """
    resolved_a = resolve_unit_string(unit_a)
    resolved_b = resolve_unit_string(unit_b)

    if (
        resolved_a["parse_status"] == UnitParseStatus.MISSING.value
        or resolved_b["parse_status"] == UnitParseStatus.MISSING.value
    ):
        status = UnitComparisonStatus.MISSING.value
        conversion_factor = None
    elif (
        resolved_a["parse_status"] == UnitParseStatus.MALFORMED.value
        or resolved_b["parse_status"] == UnitParseStatus.MALFORMED.value
    ):
        status = UnitComparisonStatus.MALFORMED.value
        conversion_factor = None
    elif resolved_a["dimensionality"] != resolved_b["dimensionality"]:
        status = UnitComparisonStatus.INCOMPATIBLE.value
        conversion_factor = None
    else:
        status = UnitComparisonStatus.COMPATIBLE.value
        quantity_a = _registry.Quantity(1.0, unit_a.strip())  # type: ignore[union-attr]
        conversion_factor = float(quantity_a.to(unit_b.strip()).magnitude)  # type: ignore[union-attr]

    return {
        "status": status,
        "conversion_factor": conversion_factor,
        "unit_a": resolved_a,
        "unit_b": resolved_b,
    }


def find_observation_unit_conflict(
    observations: list[dict], boundary_units_by_species: dict[str, str | None]
) -> dict | None:
    """Pre-flight dimensional check (task instructions §6) for a calibration/validation
    request's own observations, *before* any harness call is ever made.

    Each ``observation`` may optionally carry a ``"unit"`` key -- a Workbench-only, additive
    convention (task instructions §8): never required, and never forwarded to or read by
    Agent4/5 (their own request parsers index known keys explicitly, so an extra key is simply
    ignored). When present, it is checked for a genuine dimensional conflict against two
    sources of already-available metadata, never a fabricated one (task instructions §1/§9):

    * ``boundary_units_by_species`` -- the target species' own already-resolved
      ``ModuleBoundaryPort.unit``, when that species happens to also be a boundary species.
    * every *other* observation in the same request for the identical ``target_species_id`` --
      always available, regardless of whether the species has a boundary port at all.

    Returns the first genuinely ``INCOMPATIBLE`` comparison found (a dict carrying the
    offending ``species_id``/observation id(s)/raw units/full ``compare_units`` result), or
    ``None`` if none. Never rejects on ``MALFORMED``/``MISSING`` -- only a confirmed
    dimensional incompatibility is a pre-flight rejection; an unparseable or absent unit is a
    disclosure concern for diagnostics, not grounds to block an otherwise-valid request.
    """
    declared: dict[str, list[tuple[str | None, str]]] = {}
    for observation in observations:
        species_id = observation.get("target_species_id")
        unit = observation.get("unit")
        if species_id and unit:
            declared.setdefault(species_id, []).append((observation.get("observation_id"), unit))

    for species_id, entries in declared.items():
        known_unit = boundary_units_by_species.get(species_id)
        if known_unit:
            for observation_id, unit in entries:
                comparison = compare_units(unit, known_unit)
                if comparison["status"] == UnitComparisonStatus.INCOMPATIBLE.value:
                    return {
                        "species_id": species_id,
                        "observation_id": observation_id,
                        "observation_unit": unit,
                        "boundary_unit": known_unit,
                        "comparison": comparison,
                    }
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                observation_id_a, unit_a = entries[i]
                observation_id_b, unit_b = entries[j]
                comparison = compare_units(unit_a, unit_b)
                if comparison["status"] == UnitComparisonStatus.INCOMPATIBLE.value:
                    return {
                        "species_id": species_id,
                        "observation_id": observation_id_a,
                        "observation_unit": unit_a,
                        "other_observation_id": observation_id_b,
                        "other_observation_unit": unit_b,
                        "comparison": comparison,
                    }
    return None


__all__ = [
    "UnitComparisonStatus",
    "UnitParseStatus",
    "compare_units",
    "find_observation_unit_conflict",
    "resolve_unit_string",
]
