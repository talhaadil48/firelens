import type { Data, Shape } from "plotly.js";
import type { Profile } from "./presentation";
import type { ConditionPoint } from "./coverage";
import { chartColors, useTheme } from "./theme";
import Plot from "./plotlyComponent";

export default function CoveragePlot({
  points,
  profile,
  fullRange,
  outcome = "all",
  onPointSelect,
}: {
  points: ConditionPoint[];
  profile?: Profile;
  fullRange: boolean;
  outcome?: string;
  onPointSelect?: (point: ConditionPoint) => void;
}) {
  const theme = useTheme(),
    colors = chartColors(theme);
  const index = [
    "ignited",
    "extinguished",
    "cool_flame",
    "failed",
    "unknown",
  ].indexOf(outcome);
  const color = index >= 0 ? colors.outcomes[index] : colors.point;
  const maxPressure = Math.max(
    120,
    ...points.map((point) => point.pressure),
    profile?.pressure.minimum ?? 0,
    profile?.pressure.maximum ?? 0,
  );
  const yMax = fullRange ? Math.ceil((maxPressure * 1.06) / 10) * 10 : 120;
  const groups: Data[] = [
    {
      type: "scatter",
      mode: "markers",
      name: "Reviewed tests",
      showlegend: false,
      x: points.map((p) => p.oxygen),
      y: points.map((p) => p.pressure),
      customdata: points.map((_, i) => i),
      text: points.map(
        (p) =>
          `${p.rows.length.toLocaleString()} reviewed ${p.rows.length === 1 ? "test" : "tests"}<br>${p.accessions.join(", ")}`,
      ),
      hovertemplate:
        "%{text}<br>Oxygen: %{x:.2f}%<br>Pressure: %{y:.2f} kPa<extra></extra>",
      marker: {
        color,
        size: points.map((p) =>
          Math.min(32, 7 + Math.sqrt(p.rows.length) * 2.1),
        ),
        opacity: 0.78,
        line: { color: colors.pointLine, width: 1.2 },
      },
    },
  ];
  const shapes: Partial<Shape>[] = [],
    annotations = [];
  if (profile) {
    const o = profile.oxygen,
      p = profile.pressure;
    if (
      o.minimum != null &&
      o.maximum != null &&
      p.minimum != null &&
      p.minimum === p.maximum &&
      o.minimum === o.maximum
    ) {
      const x = o.minimum * 100,
        y = p.minimum;
      shapes.push(
        {
          type: "line",
          x0: x,
          x1: x,
          y0: 0,
          y1: y,
          line: { color: colors.target, width: 1.2, dash: "dot" },
          layer: "below",
        },
        {
          type: "line",
          x0: 0,
          x1: x,
          y0: y,
          y1: y,
          line: { color: colors.target, width: 1.2, dash: "dot" },
          layer: "below",
        },
      );
      groups.push({
        type: "scatter",
        mode: "markers",
        name: "Mission target",
        showlegend: false,
        x: [x],
        y: [y],
        marker: {
          color: colors.target,
          symbol: "diamond-open",
          size: 17,
          line: { width: 2.3 },
        },
        hovertemplate:
          "Illustrative mission target<br>O₂ %{x:.2f}%<br>Pressure %{y:.2f} kPa<extra></extra>",
      });
    } else {
      const x0 = (o.minimum ?? 0) * 100,
        x1 = (o.maximum ?? 1) * 100,
        y0 = p.minimum ?? 0,
        y1 = p.maximum ?? yMax;
      shapes.push({
        type: "rect",
        x0,
        x1,
        y0,
        y1,
        fillcolor: colors.targetFill,
        line: { color: colors.target, width: 1.3, dash: "dash" },
        layer: "below",
      });
      if (y0 <= yMax)
        annotations.push({
          x: Math.min(x1 - 1, 97),
          y: Math.min(y1, yMax - 6),
          text: "Mission envelope",
          showarrow: false,
          xanchor: "right" as const,
          yanchor: "bottom" as const,
          font: { color: colors.target, size: 11 },
        });
    }
  }
  return (
    <Plot
      data={groups}
      layout={{
        autosize: true,
        margin: { t: 18, r: 24, b: 55, l: 60 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { color: colors.text, family: "Inter, sans-serif", size: 12 },
        xaxis: {
          title: { text: "Oxygen concentration (%)", standoff: 18 },
          range: [-2, 102],
          tickvals: [0, 20, 40, 60, 80, 100],
          gridcolor: colors.grid,
          zeroline: false,
          fixedrange: false,
          ticks: "outside",
          ticklen: 5,
          tickcolor: colors.grid,
        },
        yaxis: {
          title: { text: "Pressure (kPa)", standoff: 16 },
          range: [0, yMax],
          dtick: fullRange ? undefined : 20,
          gridcolor: colors.grid,
          zeroline: false,
          ticks: "outside",
          ticklen: 5,
          tickcolor: colors.grid,
        },
        shapes,
        annotations,
        hovermode: "closest",
        hoverlabel: {
          bgcolor: colors.hover,
          bordercolor: colors.grid,
          font: { color: colors.text },
        },
        dragmode: "pan",
        uirevision: `${profile?.id}:${fullRange}:${outcome}`,
      }}
      config={{
        responsive: true,
        displaylogo: false,
        scrollZoom: false,
        modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
        toImageButtonOptions: {
          filename: "firelens-tested-conditions",
          format: "png",
          scale: 2,
        },
      }}
      useResizeHandler
      style={{ width: "100%", height: 350 }}
      onClick={(event) => {
        const point = event.points[0];
        if (point?.curveNumber === 0 && typeof point.customdata === "number") {
          const item = points[point.customdata];
          if (item) onPointSelect?.(item);
        }
      }}
    />
  );
}
