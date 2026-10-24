import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "dashboard/e2e",
  workers: 2,
  use: { baseURL: "http://localhost:5173" },
  projects: [
    {
      name: "mobile",
      use: {
        ...devices["iPhone SE"],
        defaultBrowserType: "chromium",
        viewport: { width: 375, height: 812 },
      },
    },
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: "pnpm --filter @munim/dashboard dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
  },
});
