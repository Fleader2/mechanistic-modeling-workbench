# 34. Whole-Model Antimony Import Increment

Lets a user upload an already-written Antimony text file directly — bypassing the Agent 1 →
Agent 2 build pipeline entirely — and have it verified, cataloged, and made available to every
downstream pipeline (dataset alias mapping, calibration-job arms, whole-model scenario
evaluation) exactly as an Agent2-built model already is. The uploaded file's own bytes,
filename, and checksum are preserved untouched; nothing is silently rewritten, simplified, or
replaced with a generated approximation. Spans three repositories: Agent 2
(`agent2-antimony-builder`), the integration harness (`agent-integration-harness`), and this
repository.

## 1. Architecture

Two **independent** harness round trips run against the uploaded text, never gating one on the
other:

- **Agent 3 verification** (`model_antimony_verification`, pre-existing, unmodified) compiles
  the text with the real `roadrunner` engine and reports the real, executable structure:
  floating/boundary species, compartments, global parameters. This is the authority on "does
  this model actually run," and is what `save_antimony_import` re-checks before ever creating a
  `Model` row.
- **Agent 2 audit** (`model_antimony_import`, new) runs `app.agent2.antimony_import.import_antimony`
  against the same text and reports a structural fidelity audit Agent3-side verification
  cannot provide on its own: assignment/rate/algebraic rule counts, event count, and two
  supplementary enrichments no other source has — `compartment_names` (a compartment id's own
  declared display name, e.g. `extra` → "extracellular space") and `species_compartment_ids`
  (which compartment each species actually lives in).

Agent 2's audit failing (e.g. the file uses a function definition or `InitialAssignment`, both
of which Agent 2 explicitly and correctly rejects — see §3) **never blocks saving**. The model
is still real and Agent3-verified; only the fidelity audit itself is incomplete, and that is
disclosed, never silently dropped — see `ModelImportProvenance.import_succeeded`/
`import_error_kind`/`import_message` and the Overview tab's own "Import provenance" card.

The Workbench (`app/orchestration/model_antimony_import_orchestrator.py`) owns the two-step
preview → save workflow, catalog capture built directly from the verification result's own real
ids (never from Agent 2's structural `antimony_symbol_map`, which does not exist for an
import), and presentation.

## 2. Agent 2: the module-selection bug (found and fixed this increment)

`app.agent2.antimony_import.import_antimony` already existed before this increment (27 passing
tests) and produces the same canonical `ModelSpecification` the build path produces — but a
severe, silent-data-loss bug sat in its module selection:

```python
module_name = antimony.getMainModuleName()
```

`getMainModuleName()` returns Antimony's own implicit `__main` module whenever the file has
*any* top-level statement before the `model` block (for example a bare unit declaration) — an
**empty** module, silently producing zero species/reactions/parameters for a file that
compiles and runs perfectly well. Worse, for a file declaring two or more named models, it
silently picks only the *last* one, discarding the rest with no error at all.

Fixed in `app/agent2/antimony_import/parser.py` with a new `_select_named_module`: it filters
out the implicit `__main` module, requires **exactly one** real named module remain, and raises
a new `AmbiguousAntimonyModuleError` otherwise (multiple named models, or none at all) — a
disclosed rejection, never a silent wrong answer. `ANTIMONY_IMPORT_PARSER_VERSION` bumped
`antimony-import-v1` → `antimony-import-v2` to mark the behavior change. Five new regression
tests cover: a top-level statement before the model block (previously silently empty, now
fixed), a top-level unit declaration (same), two named models (now a disclosed
`AmbiguousAntimonyModuleError`), no named model at all (same), and a single-model file
unaffected (regression guard).

The real, user-supplied EGFR-Ras model (`model EGFR_ERK_combined()`, 44 species, 39 global
parameters, 31 reactions, 3 compartments, 12 assignment rules) has no top-level statement
before its model block, so it was never itself affected by this bug — but the fix is what makes
Agent 2's audit reliable for the broader population of hand-written Antimony files this
increment exists to support, and was found by deliberately probing that exact shape during this
increment's own design phase.

## 3. Supported vs. unsupported Antimony constructs (disclosed, not invented)

| Construct | Agent 3 (execution) | Agent 2 (fidelity audit) |
|---|---|---|
| Species, compartments, reactions, global parameters | Supported | Supported |
| Assignment / rate / algebraic rules | Supported (simulated) | Counted exactly |
| Events | Supported (simulated) | Counted exactly |
| Compartment display names (`is "..."`) | n/a | Supported (`compartment_names`) |
| Function definitions | Supported (simulated) | **Rejected** — disclosed `UnsupportedAntimonyConstructError` |
| `InitialAssignment` | Supported (simulated) | **Rejected** — same |
| Full `UnitDefinition` structure | n/a | **Not parsed** — only the bare unit *symbol* survives, never the defining expression. Disclosed limitation, not required for catalog-level "available units." |

A species or parameter referenced in the file but never declared via the `species`/explicit
keyword (e.g. this model's own `Lig` and `pSOS1`, which resolve as plain parameters) is
correctly treated as a parameter, not invented into a species it was never declared as.

## 4. Model identity is separate from file-content identity

Re-uploading byte-identical content creates a second, fully independent `Model` row with its
own fresh `stable_identifier` (`f"imported::{uuid4().hex}"` — never content-derived), its own
catalog, and its own provenance row. File bytes are still deduplicated at the artifact-storage
layer (`save_model_antimony_text`, content-addressed, pre-existing and unmodified) — so two
uploads of the same file share one stored blob but are two distinct, independently-nameable
models. Verified directly: `tests/persistence/test_model_antimony_import.py::test_reupload_identical_bytes_creates_new_independent_model`.

## 5. Two bugs found and fixed during this increment's own testing

- **Zero-species-compartment exclusion**: `captured_compartments` originally only included a
  compartment with ≥1 species (built via a `Counter` over species), silently dropping a real
  compartment that compiles and runs but happens to have zero species declared in it — exactly
  the real model's own `extra` ("extracellular space") compartment. Fixed by iterating over
  **all** of the verification result's own `compartment_ids` and defaulting the species count to
  0, never omitting a real compartment for having nothing in it.
- **Audit-failure species-exclusion fallback**: when Agent 2's own audit fails outright (e.g. the
  file uses a function definition Agent 3 still executes fine), `species_compartment_ids` comes
  back empty — which originally excluded **every** species from the catalog entirely
  (`unmapped_canonical_species_ids`), even though Agent 3 confirms they are all real. Fixed with
  a `sole_compartment_id` fallback: if the model has exactly one real compartment, every species
  missing from the (failed) audit is unambiguously assigned to it; a genuinely multi-compartment
  model with an unmapped species still honestly excludes it via `unmapped_canonical_species_ids`
  — disclosed, never guessed.

## 6. What was and was not touched

No module-boundary workflow or optimization was added anywhere. `RunRecord.model_id` (already
nullable, already generic) was reused rather than adding a new FK — consistent with
`docs/33`'s own precedent of routing a non-literal-five-agent-pipeline Agent3-backed operation
through `RunStage.AGENT3`. `persist_model_species_catalog`/`persist_model_parameter_catalog`
(already existed, had zero production callers before this increment) are reused completely
unmodified. The Figma file (`4tLH4HX0rdgPxjpNB1aJOW`) was checked read-only — the five "Study
overview" screen variants' own "New Model" button (node `71:556` and siblings) is an unwired
`<Button variant="primary">` with no destination screen designed; this increment builds that
destination from scratch, following the codebase's own established screen conventions, and
reuses that exact button as the entry point (now labeled "Upload Antimony," the only model-
creation path this screen offers, so the explicit label is more honest than the generic
original). No Figma edits were made.

## 7. Test counts (all green, zero regressions)

| Repository | Suite | Result |
|---|---|---|
| Agent 2 | `pytest tests/agent2/test_antimony_import.py` | 32/32 (27 prior + 5 new) |
| Agent 2 | `pytest tests/` (full repo) | 1318/1318 |
| Agent 2 | `ruff check .` | clean (70 pre-existing unrelated findings, untouched) |
| Harness | `pytest tests/harness/test_workbench_model_antimony_import_contract.py` | 11/11 new |
| Harness | `pytest -q` (full repo) | 269/269 (258 prior + 11 new) |
| Harness | `ruff check .` | clean |
| Workbench | `pytest tests/persistence/test_model_antimony_import.py` | 7/7 new |
| Workbench | `pytest tests/api/test_model_antimony_import.py` | 11/11 new |
| Workbench | `pytest tests/ -q --ignore=tests/e2e` (full repo) | 767/767 (749 prior + 18 new) |
| Workbench | `ruff check .` | clean |
| Workbench frontend | `npm run test` | 59/59 (57 prior + 2 new) |
| Workbench frontend | `npx tsc --noEmit` / `npm run build` | clean |

Migration `0023_model_antimony_import` verified upgrade → downgrade → re-upgrade clean against
`workbench_test`, and the full migration history (`alembic downgrade base` → `upgrade head`)
was re-run clean end-to-end immediately before live-browser verification, confirming fresh-
install compatibility.

## 8. Live-browser verification (real EGFR-Ras model, real TS reference data)

Run against `workbench_test` (confirmed disposable via `require_disposable_database` before
every seed), `uvicorn` on :8000 and `vite dev` on :5173, driven by a cached Chromium binary via
Playwright (`npx playwright install` hangs on this machine; see the project's own recorded
workaround). Using the user-supplied `Test_Antimony_model.txt` (the real 44-species EGFR-Ras
model) and `TS_EGFR-Ras.xlsx` (the real time-series reference data):

1. **Upload → preview → save.** Chose the file on the new "Upload Antimony" screen
   (`/projects/{id}/studies/{id}/upload-antimony`, reached from the Modeling Study's own
   "Models" card). Preview reported, live: 44 floating species, 0 boundary species, 3
   compartments, 39 parameters, 12 assignment rules, 0 rate/algebraic rules, 0 events — matching
   Agent 3's own roadrunner-side counts exactly. Saved as "EGFR-Ras live-verification import";
   the resulting Model Overview page showed `source_type: Imported`, `status: Active`, and a
   content-addressed `artifact_reference`.
2. **Antimony tab + import provenance** (both new, both previously-disabled/non-existent). The
   Overview tab's new "Import provenance" card showed the original filename, sha256 checksum,
   supplied source/reference and verification notes, and the fidelity audit (12/0/0 rules, 0
   events) — all real, persisted values. The "Antimony" tab (previously permanently disabled)
   read back the saved source text byte-for-byte, confirmed containing the model's own
   `model EGFR_ERK_combined()` declaration.
3. **Dataset alias mapping with real naming mismatches.** The real `TS_EGFR-Ras.xlsx` file does
   not match this Workbench's own pre-existing two-tab (`Metadata`+`Data`) import template —
   it is a single flat sheet (`Time, pEGFRtot, pGAB1tot, pSHC1tot, pSHP2tot, aRAStot`). This is
   a pre-existing, unrelated-to-this-increment requirement of the dataset importer, not a gap
   this increment introduces; the real column values were reshaped into the existing template
   (every real value preserved exactly, only the sheet layout changed) and uploaded as-is. On
   the dataset's own detail screen, the imported model was selected and all five measurement
   columns were mapped to their real target species — including the two genuine naming
   mismatches the alias-mapping layer exists to resolve: `pSHP2tot` → `pShp2tot` (case) and
   `aRAStot` → `aRas` (different name entirely). Saved as mapping revision 1 (5 assigned, 0
   skipped, 0 unresolved).
4. **Calibration job + whole-model scenario evaluation**, reusing the existing
   Whole-Model Experimental-Scenario Evaluation primitive (`docs/33`) entirely unmodified: a new
   calibration job's one arm referenced the imported model; the mapped dataset was added as a
   `CALIBRATION` experiment (its current alias-mapping revision pinned automatically, exactly as
   documented); one real global parameter (`k_10`) was declared `MODEL_SPECIFIC` with bounds;
   "Complete review" captured revision 1 with zero blocking findings; "Evaluate scenario" (candidate
   value `k_10=2.0`) submitted a real run, processed by
   `scripts/calibration_scenario_evaluation_worker.py`, and **succeeded**, returning a real
   observed-vs-predicted table for all five mapped outputs across all five reference time points.

### The reference-benchmark comparison, disclosed honestly

Simulating the real model at its own stated initial conditions does **not** numerically match
the TS reference data's own t=0 row for several outputs — most visibly `pEGFRtot`: predicted
`0.093` vs. observed `1.14`. This was independently verified during this increment's research
phase to be the real model's own behavior, not a bug: `0.093` is the exact sum of the model's
own stated initial values for `pEgfr_Lig` + `aR_Shc1` + `aR_pShc1`, confirmed byte-for-byte in
the live scenario-evaluation run above. Per this project's standing discipline of never
fabricating reference evidence, both values are shown side by side, unmodified, in the existing
observed-vs-predicted table — no fitting, scaling, or forcing of agreement was applied or would
have been appropriate here; `k_10` was never the parameter whose value drives this particular
discrepancy, and no attempt was made to search for one that does.

The companion dose-series file (`DS_EGFR-Ras.xlsx`) has **no time column at all** — a
dose-response shape, not a time-series one — and so does not fit the existing
`TimeSeriesDataset` importer's schema under any reshaping. This is flagged here as an honest,
disclosed limitation: a dose-response dataset importer is a materially different shape of work,
out of scope for this increment.

## 9. Remaining limitations

- Full `UnitDefinition` structure (defining expression, not just the bare symbol) is not parsed
  by Agent 2's audit — disclosed, not required for catalog-level "available units."
- Dose-response (non-time-series) experimental data has no importer at all in this Workbench;
  demonstrated directly by the real `DS_EGFR-Ras.xlsx` file above.
- A hand-written Antimony file using function definitions or `InitialAssignment` saves
  successfully (Agent 3 executes it) but carries a disclosed, incomplete Agent 2 fidelity audit
  — never a silently wrong one.
