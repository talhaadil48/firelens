import type { Investigation, TestRow, ProfileConfig } from "./client";

export type Profile = ProfileConfig["profiles"][number];
export const number = (value: number | null | undefined, digits = 1) =>
  value == null
    ? "Not reported"
    : new Intl.NumberFormat("en", { maximumFractionDigits: digits }).format(
        value,
      );
export const reviewedRow = (row: TestRow) =>
  row.review_status === "reviewed" &&
  row.evidence_type === "measurement" &&
  !row.provenance.is_mock;
export function range(
  value: NonNullable<Investigation["condition_ranges"]>[string] | undefined,
) {
  if (!value || (value.minimum == null && value.maximum == null))
    return "Not reported";
  const factor = value.unit === "fraction" ? 100 : 1;
  const unit = value.unit === "fraction" ? "% O₂" : value.unit;
  if (value.minimum === value.maximum)
    return `${number(value.minimum == null ? null : value.minimum * factor)} ${unit}`;
  return `${value.minimum == null ? "≤" : number(value.minimum * factor)}${value.minimum != null && value.maximum != null ? "–" : ""}${value.maximum == null ? "+" : number(value.maximum * factor)} ${unit}`;
}
export const studyName = (inv: Investigation) => inv.acronym || inv.title;
export function citationText(inv: Investigation) {
  return `${inv.title}. NASA Physical Sciences Informatics (${inv.accession}), version ${inv.version}. ${inv.doi ? `https://doi.org/${inv.doi}` : inv.source_url}`;
}
export function download(content: string, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
