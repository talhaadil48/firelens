import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ChatChart from "./components/ChatChart";
import { getAllTests } from "./client";
import type { Schema, TestRow } from "./client";
vi.mock("./client", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getAllTests: vi.fn(),
}));
vi.mock("./components/EvidenceBars", () => ({
  default: ({ field }: { field: string }) => (
    <div data-testid="cited-bars">{field}</div>
  ),
}));
vi.mock("./Plot", () => ({
  default: ({ points }: { points: { rows: TestRow[] }[] }) => (
    <div data-testid="cited-plot">
      {points.flatMap((point) => point.rows).length} measurement points:{" "}
      {points
        .flatMap((point) => point.rows)
        .map((t) => t.test_id)
        .join(",")}
    </div>
  ),
}));
const row = (id: string, sourceRow: number): TestRow => ({
  accession: "PSI-69",
  test_id: id,
  fuel_phase: "liquid",
  oxygen_basis: "unknown",
  gravity: "microgravity",
  o2_fraction: 0.21,
  pressure_kpa: 101.3,
  record_kind: "individual_test",
  evidence_type: "measurement",
  source_file: "tests.csv",
  source_row: sourceRow,
  provenance: {
    source_url: "https://psi.nasa.gov/",
    source_file: "tests.csv",
    source_version: "1",
    retrieved_at: "2026-11-14T00:00:00Z",
    source_row: sourceRow,
    page: null,
    source_sha256: null,
    is_mock: false,
  },
});
const citation = (r: TestRow): Schema["Citation"] => ({
  id: `row:${r.accession}:${r.test_id}`,
  accession: r.accession,
  locator: `tests.csv row ${r.source_row}`,
  supporting_text: "Source test evidence",
  provenance: r.provenance,
});
beforeEach(() => {
  vi.mocked(getAllTests).mockReset();
});
it("plots only cited, measurements with exactly matching provenance", async () => {
  const first = row("one", 2),
    second = row("two", 3),
    grouped = {
      ...row("grouped", 4),
      record_kind: "grouped_summary" as const,
    };
  const mismatched = row("wrong-source-row", 5),
    extra = row("uncited", 6);
  const oldVersion = row("old-version", 7);
  const oldHash = row("different-file-hash", 8);
  const poisonedCitation = {
    ...citation(mismatched),
    provenance: { ...mismatched.provenance, source_row: 99 },
  };
  vi.mocked(getAllTests).mockResolvedValue([
    first,
    second,
    grouped,
    mismatched,
    extra,
    oldVersion,
    oldHash,
  ]);
  render(
    <ChatChart
      citations={[
        citation(first),
        citation(second),
        citation(grouped),
        poisonedCitation,
        {
          ...citation(oldVersion),
          provenance: { ...oldVersion.provenance, source_version: "outdated" },
        },
        {
          ...citation(oldHash),
          provenance: { ...oldHash.provenance, source_sha256: "a".repeat(64) },
        },
      ]}
    />,
  );
  expect(await screen.findByTestId("cited-plot")).toHaveTextContent(
    "2 measurement points: one,two",
  );
  expect(getAllTests).toHaveBeenCalledWith(expect.any(AbortSignal), {
    accession: "PSI-69",
  });
  fireEvent.click(screen.getByRole("button", { name: "Source rows" }));
  expect(screen.getAllByRole("row")).toHaveLength(3);
  expect(screen.queryByText("uncited")).not.toBeInTheDocument();
  expect(screen.queryByText("wrong-source-row")).not.toBeInTheDocument();
});
it("does not infer missing coordinates to manufacture a chart", async () => {
  const first = { ...row("one", 2), o2_fraction: null, pressure_kpa: null };
  vi.mocked(getAllTests).mockResolvedValue([first]);
  render(<ChatChart citations={[citation(first)]} />);
  expect(
    await screen.findByText(/A chart needs at least two/),
  ).toBeInTheDocument();
  expect(screen.queryByTestId("cited-plot")).not.toBeInTheDocument();
});
it("reports a chart retrieval failure while leaving the answer usable", async () => {
  vi.mocked(getAllTests).mockRejectedValue(new Error("offline"));
  render(<ChatChart citations={[citation(row("one", 2))]} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Cited-data chart unavailable: offline",
  );
});

it("uses an airflow bar chart when the question asks for airflow", async () => {
  const first = { ...row("one", 2), flow_cm_s: 8 },
    second = { ...row("two", 3), flow_cm_s: 12 };
  vi.mocked(getAllTests).mockResolvedValue([first, second]);
  render(
    <ChatChart
      citations={[citation(first), citation(second)]}
      question="Compare the airflow measurements"
    />,
  );
  expect(await screen.findByTestId("cited-bars")).toHaveTextContent(
    "flow_cm_s",
  );
  expect(screen.queryByTestId("cited-plot")).not.toBeInTheDocument();
});
it("does not substitute airflow bars for missing requested oxygen-pressure coordinates", async () => {
  const rows = [row("one", 2), row("two", 3)].map((r) => ({
    ...r,
    o2_fraction: null,
    pressure_kpa: null,
    flow_cm_s: 10,
  }));
  vi.mocked(getAllTests).mockResolvedValue(rows);
  render(
    <ChatChart
      citations={rows.map(citation)}
      question="What oxygen concentrations and pressures were measured?"
    />,
  );
  expect(
    await screen.findByText(/No different quantity has been substituted/),
  ).toBeInTheDocument();
  expect(screen.queryByTestId("cited-bars")).not.toBeInTheDocument();
  expect(screen.queryByTestId("cited-plot")).not.toBeInTheDocument();
});
it("does not substitute pressure when the requested airflow is missing", async () => {
  const rows = [row("one", 2), row("two", 3)];
  vi.mocked(getAllTests).mockResolvedValue(rows);
  render(
    <ChatChart
      citations={rows.map(citation)}
      question="Compare airflow velocities"
    />,
  );
  expect(
    await screen.findByText(/No different quantity has been substituted/),
  ).toBeInTheDocument();
  expect(screen.queryByTestId("cited-bars")).not.toBeInTheDocument();
});
