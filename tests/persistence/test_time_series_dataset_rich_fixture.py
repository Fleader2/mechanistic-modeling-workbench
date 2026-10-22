"""Round-trip tests for the richer regression fixture added for the Read-Only Dataset
Inspection and Time-Series Plotting increment (``tests.time_series_helpers
.rich_fixture_workbook_bytes`` -- see ``docs/28_dataset_inspection_and_time_series_plotting
_increment.md``): multiple conditions/replicates, mixed declared units, a genuinely repeated
time within one sample, rows physically out of time order, and every non-``MEASURED`` cell
status at least once. Confirms persistence/reopen preserve every one of these exactly --
nothing here is re-derived or silently corrected.
"""

from __future__ import annotations

import pytest

from app.persistence.time_series_dataset import get_time_series_dataset, persist_time_series_dataset
from app.schemas.time_series_dataset import TimeSeriesDatasetDetail
from tests.persistence.conftest import make_project_id, make_subproject_id
from tests.time_series_helpers import RICH_FIXTURE_ROWS, rich_fixture_workbook_bytes

pytestmark = pytest.mark.database


def _save_and_reopen(db_session) -> TimeSeriesDatasetDetail:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    result = persist_time_series_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="ras_mapk_rich.xlsx",
        workbook_bytes=rich_fixture_workbook_bytes(),
        saved_by="test-scientist",
    )
    dataset = get_time_series_dataset(db_session, result.entity_id)
    assert dataset is not None
    return TimeSeriesDatasetDetail.from_model(dataset)


class TestUnitPanelGrouping:
    def test_mm_columns_share_one_panel_au_and_undeclared_each_get_their_own(self, db_session):
        detail = _save_and_reopen(db_session)
        groups = [set(g.column_names) for g in detail.content.unit_panels]
        assert {"[aRAStot]", "[pBRAFtot]"} in groups
        assert {"[pMEKtot]"} in groups
        assert {"[undeclared_col]"} in groups
        assert len(groups) == 3

    def test_the_shared_mm_panel_echoes_the_declared_unit_verbatim(self, db_session):
        detail = _save_and_reopen(db_session)
        mm_group = next(g for g in detail.content.unit_panels if "[aRAStot]" in g.column_names)
        assert mm_group.shared_unit == "mM"

    def test_the_undeclared_panel_has_no_shared_unit(self, db_session):
        detail = _save_and_reopen(db_session)
        undeclared_group = next(
            g for g in detail.content.unit_panels if "[undeclared_col]" in g.column_names
        )
        assert undeclared_group.shared_unit is None


class TestConditionsReplicatesAndSampleIdentity:
    def test_every_row_carries_its_own_real_sample_condition_and_replicate_identity(
        self, db_session
    ):
        detail = _save_and_reopen(db_session)
        assert len(detail.content.rows) == len(RICH_FIXTURE_ROWS)
        sample_ids = {r.sample_id for r in detail.content.rows}
        assert sample_ids == {"S1", "S2", "S3"}
        condition_ids = {r.condition_id for r in detail.content.rows}
        assert condition_ids == {"ctrl", "treated"}

    def test_row_index_preserves_the_literal_as_uploaded_order_never_sorted_by_time(
        self, db_session
    ):
        detail = _save_and_reopen(db_session)
        rows_by_index = sorted(detail.content.rows, key=lambda r: r.row_index)
        uploaded_times = [row[0] for row in RICH_FIXTURE_ROWS]
        reopened_times = [r.time_value for r in rows_by_index]
        assert reopened_times == uploaded_times

    def test_the_genuinely_repeated_time_for_sample_s3_is_preserved_as_two_distinct_rows(
        self, db_session
    ):
        detail = _save_and_reopen(db_session)
        s3_at_60 = [
            r for r in detail.content.rows if r.sample_id == "S3" and r.time_value == 60
        ]
        assert len(s3_at_60) == 2
        values = sorted(r.measurements["[aRAStot]"].value for r in s3_at_60)
        assert values == [7.0, 7.5]
        # Never merged/averaged into one row, and never given the identical row_index.
        assert s3_at_60[0].row_index != s3_at_60[1].row_index


class TestNonnumericCellStatuses:
    def test_na_blank_unknown_and_unrecognized_are_all_distinguished_never_coerced(
        self, db_session
    ):
        detail = _save_and_reopen(db_session)
        row_t120_s1 = next(
            r for r in detail.content.rows if r.sample_id == "S1" and r.time_value == 120
        )
        assert row_t120_s1.measurements["[aRAStot]"].status == "NOT_APPLICABLE"
        assert row_t120_s1.measurements["[aRAStot]"].value is None
        assert row_t120_s1.measurements["[undeclared_col]"].status == "MISSING"
        assert row_t120_s1.measurements["[pMEKtot]"].status == "UNKNOWN"

        row_t60_s2 = next(
            r for r in detail.content.rows if r.sample_id == "S2" and r.time_value == 60
        )
        assert row_t60_s2.measurements["[pMEKtot]"].status == "UNRECOGNIZED"
        assert row_t60_s2.measurements["[pMEKtot]"].raw == "overflow"
        assert row_t60_s2.measurements["[pMEKtot]"].value is None
