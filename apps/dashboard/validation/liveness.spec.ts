import { expect, test } from "@playwright/test";

import { evidenceEnvelope, gotoDemoAndStartSession, mockSessionCreate } from "./helpers";

function frame(name: string) {
  return { name, mimeType: "image/jpeg", buffer: Buffer.from(`frame-${name}`) };
}

test.describe("D. Temporal Liveness Demo", () => {
  test.beforeEach(async ({ page }) => {
    await mockSessionCreate(page);
  });

  test("0 frames: no upload call, state unchanged", async ({ page }) => {
    let called = false;
    await page.route("**/v1/verification-sessions/*/liveness", async (route) => {
      called = true;
      await route.continue();
    });

    await gotoDemoAndStartSession(page);
    await page.setInputFiles("#liveness-upload", []);
    await page.waitForTimeout(300);

    expect(called).toBe(false);
    await expect(page.getByText("Optional frames (max 5)")).toBeVisible();
  });

  test("1 frame: uploads and reports one frame", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/liveness", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(evidenceEnvelope("LIVENESS")),
      });
    });

    await gotoDemoAndStartSession(page);
    await page.setInputFiles("#liveness-upload", [frame("a")]);

    await expect(page.getByText("1 frame(s)")).toBeVisible();
  });

  test("5 frames: uploads and reports five frames", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/liveness", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(evidenceEnvelope("LIVENESS")),
      });
    });

    await gotoDemoAndStartSession(page);
    await page.setInputFiles("#liveness-upload", ["a", "b", "c", "d", "e"].map(frame));

    await expect(page.getByText("5 frame(s)")).toBeVisible();
  });

  test("6 frames: the UI bounds the upload to 5, never sends 6", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/liveness", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(evidenceEnvelope("LIVENESS")),
      });
    });

    await gotoDemoAndStartSession(page);
    await page.setInputFiles("#liveness-upload", ["a", "b", "c", "d", "e", "f"].map(frame));

    await expect(page.getByText("5 frame(s)")).toBeVisible();
    await expect(page.getByText("6 frame(s)")).toHaveCount(0);
  });

  test("partial failure surfaces a safe message and leaves the frame count unset", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/liveness", async (route) => {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "INVALID_FRAME" }, meta: { request_id: "req_liveness_fail" } }),
      });
    });

    await gotoDemoAndStartSession(page);
    await page.setInputFiles("#liveness-upload", [frame("a"), frame("b")]);

    await expect(page.getByText("The request or media could not be accepted.")).toBeVisible();
    await expect(page.getByText("not supplied")).toBeVisible();
  });
});
