import type { components } from "./api.generated";

export type Schema = components["schemas"];
export const dataMode = import.meta.env.VITE_DATA_MODE ?? "mock";
export type Meta = Schema["MetaResponse"];
export type Investigation = Schema["Investigation"];
export type TestRow = Schema["ExperimentalTest"];
export type ProfileConfig = Schema["ProfileConfig"];
export type InvestigationList = Schema["InvestigationList"];
export type RankResponse = Schema["RankResponse"];
export type CompareResponse = Schema["CompareResponse"];
export type TestList = Schema["TestList"];
export type ExportResponse = Schema["ExportResponse"];

export interface FixtureBundle {
  meta: Meta;
  profiles: ProfileConfig;
  investigations: InvestigationList;
  investigation: Investigation;
  rank: RankResponse;
  tests: TestList;
  compare: CompareResponse;
  export: ExportResponse;
}

const mode = dataMode;
const base = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");
if (!["mock", "api"].includes(mode))
  throw new Error("VITE_DATA_MODE must be mock or api");

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

async function fixtures(signal?: AbortSignal): Promise<FixtureBundle> {
  return fetchJson<FixtureBundle>("/fixtures.json", signal);
}

export async function getMeta(signal?: AbortSignal): Promise<Meta> {
  return mode === "api"
    ? fetchJson<Meta>(`${base}/meta`, signal)
    : (await fixtures(signal)).meta;
}

export async function getProfiles(
  signal?: AbortSignal,
): Promise<ProfileConfig> {
  return mode === "api"
    ? fetchJson<ProfileConfig>(`${base}/profiles`, signal)
    : (await fixtures(signal)).profiles;
}

export async function getInvestigations(
  signal?: AbortSignal,
): Promise<InvestigationList> {
  return mode === "api"
    ? fetchJson<InvestigationList>(`${base}/investigations`, signal)
    : (await fixtures(signal)).investigations;
}

export async function getInvestigation(
  id: string,
  signal?: AbortSignal,
): Promise<Investigation> {
  if (mode === "api")
    return fetchJson<Investigation>(
      `${base}/investigations/${encodeURIComponent(id)}`,
      signal,
    );
  const found = (await fixtures(signal)).investigations.items.find(
    (item) => item.accession === id,
  );
  if (!found) throw new Error(`Unknown investigation: ${id}`);
  return found;
}

export interface TestFilters {
  accession?: string;
  oxygen_min?: number;
  oxygen_max?: number;
  pressure_min?: number;
  pressure_max?: number;
}
function filterQuery(filters: TestFilters): URLSearchParams {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });
  return query;
}
export async function getTests(
  signal?: AbortSignal,
  filters: TestFilters = {},
  offset = 0,
): Promise<TestList> {
  if (mode === "mock") return (await fixtures(signal)).tests;
  const query = filterQuery(filters);
  query.set("limit", "100");
  query.set("offset", String(offset));
  return fetchJson<TestList>(`${base}/tests?${query}`, signal);
}
export async function getAllTests(
  signal?: AbortSignal,
  filters: TestFilters = {},
): Promise<TestRow[]> {
  const first = await getTests(signal, filters);
  const rows = [...first.items];
  for (let offset = first.items.length; offset < first.total;) {
    const page = await getTests(signal, filters, offset);
    if (!page.items.length)
      throw new Error(
        "Incomplete test response. Reload the data before using the chart.",
      );
    rows.push(...page.items);
    offset += page.items.length;
  }
  return rows;
}
export async function getExport(
  filters: TestFilters = {},
  signal?: AbortSignal,
): Promise<ExportResponse> {
  if (mode === "mock") return (await fixtures(signal)).export;
  const query = filterQuery(filters);
  query.set("format", "json");
  return fetchJson<ExportResponse>(`${base}/export?${query}`, signal);
}

export interface RankInputs {
  o2_fraction?: number;
  pressure_kpa?: number;
  flow_cm_s?: number;
  gravity_level_g?: number;
  goal?: "prevention" | "detection" | "suppression";
}

export async function getRank(
  profile = "iss",
  conditions: RankInputs = {},
  signal?: AbortSignal,
): Promise<RankResponse> {
  for (const [name, value] of Object.entries(conditions)) {
    if (name === "goal" || value === undefined) continue;
    if (
      typeof value !== "number" ||
      !Number.isFinite(value) ||
      value < 0 ||
      (name === "o2_fraction" && value > 1) ||
      (name === "pressure_kpa" && value === 0)
    ) {
      throw new Error(`Invalid ${name}`);
    }
  }
  if (
    conditions.goal &&
    !["prevention", "detection", "suppression"].includes(conditions.goal)
  ) {
    throw new Error("Invalid safety goal");
  }
  if (
    profile === "custom" &&
    (conditions.o2_fraction === undefined ||
      conditions.pressure_kpa === undefined)
  ) {
    throw new Error("Custom profiles require oxygen and pressure");
  }
  const query = new URLSearchParams({ profile });
  for (const [name, value] of Object.entries(conditions)) {
    if (value !== undefined) query.set(name, String(value));
  }
  if (mode === "api")
    return fetchJson<RankResponse>(`${base}/rank?${query}`, signal);
  const fixture = await fixtures(signal);
  const selected = fixture.profiles.profiles.find(
    (item) => item.id === profile,
  );
  if (!selected) throw new Error(`Unknown profile: ${profile}`);
  const configured = {
    ...selected,
    oxygen: { ...selected.oxygen },
    pressure: { ...selected.pressure },
    flow: { ...selected.flow },
    assumptions: [...selected.assumptions],
  };
  if (conditions.o2_fraction !== undefined)
    configured.oxygen.minimum = configured.oxygen.maximum =
      conditions.o2_fraction;
  if (conditions.pressure_kpa !== undefined)
    configured.pressure.minimum = configured.pressure.maximum =
      conditions.pressure_kpa;
  if (conditions.flow_cm_s !== undefined)
    configured.flow.minimum = configured.flow.maximum = conditions.flow_cm_s;
  if (conditions.gravity_level_g !== undefined) {
    configured.gravity_level_g = conditions.gravity_level_g;
    configured.gravity =
      conditions.gravity_level_g === 1
        ? "normal_gravity"
        : conditions.gravity_level_g === 0
          ? "microgravity"
          : "reduced_gravity";
  }
  return {
    ...fixture.rank,
    profile: configured,
    safety_goal: conditions.goal ?? "prevention",
  };
}

export async function getCompare(
  ids: string[],
  signal?: AbortSignal,
): Promise<CompareResponse> {
  if (ids.length < 2 || ids.length > 3 || new Set(ids).size !== ids.length) {
    throw new Error("Choose 2–3 distinct investigations");
  }
  if (mode === "api")
    return fetchJson<CompareResponse>(
      `${base}/compare?ids=${encodeURIComponent(ids.join(","))}`,
      signal,
    );
  const fixture = await fixtures(signal);
  const items = ids.map((id) => {
    const item = fixture.investigations.items.find(
      (record) => record.accession === id,
    );
    if (!item) throw new Error(`Unknown investigation: ${id}`);
    return item;
  });
  return {
    ...fixture.compare,
    investigations: items,
    summary:
      "Metadata comparison only. No experimental equivalence or physical conclusions are established by these fixtures.",
    same: [
      "NASA Physical Sciences Informatics catalogue records; original source links retained.",
    ],
    different: items.map((item) => `${item.accession}: ${item.title}`),
  };
}

export interface ChatEvent {
  event: "progress" | "answer" | "done";
  data: Schema["ProgressEvent"] | Schema["AnswerEvent"] | Schema["DoneEvent"];
}

export async function* ask(
  question: string,
  signal?: AbortSignal,
  ids: string[] = [],
): AsyncGenerator<ChatEvent> {
  signal?.throwIfAborted();
  if (!question.trim() || question.length > 2000)
    throw new Error("Enter a question of 1–2000 characters");
  if (mode === "mock") {
    yield {
      event: "progress",
      data: { stage: "retrieval", message: "Offline mock; no LLM called." },
    };
    yield {
      event: "answer",
      data: {
        text: "Insufficient evidence: no experimental findings in this Phase 2 fixture.",
        status: "insufficient_evidence",
        mode: "mock",
        citations: [],
      },
    };
    yield { event: "done", data: { finish_reason: "insufficient_evidence" } };
    return;
  }
  const response = await fetch(`${base}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, investigation_ids: ids }),
    signal,
  });
  if (!response.ok || !response.body)
    throw new Error(`Chat failed (${response.status})`);
  const reader = response.body.getReader();
  const cancel = () => {
    void reader.cancel().catch(() => {});
  };
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) cancel();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      signal?.throwIfAborted();
      const chunk = await reader.read();
      signal?.throwIfAborted();
      if (chunk.done) {
        if (pending.trim())
          throw new Error("Incomplete chat stream. Please retry.");
        break;
      }
      pending += decoder.decode(chunk.value, { stream: true });
      pending = pending.replace(/\r\n/g, "\n");
      // Server emits LF-delimited SSE. Decode UTF-8 across arbitrary network chunks.
      let boundary: number;
      while ((boundary = pending.indexOf("\n\n")) >= 0) {
        const frame = pending.slice(0, boundary);
        pending = pending.slice(boundary + 2);
        const event = frame
          .split("\n")
          .find((line) => line.startsWith("event: "))
          ?.slice(7);
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data: "))
          .map((line) => line.slice(6))
          .join("\n");
        if (event && ["progress", "answer", "done"].includes(event) && data) {
          signal?.throwIfAborted();
          yield {
            event: event as ChatEvent["event"],
            data: JSON.parse(data) as ChatEvent["data"],
          };
        }
      }
    }
  } finally {
    signal?.removeEventListener("abort", cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
