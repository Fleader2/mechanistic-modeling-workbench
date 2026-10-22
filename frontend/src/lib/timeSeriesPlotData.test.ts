import { test } from "node:test";
import assert from "node:assert/strict";
import {
  computeAxisDomain,
  distinctConditionIds,
  filterRowsByCondition,
  groupIntoSeries,
  plottablePointsForColumn,
  summarizeExclusions,
} from "./timeSeriesPlotData.ts";
import type { TimeSeriesDataRowItem } from "../types.ts";

function row(partial: Partial<TimeSeriesDataRowItem>): TimeSeriesDataRowItem {
  return {
    row_index: 0,
    sample_id: null,
    condition_id: null,
    biological_replicate: null,
    technical_replicate: null,
    time_status: "MEASURED",
    time_value: 0,
    time_raw: null,
    measurements: {},
    ...partial,
  };
}

test("a MEASURED value at a MEASURED time is plottable", () => {
  const rows = [
    row({ row_index: 1, time_value: 10, measurements: { a: { status: "MEASURED", value: 5, raw: "5" } } }),
  ];
  const points = plottablePointsForColumn(rows, "a");
  assert.equal(points.length, 1);
  assert.equal(points[0].value, 5);
  assert.equal(points[0].time, 10);
});

test("a real, reported zero is plottable, never dropped as falsy", () => {
  const rows = [
    row({ row_index: 1, time_value: 120, measurements: { a: { status: "MEASURED", value: 0, raw: "0" } } }),
  ];
  const points = plottablePointsForColumn(rows, "a");
  assert.equal(points.length, 1);
  assert.equal(points[0].value, 0);
});

test("a row whose time itself is not MEASURED is excluded from the plot and counted as TIME_UNAVAILABLE", () => {
  const rows = [
    row({ time_status: "MISSING", time_value: null, measurements: { a: { status: "MEASURED", value: 1, raw: "1" } } }),
  ];
  assert.equal(plottablePointsForColumn(rows, "a").length, 0);
  assert.deepEqual(summarizeExclusions(rows, "a"), { TIME_UNAVAILABLE: 1 });
});

test("a nonnumeric cell is excluded from the plot and its real status is disclosed, never coerced to zero", () => {
  const rows = [
    row({ measurements: { a: { status: "NOT_APPLICABLE", value: null, raw: "NA" } } }),
    row({ measurements: { a: { status: "UNKNOWN", value: null, raw: "unknown" } } }),
    row({ measurements: { a: { status: "UNRECOGNIZED", value: null, raw: "overflow" } } }),
    row({ measurements: { a: { status: "MISSING", value: null, raw: null } } }),
  ];
  assert.equal(plottablePointsForColumn(rows, "a").length, 0);
  assert.deepEqual(summarizeExclusions(rows, "a"), {
    NOT_APPLICABLE: 1,
    UNKNOWN: 1,
    UNRECOGNIZED: 1,
    MISSING: 1,
  });
});

test("points from the same sample are connected, ordered by time", () => {
  const points = plottablePointsForColumn(
    [
      row({ row_index: 2, sample_id: "S1", time_value: 60, measurements: { a: { status: "MEASURED", value: 4, raw: "4" } } }),
      row({ row_index: 1, sample_id: "S1", time_value: 0, measurements: { a: { status: "MEASURED", value: 2, raw: "2" } } }),
    ],
    "a",
  );
  const [series] = groupIntoSeries(points);
  assert.equal(series.connectable, true);
  assert.deepEqual(series.points.map((p) => p.time), [0, 60]);
  // Sorting for display never mutates/reassigns row identity.
  assert.deepEqual(series.points.map((p) => p.rowIndex), [1, 2]);
});

test("points of the same species are connected across different sample_ids, by time -- never by sample identity", () => {
  const points = plottablePointsForColumn(
    [
      row({ row_index: 1, sample_id: "S1", time_value: 0, measurements: { a: { status: "MEASURED", value: 2, raw: "2" } } }),
      row({ row_index: 2, sample_id: "S2", time_value: 60, measurements: { a: { status: "MEASURED", value: 4, raw: "4" } } }),
      row({ row_index: 3, sample_id: "S1", time_value: 120, measurements: { a: { status: "MEASURED", value: 6, raw: "6" } } }),
    ],
    "a",
  );
  const [series] = groupIntoSeries(points);
  assert.equal(series.connectable, true);
  assert.equal(series.points.length, 3);
  assert.deepEqual(series.points.map((p) => p.time), [0, 60, 120]);
  assert.deepEqual(series.points.map((p) => p.sampleId), ["S1", "S2", "S1"]);
});

test("a point with no sample_id at all is still connected into the same species-level series", () => {
  const points = plottablePointsForColumn(
    [
      row({ row_index: 1, sample_id: null, time_value: 0, measurements: { a: { status: "MEASURED", value: 1, raw: "1" } } }),
      row({ row_index: 2, sample_id: null, time_value: 1, measurements: { a: { status: "MEASURED", value: 2, raw: "2" } } }),
    ],
    "a",
  );
  const series = groupIntoSeries(points);
  assert.equal(series.length, 1);
  assert.equal(series[0].connectable, true);
  assert.equal(series[0].points.length, 2);
});

test("a single plottable point is never connectable (nothing to draw a line to)", () => {
  const points = plottablePointsForColumn(
    [row({ row_index: 1, sample_id: "S1", time_value: 0, measurements: { a: { status: "MEASURED", value: 1, raw: "1" } } })],
    "a",
  );
  const [series] = groupIntoSeries(points);
  assert.equal(series.connectable, false);
  assert.equal(series.points.length, 1);
});

test("groupIntoSeries returns nothing for a column with no plottable points at all", () => {
  assert.deepEqual(groupIntoSeries([]), []);
});

test("points from different conditions are never connected to each other, even at the same time", () => {
  const points = plottablePointsForColumn(
    [
      row({ row_index: 1, sample_id: "S1", condition_id: "ctrl", time_value: 0, measurements: { a: { status: "MEASURED", value: 2, raw: "2" } } }),
      row({ row_index: 2, sample_id: "S1", condition_id: "ctrl", time_value: 60, measurements: { a: { status: "MEASURED", value: 4, raw: "4" } } }),
      row({ row_index: 3, sample_id: "S3", condition_id: "treated", time_value: 0, measurements: { a: { status: "MEASURED", value: 9, raw: "9" } } }),
      row({ row_index: 4, sample_id: "S3", condition_id: "treated", time_value: 60, measurements: { a: { status: "MEASURED", value: 7, raw: "7" } } }),
    ],
    "a",
  );
  const series = groupIntoSeries(points);
  assert.equal(series.length, 2);
  const conditionsSeen = series.map((s) => s.points[0].conditionId).sort();
  assert.deepEqual(conditionsSeen, ["ctrl", "treated"]);
  for (const group of series) {
    assert.ok(group.points.every((p) => p.conditionId === group.points[0].conditionId));
  }
});

test("an explicit biological-replicate identity splits trajectories within the same condition, across sample_ids", () => {
  const points = plottablePointsForColumn(
    [
      row({ row_index: 1, sample_id: "S1", condition_id: "ctrl", biological_replicate: "1", time_value: 0, measurements: { a: { status: "MEASURED", value: 2, raw: "2" } } }),
      row({ row_index: 2, sample_id: "S1", condition_id: "ctrl", biological_replicate: "1", time_value: 60, measurements: { a: { status: "MEASURED", value: 4, raw: "4" } } }),
      row({ row_index: 3, sample_id: "S2", condition_id: "ctrl", biological_replicate: "2", time_value: 0, measurements: { a: { status: "MEASURED", value: 2.1, raw: "2.1" } } }),
      row({ row_index: 4, sample_id: "S2", condition_id: "ctrl", biological_replicate: "2", time_value: 60, measurements: { a: { status: "MEASURED", value: 3.9, raw: "3.9" } } }),
    ],
    "a",
  );
  const series = groupIntoSeries(points);
  assert.equal(series.length, 2);
  const replicatesSeen = series.map((s) => s.points[0].biologicalReplicate).sort();
  assert.deepEqual(replicatesSeen, ["1", "2"]);
  for (const group of series) {
    assert.equal(group.connectable, true);
    assert.ok(group.points.every((p) => p.biologicalReplicate === group.points[0].biologicalReplicate));
  }
});

test("a technical-replicate number alone never splits or joins a trajectory -- rows differing only by it fall into the same group", () => {
  const points = plottablePointsForColumn(
    [
      row({ row_index: 1, sample_id: "S1", condition_id: "ctrl", technical_replicate: "1", time_value: 0, measurements: { a: { status: "MEASURED", value: 2, raw: "2" } } }),
      row({ row_index: 2, sample_id: "S1", condition_id: "ctrl", technical_replicate: "2", time_value: 60, measurements: { a: { status: "MEASURED", value: 4, raw: "4" } } }),
    ],
    "a",
  );
  const series = groupIntoSeries(points);
  assert.equal(series.length, 1);
  assert.equal(series[0].connectable, true);
  assert.equal(series[0].points.length, 2);
});

test("a time genuinely repeated within one explicit trajectory shows every observation, but breaks connections into, within, AND out of that tie -- never just the one edge between the tied points", () => {
  const points = plottablePointsForColumn(
    [
      row({ row_index: 1, sample_id: "S3", condition_id: "treated", biological_replicate: "1", time_value: 0, measurements: { a: { status: "MEASURED", value: 2.2, raw: "2.2" } } }),
      row({ row_index: 2, sample_id: "S3", condition_id: "treated", biological_replicate: "1", time_value: 60, measurements: { a: { status: "MEASURED", value: 7.0, raw: "7.0" } } }),
      row({ row_index: 3, sample_id: "S3", condition_id: "treated", biological_replicate: "1", time_value: 60, measurements: { a: { status: "MEASURED", value: 7.5, raw: "7.5" } } }),
      row({ row_index: 4, sample_id: "S3", condition_id: "treated", biological_replicate: "1", time_value: 120, measurements: { a: { status: "MEASURED", value: 9.0, raw: "9.0" } } }),
    ],
    "a",
  );
  const series = groupIntoSeries(points);
  // Every one of the 4 real observations is present somewhere in the output -- none dropped,
  // none averaged into a single value.
  const allPoints = series.flatMap((s) => s.points);
  assert.equal(allPoints.length, 4);
  assert.deepEqual(
    allPoints.map((p) => p.value).sort((x, y) => x - y),
    [2.2, 7.0, 7.5, 9.0].sort((x, y) => x - y),
  );
  // Naively breaking only the edge between the two t=60 observations would still have to pick
  // which one the t=0 point connects into and which one the t=120 point connects out of --
  // itself an arbitrary, undisclosed choice. Instead, the t=0 and t=120 points are *also*
  // isolated: all 4 points end up as their own unconnected segment.
  assert.equal(series.length, 4);
  for (const group of series) {
    assert.equal(group.connectable, false);
    assert.equal(group.points.length, 1);
  }
});

test("a tied bucket isolates its immediate neighbors, but a chain of unambiguous points further away still connects", () => {
  const points = plottablePointsForColumn(
    [
      row({ row_index: 1, time_value: -60, measurements: { a: { status: "MEASURED", value: 1, raw: "1" } } }),
      row({ row_index: 2, time_value: 0, measurements: { a: { status: "MEASURED", value: 2, raw: "2" } } }),
      row({ row_index: 3, time_value: 60, measurements: { a: { status: "MEASURED", value: 3, raw: "3" } } }),
      row({ row_index: 4, time_value: 60, measurements: { a: { status: "MEASURED", value: 4, raw: "4" } } }),
      row({ row_index: 5, time_value: 120, measurements: { a: { status: "MEASURED", value: 5, raw: "5" } } }),
      row({ row_index: 6, time_value: 180, measurements: { a: { status: "MEASURED", value: 6, raw: "6" } } }),
    ],
    "a",
  );
  const series = groupIntoSeries(points);
  // [-60, 0] connect to each other -- neither touches the tie. The two t=60 points are each
  // isolated from one another (the ambiguous tie itself) AND from their immediate neighbor on
  // either side: t=0's connection forward into the tie is broken, and the tie's connection
  // forward out to t=120 is broken too. t=120 and t=180, however, are a completely separate,
  // unambiguous edge one step further from the tie -- that connection is never affected by a
  // tie it does not itself touch.
  const multiPointSeries = series.filter((s) => s.points.length > 1);
  const singlePointSeries = series.filter((s) => s.points.length === 1);
  assert.equal(series.length, 4);
  assert.equal(multiPointSeries.length, 2);
  assert.equal(singlePointSeries.length, 2);
  const chains = multiPointSeries.map((s) => s.points.map((p) => p.time)).sort();
  assert.deepEqual(chains, [[-60, 0], [120, 180]]);
  for (const group of singlePointSeries) {
    assert.equal(group.points[0].time, 60);
    assert.equal(group.connectable, false);
  }
  for (const group of multiPointSeries) assert.equal(group.connectable, true);
});

test("distinctConditionIds lists real conditions in first-appearance order, plus a null bucket if any row lacks one", () => {
  const rows = [
    row({ condition_id: "treated" }),
    row({ condition_id: "ctrl" }),
    row({ condition_id: "treated" }),
    row({ condition_id: null }),
  ];
  assert.deepEqual(distinctConditionIds(rows), ["treated", "ctrl", null]);
});

test("filterRowsByCondition keeps only rows whose condition is selected, including the null bucket", () => {
  const rows = [row({ row_index: 1, condition_id: "ctrl" }), row({ row_index: 2, condition_id: null })];
  const filtered = filterRowsByCondition(rows, new Set([null]));
  assert.deepEqual(filtered.map((r) => r.row_index), [2]);
});

test("computeAxisDomain pads around real min/max without forcing zero into the domain", () => {
  const domain = computeAxisDomain([10, 20]);
  assert.ok(domain.min < 10);
  assert.ok(domain.max > 20);
  assert.ok(domain.min > 0); // not forced to include zero
});

test("computeAxisDomain never degenerates to a zero-width domain for a single repeated value", () => {
  const domain = computeAxisDomain([5, 5, 5]);
  assert.ok(domain.min < 5);
  assert.ok(domain.max > 5);
});

test("computeAxisDomain has a sane fallback for no values at all", () => {
  const domain = computeAxisDomain([]);
  assert.ok(domain.max > domain.min);
});
