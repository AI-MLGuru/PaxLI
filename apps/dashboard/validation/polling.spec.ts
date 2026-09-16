import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { evidenceEnvelope, gotoDemoAndStartSession, mockSessionCreate, sessionEnvelope } from "./helpers";

async function attachRequiredEvidence(page: Page) {
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
}

const DECISION_BY_OUTCOME = {
  VERIFIED: { outcome: "VERIFIED", reason_codes: ["POLICY:FACE_MATCH_OK"], policy: { id: "p1", version: 1, hash: "h1" } },
  REJECTED: { outcome: "REJECTED", reason_codes: ["POLICY:FACE_MATCH_FAILED"], policy: { id: "p1", version: 1, hash: "h1" } },
  REVIEW_REQUIRED: { outcome: "REVIEW_REQUIRED", reason_codes: ["POLICY:MANUAL_REVIEW"], policy: { id: "p1", version: 1, hash: "h1" } },
  INCONCLUSIVE: { outcome: "INCONCLUSIVE", reason_codes: ["POLICY:DEFAULT"], policy: { id: "p1", version: 1, hash: "h1" } },
} as const;

/** submit() itself always returns PROCESSING; subsequent GETs walk
 * through `sequence`, holding on the last entry once exhausted. */
async function mockSubmitThenPollSequence(page: Page, sequence: Array<"PROCESSING" | keyof typeof DECISION_BY_OUTCOME>) {
  await page.route("**/v1/verification-sessions/*/submit", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(sessionEnvelope({ status: "PROCESSING", decision: null })),
    });
  });

  let call = 0;
  await page.route(/\/v1\/verification-sessions\/[^/]+$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const step = sequence[Math.min(call, sequence.length - 1)];
    call += 1;
    if (step === "PROCESSING") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sessionEnvelope({ status: "PROCESSING", decision: null })),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          sessionEnvelope({ status: "COMPLETED", decision: DECISION_BY_OUTCOME[step] }),
        ),
      });
    }
  });
}

test.describe("F. Polling", () => {
  test.beforeEach(async ({ page }) => {
    await mockSessionCreate(page);
  });

  for (const outcome of ["VERIFIED", "REJECTED", "REVIEW_REQUIRED", "INCONCLUSIVE"] as const) {
    test(`PROCESSING, PROCESSING, ${outcome} resolves to the server's own terminal outcome`, async ({ page }) => {
      await mockSubmitThenPollSequence(page, ["PROCESSING", "PROCESSING", outcome]);
      await attachRequiredEvidence(page);
      await page.getByRole("button", { name: "Submit session" }).click();

      await expect(page.getByText(outcome, { exact: true })).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText("Local demonstration state only")).toBeVisible();
    });
  }

  test("malformed polling response is rejected, never manufactured into a verdict", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/submit", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sessionEnvelope({ status: "PROCESSING", decision: null })),
      });
    });
    await page.route(/\/v1\/verification-sessions\/[^/]+$/, async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: { id: "sess", status: "COMPLETED" }, meta: { request_id: "req_bad" } }),
      });
    });

    await attachRequiredEvidence(page);
    await page.getByRole("button", { name: "Submit session" }).click();

    await expect(page.getByText("The verification service returned an invalid response.")).toBeVisible({
      timeout: 10_000,
    });
    for (const outcome of ["VERIFIED", "REJECTED", "REVIEW_REQUIRED", "INCONCLUSIVE"]) {
      await expect(page.getByText(outcome, { exact: true })).toHaveCount(0);
    }
  });

  test("polling timeout (all attempts PROCESSING) surfaces a retryable message, never a fabricated verdict", async ({ page }) => {
    await mockSubmitThenPollSequence(page, ["PROCESSING"]);
    await attachRequiredEvidence(page);
    await page.getByRole("button", { name: "Submit session" }).click();

    await expect(
      page.getByText("The verification result is still processing. Refresh to check again."),
    ).toBeVisible({ timeout: 15_000 });
    for (const outcome of ["VERIFIED", "REJECTED", "REVIEW_REQUIRED", "INCONCLUSIVE"]) {
      await expect(page.getByText(outcome, { exact: true })).toHaveCount(0);
    }
  });

  test("network failure mid-poll surfaces the network-unreachable message, never a fabricated verdict", async ({ page }) => {
    await page.route("**/v1/verification-sessions/*/submit", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sessionEnvelope({ status: "PROCESSING", decision: null })),
      });
    });
    let call = 0;
    await page.route(/\/v1\/verification-sessions\/[^/]+$/, async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      call += 1;
      if (call === 1) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(sessionEnvelope({ status: "PROCESSING", decision: null })),
        });
      } else {
        await route.abort("connectionrefused");
      }
    });

    await attachRequiredEvidence(page);
    await page.getByRole("button", { name: "Submit session" }).click();

    await expect(page.getByText("The verification service could not be reached.")).toBeVisible({
      timeout: 10_000,
    });
    for (const outcome of ["VERIFIED", "REJECTED", "REVIEW_REQUIRED", "INCONCLUSIVE"]) {
      await expect(page.getByText(outcome, { exact: true })).toHaveCount(0);
    }
  });
});
