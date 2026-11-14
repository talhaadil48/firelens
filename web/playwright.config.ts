import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  outputDir: "../artifacts/phase7/browser-results",
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:4177", trace: "retain-on-failure" },
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
      command:
        "uv run --project .. uvicorn api.main:app --app-dir .. --host 127.0.0.1 --port 8017",
      url: "http://127.0.0.1:8017/meta",
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        FIRELENS_MODE: "snapshot",
        LLM_PROVIDER: "offline",
        AZURE_STORAGE_ACCOUNT_URL: "",
        FIRELENS_AZURE_STORAGE_ACCOUNT_URL: "",
        FIRELENS_LIVE_CATALOGUE_CHECK: "false",
        FIRELENS_CORS_ORIGINS: '["http://127.0.0.1:4177"]',
      },
    },
    {
      command:
        process.env.FIRELENS_E2E_PREVIEW === "1"
          ? "npm run preview -- --host 127.0.0.1 --port 4177 --strictPort"
          : "npm run dev -- --host 127.0.0.1 --port 4177 --strictPort",
      url: "http://127.0.0.1:4177",
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        VITE_DATA_MODE: "api",
        VITE_API_BASE_URL: "http://127.0.0.1:8017",
      },
    },
  ],
});
