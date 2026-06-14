const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./e2e",
  outputDir: "test-results",
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:8091",
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    colorScheme: "light",
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  webServer: {
    command: "RTLS_PORT=8091 RTLS_DATABASE=/tmp/rtls-playwright.db python3 server.py",
    url: "http://127.0.0.1:8091/api/regions",
    reuseExistingServer: !process.env.CI,
    timeout: 15000
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } }
    },
    {
      name: "mobile-chromium",
      use: { ...devices["iPhone 13"], browserName: "chromium" }
    }
  ]
});
