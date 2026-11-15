import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import CoverageMap from "../CoverageMap";
import type {
  Investigation,
  ProfileConfig,
  RankInputs,
  RankResponse,
  TestRow,
} from "../client";
import { number, range, studyName } from "../presentation";
import {
  Empty,
  ErrorNotice,
  PageTitle,
  ReviewLabel,
} from "../components/Shared";

type Props = {
  records: Investigation[];
  config: ProfileConfig;
  rank: RankResponse | null;
  rows: TestRow[];
  rowsLoading: boolean;
  profile: string;
  conditions: RankInputs;
  setProfile: (id: string, inputs?: RankInputs) => void;
  rankLoading: boolean;
  rankError: string;
  rowsError: string;
  selected: string[];
  toggle: (id: string) => void;
  exportData: (ids: string[]) => void;
};
const dimensions = [
  ["conditions", "Conditions"],
  ["fuel_realism", "Fuel realism"],
  ["safety_goal", "Safety goal"],
  ["data_richness", "Data richness"],
] as const;
export default function Explorer({
  records,
  config,
  rank,
  rows,
  rowsLoading,
  profile,
  conditions,
  setProfile,
  rankLoading,
  rankError,
  rowsError,
  selected,
  toggle,
  exportData,
}: Props) {
  const [shown, setShown] = useState(6);
  const [query, setQuery] = useState(""),
    [phase, setPhase] = useState("all"),
    [review, setReview] = useState("all");
  const [custom, setCustom] = useState({
    oxygen: "",
    pressure: "",
    flow: "",
    gravity: "",
  });
  const [customError, setCustomError] = useState("");
  const profileInfo =
    rank?.profile ?? config.profiles.find((item) => item.id === profile);
  const ordered = useMemo(() => {
    const byId = new Map(records.map((item) => [item.accession, item]));
    const ranked = rank
      ? rank.items
          .map((item) => byId.get(item.accession))
          .filter((item): item is Investigation => !!item)
      : records;
    return [
      ...ranked,
      ...records.filter(
        (item) => !ranked.some((r) => r.accession === item.accession),
      ),
    ].filter(
      (item) =>
        `${item.title} ${item.accession} ${item.acronym ?? ""} ${item.objectives ?? ""}`
          .toLowerCase()
          .includes(query.toLowerCase()) &&
        (phase === "all" || item.fuel_phase === phase) &&
        (review === "all" || item.review_status === review),
    );
  }, [records, rank, query, phase, review]);
  const visibleIds = new Set(ordered.map((item) => item.accession));
  const visibleRows = rows.filter((row) => visibleIds.has(row.accession));
  const allGaps = [
    ...new Set(
      rank?.items
        .filter((item) => visibleIds.has(item.accession))
        .flatMap((item) =>
          item.gaps.map((gap) => `${item.accession}: ${gap}`),
        ) ?? [],
    ),
  ];
  function apply(event: FormEvent) {
    event.preventDefault();
    const oxygen = Number(custom.oxygen),
      pressure = Number(custom.pressure);
    if (
      !custom.oxygen.trim() ||
      !custom.pressure.trim() ||
      !Number.isFinite(oxygen) ||
      oxygen < 0 ||
      oxygen > 100 ||
      !Number.isFinite(pressure) ||
      pressure <= 0
    ) {
      setCustomError("Enter oxygen from 0–100% and a pressure above zero.");
      return;
    }
    const extra: RankInputs = {
      o2_fraction: oxygen / 100,
      pressure_kpa: pressure,
      goal: conditions.goal,
    };
    if (custom.flow.trim()) extra.flow_cm_s = Number(custom.flow);
    if (custom.gravity.trim()) extra.gravity_level_g = Number(custom.gravity);
    if (
      [extra.flow_cm_s, extra.gravity_level_g].some(
        (v) => v !== undefined && (!Number.isFinite(v) || v < 0),
      )
    ) {
      setCustomError("Airflow and gravity must be zero or greater.");
      return;
    }
    setCustomError("");
    setProfile("custom", extra);
  }
  return (
    <>
      <PageTitle
        eyebrow="THE RESEARCH WORKSPACE"
        title="Explore the evidence."
        action={
          <button
            className="button secondary"
            onClick={() => exportData(ordered.map((inv) => inv.accession))}
          >
            Export data ↗
          </button>
        }
      >
        Find the studies closest to your research question, and see where the
        evidence ends.
      </PageTitle>
      <section
        className="panel mission-panel"
        aria-labelledby="mission-heading"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">01 / SET THE CONTEXT</p>
            <h2 id="mission-heading">Your mission environment</h2>
          </div>
          <span className="tag amber">Illustrative scenarios</span>
        </div>
        <div
          className="profile-pills"
          role="group"
          aria-label="Illustrative mission profile"
        >
          {config.profiles.map((item) => (
            <button
              key={item.id}
              aria-pressed={profile === item.id}
              onClick={() =>
                setProfile(
                  item.id,
                  item.id === "custom" ? undefined : { goal: conditions.goal },
                )
              }
            >
              {item.label}
            </button>
          ))}
        </div>
        {profile === "custom" && (
          <form
            className="custom-form"
            onSubmit={apply}
            aria-label="Custom environment conditions"
          >
            <div className="custom-grid">
              {[
                ["oxygen", "Oxygen (%)"],
                ["pressure", "Pressure (kPa)"],
                ["flow", "Airflow (cm/s, optional)"],
                ["gravity", "Gravity (g, optional)"],
              ].map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    type="number"
                    step="any"
                    min={key === "pressure" ? "0.000001" : "0"}
                    max={key === "oxygen" ? "100" : undefined}
                    required={key === "oxygen" || key === "pressure"}
                    value={custom[key as keyof typeof custom]}
                    onChange={(e) =>
                      setCustom({ ...custom, [key]: e.target.value })
                    }
                  />
                </label>
              ))}
            </div>
            <button className="button" type="submit">
              Apply custom conditions
            </button>
            {customError && <p role="alert">{customError}</p>}
          </form>
        )}
        {profileInfo && (
          <>
            <div className="mission-readouts">
              <div>
                <span>OXYGEN</span>
                <strong>{range(profileInfo.oxygen)}</strong>
              </div>
              <div>
                <span>PRESSURE</span>
                <strong>{range(profileInfo.pressure)}</strong>
              </div>
              <div>
                <span>GRAVITY</span>
                <strong>{profileInfo.gravity.replaceAll("_", " ")}</strong>
              </div>
              <label>
                Research goal
                <select
                  aria-label="Research goal"
                  value={conditions.goal ?? "prevention"}
                  onChange={(event) =>
                    setProfile(profile, {
                      ...conditions,
                      goal: event.target.value as RankInputs["goal"],
                    })
                  }
                >
                  <option value="prevention">Prevention</option>
                  <option value="detection">Detection</option>
                  <option value="suppression">Suppression</option>
                </select>
              </label>
            </div>
            <p className="muted small">
              {profileInfo.description} Research relevance describes evidence
              proximity, never a safety rating.
            </p>
          </>
        )}
      </section>
      <section
        className="panel coverage-panel"
        aria-labelledby="coverage-heading"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">02 / UNDERSTAND THE COVERAGE</p>
            <h2 id="coverage-heading">Where has NASA tested?</h2>
          </div>
          <span className="subtle-label">OXYGEN × PRESSURE</span>
        </div>
        <p className="muted">
          Explore the conditions NASA has measured. Compare them with your
          mission environment.
        </p>
        {rowsError ? (
          <ErrorNotice message={rowsError} />
        ) : rowsLoading ? (
          <div className="chart-loading" role="status">
            Loading reviewed test coordinates…
          </div>
        ) : (
          <CoverageMap
            tests={visibleRows}
            profile={profile === "custom" && !rank ? undefined : profileInfo}
            onSelect={(id) => {
              window.location.hash = `/investigations/${id}`;
            }}
          />
        )}
      </section>
      <section aria-labelledby="studies-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">03 / FOLLOW THE SOURCES</p>
            <h2 id="studies-heading">
              Relevant investigations{" "}
              <span className="count">{ordered.length}</span>
            </h2>
          </div>
          <span className="muted small" role="status">
            {rankLoading
              ? "Updating relevance…"
              : "Ranked by research relevance"}
          </span>
        </div>
        <div className="filters">
          <label className="search-field">
            <span className="sr-only">Search titles or PSI IDs</span>
            <input
              type="search"
              placeholder="Search studies, acronyms or PSI IDs…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label>
            <span className="sr-only">Fuel phase</span>
            <select
              aria-label="Fuel phase"
              value={phase}
              onChange={(e) => setPhase(e.target.value)}
            >
              <option value="all">All fuel phases</option>
              {["solid", "liquid", "gas", "mixed", "unknown"].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="sr-only">Review status</span>
            <select
              aria-label="Review status"
              value={review}
              onChange={(e) => setReview(e.target.value)}
            >
              <option value="all">All review states</option>
              <option value="reviewed">Reviewed</option>
              <option value="unreviewed">Unreviewed</option>
            </select>
          </label>
          {(query || phase !== "all" || review !== "all") && (
            <button
              className="text-button"
              onClick={() => {
                setQuery("");
                setPhase("all");
                setReview("all");
              }}
            >
              Clear filters
            </button>
          )}
        </div>
        {(query || phase !== "all" || review !== "all") && (
          <div className="active-filters" aria-label="Active filters">
            {query && (
              <button onClick={() => setQuery("")}>Search: {query} ×</button>
            )}
            {phase !== "all" && (
              <button onClick={() => setPhase("all")}>Fuel: {phase} ×</button>
            )}
            {review !== "all" && (
              <button onClick={() => setReview("all")}>
                Review: {review} ×
              </button>
            )}
          </div>
        )}
        {rankError && <ErrorNotice message={rankError} />}
        <div className="study-grid" aria-busy={rankLoading}>
          {ordered.slice(0, shown).map((inv, index) => {
            const score = rank?.items.find(
              (item) => item.accession === inv.accession,
            );
            return (
              <article className="study-card" key={inv.accession}>
                <div className="card-top">
                  <span className="mono muted">
                    {String(index + 1).padStart(2, "0")}{" "}
                    <span className="card-id">{inv.accession}</span>
                  </span>
                  <ReviewLabel inv={inv} />
                </div>
                <div className="study-title">
                  <a href={`#/investigations/${inv.accession}`}>
                    <h3>{studyName(inv)}</h3>
                  </a>
                  <span
                    className="score"
                    title="Research relevance, not a safety score"
                  >
                    {score?.score == null
                      ? "—"
                      : `${Math.round(score.score * 100)}%`}
                    <small>relevance</small>
                  </span>
                </div>
                <p className="study-full-title">{inv.title}</p>
                <p className="study-description">
                  {inv.summary?.review_status === "reviewed" &&
                  inv.summary.objective.trim().length > 12
                    ? inv.summary.objective
                    : inv.objectives && inv.objectives.trim().length > 12
                      ? inv.objectives
                      : inv.description && inv.description.trim().length > 12
                        ? inv.description
                        : "A descriptive objective is not available in this snapshot. Open the source record for details."}
                </p>
                <div className="tag-row">
                  <span className="tag neutral">{inv.fuel_phase} fuel</span>
                  {(inv.fire_safety_tags ?? []).map((tag) => (
                    <span className="tag neutral" key={tag}>
                      {tag}
                    </span>
                  ))}
                </div>
                <div
                  className="score-bars"
                  aria-label={`${inv.accession} relevance breakdown`}
                >
                  {dimensions.map(([key, label]) => (
                    <div key={key}>
                      <span>{label}</span>
                      <meter
                        aria-label={`${inv.accession} ${label}`}
                        min="0"
                        max="1"
                        value={score?.breakdown[key] ?? 0}
                        aria-valuetext={
                          score?.breakdown[key] == null
                            ? "Not available"
                            : `${Math.round(score.breakdown[key]! * 100)} percent`
                        }
                      />
                      <span className="mono">
                        {score?.breakdown[key] == null
                          ? "—"
                          : Math.round(score.breakdown[key]! * 100)}
                      </span>
                    </div>
                  ))}
                </div>
                <details className="rationale">
                  <summary>Why this result?</summary>
                  <p>
                    {score?.rationale ??
                      "Relevance is unavailable until a scenario is applied."}
                  </p>
                  {!!score?.gaps.length && (
                    <ul>
                      {score.gaps.map((gap) => (
                        <li key={gap}>{gap}</li>
                      ))}
                    </ul>
                  )}
                </details>
                <div className="card-bottom">
                  <a
                    href={`#/investigations/${inv.accession}`}
                    className="text-link"
                  >
                    View investigation ↗
                  </a>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={selected.includes(inv.accession)}
                      disabled={
                        selected.length >= 3 &&
                        !selected.includes(inv.accession)
                      }
                      onChange={() => toggle(inv.accession)}
                    />
                    Compare
                  </label>
                </div>
              </article>
            );
          })}
        </div>
        {!ordered.length && (
          <Empty title="No investigations match your search.">
            Try another search or clear your filters.
          </Empty>
        )}
        {ordered.length > shown && (
          <button
            className="button secondary load-more"
            onClick={() => setShown((old) => old + 6)}
          >
            Show more investigations ({ordered.length - shown} remaining)
          </button>
        )}
      </section>
      <section className="gap-panel" aria-labelledby="gap-heading">
        <div>
          <span className="eyebrow">KNOW THE LIMITS</span>
          <h2 id="gap-heading">What the evidence can’t tell us</h2>
          <p>Scenario assumptions and missing measurements remain visible.</p>
        </div>
        <div>
          <p className="small">
            {number(visibleRows.length, 0)} normalized rows match the study
            filters; the chart shows the reviewed subset with both coordinates.
          </p>
          <ul>
            {(allGaps.length
              ? allGaps.slice(0, 4)
              : ["No reviewed evidence has been scored for this selection."]
            ).map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
          <details>
            <summary>Scenario assumptions & ranking weights</summary>
            <ul>
              {profileInfo?.assumptions.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
            <p className="small">
              {dimensions
                .map(
                  ([key, label]) =>
                    `${label} ${Math.round(config.weights[key] * 100)}%`,
                )
                .join(" · ")}
            </p>
            {rank?.warnings.map((text) => (
              <p className="small" key={text}>
                {text}
              </p>
            ))}
          </details>
        </div>
      </section>
    </>
  );
}
