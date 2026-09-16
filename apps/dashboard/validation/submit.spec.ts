import { expect, test } from "@playwright/test";

import { evidenceEnvelope, gotoDemoAndStartSession, mockSessionCreate, sessionEnvelope } from "./helpers";

async function attachRequiredEvidence(page: import("@playwright/test").Page) {
  await page.route("**/v1/verification-sessions/*/document", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(evidenceEnvelope("DOCUMENT")),
    });
  });
  await page.route("**/v1/verification-sessions/*/selfie", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(evidenceEnvelope("SELFIE")),
    });
  });
  await gotoDemoAndStartSession(page);
  await page.setInputFiles("#document-upload", {
    name: "doc.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("doc"),
  });
  await page.setInputFiles("#selfie-upload", {
    name: "selfie.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("selfie"),
  });
  await expect(page.getByRole("button", { name: /Submit session/ })).toBeEnabled();
}

test.describe("E. Submit", () => {
  test.beforeEach(async ({ page }) => {
    await mockSessionCreate(page);
  });

  test("single click sends exactly one submit request", async ({ page }) => {
    let submitCount = 0;
    await page.route("**/v1/verification-sessions/*/submit", async (route) => {
      submitCount += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sessionEnvelope({ status: "COMPLETED", decision: {
          outcome: "VERIFIED", reason_codes: [], policy: { id: "p1", version: 1, hash: "h1" },
        } })),
      });
    });

    await attachRequiredEvidence(page);
    await page.getByRole("button", { name: "Submit session" }).click();

    await expect(page.getByText("VERIFIED", { exact: true })).toBeVisible();
    expect(submitCount).toBe(1);
  });

  test("double click (same-tick race) sends exactly one submit request", async ({ page }) => {
    let submitCount = 0;
    await page.route("**/v1/verification-sessions/*/submit", async (route) => {
      submitCount += 1;
      await new Promise((resolve) => setTimeout(resolve, 200));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sessionEnvelope({ status: "COMPLETED", decision: {
          outcome: "VERIFIED", reason_codes: [], policy: { id: "p1", version: 1, hash: "h1" },
        } })),
      });
    });

    await attachRequiredEvidence(page);
    // Two click() calls fired in the same synchronous DOM tick --
    // Playwright's own .click() waits for actionability between calls
    // (and would see the button already disabled), so this dispatches
    // both native click events before React's re-render can disable it,
    // matching a genuine double-click race rather than two well-behaved
    // sequential clicks.
    await page
      .getByRole("button", { name: "Submit session" })
      .evaluate((el: HTMLButtonElement) => {
        el.click();
        el.click();
      });

    await expect(page.getByText("VERIFIED", { exact: true })).toBeVisible();
    expect(submitCount).toBe(1);
  });

  test("rapid repeated clicks (same-tick race) send exactly one submit request", async ({ page }) => {
    let submitCount = 0;
    await page.route("**/v1/verification-sessions/*/submit", async (route) => {
      submitCount += 1;
      await new Promise((resolve) => setTimeout(resolve, 300));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sessionEnvelope({ status: "COMPLETED", decision: {
          outcome: "VERIFIED", reason_codes: [], policy: { id: "p1", version: 1, hash: "h1" },
        } })),
      });
    });

    await attachRequiredEvidence(page);
    // Five native click() calls dispatched synchronously in one DOM
    // tick -- a genuine near-simultaneous rapid-click race, all landing
    // before React's first re-render can disable the button. A
    // click({force: true}) loop was tried first and turned out to be
    // misleading here: Chromium's native "disabled controls don't
    // receive click" behavior held even under force, so each forced
    // click only actually landed once the button had already
    // re-enabled itself after the *previous* click's full submit-to-
    // completion cycle finished -- exercising sequential resubmission
    // of an already-completed session, not a same-tick race at all.
    await page
      .getByRole("button", { name: "Submit session" })
      .evaluate((el: HTMLButtonElement) => {
        for (let i = 0; i < 5; i += 1) el.click();
      });

    await expect(page.getByText("VERIFIED", { exact: true })).toBeVisible();
    expect(submitCount).toBe(1);
  });

  test("server rejection surfaces a safe message and allows a fresh retry", async ({ page }) => {
    let submitCount = 0;
    await page.route("**/v1/verification-sessions/*/submit", async (route) => {
      submitCount += 1;
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "SESSION_CONFLICT" }, meta: { request_id: "req_409" } }),
      });
    });

    await attachRequiredEvidence(page);
    await page.getByRole("button", { name: "Submit session" }).click();

    await expect(page.getByText("The verification session changed before this operation completed.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Submit session" })).toBeEnabled();
    expect(submitCount).toBe(1);
  });

  test("network failure during submit surfaces the network-unreachable message", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/submit", async (route) => {
      await route.abort("connectionrefused");
    });

    await attachRequiredEvidence(page);
    await page.getByRole("button", { name: "Submit session" }).click();

    await expect(page.getByText("The verification service could not be reached.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Submit session" })).toBeEnabled();
  });
});
