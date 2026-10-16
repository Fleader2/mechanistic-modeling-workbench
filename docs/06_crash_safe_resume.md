# Crash-Safe Resume

See `docs/05_hierarchical_review_resume.md` for the increment this one closes a failure window
in: that increment's own `resume_hierarchical_run` marked a `HierarchyCheckpoint` consumed
*before* the harness resume subprocess call returned -- a crash during that (potentially
multi-minute) external call left the checkpoint permanently, and incorrectly, marked consumed
with no durable result ever persisted. This increment eliminates that window.

## Goal

Make `resume_hierarchical_run` a genuinely crash-safe, retryable operation, while changing
nothing about who owns what: the harness still owns recursion/checkpoint/resume semantics
(unchanged, not touched by this increment at all); the Workbench still only persists durable
workflow state. No Agent2/3/4/5 changes; no GUI; no module-level Agent3/4/5 execution.

## The failure window, precisely

The previous `resume_hierarchical_run` did, in order: mark the checkpoint consumed -> transition
the `RunRecord` to `RUNNING` -> invoke the harness subprocess -> persist its result. A crash
*anywhere* between the first step and the last left a checkpoint that could never be resumed
again (`consumed_at` already set) backing a run that never actually got a new result -- a
permanently stuck `RunRecord`.

## New durable state: `HierarchyResumeAttempt`

One row per `HierarchyCheckpoint` (`hierarchy_checkpoint_id` is itself unique -- see
`app/models/hierarchy_resume_attempt.py`), with its own status machine
(`HierarchyResumeAttemptStatus`, modeled after `RunStatus`'s own style but a deliberately
separate vocabulary):

```text
PENDING -> IN_PROGRESS -> SUCCEEDED
              ^   |
              |   v
              +-- FAILED   (retryable: FAILED -> IN_PROGRESS again)
```

`attempt_count` (bumped on every `IN_PROGRESS` transition) and `started_at` (overwritten on
every `IN_PROGRESS` transition, the basis for staleness) are the only two fields this increment
needs beyond the status itself; `error_summary`/`completed_at` record the last outcome.

Because `hierarchy_checkpoint_id` is unique, a repeated resume request for the identical
checkpoint always finds and reuses this *same* row -- the idempotency key requirement 6 asks
for ("same checkpoint + decisions") falls out for free, since decisions for one checkpoint's
pending items are themselves immutable once set (`submit_review_decision` already rejects a
conflicting resubmission).

## Two explicit transaction boundaries

`app.orchestration.hierarchical_review_orchestrator.resume_hierarchical_run` is a deliberate,
disclosed exception to this repository's general "the caller commits" convention
(`app/db/session.py::get_session`'s own docstring: "Committing is the responsibility of the
caller... so that a partially-completed operation cannot partially persist workflow state").
That convention is right for every other operation in this codebase -- all fast, in-process DB
work. This is the one operation that spans a slow (up to several minutes), externally-
idempotent subprocess call, and it owns its own two boundaries accordingly:

1. **Phase 1 (durable before the external call).** Validate (run status, checkpoint not
   consumed-or-idempotently-already-succeeded, every pending item decided, no fresh
   non-stale attempt already in flight), get-or-create the `HierarchyResumeAttempt`, mark it
   `IN_PROGRESS`, and **commit**. A crash at any point after this commits leaves exactly this
   row -- nothing else -- durably on disk: the checkpoint is still unconsumed, the `RunRecord`
   is still `REQUIRES_USER_REVIEW`.
2. **Phase 2 (all-or-nothing around the call itself).** Invoke the harness; on any failure
   (a client-level error, or a cleanly-parsed but non-`SUCCEEDED` result) or any unexpected
   exception, roll the whole phase back, mark the attempt `FAILED` with the error recorded, and
   commit *that*. On success: transition the `RunRecord` to `RUNNING`, persist the new nodes/
   checkpoint-if-paused-again via the pre-existing, idempotent `persist_result_and_transition`
   (shared with the initial-invocation path, unchanged), mark the *prior* checkpoint consumed,
   mark the attempt `SUCCEEDED`, and commit all of it together. Nothing from phase 2 is ever
   partially visible: either the whole thing commits, or the whole thing rolls back to exactly
   phase 1's own end state.

This means: for the harness call's own entire duration, the `RunRecord` stays
`REQUIRES_USER_REVIEW` and the checkpoint stays unconsumed, no matter how the call ends. The
only durable side effect of a "crash" during that window is the `HierarchyResumeAttempt`
row's own `IN_PROGRESS` status -- which is exactly what staleness detection exists to recover.

## Staleness and retry

`app.persistence.hierarchy_resume_attempt.is_attempt_stale` -- `True` only for an `IN_PROGRESS`
attempt whose `started_at` is further in the past than
`STALE_RESUME_ATTEMPT_THRESHOLD_SECONDS` (1200s, deliberately independent of -- and more
generous than -- the harness's own 900s subprocess client timeout; the Workbench should never
need that internal harness detail to make its own judgment). `resume_hierarchical_run`:

* a **fresh** `IN_PROGRESS` attempt (not yet stale) raises `ResumeAttemptInProgressError` --
  refuses to race a call that may genuinely still be running;
* a **stale** `IN_PROGRESS` attempt, or a `FAILED` one, is retried: `mark_attempt_in_progress`
  is called again (with `force=True` for the stale-`IN_PROGRESS` case specifically, the
  function's own explicit acknowledgment that the caller already checked staleness), bumping
  `attempt_count`, and phase 2 runs again with the **identical, deterministic**
  `run_id = f"{run_record_id}::resume::{checkpoint.sequence}"` (keyed by checkpoint sequence,
  never by attempt count) -- so the harness's *own* idempotent-replay-by-`run_id` cache returns
  the identical result on retry without re-running real Agent 2 work, if it had in fact already
  completed on a prior, uncommitted attempt;
* a checkpoint already consumed by a **successful** attempt makes a repeat call resolve
  idempotently to the current (already-advanced) `RunRecord`, never an error or a re-invocation
  (requirement 6);
* a checkpoint already consumed with **no** matching successful attempt (an inconsistent state
  that should never occur) still raises `StaleCheckpointError`, exactly as the predecessor
  increment's own staleness protection already did -- unchanged, and requirement 7 ("once a
  newer checkpoint has been durably accepted, the older one must not be reusable") continues to
  hold structurally: `get_current_checkpoint_for_run` only ever returns the max-`sequence` row,
  so an older one is simply never reachable as "current" again, regardless of its own
  `consumed_at`.

## No weakening of existing safeguards

The `(run_record_id, node_id)` unique constraint on `hierarchy_node` (requirement 8) is
untouched, and `create_hierarchy_nodes`'s own idempotent-insert-only-new-nodes behavior
(predecessor increment) is reused unchanged via `persist_result_and_transition` -- a retried
phase 2 that successfully re-runs `persist_result_and_transition` never duplicates a node,
decision, or checkpoint row, because phase 2's own failed attempt always rolled back in full
before any retry.

## A test-fixture bug this increment surfaced and fixed

Writing the crash-simulation tests exposed a latent bug in `tests/conftest.py::db_session`:
that fixture binds its `Session` directly to a `Connection` on which `connection.begin()` was
already called externally, so a `session.commit()` inside test code did not create an
independent durability boundary at all -- a *later* `session.rollback()` in the same test
incorrectly discarded the earlier commit's own rows too (confirmed directly with a throwaway
reproduction before the fix). `db_session` now joins the session into that outer transaction
via a `SAVEPOINT`, restarted after every session-level commit/rollback (SQLAlchemy's own
documented recipe for this exact situation) -- `session.commit()`/`rollback()` inside a test
now behave exactly as they do in production (`app/db/session.py::get_session`, a plain
engine-bound `sessionmaker`, never affected by this bug in the first place), while the fixture's
own outer-transaction rollback at teardown still guarantees full per-test isolation, unchanged.
No other test's behavior changed (confirmed: full suite passes before and after).

## Tests

`tests/persistence/test_hierarchy_resume_attempt.py` (15 tests): get-or-create idempotency,
every state transition (including `force`-gated retry from `IN_PROGRESS`, and freely-allowed
retry from `FAILED`), staleness computation, `CASCADE` delete.

`tests/orchestration/test_hierarchical_review_orchestrator.py` gained 9 new tests (24 total in
that file now): a successful resume transaction's own durable end state; a harness **client**
failure leaving the checkpoint reusable, then a successful retry; a harness-**reported**
(cleanly-parsed, non-`SUCCEEDED`) failure doing the identical thing; a simulated crash after
attempt creation but before the subprocess call (stale `IN_PROGRESS`, recovered); a fresh,
not-yet-stale `IN_PROGRESS` attempt correctly blocking a concurrent call; a simulated crash
*after* a successful harness return but *before* checkpoint consumption (phase 2 rolls back in
full, nothing duplicated, retry succeeds cleanly); the old checkpoint's own permanent
unreachability once a successor checkpoint is durably persisted; and fresh-session recovery of
an `IN_PROGRESS` attempt via `session.expire_all()`. The existing "repeated resume call" test
was updated to assert the new, better idempotent-success behavior (requirement 6) in place of
the predecessor increment's own "second call errors" behavior.

Full Workbench suite: 160 passed (136 pre-existing + 15 new persistence tests + 8 new
crash-safety orchestration tests + 1 net-new test from splitting a predecessor-increment test
whose own expectation changed). Lint clean. Harness suite (sibling repository, untouched by
this increment): 164 passed; lint clean.

## Remaining failure windows

* A crash *during* phase 1's own commit (the DBAPI commit itself failing partway, as opposed to
  the application code around it) is a generic database-durability concern no application-level
  design can fully eliminate -- identical to every other `session.commit()` in any system built
  on a transactional database, not specific to this increment.
* `attempt_count`/`error_summary` are plain audit fields; nothing here pages an operator or
  automatically retries a `FAILED`/stale attempt -- recovery still requires some caller
  (eventually: a scheduled sweep, or a user re-opening the review UI) to call
  `resume_hierarchical_run` again. Building that automatic sweep is explicitly out of scope
  here (no GUI, no new background-job infrastructure in this increment).
* If the harness's own `artifacts/runs/<run_id>/` replay cache were ever deleted between a
  failed attempt and its retry, the retry would genuinely re-run real Agent 2 work rather than
  replaying -- correct and safe (not a duplication bug, since the Workbench-side persistence is
  idempotent either way), just not free.
