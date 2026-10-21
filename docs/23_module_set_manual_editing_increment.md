# Module-Set Manual Editing Increment: Rename a Module, Reassign Its Reactions

Builds on `docs/21_module_set_first_increment.md` (draft/inspect/save/reopen for an unedited
draft) and `docs/22_database_configuration_and_verification_safety.md` (the disposable-database
guard and independent-session test pattern this increment reuses throughout). Updates
`docs/20_module_set_domain_contract.md` where its original "deferred" language no longer holds.

Scope, exactly as asked: create an editable draft from a *saved version* (not only from a run);
rename a module; move a reaction between modules within that draft; server-side validation of
every change; invalidating (never silently carrying forward) a membership-edited module's
boundary ports; showing changes and blocking findings before save; preserving every earlier
version, source-run provenance, and historical execution record; marking edited origin; and
discard/stale-edit-conflict/loading/error states. Split/merge, new execution workflows,
cross-model-version editing, database cleanup, and Figma changes are all out of scope, exactly as
asked.

## The question this increment had to answer first: can reaction membership even be validated?

A dedicated research pass (grepping every "reaction"/"component_id" reference, reading
`docs/07_executable_module_materialization.md`/`docs/08_boundary_condition_semantics.md`, and
checking Figma for any actual editing screen) answered this before any code was written:

- **Yes, real, stable reaction identity exists and is already reusable.** `HierarchyNode.
  attach_payload`/`ModelModule.attach_payload` carries `memberships: [{module_id, component_type,
  component_id}, ...]`, and `component_id` for a `REACTION` membership is Agent 2's own
  canonical, whole-network reaction id (`ModuleComponentType`/`ModuleMembership` in
  `agent2-antimony-builder/app/agent2/types.py`) -- never a synthetic or name-derived value.
  `app/persistence/model_module.py::known_component_ids_by_type` already parses this, filtered to
  one module's own membership, and is already relied on by calibration/validation for
  `PARAMETER`/`SPECIES` -- this increment is simply the first caller to pass it `"REACTION"`.
- **No, the Workbench cannot independently confirm a *model's total* reaction count.** Nothing
  anywhere re-verifies that a hierarchy node's children's memberships actually *partition* their
  parent's reactions (no duplicates, nothing missing) -- that guarantee, if it holds at all, holds
  only because Agent 2's own search algorithm happened to construct an accepted decomposition that
  way; the Workbench has only ever trusted the harness's result. There is also no live,
  already-built code path that would hand back "every reaction this model actually has" --
  `derive_boundary_ports`'s own harness round-trip answers a different question (which species
  cross a boundary), not a reaction list.
- **Resolution, reported here rather than silently assumed away:** validation is scoped to the
  draft's own already-known universe, computed once at draft-creation time from whichever
  members the draft already has (either a run's materialized modules, or a prior saved version's
  own current state) -- never against some independently-verified "true" model-wide reaction
  count. A reaction can be redistributed among the modules that already jointly cover it; it can
  never be invented, and it can never be validated against ground truth the Workbench does not
  have. This is the honest, implementable version of "preserve reaction identity, never infer
  membership from names," not a claim that the Workbench can prove global completeness.
- **No Figma editing screen exists to match.** Every "Module set draft" frame in file
  `4tLH4HX0rdgPxjpNB1aJOW` shows the identical static caption ("Split, merge, rename or change
  module membership in this draft...") with no input, list control, or drag target anywhere --
  descriptive mock copy asserting the capability conceptually, never a rendered editor. The one
  related screen that *is* fully built (`48:947`+, "Reaction membership agreement" between two
  saved versions) is a read-only comparison, explicitly the already-excluded partition-comparison
  feature. The editor built here is therefore a from-scratch, functional design -- a disclosed
  deviation, not an attempt to match a mock that does not exist.

## Validation rules (the "explicit documented rules" the task asked for)

- **Hierarchy rule.** A reaction may only move between *sibling* modules -- those sharing the
  same `ModelModule.parent_model_module_id` (including multiple top-level modules, which share
  `NULL`). The move control only ever offers siblings as targets in the first place; an
  out-of-group id is never even presentable, let alone merely rejected after the fact.
- **Source-model membership rule.** A proposed reaction id must already be known to that
  sibling group, as of the draft's own creation (`original_reaction_component_ids`, frozen then,
  never re-derived from a module's live `attach_payload` afterward). An unknown or invented id is
  rejected outright (422) -- never silently accepted, never matched by name.
- **No duplication, by construction, not by afterward-checking.** Moving a reaction into module
  A that a sibling B currently owns silently removes it from B within the same transaction. A
  reaction duplicated across two members is therefore not a state the database can ever reach,
  not merely a state `validate_draft` would flag.
- **Unassigned-reaction and empty-module findings.** A reaction removed from its owner without
  yet being reassigned elsewhere is allowed to exist, transiently, mid-edit -- `validate_draft`
  reports it (`UNASSIGNED_REACTION`), and `save_draft` refuses to proceed while any such finding
  exists (`ModuleSetDraftValidationFailed`, 422 with every finding in the error context). A
  module edited down to zero reactions is flagged the same way (`EMPTY_MODULE`) -- a module with
  no scientific content is never silently allowed to save.
- **Rename rule.** Any non-empty, trimmed string. Not required to be unique across a draft's own
  members (not asked for, and inventing that requirement would be unrequested scope).

## Backend: schema

Migration `0014_module_set_editing`, purely additive, no column dropped or altered:

- `module_set_draft.edit_version` (`Integer NOT NULL DEFAULT 0`) -- optimistic-concurrency
  token, incremented by every successful member edit.
- `module_set_draft_member.display_name`/`.reaction_component_ids`/`.
  original_reaction_component_ids` (all `Text`, nullable, JSON-encoded) -- the live/edited and
  frozen-original snapshot a draft member's own edits and every validation check diff against.
- `module_set_member.display_name`/`.reaction_component_ids` (`Text`, nullable) -- carried onto
  a saved version's own immutable rows. `NULL` means "never edited," identical to every
  increment-21 row, which this migration leaves completely untouched.

`ModelModule.run_record_id` stays exactly as it was -- the schema change `docs/20` §2.1 found
blocked by four live execution entrypoints is still not needed, because editing only ever
changes a draft/version member's own overlay columns, never materializes a new `ModelModule`.

## Backend: persistence and API

`app/persistence/module_set.py` gained: `create_draft_from_version` (seeds an editable draft
from a saved version's own current member state -- each new member's `original_
reaction_component_ids` is that *version's* own current truth, so a second edit round diffs
against what was actually saved, not re-derived from `ModelModule` as if nothing had ever
happened); `edit_draft_member` (rename and/or reassign, enforcing every rule above, raising
`ModuleSetDraftStaleEdit` on an `expected_edit_version` mismatch); `validate_draft` (pure,
read-only, scoped per hierarchical sibling group); and `save_draft`'s own new pre-flight call to
`validate_draft`, raising `ModuleSetDraftValidationFailed` before touching anything if any
finding exists. Four new routes: `POST .../module-sets/{id}/versions/{v}/edit`,
`PATCH .../module-set-drafts/{id}/members/{id}`, `GET .../module-set-drafts/{id}/validation`,
plus the existing boundary-ports routes now return `409 CONFLICT` for a membership-edited
member instead of ever serving its now-untrustworthy original ports.

## Two more bugs only live-browser verification caught

Both in exactly the same bug class `docs/22` already found and fixed once for POST -- this time
for the new HTTP method this increment introduced, proving the lesson had not yet generalized to
"check this every time a new method is added," so it is generalized here with a permanent test.

1. **CORS blocked every PATCH**, identically to the earlier POST bug: `allow_methods` had never
   been updated when the first `PATCH` route in this app's history was added. Fixed to
   `["GET", "POST", "PATCH"]`. Caught by `TestCorsPreflight::
   test_patch_preflight_from_the_configured_frontend_origin_succeeds` (`tests/api/
   test_module_set_durability.py`) -- proven, by temporarily reverting the fix, to fail against
   the bug and pass against the fix, the same discipline `docs/22` established.
2. **Validation findings were only ever populated from a PATCH response, never fetched on page
   load.** Reloading a draft page (or opening a draft that already had findings from a prior
   session) showed no findings panel at all, and "Confirm save" was never disabled, even though
   real blocking findings existed -- a user could reach the save form with no visible indication
   anything was wrong. Fixed by fetching `GET .../validation` immediately after the draft loads
   (and again after a stale-edit refetch), not only after an edit made within the same page
   session. Confirmed live: reloading a draft with a deliberately-stranded reaction now shows the
   finding and disables "Confirm save" exactly as before the reload.

## Frontend

`ModuleHierarchyTable` gained an optional `editable` prop (present only on an `OPEN` draft, never
on the read-only reopened-version screen): a rename input + button per module, and a
"Reactions" column showing each reaction as a chip with a "Move to…" dropdown listing only its
own sibling modules (the hierarchy rule enforced in the UI, not only on the server) --
reassigning silently reflects on both the source and target module. An `EMPTY_MODULE` finding
renders inline on its own module's row; `UNASSIGNED_REACTION` findings render in a dedicated
"Before you can save" panel, and both block "Confirm save" until resolved. A membership-edited
module's boundary-ports panel shows an explicit "membership has been edited, cannot be shown as
still valid" message instead of ever rendering stale ports. `ModuleSetVersionScreen` gained an
"Edit this version" button that calls the new create-from-version route and navigates straight
into the resulting draft. No Figma screens were created or changed, per this increment's own
scope.

## Validation

- **Backend**: `APP_ENV=test python -m pytest -q` -- 487 passed, up from `docs/22`'s own 451
  (36 net-new: 18 in `tests/persistence/test_module_set_editing.py` covering
  `create_draft_from_version`, `edit_draft_member`'s every rule, `validate_draft`, and
  `save_draft` with edits; 14 in `tests/api/test_module_set_editing.py`; 4 added to
  `tests/api/test_module_set_durability.py` -- the new independent-session edit/save-durability
  tests plus the PATCH CORS regression test -- which already had 4 from `docs/22` and so now
  has 8 in total, not 4 new ones). `ruff check .` and `ruff format --check .` both clean.
- **Frontend**: `npm run typecheck`, `npm run build` (55 modules), `npm run test` (25 passed, no
  new routes needed since editing reuses the existing draft route) all clean.
- **Independent-session durability** (per this increment's own explicit instruction):
  `TestEditDurability`/`TestSaveWithEditsDurability` in `tests/api/test_module_set_durability.py`
  each open a *second*, independently-constructed session/connection after the mutating request
  has fully returned, and query raw SQL -- proving a rename, a cross-module reaction
  reassignment, and a save's own `MIXED_EDITED`/`display_name`/`reaction_component_ids` all
  survive independently of the request that made them; a deliberately invalid (unassigned-reaction)
  save attempt is proven to leave zero `module_set` rows behind.
- **Live browser walkthrough**, against `workbench_test` confirmed disposable by
  `scripts/db_safety.py::require_disposable_database` before seeding (`uvicorn`/`vite` started
  with `DATABASE_URL` explicitly overridden, never `APP_ENV` alone, per `docs/22`): saved a
  3-module/9-reaction unedited draft as `MS-001 v1`; created an editable draft from that version;
  renamed a module; moved a reaction to a different sibling cleanly (no findings); deliberately
  stranded a different reaction via a direct API call and confirmed, after a full page *reload*,
  that the finding is shown and "Confirm save" is disabled; resolved it and saved `v2`, confirmed
  `origin_method=MIXED_EDITED`, the renamed `display_name`, and the reassigned member's
  `membership_edited=true`; re-fetched `v1` and confirmed every member still shows
  `display_name=null`/`membership_edited=false` -- completely untouched; confirmed the edited
  member's boundary ports return `409` on both the draft and the saved version; confirmed
  editing an already-`SAVED` draft returns `409`; confirmed discard still works on a fresh edit
  draft. Console errors: 2, both the expected benign `Failed to load resource: 409` lines from
  the deliberate boundary-port-invalidation and already-saved checks.

## What boundary-port invalidation does, and does not, do

Stated precisely, because "invalidate" could otherwise be read as stronger than what this
increment actually built: invalidation is a **display/inspection-layer safeguard inside the
module-set API only.** `GET .../module-set-drafts/{id}/members/{id}/boundary-ports` and
`GET .../module-sets/.../versions/{v}/members/{id}/boundary-ports` return `409` instead of ever
serving a membership-edited member's original ports as still valid, and the frontend shows an
explicit "cannot be shown as still valid" message instead. That is the entire mechanism.

**It does not touch, and cannot gate, the actual execution entrypoint.**
`app/orchestration/model_module_orchestrator.py::request_module_simulation` -- the one real
path to an Agent 3 simulation -- reads `ModelModule.execution_status` and
`ModelModule.attach_payload` directly from the original, unedited `ModelModule` row; it has no
parameter, column, or query that references any `ModuleSetMember`/`ModuleSetDraftMember` at
all. Editing a module-set member's `reaction_component_ids` never writes to `ModelModule` in any
way (by design -- see "Backend: schema" above), so `execution_status` is exactly what it always
was, and a direct call to `request_module_simulation(model_module_id=...)` proceeds or refuses
exactly as it would have before this increment existed, completely unaware that any module-set
ever referenced that module.

This is consistent, not merely unfinished, because of a boundary increment 21 already
established and this increment never crossed: "module sets remain a pure curation/versioning
layer, never a second execution entrypoint" (`docs/20` §8). Execution never goes *through* a
module-set member -- there is no "Simulate" action anywhere in the module-set UI, and the API
has no route that would let one. Because `request_module_simulation` always uses the real
module's own real `attach_payload` for both its boundary derivation and its simulation request,
whatever it executes is always internally self-consistent regardless of what any module-set
currently curates. The risk this increment's invalidation actually closes is narrower than
"blocking an unsafe simulation" -- it is "a module-set's own UI silently implying a set of
boundary conditions still describes a module whose reaction content, *as that module-set
curates it*, has since changed." Closing that is what `docs/23`'s task instruction ("never
silently carry forward execution-specific boundary decisions as valid after membership
changes") asked for, read against a system where module-sets never execute anything themselves.
Building a cross-cutting gate that made module-set edit-state influence `execution_status` would
have meant module-sets *starting* to influence execution -- exactly the "new execution
workflows" this increment's own scope explicitly excluded.

## Remaining limitations

Split/merge, per-member origin tracking, and the `ModelModule.run_record_id` schema change all
remain exactly as deferred as `docs/20`/`docs/21` already said. New to this increment, disclosed
rather than silently assumed away: validation is bounded by the draft's own known reaction
universe, never an independently-verified total model reaction count (see "The question this
increment had to answer first," above) -- a future increment that needs true model-wide
completeness checking would need a live harness round-trip this one deliberately does not add,
staying within "reuse existing services where their assumptions remain valid" rather than
building a new execution workflow. Boundary-port invalidation is scoped to the module-set API's
own display/inspection routes only, never to `request_module_simulation`'s own readiness gate --
see "What boundary-port invalidation does, and does not, do" above for exactly why that is the
correct scope here rather than an oversight. A rename cannot currently be reverted back to "no
name" once set (only renamed again to a different string) -- a minor, acceptable simplification,
not asked for explicitly either way.
