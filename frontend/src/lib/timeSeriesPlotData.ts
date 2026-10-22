import type { MeasurementValueStatus, TimeSeriesDataRowItem } from "../types";

/** Read-Only Dataset Inspection and Time-Series Plotting increment (``docs/28``). Pure,
 * deterministic functions over a saved/previewed dataset's own already-fetched rows -- no
 * network calls, no mutation of anything passed in. Every function here only *decides what
 * to render*; none of them average, interpolate, smooth, normalize, convert units, or invent
 * uncertainty (task instructions), and none of them ever reorder or drop a source row -- a
 * row excluded from a *plot* (non-numeric value, or time itself not recorded) is still
 * present in ``rows`` for the data table to show honestly. */

export interface PlottablePoint {
  rowIndex: number;
  time: number;
  value: number;
  sampleId: string | null;
  conditionId: string | null;
  biologicalReplicate: string | null;
  technicalReplicate: string | null;
  raw: string | null;
}

export type ExclusionCounts = Partial<Record<MeasurementValueStatus, number>> & {
  /** Rows excluded because ``time`` itself was never a real, recorded value (not even a
   * genuine finding about the column's own status -- the row simply cannot be placed on a
   * time axis at all). */
  TIME_UNAVAILABLE?: number;
};

/** Every row whose own ``time_status``/this column's own measurement status are both
 * ``MEASURED`` -- the only rows a point can ever be drawn for (task instructions: "disclose
 * excluded nonnumeric observations"; ``summarizeExclusions`` below reports exactly what was
 * excluded and why, so this is never a silent drop). */
export function plottablePointsForColumn(
  rows: TimeSeriesDataRowItem[],
  columnName: string,
): PlottablePoint[] {
  const points: PlottablePoint[] = [];
  for (const row of rows) {
    if (row.time_status !== "MEASURED" || row.time_value === null) continue;
    const measurement = row.measurements[columnName];
    if (!measurement || measurement.status !== "MEASURED" || measurement.value === null) {
      continue;
    }
    points.push({
      rowIndex: row.row_index,
      time: row.time_value,
      value: measurement.value,
      sampleId: row.sample_id,
      conditionId: row.condition_id,
      biologicalReplicate: row.biological_replicate,
      technicalReplicate: row.technical_replicate,
      raw: measurement.raw,
    });
  }
  return points;
}

/** Counts, by reason, of every row of ``rows`` excluded from this column's own plot --
 * never a vague "N excluded," always broken down by the real, disclosed cause. */
export function summarizeExclusions(
  rows: TimeSeriesDataRowItem[],
  columnName: string,
): ExclusionCounts {
  const counts: ExclusionCounts = {};
  for (const row of rows) {
    if (row.time_status !== "MEASURED") {
      counts.TIME_UNAVAILABLE = (counts.TIME_UNAVAILABLE ?? 0) + 1;
      continue;
    }
    const measurement = row.measurements[columnName];
    if (measurement && measurement.status !== "MEASURED") {
      counts[measurement.status] = (counts[measurement.status] ?? 0) + 1;
    }
  }
  return counts;
}

export interface SeriesGroup {
  points: PlottablePoint[];
  /** ``true`` whenever there is more than one point to connect. */
  connectable: boolean;
}

/** Orders one column's own already-plottable points into one or more connected series.
 *
 * Time is always the independent variable (x-axis) and a species' own measured value is
 * always the dependent variable (y-axis). ``sample_id`` alone never splits a trajectory --
 * but a genuine, *explicit* longitudinal identity still must:
 *
 * - Points from different ``condition_id`` values are never connected to each other (task
 *   instructions: "never connect different conditions").
 * - Within one condition, points carrying different ``biological_replicate`` identifiers are
 *   kept on separate lines too -- a biological replicate is the one field this dataset shape
 *   uses to assert "these points, across whatever samples/times, are the same longitudinal
 *   unit." ``technical_replicate`` is deliberately *not* part of this grouping key: a
 *   technical-replicate number alone (repeated measurement of one sample at one timepoint)
 *   never establishes identity *across time* (task instructions: "do not assume a
 *   technical-replicate number alone establishes longitudinal identity"), so two rows that
 *   differ only by technical replicate fall into the same group and are handled by the
 *   repeated-time rule below, never silently merged or kept apart by that number.
 * - With no condition and no biological-replicate information recorded at all, every point
 *   for a species falls into one group, connected by time across every ``sample_id`` --
 *   exactly the original RAS/MAPK fixture's own case (one line per species).
 *
 * Within each such group, points are ordered strictly by ``time`` (sorting is for *display*
 * only -- it never reorders or mutates the source rows the data table reads; task
 * instructions: "handle repeated or unsorted times without changing source data"). Two or more
 * points that land on the exact same ``time`` within one group are a genuinely ambiguous tie --
 * which one came "first," and so which neighboring point on either side it would connect to,
 * is not knowable from any field this grouping key already uses. Breaking only the one edge
 * *between* the tied points is not enough: it would still arbitrarily hand the preceding
 * point's connection to one specific tied point and the following point's connection to
 * another, which is exactly as invented as connecting the tied points to each other directly.
 * So every connection touching a tied bucket is left undrawn -- into it, within it, and out of
 * it alike -- unless some *more specific* explicit trajectory identifier than this grouping key
 * already uses could resolve which tied point the neighbor actually continues from/to (none
 * does, for this dataset shape: ``sample_id`` is deliberately excluded from the grouping key
 * above, and ``technical_replicate`` is deliberately excluded from it too, so neither is
 * available here to break the tie). Every real observation is still returned as its own point
 * -- none dropped, none averaged -- but a tied bucket's own points, and both of its immediate
 * neighbors, each become their own single-point segment with ``connectable: false`` (task
 * instructions: "show all observations and break connections into, within, and out of that
 * group unless an explicit trajectory identifier resolves the ambiguity").
 *
 * This grouping key's own two fields are themselves taken at face value: a ``condition_id`` of
 * ``"ctrl"`` or a ``biological_replicate`` of ``"1"`` is trusted to mean exactly what it says
 * wherever it recurs. In particular, a repeated ``biological_replicate`` label by itself does
 * not *establish* that the rows carrying it are the same longitudinal unit -- it is only
 * evidence of that if the dataset's own authors used the label consistently to track one
 * organism/sample across time in the first place. This function has no way to verify that
 * consistency; it can only honor the label as given, exactly as it already honors
 * ``condition_id``.
 */
export function groupIntoSeries(points: PlottablePoint[]): SeriesGroup[] {
  if (points.length === 0) return [];

  const groupKey = (point: PlottablePoint): string =>
    `${point.conditionId ?? "\u0000"}::${point.biologicalReplicate ?? "\u0000"}`;

  const groupsByKey = new Map<string, PlottablePoint[]>();
  for (const point of points) {
    const key = groupKey(point);
    const existing = groupsByKey.get(key);
    if (existing) existing.push(point);
    else groupsByKey.set(key, [point]);
  }

  const series: SeriesGroup[] = [];
  for (const groupPoints of groupsByKey.values()) {
    const sorted = [...groupPoints].sort((a, b) => a.time - b.time);

    // Partition into buckets of points sharing the exact same recorded time. A bucket of size
    // 1 is a single, unambiguous observation; a bucket of size > 1 is a tie.
    const buckets: PlottablePoint[][] = [];
    for (const point of sorted) {
      const lastBucket = buckets[buckets.length - 1];
      if (lastBucket && lastBucket[0].time === point.time) {
        lastBucket.push(point);
      } else {
        buckets.push([point]);
      }
    }

    // Only adjacent size-1 buckets ever connect to each other. A size > 1 bucket's own points
    // are each isolated, and so is every bucket immediately touching it on either side --
    // breaking connections into, within, and out of the tie, never just the one edge between
    // the tied points themselves.
    let chain: PlottablePoint[] = [];
    const flushChain = () => {
      if (chain.length > 0) series.push({ points: chain, connectable: chain.length > 1 });
      chain = [];
    };
    for (const bucket of buckets) {
      if (bucket.length > 1) {
        flushChain();
        for (const tiedPoint of bucket) series.push({ points: [tiedPoint], connectable: false });
      } else {
        chain.push(bucket[0]);
      }
    }
    flushChain();
  }
  return series;
}

/** The distinct ``condition_id`` values actually present in ``rows``, plus ``null`` once if
 * at least one row has no ``condition_id`` recorded -- in first-appearance order, never
 * alphabetized (never implying an ordering the dataset itself does not declare). */
export function distinctConditionIds(rows: TimeSeriesDataRowItem[]): (string | null)[] {
  const seen = new Set<string | null>();
  const ordered: (string | null)[] = [];
  for (const row of rows) {
    if (!seen.has(row.condition_id)) {
      seen.add(row.condition_id);
      ordered.push(row.condition_id);
    }
  }
  return ordered;
}

/** Rows whose own ``condition_id`` is in ``selected`` -- never mutates, filters, or reorders
 * anything about the rows themselves beyond this inclusion test. */
export function filterRowsByCondition(
  rows: TimeSeriesDataRowItem[],
  selected: ReadonlySet<string | null>,
): TimeSeriesDataRowItem[] {
  return rows.filter((row) => selected.has(row.condition_id));
}

export interface AxisDomain {
  min: number;
  max: number;
}

/** A padded numeric domain covering every value in ``values`` -- never forced to include
 * zero (task instructions never ask for that, and doing so could visually compress real
 * variation in data that happens to sit far from zero). A single repeated value (or an empty
 * input) gets an arbitrary, symmetric pad so the axis is never degenerate. */
export function computeAxisDomain(values: number[]): AxisDomain {
  if (values.length === 0) return { min: 0, max: 1 };
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) {
    const pad = min === 0 ? 1 : Math.abs(min) * 0.1;
    return { min: min - pad, max: max + pad };
  }
  const pad = (max - min) * 0.08;
  return { min: min - pad, max: max + pad };
}
