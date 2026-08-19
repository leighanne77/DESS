/**
 * Playwright config for the dess-crm frontend smoke test.
 *
 * Single-browser (chromium) by design — this suite is a smoke test, not
 * comprehensive coverage. It catches UI regressions without needing the
 * real backend running.
 *
 * The test uses `page.route()` to mock every /api/* call, so no backend
 * (FastAPI, Postgres) is required to run `npm run test:e2e`.
 *
 * Written as CommonJS (.cjs) because this workspace's Node (18.17) is
 * older than Playwright's ESM-loader requirement (18.19+). The .spec.ts
 * files can stay TypeScript — Playwright transpiles those via ts-node
 * internally. Bump to .mjs or .ts if Node gets upgraded.
 */
const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Spin up the Vite preview server for the test run. We use `preview`
  // (static build output) rather than `dev` so the test exercises the
  // same bundle CI will ship.
  webServer: {
    command: "npm run build && npm run preview -- --port 4173",
    url: "http://localhost:4173",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
});
