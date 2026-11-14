import { useEffect, useState } from "react";
import { getInvestigation, getTests } from "../client";
import type { Investigation as Study, TestRow } from "../client";
import { citationText, studyName } from "../presentation";
import {
  Empty,
  ErrorNotice,
  PageTitle,
  ReviewLabel,
  StudyConditions,
  TestTable,
} from "../components/Shared";

export default function Investigation({
  id,
  selected,
  toggle,
  exportData,
}: {
  id: string;
  selected: string[];
  toggle: (id: string) => void;
  exportData: () => void;
}) {
  const [study, setStudy] = useState<Study | null>(null),
    [rows, setRows] = useState<TestRow[]>([]);
  const [error, setError] = useState(""),
    [copied, setCopied] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getInvestigation(id, controller.signal),
      getTests(controller.signal, { accession: id }),
    ])
      .then(([inv, tests]) => {
        setStudy(inv);
        setRows(tests.items.slice(0, 10));
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load investigation",
          );
      });
    return () => controller.abort();
  }, [id]);
  if (error) return <ErrorNotice message={error} />;
  if (!study)
    return (
      <p role="status" className="loading-line">
        Loading investigation and source rows…
      </p>
    );
  const summary =
    study.summary?.review_status === "reviewed" ? study.summary : null;
  const findings = [
    ...(study.findings ?? []),
    ...(summary?.findings ?? []),
  ].filter((f) => f.review_status === "reviewed");
  async function copy() {
    try {
      await navigator.clipboard.writeText(citationText(study!));
      setCopied("Citation copied.");
    } catch {
      setCopied("Clipboard unavailable. Select and copy the citation below.");
    }
  }
  return (
    <>
      <a className="breadcrumb" href="#/explorer">
        ← Investigation explorer
      </a>
      <PageTitle
        eyebrow={`${study.accession} / INVESTIGATION`}
        title={studyName(study)}
        action={
          <div className="button-row">
            <button className="button secondary" onClick={exportData}>
              Export study
            </button>
            <button
              className="button"
              disabled={selected.length >= 3 && !selected.includes(id)}
              onClick={() => toggle(id)}
            >
              {selected.includes(id) ? "Remove from compare" : "Add to compare"}
            </button>
          </div>
        }
      >
        {study.title}
      </PageTitle>
      <div className="tag-row">
        <ReviewLabel inv={study} />
        <span className="tag neutral">Version {study.version}</span>
        <span className="tag neutral">
          {study.test_count.toLocaleString()} normalized tests
        </span>
        {(study.fire_safety_tags ?? []).map((tag) => (
          <span className="tag neutral" key={tag}>
            {tag}
          </span>
        ))}
      </div>
      <div className="detail-layout">
        <div className="detail-main">
          <section className="panel">
            <p className="eyebrow">RESEARCH OBJECTIVE</p>
            <h2>What this investigation explores</h2>
            <p className="reading-text">
              {summary?.objective ??
                study.objectives ??
                study.description ??
                "Not reported in the source metadata."}
            </p>
            {!summary && study.summary && (
              <p className="small amber-text">
                The generated summary is awaiting review. Original source
                metadata is shown.
              </p>
            )}
            <a
              className="text-link"
              href={study.source_url}
              target="_blank"
              rel="noreferrer"
            >
              Verify the NASA record ↗
            </a>
            <StudyConditions inv={study} />
            <dl className="facts">
              <div>
                <dt>Fuels & geometry</dt>
                <dd>
                  {summary?.fuels_and_geometry ??
                    "See normalized rows and source documents."}
                </dd>
              </div>
              <div>
                <dt>What varied</dt>
                <dd>{summary?.varied ?? "Not reported in reviewed summary"}</dd>
              </div>
              <div>
                <dt>Sensors</dt>
                <dd>
                  {[
                    ...new Set([
                      ...(study.sensors ?? []),
                      ...(summary?.sensors ?? []),
                    ]),
                  ].join(", ") || "Not reported"}
                </dd>
              </div>
              <div>
                <dt>Hardware</dt>
                <dd>{(study.hardware ?? []).join(", ") || "Not reported"}</dd>
              </div>
              <div>
                <dt>Platform</dt>
                <dd>{study.platform ?? "Not reported"}</dd>
              </div>
              <div>
                <dt>Measurements</dt>
                <dd>
                  {(study.measurements ?? []).join(", ") || "See source tables"}
                </dd>
              </div>
            </dl>
          </section>
          <section className="panel">
            <div className="section-heading">
              <h2>Reported findings</h2>
              <span className="tag neutral">Evidence first</span>
            </div>
            {findings.length ? (
              findings.map((finding, index) => (
                <article className="finding" key={index}>
                  <p>{finding.claim}</p>
                  <span className="tag neutral">
                    {finding.evidence_type} · {finding.uncertainty_label}
                  </span>
                  {finding.uncertainty_note && (
                    <p className="small muted">{finding.uncertainty_note}</p>
                  )}
                  <div className="tag-row">
                    {finding.citation_ids.map((cid) => {
                      const cit = study.citations?.find((c) => c.id === cid);
                      return cit ? (
                        <details className="source-snippet" key={cid}>
                          <summary>
                            {cit.accession} · {cit.locator}
                          </summary>
                          <blockquote>{cit.supporting_text}</blockquote>
                          <a
                            href={cit.provenance.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open source ↗
                          </a>
                        </details>
                      ) : null;
                    })}
                  </div>
                </article>
              ))
            ) : (
              <Empty title="No reviewed findings available">
                Read the source documents before drawing physical conclusions.
              </Empty>
            )}
          </section>
        </div>
        <aside className="detail-aside">
          <section className="panel">
            <h2>Source record</h2>
            <p className="small muted">
              Keep the dataset version and DOI with your work.
            </p>
            <p className="citation-copy">{citationText(study)}</p>
            <div className="button-row">
              <button className="button secondary" onClick={copy}>
                Copy citation
              </button>
              {study.doi && (
                <a
                  className="text-link"
                  href={`https://doi.org/${study.doi}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open DOI ↗
                </a>
              )}
            </div>
            <p role="status" className="small">
              {copied}
            </p>
            <dl className="facts">
              <div>
                <dt>Licence</dt>
                <dd>{study.license ?? "Check source licence"}</dd>
              </div>
              <div>
                <dt>Retrieved</dt>
                <dd>
                  {new Date(study.retrieved_at).toLocaleDateString("en", {
                    dateStyle: "medium",
                  })}
                </dd>
              </div>
            </dl>
          </section>
          <section className="panel">
            <h2>Related investigations</h2>
            {(study.related_investigations ?? []).length ? (
              (study.related_investigations ?? []).map((accession) => (
                <a
                  className="related-link"
                  href={`#/investigations/${accession}`}
                  key={accession}
                >
                  {accession}
                  <span>Open study ↗</span>
                </a>
              ))
            ) : (
              <p className="muted small">No related investigations reported.</p>
            )}
          </section>
        </aside>
      </div>
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">TRACEABLE MEASUREMENTS</p>
            <h2>A look at the test rows</h2>
          </div>
          <span className="muted small">
            First {rows.length} rows · missing values stay missing
          </span>
        </div>
        <TestTable rows={rows} />
      </section>
      <div className="two-column">
        <section className="panel">
          <h2>Documents</h2>
          {(study.documents ?? []).length ? (
            <ul className="resource-list">
              {(study.documents ?? []).map((doc, i) => (
                <li key={i}>
                  <a href={doc.url} target="_blank" rel="noreferrer">
                    {doc.name} ↗
                  </a>
                  <span className="muted small">
                    {doc.size_bytes == null
                      ? "Size not reported"
                      : `${(doc.size_bytes / 1024 / 1024).toFixed(1)} MB`}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No document links in this record.</p>
          )}
        </section>
        <section className="panel publications-panel">
          <h2 id="publications-heading">Publications</h2>
          {(study.publications ?? []).length ? (
            <div
              className="publications-scroll"
              role="region"
              aria-labelledby="publications-heading"
              tabIndex={0}
            >
              <ul className="resource-list">
                {(study.publications ?? []).map((pub, i) => (
                  <li key={i}>
                    <span>{pub.title}</span>
                    {pub.authors && (
                      <span className="small muted">{pub.authors}</span>
                    )}
                    {(pub.url || pub.doi) && (
                      <a
                        href={pub.url ?? `https://doi.org/${pub.doi}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open publication ↗
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="muted">No publication links in this record.</p>
          )}
        </section>
      </div>
    </>
  );
}
