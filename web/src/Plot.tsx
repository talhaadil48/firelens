import type { Data, Shape } from "plotly.js";
import type { TestRow } from "./client";
import type { Profile } from "./presentation";

import Plot from "./plotlyComponent";
const outcomes: Record<
  string,
  { label: string; color: string; symbol: string }
> = {
  ignited: { label: "Ignited", color: "#79cfff", symbol: "circle" },
  extinguished: { label: "Extinguished", color: "#76d9ba", symbol: "diamond" },
  cool_flame: { label: "Cool flame", color: "#b7a4ed", symbol: "triangle-up" },
  failed: { label: "Failed (reported)", color: "#e8b574", symbol: "x" },
  unknown: { label: "Not reported", color: "#7e91a5", symbol: "circle-open" },
};
export default function CoveragePlot({
  tests,
  profile,
  onSelect,
}: {
  tests: TestRow[];
  profile?: Profile;
  onSelect?: (id: string) => void;
}) {
  const groups = Object.entries(outcomes).map(([key, style]) => {
    const rows = tests.filter((row) => (row.outcome ?? "unknown") === key);
    return {
      type: "scatter",
      mode: "markers",
      name: style.label,
      x: rows.map((r) => r.o2_fraction! * 100),
      y: rows.map((r) => r.pressure_kpa),
      customdata: rows.map((r) => r.accession),
      text: rows.map((r) => `${r.accession} · ${r.test_id}`),
      hovertemplate:
        "%{text}<br>O₂ %{x:.2f}%<br>Pressure %{y:.2f} kPa<extra>%{fullData.name}</extra>",
      marker: {
        color: style.color,
        symbol: style.symbol,
        size: 8,
        opacity: 0.7,
        line: { width: 0.5, color: "#0d1822" },
      },
    } as Data;
  });
  const shapes: Partial<Shape>[] = [];
  const annotations = [];
  if (profile) {
    const o = profile.oxygen,
      p = profile.pressure;
    const x0 = (o.minimum ?? 0) * 100,
      x1 = (o.maximum ?? 1) * 100;
    const y0 = p.minimum ?? 0,
      y1 = p.maximum ?? Math.max(110, ...tests.map((r) => r.pressure_kpa ?? 0));
    if (x0 === x1 && y0 === y1) {
      groups.push({
        type: "scatter",
        mode: "markers",
        name: "Mission target",
        x: [x0],
        y: [y0],
        marker: {
          symbol: "cross",
          size: 16,
          color: "#f4c47d",
          line: { width: 2 },
        },
        hovertemplate:
          "Illustrative target<br>O₂ %{x:.2f}%<br>%{y:.2f} kPa<extra></extra>",
      });
    } else {
      shapes.push({
        type: "rect",
        x0,
        x1,
        y0,
        y1,
        fillcolor: "rgba(244,196,125,0.08)",
        line: { color: "#f4c47d", width: 1.5, dash: "dot" },
        layer: "below",
      });
      annotations.push({
        x: x0,
        y: y1,
        text: "Mission envelope",
        showarrow: false,
        xanchor: "left" as const,
        yanchor: "bottom" as const,
        font: { color: "#f4c47d", size: 11 },
      });
    }
  }
  return (
    <Plot
      data={groups}
      layout={{
        autosize: true,
        margin: { t: 35, r: 25, b: 75, l: 60 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { color: "#a9b8c7", family: "Inter, sans-serif", size: 12 },
        xaxis: {
          title: { text: "Oxygen concentration (%)" },
          gridcolor: "#20303d",
          zeroline: false,
          rangemode: "tozero",
        },
        yaxis: {
          title: { text: "Pressure (kPa)" },
          gridcolor: "#20303d",
          zeroline: false,
          rangemode: "tozero",
        },
        legend: { orientation: "h", y: -0.25, x: 0, font: { size: 11 } },
        shapes,
        annotations,
        hovermode: "closest",
        uirevision: profile?.id ?? "coverage",
      }}
      config={{
        responsive: true,
        displaylogo: false,
        modeBarButtonsToRemove: ["lasso2d", "select2d"],
        toImageButtonOptions: {
          filename: "firelens-reviewed-coverage",
          format: "png",
          scale: 2,
        },
      }}
      useResizeHandler
      style={{ width: "100%", height: 370 }}
      onClick={(event) => {
        const id = event.points[0]?.customdata;
        if (typeof id === "string") onSelect?.(id);
      }}
    />
  );
}
