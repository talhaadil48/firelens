import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { getInvestigation, getAllTests } from "../client";
import type { Investigation as Study, TestRow } from "../client";
import { citationText, studyName } from "../presentation";
import "./investigation.css";
import Measurements from "../components/Measurements";
import {
  Empty,
  ErrorNotice,
  PageTitle,
  DataLabel,
  StudyConditions,
} from "../components/Shared";

function PanelBody({
  id,
  variant,
  children,
}: {
  id: string;
  variant?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`detail-panel-body ${variant ?? ""}`}
      role="region"
      aria-labelledby={id}
      tabIndex={0}
    >
      {children}
    </div>
  );
}

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
  const [tab, setTab] = useState("overview");
  const [error, setError] = useState(""),
    [copied, setCopied] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getInvestigation(id, controller.signal),
      getAllTests(controller.signal, { accession: id }),
    ])
      .then(([inv, tests]) => {
        setStudy(inv);
        setRows(tests);
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
  const summary = study.summary ?? null;
  const findings = [...(study.findings ?? []), ...(summary?.findings ?? [])];
  async function copy() {
    try {
      await navigator.clipboard.writeText(citationText(study!));
      setCopied("Citation copied.");
    } catch {
      setCopied("Clipboard unavailable. Select and copy the citation below.");
    }
  }
  return (
    <div className="investigation-page study-redesign">
      <a className="breadcrumb" href="#/explorer">
        Back to investigation explorer
      </a>
      <header className="study-hero">
        <PageTitle
          eyebrow={`${study.accession} / INVESTIGATION`}
          title={studyName(study)}
          action={
            <div className="button-row">
              <button className="button secondary" onClick={copy}>
                Copy citation
              </button>
              <button className="button secondary" onClick={exportData}>
                Export study
              </button>
              <button
                className="button"
                disabled={selected.length >= 3 && !selected.includes(id)}
                onClick={() => toggle(id)}
              >
                {selected.includes(id)
                  ? "Remove from compare"
                  : "Add to compare"}
              </button>
            </div>
          }
        >
          {study.title}
        </PageTitle>
        <div className="tag-row">
          <DataLabel inv={study} />
          <span className="tag neutral">Version {study.version}</span>
          {(study.fire_safety_tags ?? []).map((tag) => (
            <span className="tag neutral" key={tag}>
              {tag}
            </span>
          ))}
        </div>
        {copied && (
          <p role="status" className="small">
            {copied}
          </p>
        )}
      </header>
      <div className="study-readouts" aria-label="Investigation at a glance">
        <div className="study-test-count">
          <strong>
            {(study.record_count ?? rows.length).toLocaleString()}
          </strong>
          <span>
            Source records · {study.test_count.toLocaleString()} individual
            tests
          </span>
        </div>
        <StudyConditions inv={study} />
      </div>
      {!!study.data_gaps?.length && (
        <aside
          className="study-data-notice"
          aria-labelledby="study-data-notice-heading"
        >
          <h2 id="study-data-notice-heading">
            About this investigation’s data
          </h2>
          <ul>
            {study.data_gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </aside>
      )}
      <div
        className="study-tabs"
        role="tablist"
        aria-label="Investigation sections"
      >
        {["overview", "findings", "measurements", "sources"].map(
          (key, index, keys) => (
            <button
              key={key}
              id={`study-tab-${key}`}
              role="tab"
              aria-selected={tab === key}
              aria-controls={`study-panel-${key}`}
              tabIndex={tab === key ? 0 : -1}
              onClick={() => setTab(key)}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % 4
                    : event.key === "ArrowLeft"
                      ? (index + 3) % 4
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? 3
                          : -1;
                if (next >= 0) {
                  event.preventDefault();
                  setTab(keys[next]);
                  document.getElementById(`study-tab-${keys[next]}`)?.focus();
                }
              }}
            >
              {
                {
                  overview: "Overview",
                  findings: "Findings",
                  measurements: "Measurements",
                  sources: "Sources & publications",
                }[key]
              }
              {key === "findings" && <span>{findings.length}</span>}
              {key === "measurements" && (
                <span>
                  {(study.record_count ?? rows.length).toLocaleString()}
                </span>
              )}
            </button>
          ),
        )}
      </div>
      <div
        className="study-content"
        id={`study-panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`study-tab-${tab}`}
        tabIndex={0}
      >
        {tab === "overview" && (
          <>
            <section className="panel">
              <p className="eyebrow">RESEARCH OBJECTIVE</p>
              <h2 id="objective-heading">What this investigation explores</h2>
              <PanelBody
                id="objective-heading"
                variant="detail-overview-scroll"
              >
                <p className="reading-text">
                  {summary?.objective ??
                    study.objectives ??
                    study.description ??
                    "Not reported in the source metadata."}
                </p>
                <a
                  className="text-link"
                  href={study.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Verify the NASA record ↗
                </a>

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
                    <dd>
                      {summary?.varied ?? "Not reported in source summary"}
                    </dd>
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
                    <dd>
                      {(study.hardware ?? []).join(", ") || "Not reported"}
                    </dd>
                  </div>
                  <div>
                    <dt>Platform</dt>
                    <dd>{study.platform ?? "Not reported"}</dd>
                  </div>
                  <div>
                    <dt>Measurements</dt>
                    <dd>
                      {(study.measurements ?? []).join(", ") ||
                        "See source tables"}
                    </dd>
                  </div>
                </dl>
              </PanelBody>
            </section>
          </>
        )}
        {tab === "findings" && (
          <>
            <section className="panel">
              <div className="section-heading">
                <h2 id="findings-heading">Reported findings</h2>
                <span className="tag neutral">Evidence first</span>
              </div>
              <PanelBody id="findings-heading" variant="detail-findings-scroll">
                {findings.length ? (
                  findings.map((finding, index) => (
                    <article className="finding" key={index}>
                      <p>{finding.claim}</p>
                      <span className="tag neutral">
                        {finding.evidence_type} · {finding.uncertainty_label}
                      </span>
                      {finding.uncertainty_note && (
                        <p className="small muted">
                          {finding.uncertainty_note}
                        </p>
                      )}
                      <div className="tag-row">
                        {finding.citation_ids.map((cid) => {
                          const cit = study.citations?.find(
                            (c) => c.id === cid,
                          );
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
                  <Empty title="No source findings available">
                    Read the source documents before drawing physical
                    conclusions.
                  </Empty>
                )}
              </PanelBody>
            </section>
          </>
        )}
        {tab === "measurements" && (
          <>
            <section className="panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">TRACEABLE MEASUREMENTS</p>
                  <h2 id="tests-heading">A look at the test rows</h2>
                </div>
                <span className="muted small">
                  {rows.length.toLocaleString()} source records · original
                  values retained
                </span>
              </div>
              <PanelBody id="tests-heading">
                <Measurements key={id} rows={rows} />
              </PanelBody>
            </section>
          </>
        )}
        {tab === "sources" && (
          <>
            <div className="study-source-record">
              <section className="panel">
                <h2 id="source-heading">Source record</h2>
                <PanelBody id="source-heading" variant="detail-source-scroll">
                  <p className="small muted">
                    Keep the dataset version and DOI with your work.
                  </p>
                  <p className="citation-copy">{citationText(study)}</p>
                  <div className="button-row">
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
                </PanelBody>
              </section>
              <section className="panel">
                <h2 id="related-heading">Related investigations</h2>
                <PanelBody id="related-heading" variant="detail-related-scroll">
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
                    <p className="muted small">
                      No related investigations reported.
                    </p>
                  )}
                </PanelBody>
              </section>
            </div>
            <div className="study-library">
              <section className="panel">
                <h2 id="documents-heading">Documents</h2>
                <PanelBody
                  id="documents-heading"
                  variant="detail-documents-scroll"
                >
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
                </PanelBody>
              </section>
              <section className="panel publications-panel">
                <h2 id="publications-heading">Publications</h2>
                {(study.publications ?? []).length ? (
                  <div
                    className="detail-panel-body publications-scroll"
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
        )}
      </div>
    </div>
  );
}
