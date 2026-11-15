import { useEffect, useState } from "react";
import { useTheme, setTheme } from "./theme";
import {
  dataMode,
  getAllTests,
  getInvestigations,
  getMeta,
  getProfiles,
  getRank,
} from "./client";
import type {
  Investigation as Study,
  Meta,
  ProfileConfig,
  RankInputs,
  RankResponse,
  TestRow,
} from "./client";
import Explorer from "./views/Explorer";
import Investigation from "./views/Investigation";
import Compare from "./views/Compare";
import Ask from "./views/Ask";
import ExportDialog from "./components/ExportDialog";
import { Empty, ErrorNotice, PageTitle } from "./components/Shared";

const routeNow = () => window.location.hash.slice(1) || "/explorer";
export default function App() {
  const theme = useTheme();
  const [route, setRoute] = useState(routeNow);
  const [meta, setMeta] = useState<Meta | null>(null),
    [records, setRecords] = useState<Study[]>([]),
    [config, setConfig] = useState<ProfileConfig | null>(null);
  const [error, setError] = useState(""),
    [attempt, setAttempt] = useState(0),
    [ready, setReady] = useState(false);
  const [rows, setRows] = useState<TestRow[]>([]),
    [rowsError, setRowsError] = useState(""),
    [rowsLoading, setRowsLoading] = useState(true);
  const [profile, setProfileId] = useState("iss"),
    [conditions, setConditions] = useState<RankInputs>({ goal: "prevention" });
  const [rank, setRank] = useState<RankResponse | null>(null),
    [rankLoading, setRankLoading] = useState(false),
    [rankError, setRankError] = useState("");
  const [selected, setSelected] = useState<string[]>(
    () =>
      new URLSearchParams(routeNow().split("?")[1])
        .get("ids")
        ?.split(",")
        .filter(Boolean)
        .slice(0, 3) ?? [],
  );
  const [exportOpen, setExportOpen] = useState(false);
  const [exportSelection, setExportSelection] = useState<string[] | undefined>(
    undefined,
  );
  useEffect(() => {
    const onHash = () => {
      const next = routeNow();
      setRoute(next);
      if (next.startsWith("/compare?")) {
        const ids = new URLSearchParams(next.split("?")[1]).get("ids");
        if (ids)
          setSelected(
            [...new Set(ids.split(","))]
              .filter((id) => /^PSI-\d+$/.test(id))
              .slice(0, 3),
          );
      }
      setTimeout(() => document.getElementById("main")?.focus(), 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    getMeta(controller.signal)
      .then((status) => {
        setMeta(status);
        return Promise.all([
          getInvestigations(controller.signal),
          getProfiles(controller.signal),
        ]);
      })
      .then(([list, profiles]) => {
        setRecords(list.items);
        setConfig(profiles);
        setRankLoading(true);
        setReady(true);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load workspace",
          );
      });
    getAllTests(controller.signal)
      .then(setRows)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setRowsError(
            reason instanceof Error
              ? reason.message
              : "Could not load coverage data",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setRowsLoading(false);
      });
    return () => controller.abort();
  }, [attempt]);
  useEffect(() => {
    if (
      !ready ||
      (profile === "custom" &&
        (conditions.o2_fraction === undefined ||
          conditions.pressure_kpa === undefined))
    )
      return;
    const controller = new AbortController();
    getRank(profile, conditions, controller.signal)
      .then(setRank)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setRankError(
            reason instanceof Error
              ? reason.message
              : "Could not rank investigations",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setRankLoading(false);
      });
    return () => controller.abort();
  }, [ready, profile, conditions]);
  const path = route.split("?")[0],
    detailId = /^\/investigations\/(PSI-\d+)$/.exec(path)?.[1];
  function applyProfile(id: string, inputs: RankInputs = {}) {
    setProfileId(id);
    setConditions(inputs);
    setRank(null);
    setRankError("");
    setRankLoading(id !== "custom" || inputs.o2_fraction !== undefined);
  }
  function toggle(id: string) {
    setSelected((old) =>
      old.includes(id)
        ? old.filter((item) => item !== id)
        : old.length < 3
          ? [...old, id]
          : old,
    );
  }
  function updateCompare(ids: string[]) {
    setSelected(ids);
    window.history.replaceState(
      null,
      "",
      `#/compare${ids.length ? `?ids=${ids.join(",")}` : ""}`,
    );
  }
  function retry() {
    setError("");
    setReady(false);
    setMeta(null);
    setRowsError("");
    setRows([]);
    setRowsLoading(true);
    setAttempt((old) => old + 1);
  }
  const compareHref = `#/compare${selected.length ? `?ids=${selected.join(",")}` : ""}`;
  const active = detailId ? "/explorer" : path;
  return (
    <>
      <a
        className="skip-link"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to research workspace
      </a>
      <header className="site-header">
        <div className="header-inner">
          <a href="#/explorer" className="brand" aria-label="FireLens home">
            <svg viewBox="0 0 32 32" aria-hidden="true">
              <path
                d="M16 3C17 10 26 12 26 20A10 10 0 0 1 6 20C6 13 12 10 12 6C15 8 16 11 16 14C19 11 18 7 16 3Z"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
              />
              <circle cx="16" cy="22" r="3" fill="currentColor" />
            </svg>
            <span>
              FireLens<span className="brand-dot">.</span>
            </span>
          </a>
          <nav aria-label="Main navigation">
            {[
              ["/explorer", "Explorer"],
              ["/compare", "Compare"],
              ["/ask", "Ask FireLens"],
            ].map(([href, label]) => (
              <a
                key={href}
                href={href === "/compare" ? compareHref : `#${href}`}
                aria-current={active === href ? "page" : undefined}
              >
                {label}
                {href === "/compare" && selected.length > 0 && (
                  <span className="nav-count">{selected.length}</span>
                )}
              </a>
            ))}
          </nav>
          <button
            className="theme-toggle"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M20 15.2A8.4 8.4 0 0 1 8.8 4 8.4 8.4 0 1 0 20 15.2Z" />
              </svg>
            )}
            <span>{theme === "dark" ? "Light" : "Dark"}</span>
          </button>
          <a
            href="#/data"
            className="snapshot-badge"
            aria-label="View snapshot status"
          >
            <span
              className={`status-dot ${meta?.new_releases_since_snapshot ? "amber-dot" : ""}`}
            />
            {meta
              ? `Snapshot · ${new Date(meta.snapshot_date).toLocaleDateString("en", { month: "short", day: "numeric" })}`
              : "Connecting to data"}
          </a>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="workspace">
        <div className="workspace-kicker">
          <span>NASA PSI / COMBUSTION SCIENCE</span>
          <span>
            {dataMode === "mock" || (meta && meta.test_count === 0)
              ? "METADATA PREVIEW"
              : "EVIDENCE-LINKED RESEARCH"}
          </span>
        </div>
        {(dataMode === "mock" || (meta && meta.test_count === 0)) && (
          <aside className="notice mock-notice">
            <strong>Metadata preview</strong>
            <span>
              Real NASA catalogue records. No reviewed measurements or relevance
              scores are supplied by these fixtures.
            </span>
          </aside>
        )}
        {error ? (
          <ErrorNotice message={error} retry={retry} />
        ) : !ready || !config ? (
          <section className="cold-start" role="status" aria-live="polite">
            <span className="loader-orbit" />
            <p className="eyebrow">PREPARING YOUR WORKSPACE</p>
            <h1>
              {meta
                ? "Opening the evidence library."
                : "Waking the data service."}
            </h1>
            <p className="muted">
              The service may take a moment after being idle.
            </p>
            <ol>
              <li className={meta ? "complete" : "current"}>
                {meta ? "✓" : "01"} Connect to data service
              </li>
              <li className={meta ? "current" : ""}>
                02 Load snapshot & investigation records
              </li>
              <li>03 Prepare rankings & coverage</li>
            </ol>
          </section>
        ) : (
          <>
            {path === "/explorer" && (
              <Explorer
                records={records}
                config={config}
                rank={rank}
                rows={rows}
                rowsLoading={rowsLoading}
                profile={profile}
                conditions={conditions}
                setProfile={applyProfile}
                rankLoading={rankLoading}
                rankError={rankError}
                rowsError={rowsError}
                selected={selected}
                toggle={toggle}
                exportData={(ids) => {
                  setExportSelection(ids);
                  setExportOpen(true);
                }}
              />
            )}
            {detailId && (
              <Investigation
                key={detailId}
                id={detailId}
                selected={selected}
                toggle={toggle}
                exportData={() => {
                  setExportSelection(undefined);
                  setExportOpen(true);
                }}
              />
            )}
            {path === "/compare" && (
              <Compare
                records={records}
                ids={selected}
                setIds={updateCompare}
              />
            )}
            {path === "/ask" && <Ask records={records} />}
            {path === "/data" && (
              <>
                <PageTitle
                  eyebrow="DATA TRANSPARENCY"
                  title="A snapshot you can trace."
                >
                  Know which dataset is being used, when it was captured and
                  what still needs review.
                </PageTitle>
                <section className="panel">
                  <div className="snapshot-stats">
                    <div>
                      <span>Investigations</span>
                      <strong>
                        {meta?.investigation_count.toLocaleString()}
                      </strong>
                    </div>
                    <div>
                      <span>Normalized tests</span>
                      <strong>{meta?.test_count.toLocaleString()}</strong>
                    </div>
                    <div>
                      <span>Awaiting review</span>
                      <strong>
                        {
                          records.filter((i) => i.review_status !== "reviewed")
                            .length
                        }
                      </strong>
                    </div>
                  </div>
                  <dl className="facts">
                    <div>
                      <dt>Snapshot ID</dt>
                      <dd className="mono">{meta?.snapshot_id}</dd>
                    </div>
                    <div>
                      <dt>Captured</dt>
                      <dd>
                        {meta && new Date(meta.snapshot_date).toLocaleString()}
                      </dd>
                    </div>
                    <div>
                      <dt>Latest catalogue check</dt>
                      <dd>
                        {meta?.catalogue_checked_at
                          ? new Date(meta.catalogue_checked_at).toLocaleString()
                          : "Not checked — freshness is unverified"}
                      </dd>
                    </div>
                    <div>
                      <dt>New releases</dt>
                      <dd>
                        {meta?.new_releases_since_snapshot ?? "Not checked"}
                      </dd>
                    </div>
                  </dl>
                  {meta?.warnings.map((warning, i) => (
                    <p className="small amber-text" key={i}>
                      {warning}
                    </p>
                  ))}
                  <p className="muted small">
                    This view reports the active snapshot. Remote sync and
                    snapshot history are not available through this service.
                  </p>
                </section>
                <section className="panel">
                  <h2>Review queue</h2>
                  {records.filter((i) => i.review_status !== "reviewed")
                    .length ? (
                    records
                      .filter((i) => i.review_status !== "reviewed")
                      .map((inv) => (
                        <a
                          className="related-link"
                          key={inv.accession}
                          href={`#/investigations/${inv.accession}`}
                        >
                          {inv.accession} · {inv.title}
                          <span>Awaiting review ↗</span>
                        </a>
                      ))
                  ) : (
                    <p className="muted">
                      No investigations are marked unreviewed in the active
                      snapshot. Review flags do not replace independent
                      scientific validation.
                    </p>
                  )}
                </section>
              </>
            )}
            {!["/explorer", "/compare", "/ask", "/data"].includes(path) &&
              !detailId && (
                <Empty title="This page could not be found.">
                  <a href="#/explorer">Return to Explorer</a>
                </Empty>
              )}
          </>
        )}
      </main>
      {selected.length > 0 && path !== "/compare" && (
        <aside className="compare-tray" aria-label="Comparison selection">
          <div>
            <strong>{selected.length} / 3 investigations</strong>
            <span>{selected.join(" · ")}</span>
          </div>
          <button className="text-button" onClick={() => setSelected([])}>
            Clear
          </button>
          <a href={compareHref} className="button secondary">
            Compare selected →
          </a>
        </aside>
      )}
      <footer className="site-footer">
        <div>
          <a href="#/explorer" className="footer-brand">
            FireLens.
          </a>
          <span>Built around the evidence.</span>
        </div>
        <p>
          Source:{" "}
          <a href="https://psi.nasa.gov/" target="_blank" rel="noreferrer">
            NASA Physical Sciences Informatics ↗
          </a>
          <br />
          Independent research project · AI-assisted development · Research
          relevance is not a safety rating.
        </p>
        <a href="#/data" className="text-link">
          Data & provenance ↗
        </a>
      </footer>
      {exportOpen && (
        <ExportDialog
          close={() => setExportOpen(false)}
          accession={detailId}
          selection={exportSelection}
          records={records}
          meta={meta}
        />
      )}
    </>
  );
}
