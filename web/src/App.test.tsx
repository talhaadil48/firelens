import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import App from "./App";
import CoverageMap from "./CoverageMap";
import { ask, getCompare, getRank } from "./client";
import type { FixtureBundle, TestRow } from "./client";

vi.mock("./Plot", () => ({
  default: ({ points }: { points: { rows: TestRow[] }[] }) => (
    <div data-testid="plot">
      {points.flatMap((point) => point.rows).length} plotted reviewed points
    </div>
  ),
}));
const fixture = JSON.parse(
  readFileSync("public/fixtures.json", "utf8"),
) as FixtureBundle;
beforeEach(() => {
  document.documentElement.dataset.theme = "dark";
  localStorage.clear();
  window.history.replaceState(null, "", "/");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => structuredClone(fixture),
    }),
  );
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value() {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value() {
      this.removeAttribute("open");
    },
  });
});
async function ready() {
  await screen.findByRole("heading", { name: /Relevant investigations/ });
}
function navigate(path: string) {
  window.location.hash = path;
  fireEvent(window, new HashChangeEvent("hashchange"));
}

describe("Phase 7 research workspace", () => {
  it("shows a cold start immediately and real metadata with an explicit fixture boundary", async () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "Waking the data service." }),
    ).toBeInTheDocument();
    await ready();
    expect(
      screen.getByText(
        "Real NASA catalogue records. No reviewed measurements or relevance scores are supplied by these fixtures.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "View investigation ↗" }),
    ).toHaveLength(5);
    expect(screen.getAllByText("Metadata fixture")).toHaveLength(5);
    expect(
      screen.getByText("No reviewed measurement points yet"),
    ).toBeInTheDocument();
  });
  it("filters studies and shows an honest empty state", async () => {
    render(<App />);
    await ready();
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "PSI-69" },
    });
    expect(
      screen.getAllByRole("link", { name: "View investigation ↗" }),
    ).toHaveLength(1);
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "missing-study" },
    });
    expect(
      screen.getByText("No investigations match your search."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(
      screen.getAllByRole("link", { name: "View investigation ↗" }),
    ).toHaveLength(5);
  });
  it("reports load errors and provides a retry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 503 }),
    );
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Request failed (503)",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "View investigation ↗" }),
    ).not.toBeInTheDocument();
  });
  it("applies a custom environment using fractions without manufacturing scores", async () => {
    render(<App />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Custom environment" }));
    fireEvent.change(screen.getByLabelText("Oxygen (%)"), {
      target: { value: "34" },
    });
    fireEvent.change(screen.getByLabelText("Pressure (kPa)"), {
      target: { value: "70" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Apply custom conditions" }),
    );
    expect(await screen.findByText("34 % O₂")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
  it("opens an investigation, exposes sources and copies the real citation", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<App />);
    await ready();
    navigate("/investigations/PSI-69");
    expect(
      await screen.findByRole("heading", {
        name: "What this investigation explores",
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy citation" }));
    expect(await screen.findByText("Citation copied.")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("PSI-69"));
    const overview = screen.getByRole("tab", { name: "Overview" });
    fireEvent.keyDown(overview, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: /Findings/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.queryByRole("heading", {
        name: "What this investigation explores",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Measurements/ }));
    expect(
      screen.getByRole("heading", { name: "A look at the test rows" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("tab", { name: "Sources & publications" }),
    );
    expect(
      screen.getByRole("heading", { name: "Source record" }),
    ).toBeInTheDocument();
    fireEvent.click(overview);
    expect(
      screen.getByRole("link", { name: "Verify the NASA record ↗" }),
    ).toHaveAttribute("href", expect.stringContaining("psi.nasa.gov"));
  });
  it("compares selected studies and supports highlighting differences", async () => {
    render(<App />);
    await ready();
    const checkboxes = screen.getAllByRole("checkbox", { name: "Compare" });
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);
    expect(screen.getByLabelText("Comparison selection")).toHaveTextContent(
      "2 / 3",
    );
    navigate("/compare");
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Highlight differing fields" }),
    ).toBeChecked();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Highlight differing fields" }),
    );
    expect(document.querySelector(".diff-row")).toBeNull();
  });
  it("streams abstention and does not manufacture citation chips", async () => {
    render(<App />);
    await ready();
    navigate("/ask");
    fireEvent.change(
      await screen.findByLabelText("What would you like to understand?"),
      { target: { value: "Which material is safest?" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Search evidence ↗" }));
    expect(
      await screen.findByText("Insufficient evidence"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Insufficient evidence: no reviewed/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /test row/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Retrieval trace/)).toBeInTheDocument();
  });
  it("opens export with format options, source credit and a preview", async () => {
    render(<App />);
    await ready();
    const trigger = screen.getByRole("button", { name: "Export data ↗" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(
      await within(dialog).findByLabelText("Export preview"),
    ).toHaveTextContent("NASA Physical Sciences Informatics");
    fireEvent.click(within(dialog).getByRole("radio", { name: "JSON" }));
    await waitFor(() =>
      expect(within(dialog).getByLabelText("Export preview")).toHaveTextContent(
        "snapshot_id",
      ),
    );
    expect(
      within(dialog).getByRole("button", { name: "Download JSON ↓" }),
    ).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});

describe("evidence boundaries", () => {
  it("does not plot empty or unreviewed records", async () => {
    const row = {
      accession: "PSI-69",
      test_id: "TEST",
      o2_fraction: 0.21,
      pressure_kpa: 101.3,
      review_status: "unreviewed",
      evidence_type: "measurement",
      provenance: { is_mock: false },
    } as TestRow;
    const { rerender } = render(<CoverageMap tests={[row]} />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "No reviewed measurement points yet",
    );
    rerender(<CoverageMap tests={[{ ...row, review_status: "reviewed" }]} />);
    expect(await screen.findByTestId("plot")).toHaveTextContent(
      "1 plotted reviewed points",
    );
  });
  it("does not manufacture scores and validates custom inputs", async () => {
    const rank = await getRank("moon_base");
    expect(rank.items.every((item) => item.score === null)).toBe(true);
    await expect(getRank("custom")).rejects.toThrow(
      "require oxygen and pressure",
    );
    await expect(
      getRank("custom", { o2_fraction: 34, pressure_kpa: 70 }),
    ).rejects.toThrow("Invalid");
  });
  it("rejects duplicate comparisons", async () => {
    await expect(getCompare(["PSI-26", "PSI-26"])).rejects.toThrow("distinct");
  });
  it("streams a complete offline insufficient-evidence result", async () => {
    const events = [];
    for await (const event of ask("Which material is safest?"))
      events.push(event);
    expect(events.map((e) => e.event)).toEqual(["progress", "answer", "done"]);
    expect(events[1].data).toMatchObject({
      status: "insufficient_evidence",
      citations: [],
    });
  });
});

it("switches both appearance modes and persists the chosen theme", async () => {
  render(<App />);
  await ready();
  fireEvent.click(
    screen.getByRole("button", { name: "Switch to light theme" }),
  );
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(localStorage.getItem("firelens-theme")).toBe("light");
  fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("firelens-theme")).toBe("dark");
});
