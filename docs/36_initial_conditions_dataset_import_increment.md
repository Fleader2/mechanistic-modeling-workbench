# 36. Initial-Conditions Dataset Import increment

## 1. Motivation

The Joint Calibration Workflow's own calibration-target dataset (``TimeSeriesDataset``) answers
"how did the system change over time." It has no mechanism for answering a different, equally
real question: "what was the system's own starting state?" A model's own Antimony source
already declares *some* initial species values, but a scientist calibrating the same model
against several cell types needs a different starting abundance profile per cell type --
without retyping numbers by hand, and without conflating that profile with the time-course data
used to actually fit the model.

User's own framing of the gap: *"Each cell type will have a different set of initial protein
and metabolite abundance values at the start of an experiment that will evolve over time. The
time-dependent change information is how the model is calibrated, but we need some mechanism to
import initial species or parameter values without having to manually type them in."*

This increment adds exactly that: a new, long-format dataset type (one row per target species/
parameter, e.g. one row per protein or metabolite), its own model-specific alias mapping, and a
new calibration-binding value source that reads a binding's own value live from a pinned
dataset -- never hand-typed, identical "preserve original data" discipline the existing dose-
column binding already established (docs/31).

## 2. Why a separate dataset type, not a generalization of the existing one

``TimeSeriesDataset`` is wide-format (one row per sample/timepoint, one column per measured
species) and carries a time axis, a condition axis, and replicate identifiers. An initial-
conditions profile has none of those -- it is long-format (one row per target), with no time
axis at all (task instructions: this sets a model's own *initial* values, never a value that
itself changes over the course of an experiment). Forcing one shape to express the other would
mean fabricating a fake time column or fabricating one row per sample where there is no sample
axis at all. Every layer below mirrors its time-series counterpart in spirit but is a
deliberately separate module, exactly the discipline this codebase already applies to
``ModelParameterCatalog`` vs. ``ModelSpeciesCatalog`` (two independently-evolving catalogs from
one harness round trip, never coupled to one shared type).

## 3. Backend: the new dataset type

* ``app/initial_conditions/contract.py`` -- the Metadata/Data tab layout. One structural column,
  ``target_name`` (never ``sample_id``/``condition_id``/``time``). Metadata carries the same
  general fields as the time-series contract minus ``Time unit``, plus the identical
  "Measurement column definitions"/"Measurement uncertainty definitions" sub-tables.
* ``app/initial_conditions/template.py`` -- generates the blank two-tab workbook.
* ``app/initial_conditions/parser.py`` -- parses it. A duplicate ``target_name`` across rows is
  disclosed (``DUPLICATE_TARGET_NAME``, non-blocking) rather than merged or rejected -- both
  rows are kept; it only becomes a real problem later, at binding-resolution time, if the two
  rows' own values genuinely disagree once mapped to the identical model species/parameter (the
  identical "disclose, never silently reduce" discipline the dosing-schedule check already
  established for a varying dose column).
* ``app/models/initial_conditions_dataset.py`` / ``app/persistence/initial_conditions_dataset.py``
  -- ``InitialConditionsDataset``/``InitialConditionsMeasurementColumn``/
  ``InitialConditionsMeasurementUncertaintyColumn``/``InitialConditionsDatasetRow``, 1:1 with
  their own ``DatasetReference`` (``dataset_type="initial_conditions"``), immutable once saved.

## 4. Backend: its own alias mapping

``DatasetModelAliasMappingRevision`` maps a *column header* to a species, because the time-
series Data tab is wide-format. This dataset is long-format, so the thing mapped is each
distinct ``target_name`` *value* actually present in the rows -- a genuinely different shape,
not a reuse.

* ``app/models/initial_conditions_alias_mapping.py`` -- ``InitialConditionsAliasMappingRevision``/
  ``InitialConditionsAliasMappingAssignment``. A target may resolve to either a real species or
  a real independent parameter; ``target_kind`` records which, never left implicit.
* ``app/persistence/initial_conditions_alias_mapping.py`` -- ``save_mapping_revision`` validates
  against whichever of the model's species/parameter catalogs is actually ``AVAILABLE``.
  ``AmbiguousMappingTargetError`` rejects a target id that happens to be real in *both* catalogs
  at once -- never silently resolved one way. ``DuplicateMappingTargetIdError`` rejects two
  distinct ``target_name``s assigned to the identical resolved target. A real, compiled
  ``DERIVED`` parameter is rejected the same way ``app.persistence.calibration`` already rejects
  one as an independent calibration target.
* New enum: ``InitialConditionsAliasMappingTargetKind`` (``SPECIES``/``PARAMETER``).

## 5. Backend: wiring into calibration

* ``CalibrationExperiment`` gets two new, optional columns:
  ``initial_conditions_dataset_id`` and ``initial_conditions_alias_mapping_revision_id`` --
  entirely separate from ``time_series_dataset_id`` (the calibration *target* data). The same
  model can be evaluated against different cell types by pinning a different initial-
  conditions dataset per experiment, while the calibration-target dataset stays whatever it
  already was.
* New persistence functions, mirroring ``set_experiment_mapping`` exactly, one level down:
  ``set_experiment_initial_conditions_dataset`` (pins/clears the dataset; always clears the
  mapping revision too, since a mapping is only ever meaningful for the specific dataset it was
  validated against) and ``set_experiment_initial_conditions_mapping`` (re-pins a mapping
  revision for the dataset already pinned).
* New ``CalibrationBindingValueSource`` value: ``INITIAL_CONDITIONS_DATASET``. A binding with
  this source names its target the same way every other binding does
  (``model_meaning``/``target_component_id``), plus a ``source_column_name`` -- the existing
  field ``DATASET_COLUMN`` already uses, repurposed rather than duplicated, naming which
  measurement column of the pinned initial-conditions dataset to read (e.g. ``"Abundance"``).
* ``add_variable_binding`` requires the experiment to already have an initial-conditions dataset
  pinned before accepting this source, and validates ``source_column_name`` against that
  dataset's own declared measurement columns.
* ``app/persistence/calibration_scenario_evaluation.py``'s ``resolve_scenario`` gets a new
  resolution branch: it looks up the assignment (in the experiment's own pinned mapping
  revision) whose resolved target matches the binding's own ``target_component_id``, then reads
  every dataset row sharing that assignment's own ``target_name``. If those rows' own values
  for the named column disagree, it raises the identical dosing-schedule-style actionable error
  (naming every distinct value found) rather than silently picking one.

## 6. Frontend

* New screens, each mirroring an existing time-series counterpart in spirit but built from
  scratch for the new shape: ``InitialConditionsDatasetsListScreen`` (template download, upload,
  preview, save, saved-datasets list), ``InitialConditionsDatasetDetailScreen`` (read-only
  reopen -- no plotting machinery at all, since there is no time axis to plot),
  ``InitialConditionsAliasMappingScreen`` (per-target decision: Unresolved/Assign/Skip, with a
  Kind selector gating which catalog's picker appears).
* New sidebar nav item, "Initial-conditions datasets," active for its own subtree.
* ``CalibrationJobScreen``'s "Variables, parameters & experimental settings" step gets a new
  "Initial-conditions dataset" sub-section: pin/unpin a dataset, open its alias-mapping screen,
  re-pin to a newer mapping revision when stale -- directly beneath the existing calibration-
  target mapping controls, mirroring their own UI exactly. The binding-creation form gets a
  third ``value_source`` option, "Initial-conditions dataset," whose column picker switches to
  the pinned initial-conditions dataset's own declared measurement columns.

## 7. Testing

Backend: 803/803 passing (767 pre-existing + 17 new persistence tests -- dataset parsing/
persistence, alias-mapping validation including the ambiguous-target and derived-parameter
rejections, and a real end-to-end calibration-binding test that runs the actual harness
subprocess against a real decay model and confirms the predicted trajectory uses the pinned
abundance value (7), never the Antimony source's own baked-in default (10) -- plus 19 new API
tests covering the same surface through real HTTP calls). Ruff clean throughout. Fresh-install
migration round trip (``alembic downgrade base`` -> ``upgrade head``) verified clean.

Frontend: 74/74 passing (66 pre-existing + 8 new router tests). ``tsc --noEmit`` clean, `npm run
build` clean.

## 8. Live verification against real data

Verified end-to-end in a real browser against `workbench_test` (confirmed disposable), using
the user's own real EGFR-Ras Antimony model and a real draft species-abundance workbook
(adapted to the new contract's `target_name` header -- the only required change, since the
draft predates this increment's actual contract):

1. Imported the real Antimony model via the existing import route -- real, harness-verified
   species/parameter catalogs.
2. Uploaded the real abundance file through the new list screen: preview showed all 12 rows
   correctly, including the real duplicate `SOS1` (both values kept, disclosed), two genuinely
   missing values, and every numeric value in 3-sig-fig scientific notation. Saved.
3. Opened the new alias-mapping screen for (dataset, model): both a real species catalog and a
   real parameter catalog were available; assigned `EGFR` to a real, compiled species id
   (`Act_Grb2_SOS1`, confirmed from the live, harness-verified catalog -- not a stand-in),
   skipped `Grb2`, saved revision 1, then revision 2 -- both persisted and reread correctly.
4. Built a calibration job (job/arm/experiment) against a minimal real time-series dataset,
   pinned the real initial-conditions dataset to the experiment, pinned its mapping revision,
   then added a real `INITIAL_VALUE`/`INITIAL_CONDITIONS_DATASET` binding through the actual
   binding-creation form -- the new value-source option and its column picker (correctly
   offering `Abundance`, the pinned dataset's own declared measurement column) both worked, and
   the saved binding displayed correctly in the bindings table.

Test database reset to a clean baseline afterward; both dev servers stopped.

## 9. What this increment does not do

* No dose-response/sweep view -- unrelated to this increment (see the prior session's dose-
  series design discussion); this increment is about *initial* values only.
* A target's own unit comparison uses the dataset's first declared measurement column (in
  practice there is exactly one, e.g. `Abundance`) -- a dataset declaring more than one
  measurement column has no per-column unit distinction in the alias-mapping screen yet.
* No UI bulk-assignment helper (e.g. "assign by exact-name match against the catalog") --
  every target is assigned by hand, identical to how the time-series screen's own columns are.
