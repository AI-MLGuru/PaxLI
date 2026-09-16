import { expect, test } from "@playwright/test";

import { evidenceEnvelope, gotoDemoAndStartSession, mockSessionCreate, sessionEnvelope } from "./helpers";

const CREDENTIAL = "super-secret-demo-credential.token";

test("privacy: a complete flow leaves no credential or raw media in browser-persisted state", async ({ page }) => {
  await mockSessionCreate(page);
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
  await page.route("**/v1/verification-sessions/*/liveness", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(evidenceEnvelope("LIVENESS")),
    });
  });
  await page.route("**/v1/verification-sessions/*/submit", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        sessionEnvelope({
          status: "COMPLETED",
          decision: { outcome: "VERIFIED", reason_codes: ["POLICY:FACE_MATCH_OK"], policy: { id: "p1", version: 1, hash: "h1" } },
        }),
      ),
    });
  });

  await gotoDemoAndStartSession(page, CREDENTIAL);
  await page.setInputFiles("#document-upload", {
    name: "PASSPORT-RAW-DOCUMENT-CONTENT.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("raw-document-bytes"),
  });
  await page.setInputFiles("#selfie-upload", {
    name: "RAW-SELFIE-MEDIA.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("raw-selfie-bytes"),
  });
  await page.setInputFiles("#liveness-upload", [
    { name: "RAW-LIVENESS-FRAME.jpg", mimeType: "image/jpeg", buffer: Buffer.from("raw-liveness-bytes") },
  ]);
  await page.getByRole("button", { name: "Submit session" }).click();
  await expect(page.getByText("VERIFIED", { exact: true })).toBeVisible();

  // localStorage / sessionStorage: this demo never writes to either --
  // the strongest available assertion is that they stay empty, not
  // merely "don't contain the credential."
  const localStorageEntries = await page.evaluate(() => Object.keys(window.localStorage));
  const sessionStorageEntries = await page.evaluate(() => Object.keys(window.sessionStorage));
  expect(localStorageEntries).toEqual([]);
  expect(sessionStorageEntries).toEqual([]);

  // Cookies: never set by this SPA.
  const cookies = await page.context().cookies();
  expect(cookies).toEqual([]);

  // URL never carries the credential.
  expect(page.url()).not.toContain(CREDENTIAL);
  expect(page.url()).not.toContain("secret");

  // DOM (post-upload state) never echoes the credential or raw filenames
  // as anything other than safe attachment labels -- the credential
  // string itself must not appear anywhere in the rendered page.
  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toContain(CREDENTIAL);

  // Diagnostics: safe metadata only, no raw media/credential leakage,
  // even though the SPA state persists in-memory across navigation.
  await page.getByRole("link", { name: "Diagnostics" }).click();
  const diagnosticsText = await page.locator("main").innerText();
  expect(diagnosticsText).not.toContain(CREDENTIAL);
  expect(diagnosticsText).not.toContain("raw-document-bytes");
  expect(diagnosticsText).not.toContain("raw-selfie-bytes");
  expect(diagnosticsText).not.toContain("raw-liveness-bytes");
  // .meta-list is styled `text-transform: uppercase`; innerText() (unlike
  // textContent()) reflects that rendered transform, so compare
  // case-insensitively rather than against the source-code casing.
  expect(diagnosticsText.toLowerCase()).toContain("no secret material and no raw media retention");
});
