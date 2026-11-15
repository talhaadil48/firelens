import { lazy, Suspense, useEffect, useState } from "react";
import { getAllTests } from "../client";
import type { Schema, TestRow } from "../client";
import { measurementRow } from "../presentation";
import CoverageMap from "../CoverageMap";
import ChartBoundary from "./ChartBoundary";
import { ErrorNotice, TestTable } from "./Shared";

const Bars = lazy(() => import("./EvidenceBars"));
type Citation = Schema["Citation"];
function matchesCitation(row: TestRow, citation: Citation) {
  return (
    citation.id === `row:${row.accession}:${row.test_id}` &&
    citation.accession === row.accession &&
    citation.provenance.source_file ===
      (row.source_file ?? row.provenance.source_file) &&
    citation.provenance.source_row ===
      (row.source_row ?? row.provenance.source_row) &&
    citation.provenance.source_version === row.provenance.source_version &&
    (citation.provenance.source_sha256 == null ||
      citation.provenance.source_sha256 === row.provenance.source_sha256) &&
    !citation.provenance.is_mock &&
    measurementRow(row)
  );
}
export default function ChatChart({
  citations,
  question = "",
}: {
  citations: Citation[];
  question?: string;
}) {
  const [rows, setRows] = useState<TestRow[] | null>(null),
    [error, setError] = useState(""),
    [view, setView] = useState("chart");
  useEffect(() => {
    const controller = new AbortController();
    const rowCitations = citations.filter((c) => c.id.startsWith("row:"));
    const accessions = [...new Set(rowCitations.map((c) => c.accession))];
    Promise.all(
      accessions.map((accession) =>
        getAllTests(controller.signal, { accession }),
      ),
    )
      .then((pages) => {
        const unique = new Map(
          pages
            .flat()
            .filter((row) => rowCitations.some((c) => matchesCitation(row, c)))
            .map((row) => [`${row.accession}:${row.test_id}`, row]),
        );
        setRows([...unique.values()]);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load cited measurements",
          );
      });
    return () => controller.abort();
  }, [citations]);
  if (error)
    return <ErrorNotice message={`Cited-data chart unavailable: ${error}`} />;
  if (!rows)
    return (
      <p className="small muted" role="status">
        Checking cited measurements for a visual comparison…
      </p>
    );
  const scatter = rows.filter(
    (row) => row.o2_fraction != null && row.pressure_kpa != null,
  );
  const field = (["flow_cm_s", "pressure_kpa", "o2_fraction"] as const).find(
    (key) => rows.filter((row) => row[key] != null).length >= 2,
  );
  const requestedScatter =
    /\b(oxygen|o2)\b/i.test(question) && /\bpressures?\b/i.test(question);
  const requestedField = /\b(airflow|flow|velocit(?:y|ies))\b|flow_cm_s/i.test(
    question,
  )
    ? "flow_cm_s"
    : /\bpressures?\b/i.test(question) && !/\b(oxygen|o2)\b/i.test(question)
      ? "pressure_kpa"
      : null;
  const requestedAvailable =
    requestedField &&
    rows.filter((row) => row[requestedField] != null).length >= 2;
  if (
    (requestedScatter && scatter.length < 2) ||
    (!requestedScatter && requestedField && !requestedAvailable)
  )
    return (
      <p className="small muted">
        The cited rows lack enough measurements of the requested quantities. No
        different quantity has been substituted.
      </p>
    );
  const showScatter =
    scatter.length >= 2 && (requestedScatter || !requestedAvailable);
  const barField = requestedAvailable ? requestedField : field;
  if (scatter.length < 2 && !field)
    return (
      <p className="small muted">
        A chart needs at least two cited, measurements of the same quantity. No
        values have been inferred.
      </p>
    );
  return (
    <section
      className="chat-chart"
      aria-label="Visual answer from cited measurements"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">THE DATA BEHIND THIS ANSWER</p>
          <h3>Cited measurements, at a glance.</h3>
        </div>
        <div className="view-toggle" role="group" aria-label="Cited data view">
          <button
            aria-pressed={view === "chart"}
            onClick={() => setView("chart")}
          >
            Chart
          </button>
          <button
            aria-pressed={view === "table"}
            onClick={() => setView("table")}
          >
            Source rows
          </button>
        </div>
      </div>
      <p className="small muted">
        Only measurements matching this answer’s citations. No simulated or
        inferred values.
      </p>
      {view === "table" ? (
        <TestTable rows={rows} />
      ) : showScatter ? (
        <CoverageMap tests={scatter} />
      ) : (
        <ChartBoundary>
          <Suspense fallback={<p role="status">Preparing cited-data chart…</p>}>
            <Bars rows={rows} field={barField!} />
          </Suspense>
        </ChartBoundary>
      )}
    </section>
  );
}
