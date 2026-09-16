import { expect, test } from "@playwright/test";

import { evidenceEnvelope, gotoDemoAndStartSession, mockSessionCreate } from "./helpers";

async function trackStopCalls(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    (window as unknown as { __trackStopCalls: number }).__trackStopCalls = 0;
    const originalStop = MediaStreamTrack.prototype.stop;
    MediaStreamTrack.prototype.stop = function (this: MediaStreamTrack, ...args: []) {
      (window as unknown as { __trackStopCalls: number }).__trackStopCalls += 1;
      return originalStop.apply(this, args);
    };
  });
}

async function stopCallCount(page: import("@playwright/test").Page) {
  return page.evaluate(() => (window as unknown as { __trackStopCalls: number }).__trackStopCalls ?? 0);
}

test.describe("C. Selfie", () => {
  test.beforeEach(async ({ page }) => {
    await mockSessionCreate(page);
  });

  test("file upload records the filename as attached", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/selfie", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(evidenceEnvelope("SELFIE")),
      });
    });

    await gotoDemoAndStartSession(page);
    await page.setInputFiles("#selfie-upload", {
      name: "selfie.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from("selfie-bytes"),
    });

    await expect(page.getByText("selfie.jpg")).toBeVisible();
  });

  test("camera: permission granted, capture uploads and stops the stream", async ({ page }) => {
    await trackStopCalls(page);
    await page.route("**/v1/verification-sessions/*/selfie", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(evidenceEnvelope("SELFIE")),
      });
    });

    await gotoDemoAndStartSession(page);
    await page.getByRole("button", { name: "Use camera" }).click();
    await expect(page.locator(".camera-preview")).toBeVisible();

    // Fake device stream needs a moment to report non-zero dimensions
    // before captureCameraSelfie's videoWidth/videoHeight guard passes.
    await expect
      .poll(async () => page.evaluate(() => document.querySelector("video")?.videoWidth ?? 0))
      .toBeGreaterThan(0);

    await page.getByRole("button", { name: "Capture camera selfie" }).click();
    await expect(page.getByText("camera-selfie.jpg")).toBeVisible();
    await expect(page.locator(".camera-preview")).toHaveCount(0);
    expect(await stopCallCount(page)).toBeGreaterThan(0);
  });

  test("camera: cancel stops the stream without uploading", async ({ page }) => {
    await trackStopCalls(page);
    let uploadCalled = false;
    await page.route("**/v1/verification-sessions/*/selfie", async (route) => {
      uploadCalled = true;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(evidenceEnvelope("SELFIE")),
      });
    });

    await gotoDemoAndStartSession(page);
    await page.getByRole("button", { name: "Use camera" }).click();
    await expect(page.locator(".camera-preview")).toBeVisible();

    await page.getByRole("button", { name: "Cancel camera" }).click();
    await expect(page.locator(".camera-preview")).toHaveCount(0);
    expect(uploadCalled).toBe(false);
    expect(await stopCallCount(page)).toBeGreaterThan(0);
  });

  test("camera: permission denied surfaces a recoverable error, no preview", async ({ page }) => {
    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = () =>
        Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
    });

    await gotoDemoAndStartSession(page);
    await page.getByRole("button", { name: "Use camera" }).click();

    await expect(page.getByText("Permission denied")).toBeVisible();
    await expect(page.locator(".camera-preview")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Use camera" })).toBeVisible();
  });

  test("camera: unmounting the demo page while active stops the stream", async ({ page }) => {
    await trackStopCalls(page);
    await gotoDemoAndStartSession(page);
    await page.getByRole("button", { name: "Use camera" }).click();
    await expect(page.locator(".camera-preview")).toBeVisible();

    await page.getByRole("link", { name: "Capabilities" }).click();
    await expect(page).toHaveURL(/\/$/);
    expect(await stopCallCount(page)).toBeGreaterThan(0);
  });
});
