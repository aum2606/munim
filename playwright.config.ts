import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "dashboard/e2e",
  use: { baseURL: "http://localhost:5173" },
  projects: [
    {
      name: "mobile",
      use: { ...devices["iPhone SE"], defaultBrowserType: "chromium" },
    },
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: "pnpm --filter @munim/dashboard dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
  },
});
