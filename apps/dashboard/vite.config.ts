import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { configDefaults } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  test: {
    // validation/ holds Playwright specs (browser hostile matrix), not
    // Vitest unit tests -- both tools default to the same *.spec.ts
    // glob, so without this exclude Vitest tries (and fails) to load
    // Playwright's test.describe() outside a Playwright runner.
    exclude: [...configDefaults.exclude, "validation/**"],
  },
});
