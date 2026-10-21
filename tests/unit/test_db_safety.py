"""Tests for `scripts/db_safety.py` -- the guard that stops a one-off script from seeding or
mutating a database that was never confirmed disposable. See
`docs/22_database_configuration_and_verification_safety.md`."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from scripts.db_safety import NotADisposableDatabaseError, _check_name, require_disposable_database


class TestCheckName:
    """Pure-logic coverage of the naming rule, independent of any real connection."""

    def test_a_name_ending_in_the_required_suffix_is_accepted(self) -> None:
        _check_name("workbench_test", expected_name=None, required_suffix="_test")

    def test_a_name_not_ending_in_the_required_suffix_is_rejected(self) -> None:
        with pytest.raises(NotADisposableDatabaseError, match="workbench"):
            _check_name("workbench", expected_name=None, required_suffix="_test")

    def test_an_exact_expected_name_match_is_accepted_even_without_the_suffix(self) -> None:
        _check_name("some_scratch_db", expected_name="some_scratch_db", required_suffix="_test")

    def test_an_expected_name_mismatch_is_rejected_even_with_the_suffix(self) -> None:
        with pytest.raises(NotADisposableDatabaseError, match="other_test"):
            _check_name("other_test", expected_name="workbench_test", required_suffix="_test")

    def test_expected_name_takes_priority_over_the_suffix_rule(self) -> None:
        """A name ending in the suffix is still rejected if it doesn't match `expected_name`
        exactly -- `expected_name` is the stricter, more specific check."""
        with pytest.raises(NotADisposableDatabaseError):
            _check_name("some_other_test", expected_name="workbench_test", required_suffix="_test")


class TestRequireDisposableDatabase:
    """Integration coverage against a real connection -- this project's own test database."""

    def test_the_real_test_database_is_confirmed_disposable(self, migrated_engine: Engine) -> None:
        name = require_disposable_database(migrated_engine)
        assert name.endswith("_test")

    def test_the_real_test_database_matches_its_own_exact_name(
        self, migrated_engine: Engine
    ) -> None:
        name = require_disposable_database(migrated_engine, expected_name=None)
        assert require_disposable_database(migrated_engine, expected_name=name) == name

    def test_a_wrong_expected_name_is_rejected_against_a_real_connection(
        self, migrated_engine: Engine
    ) -> None:
        with pytest.raises(NotADisposableDatabaseError):
            require_disposable_database(migrated_engine, expected_name="definitely_not_this_one")
