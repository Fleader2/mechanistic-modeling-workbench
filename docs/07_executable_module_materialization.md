# Executable-Module Materialization

See `docs/04_hierarchical_recursion.md`/`docs/05_hierarchical_review_resume.md` for the
increments this one builds on, and
`agent-integration-harness/docs/16_workbench_module_simulation_contract.md` for that
repository's own copy of this document.

## Goal

Turn accepted hierarchy modules into durable Workbench execution targets with stable
provenance, then let a caller request a real Agent 3 simulation of one selected module --
without changing hierarchical modularization semantics, and without representing a module as
an ordinary top-level `Model`.

## Why "accepted" means more than `HierarchyNode.accepted`

`HierarchyNode.accepted` describes whether *that node's own further* decomposition was found
acceptable -- not whether the node's own module is a legitimate member of its parent's
modularization (it always is, for any depth>=1 node the hierarchy ever actually reached). A
real model's own leaf modules -- ones whose further split was correctly rejected
(`NO_VALID_CHILD_DECOMPOSITION`) -- are the *common* case, confirmed directly against a real
hierarchical-recursion run over the sibling harness repository's own real `sce00061` fixture
(every depth-1 module came back `accepted=False` there, each one still a perfectly legitimate
module). `materialize_accepted_modules` therefore gates on `HierarchyNode.attach_payload is
not None` instead -- the harness's own, independently-disclosed signal for "this module was
genuinely reached and materialized" -- which happens to exactly, and only, exclude the two
cases requirement 3's own test asks for: a `MODULE_TOO_SMALL` node (never attempted) and a
`HUMAN_REVIEW_REJECTED` node (rejected outright, never searched). The root node (depth 0) is
excluded unconditionally, preserving the existing root `Model` (requirement 5).

## Harness-side addition (minimal, additive, disclosed)

`HierarchyNodeRecord`/`HierarchyNodeSummary` gained one new field, `attach_payload: dict |
None` -- the exact `{"modularization_id", "module_ids", "memberships"}` payload the harness
used to materialize *that* node's own submodel (already computed internally; this increment
only also attaches it to the node's own persisted record). Component ids inside it are always
real, whole-network ids (submodel materialization never renames/rehashes them), so this single
payload, attached directly to a freshly-rebuilt root model, is always sufficient to
re-materialize the exact module it names later -- no multi-level attach chain is ever needed,
regardless of how deep in a hierarchy the module originally came from. A new harness-side
canonical entrypoint (`scripts/run_workbench_module_simulation_request.py`) and Agent 2 runner
(`run_agent2_materialize_module_handoff.py`) reuse Agent 2's own existing, unchanged
`build_module_calibration_request` and Agent 3's own existing, unchanged `run_agent3.py` --
nothing about recursion/acceptance/scoring semantics changed, and no Agent 2/Agent 3 algorithm
was touched.

**Boundary treatment is never fabricated.** Agent 2's own `generate_module_artifacts` only
produces a standalone, simulatable artifact for a module carrying an explicit boundary-port
declaration (`externally_controlled=True`) -- confirmed directly against Agent 2's own test
suite. The hierarchical-recursion search's own `attach_payload` never includes this (deciding
boundary treatment is not that search's job), so a module reached purely through it honestly
comes back `VIEW_ONLY` -- a genuine, disclosed "not yet simulatable" outcome, not a defect. The
harness's new Agent 2 runner accepts an *optional* `module_ports` key for a caller that already
knows the right boundary treatment (a human reviewer, or a future Agent4/5 increment) -- never
auto-derived here either.

## Schema

* `hierarchy_node.attach_payload` (new, nullable `TEXT`, opaque) -- threaded straight through
  from the harness's own new field.
* `model_module` (new table) -- one row per depth>=1, genuinely-materialized `HierarchyNode`.
  `ON DELETE RESTRICT` throughout (`run_record_id`/`hierarchy_node_id`/
  `parent_model_module_id`/`root_model_id`): unlike every `CASCADE`-deleted table the
  Hierarchical Review/Resume increment added, a `ModelModule` is a durable, independently-
  referenceable execution target -- the identical precedent `model` itself already uses.
  `hierarchy_node_id` is itself unique (1:1, the idempotency key). `parent_model_module_id` is
  `NULL` when the parent is the root model itself (never represented as its own row).
* `run_record.model_module_id` (new, nullable, `RESTRICT` FK) -- which module (if any) an
  Agent 3 run simulated; `NULL` for every other stage, including an ordinary whole-model
  Agent 3 run inside `FULL_PIPELINE` (confirmed unaffected: that path never sets this column,
  and its own existing tests pass unchanged).

See migration `0006_model_module`.

## Materialization: idempotent, automatic

`app.persistence.model_module.materialize_accepted_modules(run_record_id, session)` is called
automatically from `app.orchestration.hierarchical_run_orchestrator
.persist_result_and_transition` -- the same shared completion path both the initial
hierarchical-recursion invocation and every resume call already funnel through -- immediately
after `create_hierarchy_nodes`. It queries already-materialized `hierarchy_node_id`s first and
creates only the genuinely new ones (mirroring `create_hierarchy_nodes`'s own established
idempotency pattern), so a resumed/replayed run never duplicates a module. A node's own parent
`ModelModule` is resolved by matching its `parent_modularization_id` against an already-known
ancestor's own `child_modularization_id` -- `None` when that ancestor is the root.

`persist_result_and_transition` also now records the hierarchy run's own original stage-1
input (`agent1_organism_id`/`stage1_synthetic_source`) inside `RunRecord.artifact_reference`'s
own JSON, so a *later*, separate module-simulation request can resolve the identical input
without the caller re-supplying it. When a resume call passes neither (it has no fresh stage-1
input of its own), the run's own already-recorded values are read back and carried forward
unchanged.

## Service layer: `app.orchestration.model_module_orchestrator`

* `list_model_modules(session, run_record_id)` -- every module for one hierarchy run.
* `get_model_module_with_provenance(session, model_module_id)` -- one module; its full
  provenance (root model, parent module, hierarchy run, hierarchy node) is already reachable
  via ordinary relationship attributes (`.root_model`, `.parent_model_module`, `.run_record`,
  `.hierarchy_node`) -- no separate assembly step, since the schema already carries it as
  columns/FKs.
* `request_module_simulation(*, model_module_id, subproject_id, project_id, session, ...)` --
  resolves the module's own stored `attach_payload` and the hierarchy run's own recorded
  stage-1 input, builds a `ModuleSimulationRequest`, and invokes the harness's module-
  simulation canonical entrypoint (`app.orchestration.module_simulation_harness_client
  .invoke_module_simulation`) through a new `RunRecord` (`stage=RunStage.AGENT3`,
  `model_module_id` set). Idempotent-replay-by-existing-`run_record_id`, identical to
  `submit_hierarchical_run`'s own established convention.

## Tests

`tests/persistence/test_model_module.py` (10 tests): materialization from a genuinely-
materialized leaf node (`accepted=False`, still a valid module); exclusion of `MODULE_TOO_
SMALL`/`HUMAN_REVIEW_REJECTED`/root nodes; parent/root provenance chain across two depths;
idempotency across repeated calls and across a simulated resume that adds new child nodes;
scoping to one run; `attach_payload` round-trip; fresh-session reload.

`tests/orchestration/test_model_module_orchestrator.py` (12 tests): list/get APIs; a mocked
simulation request invoking with the correct module/`attach_payload` and linking its result
back to the module and root model via `RunRecord`; idempotent replay; a client-level
infrastructure failure and a harness-reported `MODULE_SIMULATION_FAILED` (invalid/non-
executable module) both reported clearly with provenance preserved; unknown-module and
no-recorded-stage1-input rejections; fresh-session recovery; confirmation that an ordinary
whole-model Agent 3 run never sets `model_module_id` -- plus **one real, end-to-end test**
driving the actual sibling harness repository as a genuine subprocess chain (a real
hierarchical-recursion run, then a real module-simulation request against one of its own
accepted modules), confirming the real chain reaches the correctly-disclosed `MODULE_
SIMULATION_FAILED`/`VIEW_ONLY` outcome (no boundary treatment was supplied) with provenance
correctly linked to the *specific* module, never the root. Full Workbench suite: 182 passed
(160 pre-existing + 22 new); lint clean. Harness suite (sibling repository): 175 passed; lint
clean.

## Remaining gaps

* No GUI (explicitly out of scope).
* No Agent4/Agent5 module execution (explicitly deferred to the next increment).
* No automatic boundary-treatment derivation -- a real hierarchy-search-produced module is not
  yet simulatable without a caller explicitly supplying `module_ports`; deciding that is a
  scientific question deliberately left to a future increment (a human reviewer, or Agent4/5),
  never fabricated here.
* `ModelModule` has no `Model`-style `stable_identifier`/lifecycle `status` of its own --
  `hierarchy_node_id`'s own uniqueness already serves as the idempotency key, and this
  increment does not yet need the richer `Model` lifecycle (draft/active/superseded/archived)
  a module might eventually want once Agent4/5 execution exists.
