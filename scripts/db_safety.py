"""Database-identity safety guard for one-off scripts that seed or mutate data outside the
test suite (live-verification seed scripts, manual data fixes, exploratory queries).

See `docs/22_database_configuration_and_verification_safety.md` for the incident this exists
to prevent: `APP_ENV` has no effect anywhere on which database the application connects to
(only `DATABASE_URL` does), so a script that merely *assumes* an env var redirected it to a
disposable database can silently seed the real development database instead.

This guard asks the connected server for its own database name (`SELECT current_database()`)
rather than trusting the connection URL string a script was built from -- the URL is exactly
the kind of assumption that caused the incident this guard exists to prevent.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text


class NotADisposableDatabaseError(RuntimeError):
    """Raised when a script would otherwise seed or mutate a database that was never
    confirmed disposable."""


def _check_name(name: str, *, expected_name: str | None, required_suffix: str) -> None:
    if expected_name is not None:
        if name != expected_name:
            raise NotADisposableDatabaseError(
                f"Refusing to proceed against database {name!r}: expected exactly "
                f"{expected_name!r}. Pass the correct `expected_name`, or omit it and rely on "
                f"`required_suffix` instead, if {name!r} really is the intended disposable "
                "database."
            )
        return
    if not name.endswith(required_suffix):
        raise NotADisposableDatabaseError(
            f"Refusing to proceed against database {name!r}: its name does not end with "
            f"{required_suffix!r}, so it cannot be confirmed disposable. Pass "
            "`expected_name=` explicitly if this really is the intended database."
        )


def require_disposable_database(
    engine: Engine, *, expected_name: str | None = None, required_suffix: str = "_test"
) -> str:
    """Raise `NotADisposableDatabaseError` unless the database `engine` is connected to is
    unambiguously disposable, returning its name when it is.

    By default, "disposable" means the database's own name ends with `required_suffix`
    (`"_test"`) -- matching this project's `TEST_DATABASE_URL` naming convention
    (`workbench_test`). Pass `expected_name` for an exact match instead (e.g. against a
    differently-named scratch database).
    """
    with engine.connect() as conn:
        name = conn.execute(text("SELECT current_database()")).scalar()
    assert name is not None
    _check_name(name, expected_name=expected_name, required_suffix=required_suffix)
    return name


def require_disposable_database_url(
    url: str, *, expected_name: str | None = None, required_suffix: str = "_test"
) -> str:
    """Same as `require_disposable_database`, for a script that only has a connection URL
    (e.g. a `DATABASE_URL` override) rather than an already-open `Engine`."""
    engine = create_engine(url)
    try:
        return require_disposable_database(
            engine, expected_name=expected_name, required_suffix=required_suffix
        )
    finally:
        engine.dispose()
