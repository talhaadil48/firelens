import { lazy, Suspense } from "react";
import ChartBoundary from "./components/ChartBoundary";
import type { Profile } from "./presentation";
import { reviewedRow } from "./presentation";
import type { TestRow } from "./client";

const Plot = lazy(() => import("./Plot"));
export default function CoverageMap({
  tests,
  profile,
  onSelect,
}: {
  tests: TestRow[];
  profile?: Profile;
  onSelect?: (accession: string) => void;
}) {
  const reviewed = tests.filter(
    (row) =>
      reviewedRow(row) && row.o2_fraction != null && row.pressure_kpa != null,
  );
  if (!reviewed.length)
    return (
      <div className="empty-state" role="status">
        <span className="empty-orbit">＋</span>
        <strong>No reviewed measurement points yet</strong>
        <p>
          Only reviewed rows with both oxygen and pressure are shown. Missing
          values stay missing.
        </p>
      </div>
    );
  return (
    <>
      <ChartBoundary>
        <Suspense
          fallback={
            <div className="chart-loading" role="status">
              Preparing the coverage map…
            </div>
          }
        >
          <Plot tests={reviewed} profile={profile} onSelect={onSelect} />
        </Suspense>
      </ChartBoundary>
      <p className="chart-caption">
        {reviewed.length.toLocaleString()} reviewed rows with both coordinates ·
        Select a point to open its study. Overlapping points may represent
        several tests.
      </p>
      <details className="chart-table">
        <summary>View accessible chart data</summary>
        <div className="table-scroll">
          <table>
            <caption>Reviewed plotted test rows</caption>
            <thead>
              <tr>
                <th>Study / test</th>
                <th>Oxygen (%)</th>
                <th>Pressure (kPa)</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {reviewed.map((row) => (
                <tr key={`${row.accession}:${row.test_id}`}>
                  <td>
                    <a href={`#/investigations/${row.accession}`}>
                      {row.accession} / {row.test_id}
                    </a>
                  </td>
                  <td>{(row.o2_fraction! * 100).toFixed(2)}</td>
                  <td>{row.pressure_kpa}</td>
                  <td>{row.outcome ?? "Not reported"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
