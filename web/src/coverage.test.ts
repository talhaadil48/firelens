import { expect, it } from "vitest";
import { coverageRows, groupConditions } from "./coverage";
import type { TestRow } from "./client";
const row = (id: string, oxygen = 0.21, pressure = 101.3): TestRow => ({
  accession: "PSI-69",
  test_id: id,
  fuel_phase: "liquid",
  oxygen_basis: "mole",
  gravity: "microgravity",
  o2_fraction: oxygen,
  pressure_kpa: pressure,
  review_status: "reviewed",
  evidence_type: "measurement",
  provenance: {
    source_url: "https://psi.nasa.gov/",
    source_file: "tests.csv",
    source_version: "1",
    retrieved_at: "2026-11-14T00:00:00Z",
    source_row: 2,
    page: null,
    source_sha256: null,
    is_mock: false,
  },
});
it("groups exactly identical conditions without discarding test rows or source studies", () => {
  const a = row("one"),
    b = { ...row("two"), accession: "PSI-25" },
    c = row("three", 0.35, 70);
  const groups = groupConditions([a, b, c]);
  expect(groups).toHaveLength(2);
  expect(groups[0].rows).toEqual([a, b]);
  expect(groups[0].accessions).toEqual(["PSI-69", "PSI-25"]);
  expect(groups.reduce((count, group) => count + group.rows.length, 0)).toBe(3);
});
it("does not round or jitter similar but distinct physical conditions", () => {
  const groups = groupConditions([
    row("one", 0.21, 101.3),
    row("two", 0.210001, 101.3),
    row("three", 0.21, 101.30001),
  ]);
  expect(groups).toHaveLength(3);
  expect(groups.some((p) => p.pressure === 101.30001)).toBe(true);
});
it("retains high-pressure data instead of deleting it from the condition groups", () => {
  const groups = groupConditions([row("one"), row("high-pressure", 0.21, 500)]);
  expect(groups.map((p) => p.pressure)).toEqual([101.3, 500]);
});
it("excludes unreviewed, simulated, mock and missing-coordinate rows", () => {
  const source = row("one");
  const rows: TestRow[] = [
    source,
    { ...row("two"), review_status: "unreviewed" },
    { ...row("three"), evidence_type: "simulation" },
    { ...row("four"), provenance: { ...source.provenance, is_mock: true } },
    { ...row("five"), pressure_kpa: null },
  ];
  expect(coverageRows(rows)).toEqual([source]);
  expect(groupConditions(rows)).toHaveLength(1);
});
