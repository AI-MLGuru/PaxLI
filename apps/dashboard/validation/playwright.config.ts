import { defineConfig, devices } from "@playwright/test";

/**
 * Disposable Playwright harness for Slice L browser validation.
 * Runs against the native Windows Chromium build (this repo's WSL
 * environment is missing libnspr4.so and other native browser deps --
 * see BD-001.20 continuation notes), driven by Windows-native Node.
 */
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  outputDir: "../test-results",
  use: {
    baseURL: "http://localhost:5173",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    permissions: ["camera"],
    launchOptions: {
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    cwd: "..",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 30_000,
    // Same-origin as the dev server -- avoids a cross-origin CORS
    // preflight the mocked routes below don't answer for. Real backend
    // integration (task step 22) uses the actual configured base URL,
    // not this mocked harness.
    env: { VITE_PAXLI_API_BASE_URL: "http://localhost:5173" },
  },
});
