import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import type { Investigation, TestRow } from "../client";
import { number, range } from "../presentation";

export function PageTitle({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {children && <p className="page-intro">{children}</p>}
      </div>
      {action}
    </div>
  );
}
export function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="notice error" role="alert">
      <div>
        <strong>We couldn’t load this information.</strong>
        <p>{message}</p>
      </div>
      {retry && (
        <button className="button secondary" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}
export function ReviewLabel({ inv }: { inv: Investigation }) {
  return (
    <span
      className={`tag ${inv.fixture ? "neutral" : inv.review_status === "reviewed" ? "green" : "amber"}`}
    >
      {inv.fixture
        ? "Metadata fixture"
        : inv.review_status === "reviewed"
          ? "Reviewed data"
          : inv.review_status === "rejected"
            ? "Rejected evidence"
            : "Awaiting review"}
    </span>
  );
}
export function StudyConditions({ inv }: { inv: Investigation }) {
  return (
    <dl className="condition-grid">
      <div>
        <dt>Oxygen</dt>
        <dd>{range(inv.condition_ranges?.oxygen)}</dd>
      </div>
      <div>
        <dt>Pressure</dt>
        <dd>{range(inv.condition_ranges?.pressure)}</dd>
      </div>
      <div>
        <dt>Airflow</dt>
        <dd>{range(inv.condition_ranges?.flow)}</dd>
      </div>
    </dl>
  );
}
export function TestTable({ rows }: { rows: TestRow[] }) {
  if (!rows.length)
    return (
      <Empty title="No normalized rows available">
        This study may contain metadata or study-level ranges rather than
        individual tests.
      </Empty>
    );
  return (
    <div className="table-scroll">
      <table>
        <caption>
          Normalized tests · source locations are retained for verification
        </caption>
        <thead>
          <tr>
            <th>Test / fuel</th>
            <th>O₂ (%)</th>
            <th>Pressure (kPa)</th>
            <th>Flow (cm/s)</th>
            <th>Outcome</th>
            <th>Review</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.accession}:${row.test_id}`}>
              <td>
                <strong>{row.test_id}</strong>
                <small>{row.fuel ?? "Fuel not reported"}</small>
              </td>
              <td>
                {number(
                  row.o2_fraction == null ? null : row.o2_fraction * 100,
                  2,
                )}
              </td>
              <td>{number(row.pressure_kpa, 2)}</td>
              <td>{number(row.flow_cm_s)}</td>
              <td>{row.outcome?.replaceAll("_", " ") ?? "Not reported"}</td>
              <td>
                {row.review_status} · {row.evidence_type}
              </td>
              <td>
                <a
                  href={row.provenance.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {row.source_file ?? row.provenance.source_file}
                  <small>
                    row{" "}
                    {row.source_row ??
                      row.provenance.source_row ??
                      "not reported"}
                  </small>
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = ref.current;
    const trigger =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    node?.showModal();
    return () => {
      node?.close();
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
      aria-labelledby="modal-title"
    >
      <div className="modal-heading">
        <h2 id="modal-title">{title}</h2>
        <button
          onClick={close}
          className="icon-button"
          aria-label={`Close ${title}`}
        >
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}
