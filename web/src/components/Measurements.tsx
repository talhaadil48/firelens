import { useState } from "react";
import type { TestRow } from "../client";
import { TestTable } from "./Shared";

export default function Measurements({ rows }: { rows: TestRow[] }) {
  const [file, setFile] = useState("");
  const [page, setPage] = useState(0);
  const [mode, setMode] = useState("source");
  const files = [...new Set(rows.map((row) => row.provenance.source_file))];
  const activeFile = files.includes(file) ? file : files[0];
  const filtered = rows.filter(
    (row) => row.provenance.source_file === activeFile,
  );
  const start = page * 50;
  const visible = filtered.slice(start, start + 50);
  const columns = new Map<number, string>();
  for (const row of filtered)
    for (const cell of row.source_cells ?? [])
      columns.set(cell.column_index, cell.column);
  const headers = [...columns].sort((a, b) => a[0] - b[0]);
  return (
    <>
      <p className="small muted">
        All {rows.length.toLocaleString()} imported source records are available
        below. A source row may describe one test, a group, a session or a
        reference. Blank cells stay blank; lists and ranges are preserved
        without inventing combinations.
      </p>
      {!rows.length ? (
        <TestTable rows={[]} />
      ) : (
        <>
          <div className="measurement-controls">
            <label>
              Source table
              <select
                value={activeFile}
                onChange={(event) => {
                  setFile(event.target.value);
                  setPage(0);
                }}
              >
                {files.map((name) => (
                  <option key={name}>{name}</option>
                ))}
              </select>
            </label>
            <label>
              Display
              <select
                value={mode}
                onChange={(event) => setMode(event.target.value)}
              >
                <option value="source">Original source columns</option>
                <option value="standardized">Standardized fields</option>
              </select>
            </label>
          </div>
          <p className="small muted">
            Scroll across the table to see every source column.
          </p>
          <div
            className="detail-tests-scroll detail-panel-body"
            role="region"
            aria-label="Source measurements"
            tabIndex={0}
          >
            {mode === "source" && headers.length ? (
              <table className="source-measurements">
                <caption>
                  Original cells from {activeFile}. Values retain their original
                  spelling and units.
                </caption>
                <thead>
                  <tr>
                    <th>Source row / record type</th>
                    {headers.map(([index, name]) => (
                      <th key={index}>{name || `Unnamed column ${index}`}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visible.map((row) => (
                    <tr key={row.test_id}>
                      <td>
                        <a
                          href={row.provenance.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Row {row.provenance.source_row}
                        </a>
                        <small>
                          {row.record_kind?.replaceAll("_", " ") ??
                            "individual test"}
                        </small>
                      </td>
                      {headers.map(([index]) => (
                        <td key={index}>
                          {row.source_cells?.find(
                            (cell) => cell.column_index === index,
                          )?.value ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <>
                <TestTable rows={visible} />
                {visible.map((row) => (
                  <details className="measurement-record" key={row.test_id}>
                    <summary>
                      {row.test_id} · All standardized fields, metrics &
                      provenance
                    </summary>
                    <dl className="facts">
                      {Object.entries(row)
                        .filter(([key]) => key !== "source_cells")
                        .map(([key, value]) => (
                          <div key={key}>
                            <dt>{key.replaceAll("_", " ")}</dt>
                            <dd>
                              {value == null ? (
                                "Not available"
                              ) : typeof value === "object" ? (
                                <pre>{JSON.stringify(value, null, 2)}</pre>
                              ) : (
                                String(value)
                              )}
                            </dd>
                          </div>
                        ))}
                    </dl>
                  </details>
                ))}
              </>
            )}
          </div>
          <div className="measurement-pagination">
            <span className="small muted">
              {start + 1}–{Math.min(start + 50, filtered.length)} of{" "}
              {filtered.length.toLocaleString()} records in this table
            </span>
            <div className="button-row">
              <button
                className="button secondary"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                Previous rows
              </button>
              <button
                className="button secondary"
                disabled={start + 50 >= filtered.length}
                onClick={() => setPage(page + 1)}
              >
                Next rows
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
