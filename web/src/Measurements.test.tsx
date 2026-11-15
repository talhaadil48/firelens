import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import Measurements from "./components/Measurements";
import type { TestRow } from "./client";

function record(index: number): TestRow {
  return {
    accession: "PSI-68",
    test_id: `source-${index}`,
    record_kind: "grouped_summary",
    evidence_type: "measurement",
    fuel_phase: "liquid",
    oxygen_basis: "unknown",
    gravity: "unknown",
    o2_fraction: null,
    pressure_kpa: null,
    source_cells: [
      { column: "Fuel", value: `Fuel ${index}`, column_index: 1 },
      { column: "Oxygen list", value: "0.17; 0.21; 0.3", column_index: 2 },
      {
        column: "Extra source column",
        value: "reported value",
        column_index: 3,
      },
    ],
    provenance: {
      source_url: "https://psi.nasa.gov/",
      source_file: "summary.csv",
      source_version: "1",
      source_row: index + 2,
      retrieved_at: "2026-11-14T00:00:00Z",
      is_mock: false,
      page: null,
      source_sha256: null,
    },
  };
}
it("retains partial source cells, ranges and every row beyond the first page", () => {
  render(
    <Measurements
      rows={Array.from({ length: 51 }, (_, index) => record(index))}
    />,
  );
  expect(
    screen.getByRole("columnheader", { name: "Extra source column" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("0.17; 0.21; 0.3")).toHaveLength(50);
  expect(screen.queryByText("Fuel 50")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next rows" }));
  expect(screen.getByText("Fuel 50")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next rows" })).toBeDisabled();
  expect(screen.getByText("grouped summary")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Display"), {
    target: { value: "standardized" },
  });
  expect(
    screen.getByText(
      "source-50 · All standardized fields, metrics & provenance",
    ),
  ).toBeInTheDocument();
});
it("keeps separate source tables accessible", () => {
  const other = record(2);
  other.provenance = { ...other.provenance, source_file: "second.csv" };
  render(<Measurements rows={[record(1), other]} />);
  fireEvent.change(screen.getByLabelText("Source table"), {
    target: { value: "second.csv" },
  });
  expect(screen.getByText("Fuel 2")).toBeInTheDocument();
  expect(screen.queryByText("Fuel 1")).not.toBeInTheDocument();
});
