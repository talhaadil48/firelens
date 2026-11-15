import { useEffect, useMemo, useState } from "react";
import { getExport } from "../client";
import type { ExportResponse, Investigation, Meta } from "../client";
import { download } from "../presentation";
import { ErrorNotice, Modal } from "./Shared";

export default function ExportDialog({
  close,
  accession,
  selection,
  records,
  meta,
}: {
  close: () => void;
  accession?: string;
  selection?: string[];
  records: Investigation[];
  meta: Meta | null;
}) {
  const [scope, setScope] = useState(
      accession ?? (selection ? "__filtered" : ""),
    ),
    [format, setFormat] = useState("csv");
  const [metrics, setMetrics] = useState(true),
    [metadata, setMetadata] = useState(true);
  const [data, setData] = useState<ExportResponse | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    getExport(
      scope && scope !== "__filtered" ? { accession: scope } : {},
      controller.signal,
    )
      .then((value) => {
        setData(value);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not prepare export",
          );
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [scope]);
  const prepared = useMemo(() => {
    if (!data) return { content: "", count: 0 };
    const selectedData =
      scope === "__filtered" && selection
        ? {
            ...data,
            tests: data.tests.filter((row) =>
              selection.includes(row.accession),
            ),
            investigations: data.investigations.filter((inv) =>
              selection.includes(inv.accession),
            ),
          }
        : data;
    const rows = selectedData.tests;
    const tests = rows.map((row) => {
      const value: Record<string, unknown> = { ...row };
      if (!metrics) delete value.metrics;
      return value;
    });
    const provenance = {
      source_credit: data.source_credit,
      snapshot_id: meta?.snapshot_id,
      snapshot_date: meta?.snapshot_date,
      filters: {
        accession: scope === "__filtered" ? null : scope || null,
        selected_accessions: scope === "__filtered" ? selection : undefined,
      },
      units: {
        o2_fraction: "fraction (0–1)",
        pressure_kpa: "kPa",
        flow_cm_s: "cm/s",
      },
      notes:
        "Research evidence, not a safety assessment. Missing values remain empty/null.",
    };
    if (format === "json")
      return {
        count: tests.length,
        content: JSON.stringify(
          {
            ...provenance,
            investigations: metadata ? selectedData.investigations : undefined,
            tests,
          },
          null,
          2,
        ),
      };
    const columns = [
      "accession",
      "test_id",
      "test_date",
      "fuel",
      "fuel_phase",
      "sample_geometry",
      "o2_fraction",
      "pressure_kpa",
      "flow_cm_s",
      "gravity",
      "outcome",
      ...(metrics ? ["metrics"] : []),
      "evidence_type",
      "record_kind",
      "source_cells",
      "notes",
      "doi",
      "source_file",
      "source_row",
      "source_url",
      "source_version",
    ];
    for (const row of rows)
      for (const key of Object.keys(row)) {
        if ((metrics || key !== "metrics") && !columns.includes(key))
          columns.push(key);
      }
    const quote = (value: unknown) => {
      const text =
        value == null
          ? ""
          : typeof value === "object"
            ? JSON.stringify(value)
            : String(value);
      return `"${text.replaceAll('"', '""')}"`;
    };
    const lines = rows.map((row) => {
      const values: Record<string, unknown> = {
        ...row,
        source_url: row.provenance.source_url,
        source_version: row.provenance.source_version,
        source_file: row.source_file ?? row.provenance.source_file,
        source_row: row.source_row ?? row.provenance.source_row,
        doi:
          row.doi ??
          selectedData.investigations.find(
            (inv) => inv.accession === row.accession,
          )?.doi,
      };
      return columns.map((key) => quote(values[key])).join(",");
    });
    const credit = [
      `# ${data.source_credit}`,
      `# Snapshot: ${meta?.snapshot_id ?? "unknown"}; ${meta?.snapshot_date ?? "unknown"}`,
      `# Source DOIs: ${
        selectedData.investigations
          .map((inv) => inv.doi)
          .filter(Boolean)
          .join("; ") || "not reported"
      }`,
      "# Units: oxygen fraction (0-1), pressure kPa, airflow cm/s. Missing values are empty.",
      "# Research evidence only; source files, rows and original source cells retained.",
    ];
    return {
      count: rows.length,
      content: [...credit, columns.join(","), ...lines].join("\r\n") + "\r\n",
    };
  }, [data, format, metadata, metrics, scope, meta, selection]);
  return (
    <Modal title="Export research data" close={close}>
      <p className="muted">
        Take the data with its source, units and source values.
      </p>
      <div className="export-controls">
        <label>
          Study scope
          <select
            value={scope}
            onChange={(e) => {
              setScope(e.target.value);
              setLoading(true);
              setError("");
              setData(null);
            }}
          >
            <option value="">Entire snapshot</option>
            {selection && (
              <option value="__filtered">
                Filtered investigations ({selection.length})
              </option>
            )}
            {records.map((inv) => (
              <option value={inv.accession} key={inv.accession}>
                {inv.accession} · {inv.acronym ?? inv.title}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend>File format</legend>
          <div className="segmented">
            {["csv", "json"].map((value) => (
              <label key={value}>
                <input
                  type="radio"
                  name="format"
                  value={value}
                  checked={format === value}
                  onChange={() => setFormat(value)}
                />
                {value.toUpperCase()}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      <div className="export-options">
        <label className="check-label">
          <input
            type="checkbox"
            checked={metrics}
            onChange={(e) => setMetrics(e.target.checked)}
          />
          Include reported metrics
        </label>
        {format === "json" && (
          <label className="check-label">
            <input
              type="checkbox"
              checked={metadata}
              onChange={(e) => setMetadata(e.target.checked)}
            />
            Include investigation metadata
          </label>
        )}
      </div>
      <p className="small muted">
        Citations, source locations and original source cells are always
        included.
      </p>
      {error && <ErrorNotice message={error} />}
      {loading ? (
        <p role="status">Preparing source-linked export…</p>
      ) : (
        <>
          <div className="section-heading">
            <h3>Preview</h3>
            <span className="mono muted small">
              {prepared.count.toLocaleString()} rows · {format.toUpperCase()}
            </span>
          </div>
          <pre
            className="export-preview"
            tabIndex={0}
            aria-label="Export preview"
          >
            {prepared.content.split(/\r?\n/).slice(0, 12).join("\n")}
            {prepared.content.split(/\r?\n/).length > 12 ? "\n…" : ""}
          </pre>
        </>
      )}
      <div className="modal-footer">
        <button className="button secondary" onClick={close}>
          Cancel
        </button>
        <button
          className="button"
          disabled={loading || !!error || !data}
          onClick={() =>
            download(
              prepared.content,
              `firelens-${scope || "snapshot"}-${meta?.snapshot_id ?? "data"}.${format}`,
              format === "json" ? "application/json" : "text/csv;charset=utf-8",
            )
          }
        >
          Download {format.toUpperCase()} ↓
        </button>
      </div>
    </Modal>
  );
}
