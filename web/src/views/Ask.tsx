import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ask } from "../client";
import type { Investigation, Schema } from "../client";
import ChatChart from "../components/ChatChart";
import { PageTitle, ErrorNotice, Empty } from "../components/Shared";

type Citation = Schema["Citation"];
const suggestions = [
  "Which experiments report reduced flame spread?",
  "Which fabric tests burned above 30% oxygen?",
  "What cool-flame behavior was reported in FLEX?",
];
function AnswerText({
  text,
  citations,
  select,
}: {
  text: string;
  citations: Citation[];
  select: (citation: Citation) => void;
}) {
  return (
    <div className="answer-text">
      {text.split(/(\[PSI-\d+, [^\]\n]+\])/g).map((part, index) => {
        const citation = citations.find(
          (c) =>
            part.startsWith(`[${c.accession}, `) &&
            part.endsWith(`, ${c.locator}]`),
        );
        return citation ? (
          <button
            className="inline-citation"
            key={index}
            onClick={() => select(citation)}
            title={citation.locator}
          >
            {citation.accession} ↗
          </button>
        ) : (
          <span key={index}>{part}</span>
        );
      })}
    </div>
  );
}
export default function Ask({ records }: { records: Investigation[] }) {
  const [question, setQuestion] = useState(""),
    [scope, setScope] = useState(""),
    [asked, setAsked] = useState("");
  const [answer, setAnswer] = useState<Schema["AnswerEvent"] | null>(null),
    [trace, setTrace] = useState<string[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [selected, setSelected] = useState<Citation | null>(null);
  const controller = useRef<AbortController | null>(null),
    input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !question.trim()) return;
    const run = new AbortController();
    controller.current = run;
    setAsked(question.trim());
    setBusy(true);
    setError("");
    setTrace([]);
    setAnswer(null);
    setSelected(null);
    let finished = false,
      received = false;
    try {
      for await (const event of ask(
        question.trim(),
        run.signal,
        scope ? [scope] : [],
      )) {
        if (run.signal.aborted) return;
        if (event.event === "progress")
          setTrace((old) => [
            ...old,
            (event.data as Schema["ProgressEvent"]).message,
          ]);
        if (event.event === "answer") {
          const value = event.data as Schema["AnswerEvent"];
          setAnswer(value);
          setSelected(value.citations[0] ?? null);
          received = true;
        }
        if (event.event === "done") {
          finished = true;
          if ((event.data as Schema["DoneEvent"]).finish_reason === "error")
            throw new Error(
              "The evidence service could not finish. Please try again.",
            );
        }
      }
      if (!finished || !received)
        throw new Error("The answer stream ended early. Please try again.");
    } catch (reason) {
      if (!run.signal.aborted)
        setError(
          reason instanceof Error
            ? reason.message
            : "Could not retrieve evidence",
        );
    } finally {
      if (!run.signal.aborted) setBusy(false);
    }
  }
  function stop() {
    controller.current?.abort();
    setBusy(false);
    setTrace((old) => [...old, "Request stopped."]);
  }
  return (
    <>
      <PageTitle eyebrow="ASK FIRELENS" title="Questions meet evidence.">
        Search reviewed NASA combustion research. Follow every answer back to
        its source.
      </PageTitle>
      <div className="ask-layout">
        <div>
          <section className="panel ask-compose">
            <label htmlFor="question" className="compose-label">
              What would you like to understand?
            </label>
            <form onSubmit={submit}>
              <textarea
                ref={input}
                id="question"
                maxLength={2000}
                rows={4}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask about flame spread, tested conditions or experiment outcomes…"
                required
              />
              <div className="compose-actions">
                <label>
                  <span className="sr-only">Search scope</span>
                  <select
                    aria-label="Search scope"
                    value={scope}
                    onChange={(e) => setScope(e.target.value)}
                    disabled={busy}
                  >
                    <option value="">All reviewed investigations</option>
                    {records.map((inv) => (
                      <option key={inv.accession} value={inv.accession}>
                        {inv.accession} · {inv.acronym ?? inv.title}
                      </option>
                    ))}
                  </select>
                </label>
                {busy ? (
                  <button
                    type="button"
                    className="button secondary"
                    onClick={stop}
                  >
                    Stop request
                  </button>
                ) : (
                  <button
                    className="button"
                    type="submit"
                    disabled={!question.trim()}
                  >
                    Search evidence ↗
                  </button>
                )}
              </div>
            </form>
            <p className="small muted">
              Sources may be incomplete. Unsupported questions receive an
              insufficient-evidence response.
            </p>
          </section>
          <div className="suggestions">
            <span className="eyebrow">TRY A RESEARCH QUESTION</span>
            {suggestions.map((q) => (
              <button
                key={q}
                className="suggestion"
                onClick={() => {
                  setQuestion(q);
                  input.current?.focus();
                }}
              >
                {q}
                <span>↗</span>
              </button>
            ))}
          </div>
          {asked && (
            <section className="panel answer-panel">
              <div className="section-heading">
                <p className="eyebrow">YOUR QUESTION</p>
                {answer && (
                  <span
                    className={`tag ${answer.status === "supported" ? "green" : "amber"}`}
                  >
                    {answer.status === "supported"
                      ? "Source-backed excerpts"
                      : "Insufficient evidence"}
                  </span>
                )}
              </div>
              <h2>{asked}</h2>
              {busy && (
                <p role="status" className="loading-line">
                  Retrieving and checking evidence…
                </p>
              )}
              {answer && (
                <>
                  <AnswerText
                    text={answer.text}
                    citations={answer.citations}
                    select={setSelected}
                  />
                  {answer.status === "supported" &&
                    answer.citations.filter((c) => c.id.startsWith("row:"))
                      .length >= 2 && (
                      <ChatChart
                        citations={answer.citations}
                        question={asked}
                      />
                    )}
                  {!!answer.citations.length && (
                    <div className="tag-row">
                      {answer.citations.map((c) => (
                        <button
                          className="source-chip"
                          key={c.id}
                          onClick={() => setSelected(c)}
                        >
                          {c.accession} ·{" "}
                          {c.id.startsWith("row:") ? "test row" : "source text"}
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}
              {!!trace.length && (
                <details className="trace" open={busy}>
                  <summary>Retrieval trace · {trace.length} steps</summary>
                  <ol>
                    {trace.map((step, i) => (
                      <li key={i}>{step}</li>
                    ))}
                  </ol>
                </details>
              )}
              {error && <ErrorNotice message={error} />}
            </section>
          )}
        </div>
        <aside className="panel evidence-panel">
          <div className="section-heading">
            <h2>Evidence viewer</h2>
            <span className="tag neutral">
              {answer?.citations.length ?? 0} sources
            </span>
          </div>
          {selected ? (
            <>
              <span className="eyebrow">
                {selected.id.startsWith("row:")
                  ? "NORMALIZED TEST ROW"
                  : "SOURCE EXCERPT"}
              </span>
              <h3>{selected.accession}</h3>
              <p className="mono small source-location">{selected.locator}</p>
              <blockquote
                tabIndex={0}
                aria-label="Full supporting source excerpt"
              >
                {selected.supporting_text}
              </blockquote>
              <dl className="facts">
                <div>
                  <dt>Dataset version</dt>
                  <dd>{selected.provenance.source_version}</dd>
                </div>
                <div>
                  <dt>Evidence location</dt>
                  <dd>
                    {selected.provenance.page
                      ? `Page ${selected.provenance.page}`
                      : selected.provenance.source_row
                        ? `Row ${selected.provenance.source_row}`
                        : selected.locator}
                  </dd>
                </div>
              </dl>
              <a
                className="button secondary"
                href={selected.provenance.source_url}
                target="_blank"
                rel="noreferrer"
              >
                Open underlying source ↗
              </a>
              {records.find((inv) => inv.accession === selected.accession)
                ?.doi && (
                <a
                  className="text-link doi-link"
                  href={`https://doi.org/${records.find((inv) => inv.accession === selected.accession)!.doi}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open dataset DOI ↗
                </a>
              )}
              <p className="small muted">
                An excerpt reports the source. It does not establish a safety
                recommendation.
              </p>
            </>
          ) : (
            <Empty title="The source belongs beside the answer.">
              Ask a question, then select a citation to inspect the exact
              supporting excerpt or test row.
            </Empty>
          )}
        </aside>
      </div>
    </>
  );
}
