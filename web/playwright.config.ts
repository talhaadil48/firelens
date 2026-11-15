import { defineConfig, devices } from "@playwright/test";

const apiPort = Number(process.env.FIRELENS_E2E_API_PORT ?? 8017);
const webPort = Number(process.env.FIRELENS_E2E_WEB_PORT ?? 4177);
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const webOrigin = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  outputDir: "../artifacts/phase7/browser-results",
  reporter: "list",
  use: { baseURL: webOrigin, trace: "retain-on-failure" },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
      },
    },
  ],
  webServer: [
    {
      command: `uv run --project .. uvicorn api.main:app --app-dir .. --host 127.0.0.1 --port ${apiPort}`,
      url: `${apiOrigin}/meta`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        FIRELENS_MODE: "snapshot",
        LLM_PROVIDER: "offline",
        AZURE_STORAGE_ACCOUNT_URL: "",
        FIRELENS_AZURE_STORAGE_ACCOUNT_URL: "",
        FIRELENS_LIVE_CATALOGUE_CHECK: "false",
        FIRELENS_CORS_ORIGINS: JSON.stringify([webOrigin]),
      },
    },
    {
      command:
        process.env.FIRELENS_E2E_PREVIEW === "1"
          ? `npm run preview -- --host 127.0.0.1 --port ${webPort} --strictPort`
          : `npm run dev -- --host 127.0.0.1 --port ${webPort} --strictPort`,
      url: webOrigin,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        VITE_DATA_MODE: "api",
        VITE_API_BASE_URL: apiOrigin,
      },
    },
  ],
});
