# GUI–Backend Integration Readiness Audit

Audit date: 2026-10-20. Scope: compare the **current** Figma prototype (file key
`4tLH4HX0rdgPxjpNB1aJOW`, fetched live via the Figma MCP server during this audit — not
reconstructed from memory or an earlier description) against the **current** state of
`mechanistic-modeling-workbench`, `agent-integration-harness`, and
`agent1-biochemical-curator` through `agent5-validation-experimental-design`, verified by
reading the actual code (not prior completion reports). Audit and planning only — nothing in
this document changes any backend behavior, scientific algorithm, or the Figma file itself.

## Methodology

The Figma file's own `00 — START HERE · Screen map` frame (node `103:715`) states the intended
navigation hierarchy and explicitly disclaims: *"Design inventory only — implementation status
has not yet been checked against operating code."* This audit is exactly that check.

The file has one page with 7 numbered top-level sections plus the screen map. Each section was
inventoried independently (metadata + screenshots, cross-checked against each other) and
produced **38 distinct real screens/modal states** (duplicate "second-click"/prototype-timing
frames that render no new content are explicitly excluded from the screen count but noted where
they revealed something, e.g. an unfinished interaction). Backend capabilities were verified by
reading the actual Python source in all six repositories — `grep`/direct file reads, not
assumptions — and are cited by file path.

| # | Section (Figma node) | Screens | Role (per the file's own screen map) |
|---|---|---|---|
| 01 | All Projects (`103:695`) | 2 | Browse/create projects; choose Microbial Metabolism or Regulatory Networks |
| 02 | Current Project (`103:698`) | 3 | Project metadata + Modeling Studies list |
| 03 | Modeling Study (`103:701`) | 5 | Study info + models; shared context for datasets/modules/runs |
| 04 | Datasets (`103:703`) | 10 | Dataset catalog → viewer → Edit Aliases; upload, preview, column mapping |
| 05 | Models (`103:706`) + Module set drafts (`112:671`) | 18 + 20\* | All models → model workspace (tabs) → Export Antimony; module-set drafting/saving |
| 06 | All Modules (`103:709`) | 1 (+3 no-op duplicates) | Study-wide module-set catalog grouped by model+version |
| 07 | Runs & Results (`103:712`) | 8 | Configure a run → Review → Run; results; exports |

\* The 20 "Module set drafts and explicit saving" screens are 5 screen *types* (Draft → Save-as-new-set / Save-new-version → Saved confirmation) instantiated 4 times for 4 different model/method combinations — counted once per distinct screen type in the roadmap/mapping below.

---

## 1. Current Figma Screen Inventory

### 01 — All Projects

| Screen | Node | Purpose |
|---|---|---|
| 01 — Projects | `46:112` | Project list table (Project / Mode / Organism·system / Studies), row-select → read-only metadata preview panel, double-click → open project. Inline "Create a new project" panel (mode radio + disabled-until-selected "Create Project" button). |
| 01Create — Create a project | `47:653` | Full-page creation form: 3-column mode picker (Microbial Metabolism / Regulatory Networks / "Shared infrastructure" — informational only, not selectable) + a "Project details" panel whose field labels change per selected mode. |

**Flagged by the audit:** the "Search projects" button has no associated search UI anywhere in the file (destination/behavior unresolved). The mode-selector control is implemented two different ways across the two screens (a discrete radio component on screen 1 vs. a bullet character baked into the label text on screen 2) — the same semantic state, inconsistently represented. The "Project details" form fields show no visible input/editable-field chrome in any state (always pre-filled, never empty) — ambiguous whether real text inputs or a review-only display are intended.

### 02 — Current Project

| Screen | Node | Purpose |
|---|---|---|
| 02 — Yeast Fatty Acid Engineering (PRJ-001) | `46:203` | Project detail: metadata card, "Edit project" button, Modeling Studies table (Study / Scientific question / Models / Datasets), "New Modeling Study" button. Double-click a row to open. |
| 02R — EGFR Drug Response (PRJ-002) | `47:462` | Same template, Regulatory Networks mode. **No "Edit project" button** (present on the other two project screens). Table's second column is labeled "Context" instead of "Scientific question." Bottom button is a named deep-link ("Open erlotinib study") instead of a generic "New Modeling Study" CTA. |
| 02 — Central Carbon Reconstruction (PRJ-003) | `49:368` | Same template as PRJ-001. Contains a real design-file data anomaly: the layer tree holds 4 study records but only 2 render in the (height-clipped) table, and a second, hidden, unlabeled button sits next to the visible "New Modeling Study" button. |

**Flagged by the audit:** Investigator ("Dr. Morgan Lee") and Start date ("16 October 2026") are identical literal values across all three projects — clearly placeholder data, not evidence of real per-project fields being exercised. Column labels, CTA semantics, and button presence are inconsistent across what should be one reusable template.

### 03 — Modeling Study

| Screen | Node | Purpose |
|---|---|---|
| 03 — ACC1 perturbation (ST-001) | `46:314` | Study overview: free-text question, 3 labeled scope fields (Biological scope / Conditions / Success criterion), a pipeline-stage caption, "Edit Study" button, Models table (4 cols: Models/Version/Construction/Calibration·validation), "New Model" button. |
| 03R — Erlotinib response (ST-002) | `47:551` | Same template, regulatory-network field labels (Tissue·cell type / Condition·intervention / Seeds) and a different pipeline caption. Models table here uses a **different 3-column schema** (Model/Version/Description), Version always "—". |
| 03 — Carbon allocation | `52:361` | A visibly lighter template: no study ID, no labeled scope fields — just a one-line question + a model/dataset count + "Project mode" line. |
| 03 — Lipid productivity | `52:475` | Same light template, 1 model. |
| 03 — Reference reconstruction | `52:589` | Same light template, 1 model. |

**Flagged by the audit:** two incompatible Study-information schemas (rich/labeled vs. light/summary) and two incompatible Models-table schemas coexist in one section with no indication which is canonical. Study IDs ("ST-00x") appear only on 2 of 5 example screens.

### 04 — Datasets

| Screen | Node | Purpose |
|---|---|---|
| 04 — Experimental Data | `46:435` | Dataset catalog (Dataset/Measurement type/Samples/Model role/Status), "Upload Data" + "Download Excel template" buttons, row-select preview with a sample data-rows table. |
| 04Viewer — \<dataset\> (×4: WT metabolomics, ACC1 perturbation, Protein abundance, Steady-state flux) | `47:202`, `54:4895`, `54:5043`, `54:5191` | Read-only "column aliases → Antimony identifiers" summary per dataset: Original column / Antimony alias / role / Units / Mapping status. The Protein abundance variant is the file's clearest unresolved/error state ("No matching enzyme species"). The flux variant targets *reaction* observables rather than species. |
| 04Upload — Import experimental data | `47:358` | 3-step wizard (Upload workbook → Review metadata & mapping → Save dataset); documents 4 required workbook sheets (Dataset/Samples/Measurements/Mapping). No drag-and-drop control, no upload-progress/failure state, only one unmapped-analyte row shown even though the schema implies many. |
| 04 Edit Aliases — \<dataset\> (×4) | `74:669`, `74:778`, `74:890`, `74:1004` | Modal: per-row Mapping dropdown (Preserve / Assign / Skip) + target-identifier dropdown; sample-value pager ("Sample N of 24"); "Apply Aliases" is **disabled** when unresolved columns remain (one confirmed client-side-validation-gated submit in the whole file). |
| 04 Alias target picker | `75:899` (+ mirror `75:1202`) | Overlay with exactly two choices: "Assign to \<species\>·\<compartment\>" or "Do not map this column." |

**Flagged by the audit:** no colored/iconic status indicators anywhere in this section — severity ("Ready" vs. "Partial metadata" vs. "No matching enzyme species") is conveyed by wording alone. Observed mapping-status vocabulary: **Preserved, Matched·\<compartment\>, Skipped, Unconfirmed/No matching enzyme species**. Observed target-type vocabulary: **species identifiers** vs. **reaction observables**.

### 05 — Models (+ Module set drafts)

| Screen | Node | Purpose |
|---|---|---|
| Study collection — All models | `60:598` | Model list (Model/Saved version/Status/Modules·partitions), "Build a new model" + "Upload Antimony" buttons. |
| Model workspace tabs (Overview, Compartments, Species, Reactions, Parameters, Antimony, Modules, History) | `46:564`, `48:223`, `48:341`, `48:479`, `48:598`, `48:725`, `48:804`, `46:696` (+ `60:1032`, `60:1163` for other models/sets) | Per-model tabbed workspace. Overview shows a "Values needing review" table (Parameter/Editable value/Units/Evidence/Review) and "Validate model" / "Export Antimony" / "Save new version" buttons. Antimony tab shows a literal source editor + a validation report (syntax/identifiers/scientific warnings). History tab shows a version list with a "Technical provenance (expand)" note. |
| Compare modularizations | `48:923` | Side-by-side MS-001 (Manual) vs. MS-002 (Automated): reaction-membership agreement %, boundary-interface changes, per-reaction/interface review column (Changed/Matched/"Inspect boundary"). Buttons: "Save as new module set," "Export comparison," "Back to modules." |
| Export Antimony (v1.3, v1.4) | `56:1089`, `56:2337` | Named `.ant` file download card. |
| Module set draft → Save-as-new-set / Save-new-version → Saved confirmation (5 screen types × 4 model/method combinations) | `112:672`…`112:1663` | Explicit multi-step save flow with a disclaimer that field values shown are prototype placeholders, not functional inputs yet. Two different draft methods (Manual/Automated) on the same model independently claim to produce the same resulting version label (e.g. both land on "MS-003 · Reference partition · v2") — unreconciled in the mock. |

**Flagged by the audit:** breadcrumb clickability is inconsistently represented (some screens use a componentized, clearly-linked breadcrumb; others a flat, unstyled text string). "Export Antimony" has no equivalent *import* confirmation flow despite "Upload Antimony" existing as a button on the All-models screen. The "Module set draft" screen's own body text promises splitting/merging/renaming modules, but no editing control for any of that exists on the screen.

### 06 — All Modules

One real screen, `60:756` ("All modules / Study collection"): module sets grouped by model+version (3 sets across 2 models in the mock), with filters for Model and Method, and a footer caveat: *"Select a set to inspect its modules. Identical names across sets do not establish module identity."* The three "second click" interaction frames meant to show what happens after selecting a set (`61:1050`/`61:1202`/`61:1354`) are **pixel-identical duplicates of the main screen** — confirmed by MD5 checksum — meaning the prototype never actually demonstrates the module-set detail/selection behavior it names. No "create module set" entry point exists on this screen.

### 07 — Runs & Results

| Screen | Node | Purpose |
|---|---|---|
| Runs & Results (list) | `46:816` | Run table (Run·type / Model·evidence / State / Result), including one inline **Failed** row with an error message ("Missing initial ATP value") — the only error state shown anywhere in this section. "Selected result" detail panel with Review results / Inspect run provenance / Export results buttons. |
| Configure a run (unreviewed) | `48:1033` | Model single-select, 4-way Analysis-type selector (Simulation/Calibration/Validation/Modularization), "Run" button rendered disabled until review completes. |
| Review run | `82:671` | Read-only summary (Model / Evidence & initial conditions / Run settings) plus "Complete review" (→ enables Run), "Return without completing," "Inspect model," "Inspect datasets." |
| Configure a run (review completed) | `99:724` | Same screen, "Run" now enabled. |
| Export study artifacts | `48:1136` | Checkbox-selectable artifact bundle (model+params, module definitions, experimental data, results, comparison/provenance) → named `.zip` package with a stated manifest/reproducibility guarantee. |
| Calibration results · CAL-008 | `48:1246` | Chart (observed vs. simulated), RMSE, one fitted-parameter row with a 95% interval, "Accept as new model version" / "Export results" buttons. |
| Modularization results · MOD-003 | `65:640` | Same comparison UI as the Models-section "Compare modularizations" screen, reached via Runs & Results instead. |

**Flagged by the audit — the most consequential gap in the whole file:** there is **no run-submission lifecycle UI anywhere** (no loading/queued/in-progress/polling state) and **no export-job lifecycle UI** (no progress/success/failure state for "Export selected"). The design jumps directly from "Run enabled" to the list already showing the run as Completed or Failed. Dedicated result screens exist only for **Calibration** and **Modularization** — Simulation and Validation runs appear as rows in the list but have no detail screen of their own anywhere in the file.

---

## 2. GUI-to-Backend Mapping Matrix

Legend: ✅ exists and matches · 🟡 partially exists (real gap remains) · ❌ missing entirely.

### 01 — All Projects

| Interaction | Backend operation needed | Status | Notes |
|---|---|---|---|
| List all projects, with Mode/Organism/Studies-count columns | `list_projects(...)` query | ❌ | No `list_*` function exists for `Project` anywhere in `app/persistence/project.py` — only `persist_project`/`get_project` (by id). The GUI's very first screen cannot be served today. |
| Project row metadata preview | `get_project(session, project_id)` | ✅ | Exists; covers every field the preview panel shows (`app/models/project.py`). |
| Create a project, mode-specific fields | `persist_project(...)` | ✅ | `Project` already carries both metabolic fields (`biological_process`, `strain_genotype_notes`) and regulatory fields (`disease`, `tissue`, `cell_type`) as plain nullable columns — a good match for the GUI's per-mode field sets. |
| "Studies" count column | derived count query | ❌ | No existing query counts `Subproject` rows per project. |
| Investigator / Start date fields | — | ❌ | No investigator/owner or dedicated start-date field exists on `Project` (consistent with "zero auth" finding below); `created_at` is the closest analogue. |

### 02 — Current Project

| Interaction | Backend operation needed | Status | Notes |
|---|---|---|---|
| List a project's Modeling Studies (with Models/Datasets counts) | `list_subprojects(project_id)` + derived counts | ❌ | No `list_subprojects` function exists in `app/persistence/subproject.py` (only `persist_subproject`/`get_subproject` by id). |
| "Edit project" | an update function for `Project` | ❌ | `app/persistence/project.py` has no update path at all — only create (idempotent by `stable_identifier`) and get. |
| "New Modeling Study" | `persist_subproject(...)` | ✅ | Exists and covers `title`/`objective`/`task_type`. |

### 03 — Modeling Study

| Interaction | Backend operation needed | Status | Notes |
|---|---|---|---|
| Study overview (question, scope, success criterion / tissue, condition, seeds) | richer `Subproject` fields or a dedicated Study metadata model | ❌ | `Subproject` (`app/models/subproject.py`) only has `title`/`objective`/`task_type`/`status`/`notes` — no structured scope/condition/success-criterion fields, no stable display id (`ST-001`) the way `Project`/`Model` have `stable_identifier`. The design's own two incompatible schemas (§1) make it unclear what the target shape even is yet — this needs product/design reconciliation before a schema can be finalized. |
| "Edit Study" | an update function for `Subproject` | ❌ | No update function exists. |
| Models table (Version/Construction/Calibration·validation columns) | `list_models(subproject_id)` + derived calibration/validation status | ❌ | No `list_*` function exists for `Model` in `app/persistence/model.py` (only `persist_model`/`get_model` by id). "Construction"/"Calibration · validation" columns have no direct backend field — they'd need to be derived from `RunRecord`/`ModuleExecutionSnapshot` history, which is possible but unbuilt. |

### 04 — Datasets

| Interaction | Backend operation needed | Status | Notes |
|---|---|---|---|
| Dataset catalog list | `list_dataset_references(project_id/subproject_id)` | ❌ | No `list_*` function exists in `app/persistence/dataset_reference.py` (only `persist_dataset_reference`/`get_dataset_reference` by id). |
| "Upload Data" (file upload + parsing wizard) | file storage + an Excel/CSV parsing pipeline | ❌ | `DatasetReference.artifact_reference` is explicitly documented as "opaque... never parsed here" (`app/models/dataset_reference.py`). No upload endpoint, no blob storage, no parser exists anywhere in the Workbench. |
| Column-alias mapping (Original column → Antimony identifier, with Units + Mapping status) | a new "dataset column mapping" concept | ❌ | **No corresponding backend entity exists at all.** `DatasetReference` has no per-column structure, no species/reaction mapping, no mapping-status enum. This is a genuinely new schema surface, not a wiring gap. |
| Units shown per mapped column | `app.units.resolve_unit_string`/`compare_units` | ✅ (as a building block) | The Structured Units increment (this repository's own most recent increment) already gives exactly the dimensional-resolution/compatibility machinery this screen's "Units" column would need — it is just not yet wired to any dataset-column concept, because that concept doesn't exist yet either. |
| "No matching enzyme species" unresolved state | — | ❌ | No equivalent validation exists; would need the mapping feature above plus a lookup against a module's known species/parameter ids (the same `known_component_ids_by_type` helper used by calibration/validation request validation, `app/persistence/model_module.py`, could plausibly be reused here). |
| "Download Excel template" / "Download original" | static file serving | ❌ | No file-serving mechanism exists in the Workbench at all. |

### 05 — Models

| Interaction | Backend operation needed | Status | Notes |
|---|---|---|---|
| All-models list, Status/Modules·partitions columns | `list_models(subproject_id)` + module-set summary | ❌ | Missing list function (see §03); "Modules/partitions" summary has no existing query. |
| "Upload Antimony" (import an existing model) | `import_antimony(antimony_text)` → `persist_model(..., source_type=IMPORTED)` | 🟡 | **Agent2 already has a real, working `import_antimony` parser** (`agent2-antimony-builder/app/agent2/antimony_import/parser.py:454`) that turns real Antimony source into a canonical `ModelSpecification`. Nothing in the Harness or Workbench calls it. `ModelSourceType.IMPORTED` exists as an enum value with zero orchestration wiring (`app/models/enums.py`). This is an **integration gap, not a from-scratch capability gap** — the hard scientific part already exists. |
| Model workspace tabs (Compartments/Species/Reactions/Parameters) | read access to a materialized model's own structure | 🟡 | `ModuleExecutionSnapshot.snapshot_payload` already stores full `species`/`parameters` arrays for a module after a real calibration/validation run (`app/orchestration/module_calibration_orchestrator.py:350-351`) — but only for a *module*, only after a run, and only two of the four tabs' worth of data (no durable `reactions`/`compartments` listing is persisted anywhere). |
| "Export Antimony" | persist + serve the model's own Antimony text | 🟡 | **The actual Antimony text already flows through the pipeline today** — Agent2's own `module_handoff["antimony_text"]` (`agent2-antimony-builder/app/agent2/pipeline.py:339,428`) is returned in the harness result's full `module_handoff` dict, which `request_module_calibration`/`request_module_validation` already receive in full — but both orchestrators explicitly discard it, extracting only `parameters`/`species` into the snapshot (`app/orchestration/module_calibration_orchestrator.py:343-351`). **This is a few-line persistence gap, not an integration gap**: the data is already in hand at the moment it is thrown away. The harness's own transient `artifacts/runs/<run_id>/` output (where the file briefly exists on disk) is explicitly gitignored/regenerable and is deleted by this repository's own tests after use (`app/models/run_record.py`'s own docstring: *"the harness itself owns no persistent run history; the Workbench is the first repository positioned to keep one"* — stated intent never finished). |
| "Values needing review" (parameter Evidence/Review status) | provenance-rich parameter records | 🟡 | A calibration snapshot already carries `fitted_value`/target id and (after the Structured Units increment) can carry `unit`, but has no `evidence_status`/`uncertainty`/`change_reason` fields the mock shows — Agent4's *own* real report is actually richer than what's persisted (`identifiability_findings`, `parameter_correlations`, confidence intervals all already exist in a real `agent4_report`, confirmed directly against a live run output) but the Workbench currently persists only `parameter_estimates`. |
| "Save new version" | `persist_model(..., parent_model_id=...)` | ✅ | `Model.parent_model_id` lineage already exists and is exactly this shape (`app/models/model.py`). |
| Compare modularizations (reaction-membership agreement, boundary-interface changes) | `cross_module_diagnostics_orchestrator` + `module_aggregation_orchestrator` | ✅ — **the single strongest existing match in the whole file** | `run_diagnostics`/`get_current_findings` (`app/orchestration/cross_module_diagnostics_orchestrator.py`) already detect exactly this: shared-boundary-species conflicts, parameter conflicts, and (after the Structured Units increment) real dimensional unit comparisons — with full evidence/provenance traceable back to source `ModuleBoundaryPort`/`RunRecord` rows. `build_module_aggregate` (`app/orchestration/module_aggregation_orchestrator.py`) already rolls up multi-module coverage/completeness. This screen is mostly a visualization problem, not a missing-backend problem. |
| Module set draft → save-as-new-set / save-new-version | a new "explicit module-set save" workflow | ❌ | **No concept of an independently-versioned "module set" exists in the schema at all.** `ModelModule` rows are created once per hierarchical run (`materialize_accepted_modules`, `app/persistence/model_module.py`) and have no separate set-identity/set-version column, no "Manual"/"Automated" method tag, and no draft/working-state distinct from a committed hierarchical-run result. This is a genuine new schema + orchestration surface — not a wiring gap — and the Figma file's own unreconciled "two methods produce the same version label" ambiguity (§1, Models section) means the target data model needs design sign-off before it can be built. |

### 06 — All Modules

| Interaction | Backend operation needed | Status | Notes |
|---|---|---|---|
| Study-wide module-set catalog grouped by model+version | a cross-run, cross-model module-set listing | ❌ | Depends entirely on the "module set" concept above not existing yet. `list_model_modules_for_run(session, run_record_id)` (`app/persistence/model_module.py:106`) only lists modules for *one* hierarchical run — there is no query spanning "every module set ever produced for this study," because nothing durably groups modules into a "set" independent of the run that produced them. |
| Model/Method filters | — | ❌ | Same dependency. |

### 07 — Runs & Results

| Interaction | Backend operation needed | Status | Notes |
|---|---|---|---|
| Runs list (Run/type, Model/evidence, State, Result) | `list_calibration_runs`/`list_validation_runs` + a simulation/modularization-run equivalent | 🟡 | Per-module list functions already exist for calibration (`app/orchestration/module_calibration_orchestrator.py:394`) and validation (`app/orchestration/module_validation_orchestrator.py:535`) — but nothing lists *all* run kinds (simulation, calibration, validation, modularization) together across a whole study the way this one table does. |
| "Configure a run" → model/analysis-type selection | — | ✅ (as inputs) | Every analysis type the selector offers (Simulation/Calibration/Validation/Modularization) already has a real, working Workbench orchestrator (`model_module_orchestrator.request_module_simulation`, `module_calibration_orchestrator.request_module_calibration`, `module_validation_orchestrator.request_module_validation`, `hierarchical_run_orchestrator.submit_hierarchical_run`). The GUI concept of "one Configure screen for all four" is new; the underlying calls are not. |
| "Review" gate before "Run" is enabled | pre-flight request validation | ✅ (as a pattern, not this exact screen) | Every orchestrator above already validates its own request *before* ever invoking the harness (`_validate_calibration_request`, `_validate_validation_request`, the module-boundary readiness gate) — raising a typed error rather than a silent failure. The GUI's explicit two-step "Review → Run enabled" flow doesn't exist as its own backend state machine, but the validation discipline it depends on already does. |
| Run submitted → in-progress → completed/failed, with polling | an async job layer | ❌ | **The single most consequential infrastructure gap in this audit.** Every orchestrator call that reaches the harness today is **fully synchronous** — `subprocess_runner.py`'s own default `timeout_seconds=300.0` is used uniformly across `module_simulation.py`, `module_calibration.py`/`module_calibration_execution.py`, `module_validation_execution.py`, and `module_boundary_derivation.py` (`agent-integration-harness/app/harness/*.py`) — meaning a caller blocks for up to 5 minutes per call. `RunRecord.status` (`PENDING`/`RUNNING`/`REQUIRES_USER_REVIEW`/`SUCCEEDED`/`FAILED`, `app/models/enums.py`) already models exactly the state machine a polling GUI needs — but nothing today *starts* a run in the background and lets a caller poll; `start_run`→subprocess call→`complete_run` all happen inside one blocking function call. |
| "Failed" row with inline error ("Missing initial ATP value") | structured error surfacing | ✅ | `RunRecord.error_summary` plus every orchestrator's own typed validation-error classes already carry human-readable failure reasons; this is a formatting/exposure problem, not a missing-capability one. |
| "Export study artifacts" (checkbox bundle → named `.zip`) | an export-assembly service | ❌ | No export/bundling code exists anywhere in the Workbench (`grep` for `def .*export` across `app/` returns nothing). Every artifact the screen wants to bundle (model+params, module definitions, datasets, run results, comparison/provenance) is already *data the Workbench owns*, just never assembled into a package. |
| Calibration results (chart, RMSE, fitted parameters + 95% CI) | `agent4_report` already carries this | 🟡 | Confirmed directly: a real `agent4_report["calibration"]` already contains `parameter_estimates`, `identifiability_findings`, `parameter_correlations`, and multistart diagnostics. The Workbench persists the full snapshot payload but no dedicated read API surfaces it in the shape this screen wants (time-series observed-vs-simulated specifically needs the underlying Agent3 trajectory, which is part of `agent3_report`, not currently extracted into the snapshot at all). |
| Modularization results / comparison | same as the Models-section "Compare modularizations" mapping | ✅ | See §05 above — this is the same backend capability reached from a second screen. |
| Simulation / Validation dedicated result screens | — | — | No corresponding screens exist in the current design at all (see §1) — nothing to map yet. |

---

## 3. Backend Capability Inventory

Verified directly against source in this session; **Fully** = production-ready end-to-end including tests, **Partially** = real working code exists but with a named, concrete gap, **Missing** = no code exists.

| Capability | Status | Evidence |
|---|---|---|
| Project / Subproject persistence (create, get-by-id) | **Partially** | `app/persistence/project.py`, `app/persistence/subproject.py` — create (idempotent) + get-by-id only; **no list/update/delete for either**. |
| Model persistence (create, get-by-id, lineage) | **Partially** | `app/persistence/model.py` — create + get-by-id + `parent_model_id` lineage; **no list/update**; no durable storage of the actual Antimony text (`artifact_reference` is an opaque, unparsed pointer). |
| ModelBuildRequest (scoped Agent2 builds, 8 child tables for species/reaction/gene-protein/compartment/regulatory-interaction/enzyme-state/pathway/assumption roles) | **Fully** (for what it covers) | `app/persistence/model_build_request.py`, `app/models/model_build_request.py`; live-wired to a real Agent2 subprocess via `run_orchestrator.submit_subproject_run` (`docs/03_workbench_harness_contract.md`). Does not cover Antimony *import* (see below). |
| Antimony model import | **Partially** | The real parser exists and works (`agent2-antimony-builder/app/agent2/antimony_import/parser.py:454`, `import_antimony`); `ModelSourceType.IMPORTED` is a defined-but-unwired enum value (`app/models/enums.py`); no Harness canonical entrypoint or Workbench orchestrator calls it. |
| Antimony model export | **Partially** | The text already reaches the Workbench via a real calibration/validation `module_handoff["antimony_text"]` and is discarded without being persisted (`app/orchestration/module_calibration_orchestrator.py:343-351`); no export/download endpoint exists. |
| Experimental dataset cataloging | **Partially** | `DatasetReference` create/get-by-id exists (`app/persistence/dataset_reference.py`); **no list, no file upload, no parsing, no column-alias/species-mapping concept at all.** |
| Hierarchical modularization (automatic recursive decomposition) | **Fully** | `app/orchestration/hierarchical_run_orchestrator.py`, live-wired to a real Harness/Agent2 subprocess chain, persisted as first-class `HierarchyNode` rows (`docs/04_hierarchical_recursion.md`). |
| Hierarchical review/resume (human-in-the-loop pause/approve/reject) | **Fully** | `app/orchestration/hierarchical_review_orchestrator.py`, crash-safe resume via `HierarchyResumeAttempt` (`docs/05_hierarchical_review_resume.md`, `docs/06_crash_safe_resume.md`). |
| Boundary-condition management | **Fully** | `app/orchestration/module_boundary_orchestrator.py` — derive candidate boundary ports from real Agent2 topology, persist human treatment decisions, compute `execution_status` gating (`docs/08_boundary_condition_semantics.md`). |
| Module-level Agent3 simulation | **Fully** | `app/orchestration/model_module_orchestrator.request_module_simulation`, real subprocess chain (`docs/07_executable_module_materialization.md`). |
| Module-level Agent4 calibration | **Fully**, with immutable provenance | `app/orchestration/module_calibration_orchestrator.py`, `ModuleExecutionSnapshot` (`docs/09_module_level_agent4_calibration.md`). |
| Module-level Agent5 validation | **Fully**, with boundary-condition pinning to the calibration's own conditions | `app/orchestration/module_validation_orchestrator.py` (`docs/10_module_level_agent5_validation.md`, `docs/11_module_validation_boundary_pinning.md`). |
| Hierarchical aggregation (roll-up of module-level results) | **Fully** | `app/orchestration/module_aggregation_orchestrator.py`, immutable/versioned (`docs/12_hierarchical_aggregation.md`). |
| Cross-module consistency diagnostics | **Fully** | `app/orchestration/cross_module_diagnostics_orchestrator.py`, 7-category taxonomy, now unit-aware (`docs/13_cross_module_diagnostics.md`, `docs/14_structured_units.md`). |
| Structured units / dimensional consistency | **Fully** (as a library), **Partially wired** | `app/units.py`, `app/persistence/unit_resolution.py` work and are tested; applied today only to `ModuleBoundaryPort` units, calibration-snapshot parameter units, and an optional observation-level annotation — not yet to any dataset-column concept (which doesn't exist yet either). |
| Scientific provenance (immutable execution snapshots, audit trail) | **Fully** | `ModuleExecutionSnapshot` (`app/models/module_execution_snapshot.py`) captures exact inputs before every harness call, never mutated after creation. |
| Artifact management (durable storage of model/result files) | **Missing** | Real executable content (Antimony text, result files) lives only transiently in the Harness's own `artifacts/runs/<run_id>/` directory, explicitly documented as gitignored/regenerable (`app/models/run_record.py`'s own docstring). No durable Workbench-owned file store exists. |
| REST/HTTP API layer (any repository) | **Missing**, except: | No `fastapi`/`flask`/`uvicorn` dependency and no `app/api`-style directory exists in the Workbench, Harness, or Agent2/3/4/5. **Agent1 alone** has a real `fastapi`+`uvicorn` dependency and a started `app/api/v1/` router — but only `health`/`system` routes are implemented; the full curation API described in its own `04_api_spec.md` is unbuilt, and nothing in the Workbench or Harness calls it today (Agent1's curated output reaches the pipeline only via the Harness's own `run_agent1.py` subprocess runner, a direct DB/library call, not an HTTP call). |
| Asynchronous/long-running job execution | **Missing** | Every harness-invoking orchestrator call is synchronous, with a uniform 300-second subprocess timeout (`agent-integration-harness/app/harness/subprocess_runner.py` and every caller of it). No background-worker/task-queue pattern exists anywhere. |
| Authentication / authorization | **Missing** | No user/account/session model exists anywhere in the Workbench. Every "who did this" field (`ModuleBoundaryPort.decided_by`, `HierarchyReviewDecision.decided_by`, `CrossModuleDiagnostic.reviewed_by`) is free text with no identity system behind it. |
| Microbial-metabolism vs. regulatory-network behavioral divergence | **Missing** (by design, so far) | `ProjectType.REGULATORY_NETWORK` exists purely as an enum label (`app/models/enums.py`); `grep` confirms zero other reference to it anywhere in `app/` — no orchestrator, validator, or persistence function branches on it today. The Figma design's own per-mode field-label switching (§1, §2) has no backend analogue yet beyond `Project`'s already-flexible nullable columns. |

---

## 4. Prioritized Gap Analysis

### P0 — Blockers (nothing in the GUI can function without these)

1. **No REST/HTTP API layer exists anywhere the GUI could call.** Every capability above is a Python function requiring a live `Session` and direct import of `app.*` — unusable from a browser.
2. **No `list_*` query function exists for `Project`, `Subproject`, or `Model`.** The GUI's own first three screens (All Projects, Current Project, Modeling Study) cannot be served even with an API layer added, because the underlying queries don't exist.
3. **No asynchronous job execution model.** Every Harness-invoking call blocks for up to 5 minutes. A synchronous HTTP endpoint wrapping these calls directly would time out or stall a web server's worker pool; this must be solved *before* wiring any "Run"/"Configure a run" screen to a real backend call.
4. **No file upload/storage pipeline.** The Datasets section's entire reason for existing (upload → preview → map columns) has zero backend support — not even a place to put the bytes.

### P1 — Important (needed for a usably complete first vertical slice, not literally impossible without)

5. **No durable Antimony-text storage or export path**, despite the text already being available in-process at calibration/validation time — a comparatively small fix with outsized GUI payoff (unblocks "Export Antimony," "Download Antimony," and the model workspace's Antimony tab).
6. **No dataset column-alias/species-mapping concept.** This is the Datasets section's central feature and has no backend representation at all; needs new schema design, not just wiring — and should reuse the already-built `app.units` machinery for its "Units" column.
7. **No "module set" identity/versioning concept independent of a single hierarchical run.** Blocks the Models-section module-set drafting/saving flow and the entire "06 — All Modules" study-wide catalog. The Figma file's own unreconciled ambiguity here (two draft methods producing the same version label) needs a design decision before this schema can be written.
8. **No update function for `Project`/`Subproject`/`Model`** ("Edit project," "Edit Study" have nothing to call).
9. **No export-assembly service** for the "Export study artifacts" bundle — every ingredient already exists as Workbench-owned data, just never packaged.
10. **No Study-level structured scientific metadata** (question/scope/condition/success-criterion) on `Subproject` — needed once the two Figma-side schema variants (§1, §03) are reconciled by design.
11. **No authentication/identity system.** Workable to defer for a genuinely single-user local deployment (every "who decided this" field already accepts free text), but should be flagged before any multi-user hosting is considered.

### P2 — Future enhancements (real, but not needed for an initial usable GUI)

12. No cross-run, cross-model "all run kinds" listing (today split across per-module-per-kind list functions).
13. No extraction of Agent3's full simulated trajectory into a durable, queryable shape for the "observed vs. simulated" chart (the raw data exists in `agent3_report`, just not persisted in queryable form).
14. No richer per-parameter provenance fields (`evidence_status`, `uncertainty`, `change_reason`) distinct from the raw fitted value, even though Agent4's own real report already contains the diagnostic data (`identifiability_findings`, `parameter_correlations`) to back them.
15. No behavioral divergence for `ProjectType.REGULATORY_NETWORK` beyond already-flexible nullable fields — fine as GUI-level labeling/filtering only, until/unless the agents themselves diverge.
16. No dedicated Simulation/Validation result screens exist in the current design at all — a design gap to raise with the Figma file's owner, not a backend gap.

---

## 5. Recommended Application Architecture

**Guiding principle:** the GUI must never duplicate scientific logic the Harness or Agents already own. Every recommendation below is a thin layer *around* the existing Workbench orchestrators, never a reimplementation of them.

### Frontend
- **React + TypeScript**, a SPA. Matches the Figma file's own component-oriented structure (named, reusable instances for buttons/tables/panels throughout every section inventoried above) and lets an OpenAPI-generated TypeScript client track the backend contract automatically (see API layer below).
- **Charting:** Plotly.js for the scientific visualizations the design calls for (observed-vs-simulated time series, overlaid fit curves, residual plots) — the multi-curve overlay/comparison need (Calibration results, the Antimony validation report, module comparison tables) fits Plotly's strengths better than a simpler dashboard-chart library.
- Component architecture should mirror the Figma file's own navigation hierarchy one-to-one: a persistent app shell (header + left `WORKBENCH`/`PROJECT MODE` sidebar, present identically on all 38 screens) wrapping a router for the 7 section areas.

### REST/API layer around existing Workbench services
- **FastAPI**, following the precedent Agent1 itself already started (`agent1-biochemical-curator/app/api/`) rather than inventing a second convention. Pydantic request/response models wrap the existing `app.contracts.*` dataclasses and `app.orchestration.*` function signatures directly — the API layer's own job is translation and validation-error-to-HTTP-status mapping, never new business logic.
- Every orchestrator's own already-raised, already-typed exceptions (`ModuleCalibrationValidationError`, `ModuleValidationValidationError`, `ModuleBoundaryDerivationError`, `StaleCheckpointError`, `ResumeAttemptInProgressError`, plain `ValueError` for readiness gates) map to structured 4xx responses with a machine-readable code, mirroring the existing `WorkbenchRunErrorCode` enum convention already used at the Harness contract boundary.
- New endpoints are needed for every P0/P1 gap above (`list_projects`, `list_subprojects`, `list_models`, `list_dataset_references`, project/subproject/model update, dataset upload, export-bundle assembly) — these should be written as new `app/persistence`/`app/orchestration` functions first (testable in isolation, matching this repository's own established pattern), with the FastAPI route as a thin final wrapper.

### Database
- No change: PostgreSQL remains the system of record. New tables (dataset column mappings, module-set identity/versioning, richer Study metadata) follow the exact conventions already established across this codebase's 12 prior migrations (immutable-where-provenance-matters, `ON DELETE RESTRICT` for durable records vs. `CASCADE` for subordinate rows, idempotency via content fingerprinting).

### Harness and agent subprocess execution
- Unchanged. The API layer calls the exact same `app.orchestration.*` functions that already call the Harness's canonical entrypoints as subprocesses. No new direct-to-Harness or direct-to-Agent wiring should be added anywhere in the GUI stack.

### Long-running task management and progress reporting
- Start with the **simplest viable option**: a thread-pool-backed background task runner inside the FastAPI process itself (no separate broker/Redis needed for a standalone local deployment). Each submission creates a `RunRecord` in `PENDING` immediately and returns its id; a worker thread then runs the existing orchestrator call (`start_run` → subprocess → `complete_run`, already the exact sequence every orchestrator uses today) and the GUI polls `GET /runs/{id}` for status. `RunRecord.status`'s existing five-value state machine (`PENDING`/`RUNNING`/`REQUIRES_USER_REVIEW`/`SUCCEEDED`/`FAILED`) is already the right shape for this — no new state machine needs inventing.
- Upgrade path (not needed for v1): Celery/RQ + Redis if concurrent multi-user load grows past what an in-process thread pool can handle.

### File upload/download and scientific data exchange
- Local filesystem storage for the standalone deployment mode (e.g. a Workbench-owned `artifacts/datasets/` and `artifacts/exports/` directory, mirroring the naming convention the Harness already uses for its own transient `artifacts/runs/`), with `DatasetReference.artifact_reference`/export-bundle paths pointing into it. Upgrade path to S3-compatible object storage if/when a hosted multi-user deployment is needed — the `artifact_reference` field is already an opaque string, so this swap requires no schema change.

### Model visualization and scientific results presentation
- Served by the REST layer reading already-persisted `ModuleExecutionSnapshot`/`ModuleAggregate`/`CrossModuleDiagnostic` rows — no new computation, only new read endpoints and frontend rendering.

### Local standalone deployment, with a path to future multiuser support
- Docker Compose bundling Postgres + the FastAPI app + the built frontend, matching the "practical approach for running locally" requirement. Authentication is explicitly deferred for this mode (a single implicit "Local workspace · Scientist" identity, exactly as the Figma header already literally displays on every screen) with a clearly-marked upgrade seam (the free-text `decided_by`/`reviewed_by` fields) for adding real identity later without a schema migration being forced by the GUI's own arrival.

---

## 6. Phased Implementation Roadmap

Each phase is independently testable and ships value before the next begins. Phases are ordered to resolve P0 blockers first, then unlock the Figma file's own stated navigation order (Projects → Current Project → Modeling Study → Datasets/Models/Modules/Runs & Results).

| Phase | Scope | Unblocks |
|---|---|---|
| **0 — Foundations** | FastAPI app skeleton (health check, error-mapping middleware); `list_projects`/`list_subprojects`/`list_models`/`list_dataset_references` + update functions for `Project`/`Subproject`/`Model`; background-task runner wrapping existing orchestrator calls, with a `GET /runs/{id}` polling endpoint. | P0 #1–3. Nothing GUI-visible yet, but every later phase depends on this. |
| **1 — Projects & Studies** | `GET/POST /projects`, `GET/POST /subprojects`, `GET/POST /models` (thin wrappers over Phase 0's functions); matching React screens for "01 — All Projects," "02 — Current Project," "03 — Modeling Study" (using whichever of the two Figma-side schema variants design confirms as canonical). | Sections 01–03 of the Figma file, read+create paths. |
| **2 — Datasets** | File upload endpoint + local-disk storage; a new `DatasetColumnMapping`-style table and orchestration (reusing `app.units` for the Units column, and `known_component_ids_by_type` for species/reaction-id lookups); Datasets catalog/viewer/Edit-Aliases screens. | Section 04. |
| **3 — Model workspace & Antimony import/export** | Wire Agent2's existing `import_antimony` through a new Harness canonical entrypoint + Workbench orchestrator; persist `antimony_text` into `ModuleExecutionSnapshot` (or a new durable `Model`-level artifact store) instead of discarding it; Export-Antimony download endpoint; model workspace tabs reading already-persisted species/parameter data. | Most of Section 05 (excluding module-set drafting). |
| **4 — Module sets** | Design sign-off on the module-set identity/versioning schema (resolving the Figma file's own unreconciled ambiguity first); new schema + orchestration; module-set draft/save screens; "06 — All Modules" study-wide catalog. | Section 06, remainder of Section 05. |
| **5 — Runs & Results** | `POST /runs` (model + analysis-type selection) atop Phase 0's async runner; Review/Configure-a-run screens; Runs list with live polling; Calibration-results screen reading existing `agent4_report` data; Modularization-results screen reading existing `cross_module_diagnostics_orchestrator`/`module_aggregation_orchestrator` output (the strongest existing backend match in the whole audit). | Section 07, minus export. |
| **6 — Export** | Export-bundle assembly service (model + params, module definitions, datasets, results, provenance → a named `.zip`); Export-study-artifacts screen; export-job progress state (the one lifecycle gap this phase must not reintroduce). | Remainder of Section 07. |
| **7 — Hardening** | Multi-user authentication (if/when needed), S3-compatible storage upgrade (if/when needed), dedicated Simulation/Validation result screens (pending a Figma design update), richer per-parameter provenance fields. | P2 items. |

---

## 7. Recommended First Implementation Increment

**Scope:** Phase 0 ("Foundations") plus the read-only half of Phase 1 ("Projects & Studies") — i.e., make the Figma file's own literal entry point ("01 — All Projects," node `46:112`) real, end to end, without yet building creation/editing or any later section.

This is the safest, highest-leverage first increment under the current uncertainty: it resolves the single most-blocking gap (no API layer, no list queries) and delivers the one screen every other screen in the file is reachable from, while deliberately deferring every decision that still needs design sign-off (the two incompatible Study schemas, the module-set versioning model) rather than guessing at them.

**In scope:**
- `app/persistence/project.py`: add `list_projects(session) -> list[Project]`.
- `app/persistence/subproject.py`: add `list_subprojects(session, project_id) -> list[Subproject]` (used by the project-detail preview this increment also needs, even though full Section-02 screens are out of scope).
- A new `app/api/` package: FastAPI app factory, a health-check route, an error-handling middleware mapping `ValueError`/the existing orchestrator-specific validation-error classes to structured JSON error responses, and:
  - `GET /api/v1/projects` → calls `list_projects`, returns every field the "01 — All Projects" table and preview panel show (`Project` + a derived `study_count` via `list_subprojects`-backed count, per project).
  - `GET /api/v1/projects/{project_id}` → calls `get_project` (already exists), for the row-select preview panel.
- Minimal React scaffold: app shell (header + left sidebar, matching the Figma file's persistent chrome) + the "01 — All Projects" table/preview screen only, calling the two endpoints above. No create-project form yet (that is explicitly Phase 1's remaining, out-of-scope half, since the mode-selector inconsistency flagged in §1 should be resolved with design first).

**Explicitly out of scope:** project creation/editing, any Section 02–07 screen, authentication, async job execution (not needed yet — this increment adds no new Harness-invoking call).

**Files/components affected:**
- New: `app/persistence/project.py::list_projects`, `app/persistence/subproject.py::list_subprojects`, `app/api/__init__.py`, `app/api/main.py`, `app/api/v1/routes/projects.py`, `app/api/v1/schemas/project.py` (Pydantic response models), `pyproject.toml` (add `fastapi`/`uvicorn` to `dependencies`).
- New frontend package (outside this repository's current scope, or a new top-level directory if co-located): app shell component, a `ProjectsListScreen` component, a typed API client (hand-written or OpenAPI-generated from the new FastAPI app's own schema).
- No existing file's behavior changes — this is purely additive.

**Acceptance criteria:**
1. `list_projects`/`list_subprojects` are pure additive persistence functions with their own unit tests (empty list, single project, multiple projects, correct ordering) — no existing test regresses.
2. `GET /api/v1/projects` returns 200 with a JSON array matching every column the Figma "01 — Projects" table shows (Project/Mode/Organism·system/Studies), verified against a real seeded database in a test.
3. `GET /api/v1/projects/{id}` returns 200 with every field the "Selected project metadata" panel shows, and 404 (not a 500) for an unknown id.
4. The React screen, run locally against the new API, visually matches node `46:112`'s table/preview layout for a seeded set of projects (manual comparison against the Figma screenshot already captured during this audit is sufficient — no pixel-diff tooling required for this first increment).
5. `ruff check`/`ruff format --check` and the full existing Workbench test suite pass with zero regressions, exactly as every prior backend increment in this repository has required.

**Testing requirements:** persistence-layer tests for both new `list_*` functions (`tests/persistence/`, following this repository's existing `pytest.mark.database` convention); API-layer tests using FastAPI's `TestClient` against a seeded test database (new `tests/api/` directory); one manual, screenshot-compared frontend verification (no automated visual-regression tooling required yet, since this is the first frontend code in the repository).

---

## Summary

The Figma prototype is far more complete and internally self-aware than a first glance suggests — it documents its own scope, flags several of its own inconsistencies in body text, and in two places (the module-set comparison screens) describes a capability the Workbench backend has *already fully built*, just never exposed through a UI. The single largest structural problem is that **no part of this five-agent system exposes an HTTP API today** — the Workbench's substantial, well-tested orchestration layer (hierarchical modularization, boundary-condition review, module-level simulation/calibration/validation, aggregation, unit-aware cross-module diagnostics) is reachable only from Python. The second-largest problem is that several of the GUI's own central features — dataset column-alias mapping, and module-set identity/versioning — have **no corresponding backend concept at all yet**, not because the wiring is missing but because the schema itself doesn't exist. Everything else in this audit sits between those two extremes: real capabilities, a few API calls away from being usable, or small persistence gaps (most notably: Antimony model text already flows through the pipeline and is simply discarded) a few lines away from being closed.

**Recommended architecture:** React + TypeScript frontend, a new FastAPI layer (following Agent1's own started-but-unfinished precedent) wrapping the existing Workbench orchestrators without duplicating any scientific logic, a simple in-process background-task runner built on `RunRecord`'s already-correct status state machine (no broker needed for the standalone local deployment this requires first), and local-filesystem artifact storage with a clean upgrade seam to object storage later.

**Recommended first increment:** build the REST API layer's foundations (list queries, FastAPI skeleton, error mapping) and make exactly one screen — "01 — All Projects," the Figma file's own stated starting point — real end to end. It is the smallest increment that proves the whole integration approach works, without having to guess at any of the design decisions (Study schema, module-set versioning) that this audit found still need resolving with whoever owns the Figma file.
