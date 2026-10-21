"""Shared test fixtures.

Tests run against a dedicated PostgreSQL test database identified by
``TEST_DATABASE_URL``. A guard refuses to run when that URL matches
``DATABASE_URL``, so the suite cannot operate on a development database --
the identical convention used by ``agent1-biochemical-curator``
(``tests/conftest.py``).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.db.session import get_engine, get_session, reset_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _configured_urls() -> tuple[str | None, str | None]:
    primary = os.environ.get("DATABASE_URL")
    test = os.environ.get("TEST_DATABASE_URL")
    if primary and test:
        return primary, test

    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError:
        return primary, test

    if not primary:
        primary = settings.sqlalchemy_url
    if not test and settings.test_database_url is not None:
        test = str(settings.test_database_url)
    return primary, test


def _require_test_database_url() -> str:
    primary_url, test_url = _configured_urls()

    if not test_url:
        pytest.exit(
            "TEST_DATABASE_URL is not set. Database tests require a dedicated "
            "PostgreSQL test database.",
            returncode=1,
        )

    if primary_url and primary_url == test_url:
        pytest.exit(
            "TEST_DATABASE_URL must differ from DATABASE_URL so that tests cannot "
            "modify a development database.",
            returncode=1,
        )
    return test_url


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Validated URL of the PostgreSQL test database."""
    return _require_test_database_url()


@pytest.fixture(scope="session", autouse=True)
def test_environment(
    test_database_url: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Point application configuration at the test database for the whole session.

    Also redirects ``artifacts_dir`` (``app.storage``'s own durable-file root) to a session-
    scoped temp directory -- without this, a time-series dataset save during a test run would
    write real content-addressed ``.xlsx`` blobs straight into this repository's own working
    directory, not a disposable location.
    """
    previous = {key: os.environ.get(key) for key in ("DATABASE_URL", "APP_ENV", "ARTIFACTS_DIR")}

    os.environ["DATABASE_URL"] = test_database_url
    os.environ["APP_ENV"] = "test"
    os.environ["ARTIFACTS_DIR"] = str(tmp_path_factory.mktemp("artifacts"))

    get_settings.cache_clear()
    reset_engine()

    yield

    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    get_settings.cache_clear()
    reset_engine()


@pytest.fixture(scope="session")
def settings(test_environment: None) -> Settings:
    """Application settings resolved against the test environment."""
    del test_environment
    return get_settings()


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    """Alembic configuration rooted at the project directory."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return config


def reset_test_database(alembic_config: Config) -> None:
    """Replay the full migration history, restoring the database to exactly
    the clean baseline a fresh migration run produces.

    See ``agent1-biochemical-curator/docs/29_test_database_isolation.md``
    for the full root-cause rationale behind replaying history rather than
    relying on per-test rollback alone -- the identical reasoning applies
    here.
    """
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


@pytest.fixture(scope="session")
def migrated_engine(settings: Settings, alembic_config: Config) -> Iterator[Engine]:
    """Engine bound to the test database, migrated to head and reset to a
    clean baseline once per session.
    """
    alembic_config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url)
    reset_test_database(alembic_config)

    engine = get_engine()
    yield engine


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """Session wrapped in a transaction that is rolled back after each test.

    Joined into that outer transaction via a ``SAVEPOINT`` that is immediately restarted every
    time the session itself ends a transaction (SQLAlchemy's own documented "joining a Session
    into an external transaction" recipe for test suites) -- so test code that calls
    ``session.commit()``/``session.rollback()`` (e.g. a Crash-Safe Resume increment test
    simulating one logical operation's own separate transaction boundaries) gets real,
    independent commit/rollback semantics *within* the test, while the outer ``transaction``
    (rolled back in the ``finally`` block below, exactly as before) still guarantees nothing
    this fixture ever produces is durable past the end of the test -- full isolation is
    unchanged. Without this, a mid-test ``session.commit()`` does not create an independent
    durability boundary at all (the externally-pre-begun outer transaction is the only thing
    actually controlling the DBAPI transaction), so a *later* ``session.rollback()`` in the
    same test incorrectly discards that earlier commit's own rows too -- confirmed directly
    before this fix was added.
    """
    connection = migrated_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess: Session, trans: object) -> None:
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        event.remove(session, "after_transaction_end", _restart_savepoint)
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def app(db_session: Session) -> Iterator[FastAPI]:
    """Application instance with its database dependency overridden to use
    ``db_session``, so API-test seed data (flushed but never committed) is
    visible to requests within the same test, and nothing persists past it.
    """
    from app.main import create_app

    def _override_get_session() -> Iterator[Session]:
        yield db_session

    application = create_app()
    application.dependency_overrides[get_session] = _override_get_session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """HTTP client for API tests."""
    with TestClient(app) as test_client:
        yield test_client
