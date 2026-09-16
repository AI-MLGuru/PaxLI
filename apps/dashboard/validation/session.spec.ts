import { expect, test } from "@playwright/test";

import { mockSessionCreate, sessionEnvelope } from "./helpers";

test.describe("A. Session", () => {
  test("valid credential creates a session and reveals the capture surface", async ({ page }) => {
    await mockSessionCreate(page);
    await page.goto("/demo");
    await page.locator('input[type="password"]').fill("valid-credential.secret");
    await page.getByRole("button", { name: "Start session" }).click();

    await expect(page.getByText("11111111-1111-4111-8111-111111111111")).toBeVisible();
    await expect(page.locator("#document-upload")).toBeAttached();
  });

  test("missing credential is rejected client-side without a network call", async ({ page }) => {
    let requested = false;
    await page.route("**/v1/verification-sessions", async (route) => {
      requested = true;
      await route.continue();
    });

    await page.goto("/demo");
    await page.getByRole("button", { name: "Start session" }).click();

    await expect(page.getByText("Enter a temporary demo credential to start a session.")).toBeVisible();
    expect(requested).toBe(false);
  });

  test("invalid credential / 401 surfaces the safe authentication message", async ({ page }) => {
    await page.route("**/v1/verification-sessions", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "INVALID_CREDENTIAL" }, meta: { request_id: "req_401" } }),
      });
    });

    await page.goto("/demo");
    await page.locator('input[type="password"]').fill("bad-credential.secret");
    await page.getByRole("button", { name: "Start session" }).click();

    await expect(page.getByText("Authentication was not accepted.")).toBeVisible();
    // The raw error code must never reach the DOM (safe-error normalization).
    await expect(page.getByText("INVALID_CREDENTIAL")).toHaveCount(0);
    // No session surface must appear on a failed creation.
    await expect(page.locator("#document-upload")).toHaveCount(0);
  });

  test("malformed session response is rejected rather than accepted as a session", async ({ page }) => {
    await page.route("**/v1/verification-sessions", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ data: { id: "sess_only" }, meta: { request_id: "req_bad" } }),
      });
    });

    await page.goto("/demo");
    await page.locator('input[type="password"]').fill("valid-credential.secret");
    await page.getByRole("button", { name: "Start session" }).click();

    await expect(page.getByText("The verification service returned an invalid response.")).toBeVisible();
    await expect(page.locator("#document-upload")).toHaveCount(0);
  });

  test("duplicate session creation attempts each carry their own idempotency key", async ({ page }) => {
    const idempotencyKeys: string[] = [];
    await page.route("**/v1/verification-sessions", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      const key = route.request().headers()["idempotency-key"];
      if (key) idempotencyKeys.push(key);
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(sessionEnvelope()),
      });
    });

    await page.goto("/demo");
    await page.locator('input[type="password"]').fill("valid-credential.secret");
    await page.getByRole("button", { name: "Start session" }).click();
    await expect(page.locator("#document-upload")).toBeAttached();

    // A second, independent session-creation attempt (e.g. Reset -> Start
    // session again) must mint its own idempotency key, never reuse the
    // first -- the UI never asserts idempotent replay semantics itself,
    // that is the server's job; the client's only obligation is to not
    // silently collapse two distinct user-initiated attempts under one key.
    await page.getByRole("button", { name: "Reset" }).click();
    await page.locator('input[type="password"]').fill("valid-credential.secret");
    await page.getByRole("button", { name: "Start session" }).click();
    await expect(page.locator("#document-upload")).toBeAttached();

    expect(idempotencyKeys).toHaveLength(2);
    expect(idempotencyKeys[0]).not.toBe(idempotencyKeys[1]);
  });
});
