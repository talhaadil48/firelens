import { useEffect, useState } from "react";
import { getCompare } from "../client";
import type { CompareResponse, Investigation } from "../client";
import { range, studyName } from "../presentation";
import { Empty, ErrorNotice, PageTitle, DataLabel } from "../components/Shared";

const fields: [string, (inv: Investigation) => string][] = [
  ["Objective", (inv) => inv.objectives ?? "Not reported"],
  ["Fuel phase", (inv) => inv.fuel_phase],
  [
    "Fuels & geometry",
    (inv) =>
      inv.summary != null
        ? (inv.summary.fuels_and_geometry ?? "Not reported")
        : "No source summary",
  ],
  ["Oxygen", (inv) => range(inv.condition_ranges?.oxygen)],
  ["Pressure", (inv) => range(inv.condition_ranges?.pressure)],
  ["Airflow", (inv) => range(inv.condition_ranges?.flow)],
  [
    "What varied",
    (inv) =>
      inv.summary != null
        ? (inv.summary.varied ?? "Not reported")
        : "No source summary",
  ],
  ["Hardware", (inv) => (inv.hardware ?? []).join(", ") || "Not reported"],
  ["Sensors", (inv) => (inv.sensors ?? []).join(", ") || "Not reported"],
  [
    "Safety categories",
    (inv) => (inv.fire_safety_tags ?? []).join(", ") || "Not reported",
  ],
  ["Normalized tests", (inv) => String(inv.test_count)],
  ["Platform", (inv) => inv.platform ?? "Not reported"],
];
export default function Compare({
  records,
  ids,
  setIds,
}: {
  records: Investigation[];
  ids: string[];
  setIds: (ids: string[]) => void;
}) {
  const [response, setResponse] = useState<CompareResponse | null>(null),
    [error, setError] = useState(""),
    [highlight, setHighlight] = useState(true);
  const key = ids.join(",");
  useEffect(() => {
    const controller = new AbortController();
    if (key.split(",").filter(Boolean).length >= 2)
      getCompare(key.split(","), controller.signal)
        .then(setResponse)
        .catch((reason: unknown) => {
          if (!controller.signal.aborted)
            setError(
              reason instanceof Error
                ? reason.message
                : "Comparison unavailable",
            );
        });
    return () => controller.abort();
  }, [key]);
  const current =
    response?.investigations.map((i) => i.accession).join(",") === key
      ? response
      : null;
  return (
    <>
      <PageTitle eyebrow="SIDE BY SIDE" title="Compare the research.">
        Choose two or three investigations. Compare reported conditions before
        interpreting outcomes.
      </PageTitle>
      <section className="panel">
        <div className="compare-pickers">
          {[0, 1, 2].map((index) => (
            <label key={index}>
              Investigation {index + 1}
              {index === 2 ? " (optional)" : ""}
              <select
                aria-label={`Investigation ${index + 1}`}
                value={ids[index] ?? ""}
                onChange={(e) => {
                  const next = [...ids];
                  if (e.target.value) next[index] = e.target.value;
                  else next.splice(index, 1);
                  setError("");
                  setIds(next.filter(Boolean));
                }}
              >
                <option value="">Choose investigation</option>
                {records.map((inv) => (
                  <option
                    value={inv.accession}
                    key={inv.accession}
                    disabled={
                      ids.includes(inv.accession) &&
                      ids[index] !== inv.accession
                    }
                  >
                    {inv.accession} · {studyName(inv)}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        <label className="check-label">
          <input
            type="checkbox"
            checked={highlight}
            onChange={(e) => setHighlight(e.target.checked)}
          />
          Highlight differing fields
        </label>
      </section>
      {error && <ErrorNotice message={error} />}
      {ids.length < 2 ? (
        <Empty title="Choose at least two investigations">
          Use the selectors above or add studies from the Explorer.
        </Empty>
      ) : !current ? (
        <p role="status">Loading source-grounded comparison…</p>
      ) : (
        <>
          <section className="panel">
            <div className="table-scroll compare-scroll">
              <table className="compare-table">
                <caption>
                  Source-backed comparison · highlighted cells contain differing
                  reported fields
                </caption>
                <thead>
                  <tr>
                    <th>REPORTED FIELD</th>
                    {current.investigations.map((inv) => (
                      <th key={inv.accession}>
                        <span className="mono muted">{inv.accession}</span>
                        <a href={`#/investigations/${inv.accession}`}>
                          <h2>{studyName(inv)}</h2>
                        </a>
                        <DataLabel inv={inv} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {fields.map(([label, read]) => {
                    const values = current.investigations.map(read);
                    const differs = new Set(values).size > 1;
                    return (
                      <tr
                        key={label}
                        className={highlight && differs ? "diff-row" : ""}
                      >
                        <th scope="row">{label}</th>
                        {values.map((v, i) => (
                          <td key={i}>{v}</td>
                        ))}
                      </tr>
                    );
                  })}
                  <tr>
                    <th scope="row">Underlying source</th>
                    {current.investigations.map((inv) => (
                      <td key={inv.accession}>
                        <a
                          href={
                            inv.doi
                              ? `https://doi.org/${inv.doi}`
                              : inv.source_url
                          }
                          target="_blank"
                          rel="noreferrer"
                        >
                          {inv.doi ?? inv.accession} ↗
                        </a>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
          <section className="panel">
            <p className="eyebrow">READING THE COMPARISON</p>
            <h2>Shared context. Different conditions.</h2>
            <p className="reading-text">{current.summary}</p>
            <div className="two-column">
              <div>
                <h3>In common</h3>
                <ul className="reading-list">
                  {current.same.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h3>Where they differ</h3>
                <ul className="reading-list">
                  {current.different.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
            {current.warnings.map((warning, i) => (
              <p className="small amber-text" key={i}>
                {warning}
              </p>
            ))}
          </section>
        </>
      )}
    </>
  );
}
