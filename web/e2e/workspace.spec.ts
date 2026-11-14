import { expect, test } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
const artifacts = path.resolve("../artifacts/phase7");
const snapshot = existsSync(path.resolve("../snapshots/latest.json"));
test.skip(
  !snapshot,
  "Generate a local NASA snapshot with harvest.pipeline before running real-data browser tests.",
);

test("real snapshot: explore → detail → compare → cited graphical answer → export", async ({
  page,
}) => {
  mkdirSync(artifacts, { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Explore the evidence." }),
  ).toBeVisible();
  await expect(
    page.getByText(/reviewed rows with both coordinates/),
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".coverage-panel .js-plotly-plot")).toBeVisible();
  await page.getByRole("button", { name: "Moon base", exact: true }).click();
  await expect(page.getByText("Updating relevance…")).toBeHidden();
  await expect(
    page
      .locator(".coverage-panel .annotation")
      .filter({ hasText: "Mission envelope" }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(artifacts, "explorer-desktop.png"),
    fullPage: true,
  });
  const selections = page.getByRole("checkbox", {
    name: "Compare",
    exact: true,
  });
  await selections.nth(0).check();
  await selections.nth(1).check();
  await page
    .getByRole("link", { name: "View investigation ↗" })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "What this investigation explores" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Verify the NASA record ↗" }),
  ).toHaveAttribute("href", /psi\.nasa\.gov/);
  await page.getByRole("button", { name: "Copy citation" }).click();
  await expect(
    page.getByText(/Citation copied\.|Clipboard unavailable/),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(artifacts, "investigation-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Compare selected →" }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await page
    .getByRole("checkbox", { name: "Highlight differing fields" })
    .uncheck();
  await expect(page.locator(".diff-row")).toHaveCount(0);
  await page.screenshot({
    path: path.join(artifacts, "compare-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Ask FireLens", exact: true }).click();
  await page.getByLabel("Search scope").selectOption("PSI-69");
  await page
    .getByLabel("What would you like to understand?")
    .fill("Show PSI-69 tests with oxygen and pressure");
  await page.getByRole("button", { name: "Search evidence ↗" }).click();
  await expect(page.getByText("Source-backed excerpts")).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    page.getByRole("region", { name: "Visual answer from cited measurements" }),
  ).toBeVisible();
  await expect(page.locator(".chat-chart .js-plotly-plot")).toBeVisible();
  await page.getByRole("button", { name: "Source rows", exact: true }).click();
  await expect(page.locator(".chat-chart table")).toBeVisible();
  await page.getByRole("button", { name: "Chart", exact: true }).click();
  await page.locator(".source-chip").first().click();
  await expect(page.locator(".evidence-panel blockquote")).toBeVisible();
  await page.screenshot({
    path: path.join(artifacts, "ask-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Explorer", exact: true }).click();
  await page.getByRole("button", { name: "Export data ↗" }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "Download CSV ↓" }),
  ).toBeEnabled({ timeout: 60_000 });
  const download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download CSV ↓" }).click();
  const csv = await download;
  expect(csv.suggestedFilename()).toContain(".csv");
  await csv.saveAs(path.join(artifacts, "verified-export.csv"));
  const exported = readFileSync(
    path.join(artifacts, "verified-export.csv"),
    "utf8",
  );
  expect(exported).toContain("source_row");
  expect(exported).toContain("pressure_kpa");
  expect(exported).toContain("PSI-69");
  expect(exported).toContain("# Snapshot:");
  await dialog.getByRole("radio", { name: "JSON", exact: true }).check();
  await expect(dialog.getByLabel("Export preview")).toContainText(
    "snapshot_id",
  );
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(errors).toEqual([]);
});

test("mobile: readable layout, navigation and keyboard-accessible data", async ({
  page,
}) => {
  await page.setViewportSize({ width: 393, height: 852 });
  await page.goto("/#/explorer");
  await expect(
    page.getByRole("heading", { name: "Explore the evidence." }),
  ).toBeVisible();
  await expect(page.locator(".coverage-panel .js-plotly-plot")).toBeVisible({
    timeout: 60_000,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByText("View accessible chart data", { exact: true }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByText("View accessible chart data", { exact: true }).click();
  await page.screenshot({
    path: path.join(artifacts, "explorer-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Ask FireLens", exact: true }).click();
  await expect(
    page.getByLabel("What would you like to understand?"),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(artifacts, "ask-mobile.png"),
    fullPage: true,
  });
});

test("three-way comparison and requested bar chart are backed by real API data", async ({
  page,
}) => {
  await page.goto("/#/compare?ids=PSI-25,PSI-69,PSI-159");
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.locator(".compare-table thead th")).toHaveCount(4);
  await page.getByRole("link", { name: "Ask FireLens", exact: true }).click();
  await page.getByLabel("Search scope").selectOption("PSI-69");
  await page
    .getByLabel("What would you like to understand?")
    .fill("Show PSI-69 tests and compare pressure");
  await page.getByRole("button", { name: "Search evidence ↗" }).click();
  await expect(page.getByText("Source-backed excerpts")).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.locator(".chat-chart .barlayer")).toBeVisible();
  await page.screenshot({
    path: path.join(artifacts, "ask-pressure-bars.png"),
    fullPage: true,
  });
});

test("custom scenario, filtered export and modal keyboard behavior", async ({
  page,
}) => {
  await page.goto("/#/explorer");
  await page
    .getByRole("button", { name: "Custom environment", exact: true })
    .click();
  await page.getByLabel("Oxygen (%)", { exact: true }).fill("34");
  await page.getByLabel("Pressure (kPa)", { exact: true }).fill("70");
  await page
    .getByRole("button", { name: "Apply custom conditions", exact: true })
    .click();
  await expect(page.getByText("34 % O₂", { exact: true })).toBeVisible();
  await page.getByRole("searchbox").fill("PSI-69");
  await expect(
    page.getByRole("link", { name: "View investigation ↗" }),
  ).toHaveCount(1);
  await page.getByRole("button", { name: "Export data ↗" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("274 rows · CSV")).toBeVisible({
    timeout: 60_000,
  });
  await expect(dialog.getByRole("combobox")).toHaveValue("__filtered");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Export data ↗" }),
  ).toBeFocused();
});

test("light and dark themes persist and the new condition explorer preserves source data", async ({
  page,
}) => {
  await page.goto("/#/explorer");
  await expect(page.locator(".coverage-panel .js-plotly-plot")).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    page.getByRole("button", { name: "Cabin pressures 0–120 kPa" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText(/tests above 120 kPa are outside/)).toBeVisible();
  await page.getByRole("button", { name: "Full range", exact: true }).click();
  const bubble = page
    .locator(".coverage-panel .scatterlayer .trace .points path.point")
    .first();
  await bubble.scrollIntoViewIfNeeded();
  const bubbleBox = await bubble.boundingBox();
  if (!bubbleBox)
    throw new Error("No plotted bubble was available for selection");
  // Plotly receives pointer events on its interaction layer above the SVG marks.
  await page.mouse.click(
    bubbleBox.x + bubbleBox.width / 2,
    bubbleBox.y + bubbleBox.height / 2,
  );
  await expect(page.getByLabel("Selected tested condition")).toBeVisible();
  expect(
    await page.locator(".condition-selection .selected-study-links a").count(),
  ).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Close selected condition" }).click();
  await expect(page.getByText(/tests above 120 kPa are outside/)).toBeHidden();
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(
    await page
      .locator(".panel")
      .first()
      .evaluate((node) => getComputedStyle(node).backgroundColor),
  ).toBe("rgb(255, 255, 255)");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Switch to dark theme" }),
  ).toBeVisible();
  await expect(page.locator(".coverage-panel .js-plotly-plot")).toBeVisible();
  await page.screenshot({
    path: path.join(artifacts, "coverage-light.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Export data ↗" }).click();
  const exportDialog = page.getByRole("dialog");
  await expect(
    exportDialog.getByRole("button", { name: "Download CSV ↓" }),
  ).toBeEnabled();
  expect(
    await exportDialog.evaluate(
      (node) => getComputedStyle(node).backgroundColor,
    ),
  ).toBe("rgb(255, 255, 255)");
  await page.keyboard.press("Escape");
  const filter = page.getByRole("group", {
    name: "Filter chart by reported outcome",
  });
  await filter.getByRole("button", { name: /^Extinguished/ }).click();
  await expect(
    filter.getByRole("button", { name: /^Extinguished/ }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByText("View accessible chart data", { exact: true }).click();
  const outcomes = await page
    .locator(".chart-table tbody tr td:last-child")
    .allTextContents();
  expect(outcomes.length).toBeGreaterThan(0);
  expect(outcomes.every((outcome) => outcome === "extinguished")).toBe(true);
  await page.getByText("View accessible chart data", { exact: true }).click();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await filter.getByRole("button", { name: /^All outcomes/ }).click();
  await page.screenshot({
    path: path.join(artifacts, "coverage-dark.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await page.getByRole("link", { name: "Ask FireLens", exact: true }).click();
  await page.getByLabel("Search scope").selectOption("PSI-69");
  await page
    .getByLabel("What would you like to understand?")
    .fill("Show PSI-69 tests and compare pressure");
  await page.getByRole("button", { name: "Search evidence ↗" }).click();
  await expect(page.locator(".chat-chart .barlayer")).toBeVisible();
  await page.screenshot({
    path: path.join(artifacts, "ask-light.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 393, height: 852 });
  await page.getByRole("link", { name: "Explorer", exact: true }).click();
  await expect(page.locator(".coverage-panel .js-plotly-plot")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(artifacts, "coverage-light-mobile.png"),
    fullPage: true,
  });
});
