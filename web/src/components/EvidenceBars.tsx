import type { TestRow } from "../client";
import Plot from "../plotlyComponent";
import { useTheme, chartColors } from "../theme";
const labels = {
  flow_cm_s: "Airflow (cm/s)",
  pressure_kpa: "Pressure (kPa)",
  o2_fraction: "Oxygen (%)",
};
export default function EvidenceBars({
  rows,
  field,
}: {
  rows: TestRow[];
  field: keyof typeof labels;
}) {
  const colors = chartColors(useTheme());
  const valid = rows.filter((row) => row[field] != null);
  return (
    <>
      <Plot
        data={[
          {
            type: "bar",
            orientation: "h",
            y: valid.map((r) => `${r.accession} / ${r.test_id}`),
            x: valid.map(
              (r) => r[field]! * (field === "o2_fraction" ? 100 : 1),
            ),
            marker: { color: colors.point },
            hovertemplate: "%{y}<br>%{x}<extra></extra>",
          },
        ]}
        layout={{
          autosize: true,
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          margin: { l: 130, r: 20, t: 20, b: 50 },
          font: { color: colors.text, size: 11 },
          xaxis: {
            title: { text: labels[field] },
            gridcolor: colors.grid,
            rangemode: "tozero",
          },
          yaxis: { autorange: "reversed" },
        }}
        config={{ responsive: true, displaylogo: false }}
        useResizeHandler
        style={{ width: "100%", height: Math.max(220, valid.length * 40 + 80) }}
      />
      <p className="chart-caption">
        {valid.length} cited measurements · Each bar represents a reported test
        value.
      </p>
      <details>
        <summary>View accessible chart data</summary>
        <div className="table-scroll">
          <table>
            <caption>Exact cited measurements used in the chart</caption>
            <thead>
              <tr>
                <th>Study / test</th>
                <th>{labels[field]}</th>
                <th>Source row</th>
              </tr>
            </thead>
            <tbody>
              {valid.map((row) => (
                <tr key={`${row.accession}:${row.test_id}`}>
                  <td>
                    {row.accession} / {row.test_id}
                  </td>
                  <td>{row[field]! * (field === "o2_fraction" ? 100 : 1)}</td>
                  <td>
                    {row.source_file ?? row.provenance.source_file}, row{" "}
                    {row.source_row ?? row.provenance.source_row}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
