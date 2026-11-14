import type { TestRow } from "./client";
import { reviewedRow } from "./presentation";

export const outcomeOptions = [
  { id: "all", label: "All outcomes" },
  { id: "ignited", label: "Ignited" },
  { id: "extinguished", label: "Extinguished" },
  { id: "cool_flame", label: "Cool flame" },
  { id: "failed", label: "Failed (reported)" },
  { id: "unknown", label: "Not reported" },
] as const;
export interface ConditionPoint {
  oxygen: number;
  pressure: number;
  rows: TestRow[];
  accessions: string[];
}
export function coverageRows(tests: TestRow[]) {
  return tests.filter(
    (row) =>
      reviewedRow(row) && row.o2_fraction != null && row.pressure_kpa != null,
  );
}
export function groupConditions(rows: TestRow[]): ConditionPoint[] {
  const groups = new Map<string, ConditionPoint>();
  for (const row of coverageRows(rows)) {
    // Exact numeric coordinates only: no rounding, binning or synthetic jitter.
    const key = `${row.o2_fraction}:${row.pressure_kpa}`;
    const existing = groups.get(key);
    if (existing) {
      existing.rows.push(row);
      if (!existing.accessions.includes(row.accession))
        existing.accessions.push(row.accession);
    } else
      groups.set(key, {
        oxygen: row.o2_fraction! * 100,
        pressure: row.pressure_kpa!,
        rows: [row],
        accessions: [row.accession],
      });
  }
  return [...groups.values()].sort(
    (a, b) => a.oxygen - b.oxygen || a.pressure - b.pressure,
  );
}
