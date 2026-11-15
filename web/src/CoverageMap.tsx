import { lazy, Suspense, useState } from "react";
import ChartBoundary from "./components/ChartBoundary";
import type { Profile } from "./presentation";
import { number, range } from "./presentation";
import type { TestRow } from "./client";
import { coverageRows, groupConditions, outcomeOptions } from "./coverage";
import type { ConditionPoint } from "./coverage";

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
  const [outcome, setOutcome] = useState("all"),
    [fullRange, setFullRange] = useState(false),
    [selected, setSelected] = useState<ConditionPoint | null>(null);
  const reviewed = coverageRows(tests);
  const filtered = reviewed.filter(
    (row) => outcome === "all" || (row.outcome ?? "unknown") === outcome,
  );
  const points = groupConditions(filtered);
  const inView = filtered.filter(
    (row) => fullRange || row.pressure_kpa! <= 120,
  );
  const outside = filtered.length - inView.length;
  const studies = new Set(filtered.map((row) => row.accession)).size;
  const targetOutside =
    !fullRange && profile && (profile.pressure.minimum ?? 0) > 120;
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
    <div className="coverage-workspace">
      <div className="coverage-toolbar">
        <div
          className="coverage-view-switch"
          role="group"
          aria-label="Pressure view"
        >
          <button
            aria-pressed={!fullRange}
            title="Display preset for readability, not a NASA pressure limit"
            onClick={() => {
              setFullRange(false);
              setSelected(null);
            }}
          >
            Cabin pressures <span>0–120 kPa</span>
          </button>
          <button
            aria-pressed={fullRange}
            onClick={() => {
              setFullRange(true);
              setSelected(null);
            }}
          >
            Full range
          </button>
        </div>
        <p className="coverage-view-count" aria-live="polite">
          <strong>{inView.length.toLocaleString()}</strong> of{" "}
          {filtered.length.toLocaleString()} tests{" "}
          {fullRange ? "across the full pressure range" : "at 0–120 kPa"}
        </p>
      </div>
      <div
        className="outcome-filters"
        role="group"
        aria-label="Filter chart by reported outcome"
      >
        {outcomeOptions.map((option, i) => {
          const count =
            option.id === "all"
              ? reviewed.length
              : reviewed.filter(
                  (row) => (row.outcome ?? "unknown") === option.id,
                ).length;
          if (!count && option.id !== "all") return null;
          return (
            <button
              key={option.id}
              className={`outcome-filter outcome-${i}`}
              aria-pressed={outcome === option.id}
              onClick={() => {
                setOutcome(option.id);
                setSelected(null);
              }}
            >
              <span className="outcome-dot" />
              {option.label}
              <span className="outcome-count">{count.toLocaleString()}</span>
            </button>
          );
        })}
      </div>
      <div className="coverage-canvas">
        <ChartBoundary>
          <Suspense
            fallback={
              <div className="chart-loading" role="status">
                Preparing the coverage map…
              </div>
            }
          >
            <Plot
              points={points}
              profile={profile}
              fullRange={fullRange}
              outcome={outcome}
              onPointSelect={setSelected}
            />
          </Suspense>
        </ChartBoundary>
      </div>
      {(outside > 0 || targetOutside) && (
        <p className="coverage-outside">
          <span aria-hidden="true">↗</span>
          {outside > 0
            ? `${outside.toLocaleString()} tests above 120 kPa are outside the cabin view.`
            : "Your mission target is above the cabin view."}{" "}
          <button className="text-button" onClick={() => setFullRange(true)}>
            Show full range
          </button>
        </p>
      )}
      {selected && (
        <aside
          className="condition-selection"
          aria-label="Selected tested condition"
        >
          <div>
            <span className="eyebrow">SELECTED CONDITION</span>
            <strong>
              {number(selected.oxygen, 2)}% O₂ <span>·</span>{" "}
              {number(selected.pressure, 2)} kPa
            </strong>
            <p>
              {selected.rows.length} reviewed tests at this oxygen and pressure
            </p>
          </div>
          <div className="selected-study-links">
            {selected.accessions.map((id) => (
              <a
                href={`#/investigations/${id}`}
                key={id}
                onClick={(event) => {
                  if (onSelect) {
                    event.preventDefault();
                    onSelect(id);
                  }
                }}
              >
                {id} ↗
              </a>
            ))}
          </div>
          <button
            className="icon-button"
            aria-label="Close selected condition"
            onClick={() => setSelected(null)}
          >
            ×
          </button>
        </aside>
      )}
      <div className="coverage-footnote">
        <div className="bubble-key">
          <span className="bubble-key-small" />
          <span className="bubble-key-large" />
          <p>Bubble size = tests at the same oxygen & pressure</p>
        </div>
        {profile && (
          <p className="mission-key">
            <span />
            Mission: {range(profile.oxygen)} · {range(profile.pressure)}
          </p>
        )}
      </div>
      <p className="chart-caption">
        {filtered.length.toLocaleString()} reviewed rows with both coordinates ·{" "}
        {points.length.toLocaleString()} oxygen / pressure pairs · {studies}{" "}
        studies. Select a bubble to inspect its source studies.
      </p>
      <details className="chart-table">
        <summary>View accessible chart data</summary>
        <p className="small muted">
          All rows matching the outcome filter, including those outside the
          current pressure view.
        </p>
        <div className="table-scroll">
          <table>
            <caption>
              Reviewed plotted test rows · original coordinates retained
            </caption>
            <thead>
              <tr>
                <th>Study / test</th>
                <th>Oxygen (%)</th>
                <th>Pressure (kPa)</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
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
    </div>
  );
}
