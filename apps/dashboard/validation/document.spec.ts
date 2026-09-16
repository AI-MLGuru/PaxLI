import { expect, test } from "@playwright/test";

import { evidenceEnvelope, gotoDemoAndStartSession, mockSessionCreate } from "./helpers";

test.describe("B. Document", () => {
  test.beforeEach(async ({ page }) => {
    await mockSessionCreate(page);
  });

  test("valid document upload records the filename as attached", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/document", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(evidenceEnvelope("DOCUMENT")),
      });
    });

    await gotoDemoAndStartSession(page);
    await page.setInputFiles("#document-upload", {
      name: "passport.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from("document-bytes"),
    });

    await expect(page.getByText("passport.jpg")).toBeVisible();
    await expect(page.getByText("attached")).toBeVisible();
  });

  test("missing document keeps submit disabled even with a selfie attached", async ({ page }) => {
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

    await expect(page.getByRole("button", { name: /Submit session/ })).toBeDisabled();
  });

  test("upload rejection (422) surfaces a safe message and does not mark the document attached", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/document", async (route) => {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "UNSUPPORTED_MEDIA" }, meta: { request_id: "req_422" } }),
      });
    });

    await gotoDemoAndStartSession(page);
    await page.setInputFiles("#document-upload", {
      name: "corrupt.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from("bad-bytes"),
    });

    await expect(page.getByText("The request or media could not be accepted.")).toBeVisible();
    const documentRow = page.locator("dl.meta-list > div").filter({ hasText: "Document" });
    await expect(documentRow.locator("dd")).toHaveText("pending");
  });

  test("network failure during document upload surfaces the network-unreachable message", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/document", async (route) => {
      await route.abort("connectionrefused");
    });

    await gotoDemoAndStartSession(page);
    await page.setInputFiles("#document-upload", {
      name: "passport.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from("document-bytes"),
    });

    await expect(page.getByText("The verification service could not be reached.")).toBeVisible();
  });
});
