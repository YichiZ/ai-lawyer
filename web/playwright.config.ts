import { defineConfig, devices } from "@playwright/test";

// End-to-end UI tests. The API runs with AI_FAKE=1 (deterministic model, no Vertex calls) against the dev database,
// on separate ports so they don't collide with `make api` / `make web`.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3001",
    ...devices["Desktop Chrome"],
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8001",
      cwd: "..",
      url: "http://localhost:8001/laws",
      env: { AI_FAKE: "1", REDIS_URL: "redis://localhost:6379/1" }, // db 1: never the dev worker's stream
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npx next dev --port 3001",
      url: "http://localhost:3001",
      env: { API_URL: "http://localhost:8001", NEXT_DIST_DIR: ".next-e2e" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
