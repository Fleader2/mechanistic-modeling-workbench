# Database Configuration, the `APP_ENV`/`DATABASE_URL` Incident, and a Verification Safety Guard

During `docs/21_module_set_first_increment.md`'s live-browser verification, a seed script was
run with `APP_ENV=test` and crashed against a database that turned out to be the real
development database (`workbench`), not a disposable one. Investigating why revealed that this
mistake had been made consistently since `docs/16`'s increment: every prior "live-verification"
session in this repository's history started `uvicorn` with `APP_ENV=test`, believing that
redirected it to the test database. It never did. This document records exactly how the two
settings actually interact, the resulting state of the development database, and the guard now
in place so this class of mistake cannot recur silently.

## How `APP_ENV` and `DATABASE_URL` actually interact

- **`app/db/session.py::get_engine`** always binds to `settings.sqlalchemy_url`, which
  `app/config/settings.py` always derives from `DATABASE_URL` -- never from `TEST_DATABASE_URL`,
  regardless of `APP_ENV`.
- **`app_env` is read nowhere in `app/`.** `grep -rn "app_env" app/` finds exactly one line: the
  field's own declaration in `Settings`. It has no effect on database selection, or on anything
  else, anywhere in the running application.
- **The test suite's own `DATABASE_URL` override is what actually works**, and it is what
  created the illusion that `APP_ENV=test` mattered. `tests/conftest.py`'s `test_environment`
  fixture sets *both* `os.environ["DATABASE_URL"] = test_database_url` *and*
  `os.environ["APP_ENV"] = "test"` together, for the pytest process only. Reading that fixture
  without noticing which of the two lines is load-bearing is exactly how this mistake started:
  the correlation looked like causation.
- **The only way to point a standalone `uvicorn` process (or any one-off script) at the test
  database is to override `DATABASE_URL` itself**, e.g.:

  ```bash
  DATABASE_URL="postgresql+psycopg://agent1:agent1@localhost:5432/workbench_test" \
    uvicorn app.main:app --port 8000
  ```

  `APP_ENV=test` may still be set alongside it for clarity/logging, but it is decorative in this
  context, not functional.

## State of the development database found by this audit

A read-only inspection (`SELECT * FROM alembic_version`, a full column listing per table, and
row counts) found the `workbench` database stamped at `0001_initial_workbench_schema` --
**twelve migrations behind head** (`0002` through `0013` were never applied). It contains
exactly the tables migration `0001` creates; every table migration `0002`+ would have added
(`hierarchy_node`, `model_module`, `module_boundary_port`, `module_aggregate`, `module_set` and
its siblings, etc.) is entirely absent, and `run_record` itself is missing the columns `0002`
added to it. Its only data is 3 `project` rows, 5 `subproject` rows, and 8 `model` rows --
`PRJ-101`/`PRJ-102`/`PRJ-201` ("Yeast Fatty Acid Engineering"/"EGFR Drug Response"), with
`created_at` timestamps matching this and prior increments' own seed scripts. `run_record` has
0 rows, confirming no script before this increment's ever attempted to create one against this
database (this increment's own seed script is the first to need `RunRecord`/`HierarchyNode`,
which is why this gap was never noticed before). The most likely explanation: `alembic upgrade
head` (the README's own documented setup step) was run once, early, against `workbench`, and
never re-run as migrations `0002`-`0013` were added -- a Workbench-only maintenance gap, not
evidence of anything else being wrong.

**This audit did not modify, migrate, or delete anything in `workbench`.** Before even reading
it, it was backed up in full: a custom-format `pg_dump`, a schema-only dump, and a data-only
(`--inserts`) dump, all under this session's scratchpad directory. Whether to migrate, reset, or
otherwise clean up `workbench` is left for the user to decide -- see "Proposed cleanup (not yet
applied)" below.

## The guard: `scripts/db_safety.py`

`require_disposable_database(engine, *, expected_name=None, required_suffix="_test")` asks the
**connected server itself** for its own name (`SELECT current_database()`) and raises
`NotADisposableDatabaseError` unless that name ends with `required_suffix` (default `"_test"`,
matching this project's `TEST_DATABASE_URL` convention) or matches `expected_name` exactly. It
deliberately does not trust the connection URL string a script was built from -- trusting an
assumption about what a URL or env var resolved to is exactly the failure mode this guard exists
to close. `require_disposable_database_url(url, ...)` is the same check for a script that only
has a URL rather than an already-open `Engine`.

Covered by `tests/unit/test_db_safety.py`: pure-logic cases for the naming rule (suffix match,
suffix mismatch, exact-name override, exact-name mismatch even when the suffix also matches) and
two integration cases against the real test database via the `migrated_engine` fixture.

Demonstrated live: the module-set seed script (`require_disposable_database(get_engine())` as
its first executable line, before any other import does real work) now refuses to run at all
against `workbench` --

```
scripts.db_safety.NotADisposableDatabaseError: Refusing to proceed against database 'workbench':
its name does not end with '_test', so it cannot be confirmed disposable. Pass `expected_name=`
explicitly if this really is the intended database.
```

-- and proceeds normally once `DATABASE_URL` is actually overridden to `workbench_test`. Every
future one-off verification/seed script should open with this same call.

## Independent-session persistence tests added

The two bugs `docs/21` found by live verification alone (CORS blocking every POST; the three
mutating module-set routes never calling `session.commit()`) were invisible to the existing API
test suite because `tests/conftest.py`'s `client`/`db_session` fixtures share one SQLAlchemy
session between the test's own request and its own assertions -- an uncommitted write is still
visible to a read sharing the same transaction, exactly the condition that does not hold for two
independent real HTTP requests. `tests/api/test_module_set_durability.py` closes that gap:

- **`test_a_created_draft_is_visible_from_a_second_independent_session`** -- creates a draft via
  the `TestClient`, then opens a *second*, independently-constructed `Session` bound to the same
  `migrated_engine` and queries for the row directly with raw SQL, bypassing the shared
  `db_session`/dependency-override machinery entirely. This is exactly the check that would have
  caught the missing `session.commit()` bug.
- **`test_a_discarded_draft_is_durable_from_a_second_independent_session`** and
  **`test_a_saved_version_is_durable_from_a_second_independent_session`** -- the same pattern for
  discard and save, the other two previously-uncommitted routes.
- **`test_post_preflight_from_the_configured_frontend_origin_succeeds`** -- an `OPTIONS`
  preflight request carrying `Origin`/`Access-Control-Request-Method: POST` headers against a
  real mutating route, asserting `allow-methods` includes `POST` and the response is not `400`.
  This is exactly the check that would have caught the `allow_methods=["GET"]` bug.

## Repeating earlier navigation checks against a confirmed-disposable database

The Playwright navigation walkthroughs originally run for `docs/16`-`19` (All Projects, Current
Project, Modeling Study, Model Overview) were re-run against `workbench_test`, with
`require_disposable_database` confirming its identity before seeding and `uvicorn` started with
`DATABASE_URL` explicitly overridden (never `APP_ENV` alone). All four navigation flows render
and behave exactly as those docs already describe -- nothing about the application behavior
itself was wrong, only each doc's claim about *which* database it was verified against. Each of
`docs/16_projects_api_first_increment.md`, `docs/17_current_project_increment.md`,
`docs/18_modeling_study_increment.md`, and `docs/19_model_overview_increment.md` has been
corrected in place: their validation sections now state plainly that the original verification
ran against the real development database rather than a disposable one (the application
behavior each doc describes was and remains correct; only the database-identity claim was
wrong), and link back here.

## Proposed cleanup (not yet applied)

Disposable, by inspection -- their `created_at` timestamps, titles, and stable identifiers match
exactly this repository's own seed-script conventions, and the full backup means nothing is at
risk if this judgment is wrong:

- The 3 `project` rows (`PRJ-101`, `PRJ-102`, `PRJ-201`) and everything that cascades from them
  (5 `subproject` rows, 8 `model` rows).
- The schema gap itself (`workbench` stamped at `0001`) should be closed by running `alembic
  upgrade head` against it -- the README's own documented setup step, simply never re-run.

**Not applied by this audit.** Both require the user's explicit go-ahead: running `alembic
upgrade head` against `workbench` and deleting the fixture-looking rows are both the kind of
action this project's own operating conventions reserve for explicit confirmation, identifiers
looking like fixtures is a strong signal but not proof, and a backup taken five minutes ago is a
poor substitute for simply asking first.
