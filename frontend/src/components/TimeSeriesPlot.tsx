import { useState } from "react";
import type { TimeSeriesDataRowItem, TimeSeriesMeasurementColumnItem } from "../types";
import { formatScientific, fullPrecisionValue } from "../format";
import {
  computeAxisDomain,
  groupIntoSeries,
  plottablePointsForColumn,
  summarizeExclusions,
  type PlottablePoint,
} from "../lib/timeSeriesPlotData";

/** A fixed, colorblind-distinguishable-enough categorical palette -- this project has no
 * design-token library for data series colors, so one small, deliberately bounded list is
 * introduced here rather than generating colors ad hoc. A column beyond the palette's own
 * length repeats it; see the module docstring for why that is an accepted limitation. */
const SERIES_COLORS = [
  "#2563eb",
  "#dc2626",
  "#059669",
  "#d97706",
  "#7c3aed",
  "#0891b2",
  "#db2777",
  "#65a30d",
];

const WIDTH = 640;
const HEIGHT = 260;
const MARGIN = { top: 16, right: 16, bottom: 36, left: 56 };

interface TooltipState {
  x: number;
  y: number;
  point: PlottablePoint;
  columnName: string;
  unit: string | null;
}

interface TimeSeriesPlotProps {
  panelColumns: TimeSeriesMeasurementColumnItem[];
  selectedColumnNames: Set<string>;
  rows: TimeSeriesDataRowItem[];
  sharedUnit: string | null;
}

/** One unit-compatible panel's own interactive plot -- a hand-rolled SVG scatter/line chart
 * (no charting library exists in this frontend yet; adding one for a single chart type was
 * judged not worth the new dependency). Renders only the dataset's own real, original
 * measurement values under their own original column names (task instructions: "plot
 * original measurements using original column names"); see ``lib/timeSeriesPlotData.ts`` for
 * every data decision (exclusion, series grouping, connectability) -- this component only
 * draws what that module already decided. The data table rendered alongside this by the
 * caller is the fully accessible, non-truncated source of truth; this plot is a visual,
 * pointer/keyboard-hoverable supplement, never the only place a value can be read. */
export function TimeSeriesPlot({
  panelColumns,
  selectedColumnNames,
  rows,
  sharedUnit,
}: TimeSeriesPlotProps) {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const activeColumns = panelColumns.filter((c) => selectedColumnNames.has(c.column_name));

  if (activeColumns.length === 0) return null;

  const perColumn = activeColumns.map((column) => {
    const points = plottablePointsForColumn(rows, column.column_name);
    return { column, points, series: groupIntoSeries(points) };
  });

  const allValues = perColumn.flatMap((c) => c.points.map((p) => p.value));
  const allTimes = perColumn.flatMap((c) => c.points.map((p) => p.time));
  const yDomain = computeAxisDomain(allValues);
  const xDomain = computeAxisDomain(allTimes);

  const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

  function xPixel(time: number): number {
    const span = xDomain.max - xDomain.min;
    const fraction = span === 0 ? 0.5 : (time - xDomain.min) / span;
    return MARGIN.left + fraction * innerWidth;
  }
  function yPixel(value: number): number {
    const span = yDomain.max - yDomain.min;
    const fraction = span === 0 ? 0.5 : (value - yDomain.min) / span;
    return MARGIN.top + (1 - fraction) * innerHeight;
  }

  const anyExcluded = activeColumns.some((column) => {
    const counts = summarizeExclusions(rows, column.column_name);
    return Object.values(counts).some((n) => (n ?? 0) > 0);
  });

  return (
    <div className="time-series-plot-panel">
      <div className="time-series-plot-legend" role="list" aria-label="Plotted measurement columns">
        {perColumn.map(({ column }, index) => (
          <span className="time-series-plot-legend-item" role="listitem" key={column.column_name}>
            <span
              className="time-series-plot-legend-swatch"
              style={{ background: SERIES_COLORS[index % SERIES_COLORS.length] }}
              aria-hidden="true"
            />
            {column.column_name}
          </span>
        ))}
        <span className="time-series-plot-legend-unit">
          {sharedUnit ? `Unit: ${sharedUnit}` : "Unit not declared"}
        </span>
      </div>

      <div className="time-series-plot-svg-wrapper">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width="100%"
        role="img"
        aria-label={`Time-course plot of ${activeColumns
          .map((c) => c.column_name)
          .join(", ")}, unit ${sharedUnit ?? "not declared"}`}
      >
        <line
          x1={MARGIN.left}
          y1={HEIGHT - MARGIN.bottom}
          x2={WIDTH - MARGIN.right}
          y2={HEIGHT - MARGIN.bottom}
          className="time-series-plot-axis"
        />
        <line
          x1={MARGIN.left}
          y1={MARGIN.top}
          x2={MARGIN.left}
          y2={HEIGHT - MARGIN.bottom}
          className="time-series-plot-axis"
        />
        <text x={MARGIN.left} y={HEIGHT - 6} className="time-series-plot-axis-label">
          <title>{fullPrecisionValue(xDomain.min)}</title>
          {formatScientific(xDomain.min)}
        </text>
        <text
          x={WIDTH - MARGIN.right}
          y={HEIGHT - 6}
          textAnchor="end"
          className="time-series-plot-axis-label"
        >
          <title>{fullPrecisionValue(xDomain.max)}</title>
          {formatScientific(xDomain.max)} (time)
        </text>
        <text x={4} y={MARGIN.top + 8} className="time-series-plot-axis-label">
          <title>{fullPrecisionValue(yDomain.max)}</title>
          {formatScientific(yDomain.max)}
        </text>
        <text x={4} y={HEIGHT - MARGIN.bottom} className="time-series-plot-axis-label">
          <title>{fullPrecisionValue(yDomain.min)}</title>
          {formatScientific(yDomain.min)}
        </text>

        {perColumn.map(({ column, series }, colorIndex) => {
          const color = SERIES_COLORS[colorIndex % SERIES_COLORS.length];
          return (
            <g key={column.column_name}>
              {series.map((group, seriesIndex) => (
                <g key={`${column.column_name}-series-${seriesIndex}`}>
                  {group.connectable && group.points.length > 1 && (
                    <polyline
                      points={group.points
                        .map((p) => `${xPixel(p.time)},${yPixel(p.value)}`)
                        .join(" ")}
                      fill="none"
                      stroke={color}
                      strokeWidth={1.5}
                      className="time-series-plot-line"
                    />
                  )}
                  {group.points.map((point) => (
                    <circle
                      key={point.rowIndex}
                      cx={xPixel(point.time)}
                      cy={yPixel(point.value)}
                      r={4}
                      fill={color}
                      tabIndex={0}
                      className="time-series-plot-point"
                      onMouseEnter={() =>
                        setTooltip({
                          x: xPixel(point.time),
                          y: yPixel(point.value),
                          point,
                          columnName: column.column_name,
                          unit: column.unit,
                        })
                      }
                      onFocus={() =>
                        setTooltip({
                          x: xPixel(point.time),
                          y: yPixel(point.value),
                          point,
                          columnName: column.column_name,
                          unit: column.unit,
                        })
                      }
                      onMouseLeave={() => setTooltip(null)}
                      onBlur={() => setTooltip(null)}
                    >
                      <title>
                        {column.column_name} = {fullPrecisionValue(point.value)} (
                        {column.unit ?? "unit not declared"}) at time{" "}
                        {fullPrecisionValue(point.time)}
                        {point.sampleId ? `, sample ${point.sampleId}` : ", no sample id recorded"}
                        {point.conditionId ? `, condition ${point.conditionId}` : ""}
                        {" -- row "}
                        {point.rowIndex}
                      </title>
                    </circle>
                  ))}
                </g>
              ))}
            </g>
          );
        })}
      </svg>

      {tooltip && (
        <div
          className="time-series-plot-tooltip"
          style={{ left: `${(tooltip.x / WIDTH) * 100}%`, top: `${(tooltip.y / HEIGHT) * 100}%` }}
          role="status"
        >
          <strong>{tooltip.columnName}</strong> = {fullPrecisionValue(tooltip.point.value)}
          {tooltip.unit ? ` ${tooltip.unit}` : " (unit not declared)"}
          <br />
          time = {fullPrecisionValue(tooltip.point.time)}
          <br />
          sample: {tooltip.point.sampleId ?? "not recorded"}
          <br />
          condition: {tooltip.point.conditionId ?? "not recorded"}
          <br />
          biological replicate: {tooltip.point.biologicalReplicate ?? "not recorded"}
          <br />
          technical replicate: {tooltip.point.technicalReplicate ?? "not recorded"}
          <br />
          source row: {tooltip.point.rowIndex}
        </div>
      )}
      </div>

      {anyExcluded && (
        <ul className="time-series-plot-exclusions">
          {activeColumns.map((column) => {
            const counts = summarizeExclusions(rows, column.column_name);
            const parts = Object.entries(counts)
              .filter(([, n]) => (n ?? 0) > 0)
              .map(([reason, n]) => `${n} ${reason.replace(/_/g, " ").toLowerCase()}`);
            if (parts.length === 0) return null;
            return (
              <li key={column.column_name}>
                {column.column_name}: {parts.join(", ")} excluded from this plot (shown in the
                table below).
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
