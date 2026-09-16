import { expect, test } from "@playwright/test";

const SESSION_ID = "11111111-1111-4111-8111-111111111111";

function sessionEnvelope(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      id: SESSION_ID,
      tenant_id: "tenant-smoke",
      external_reference: null,
      status: "CREATED",
      assurance_level: "STANDARD",
      created_at: "2026-09-16T00:00:00Z",
      expires_at: "2026-09-16T01:00:00Z",
      completed_at: null,
      decision: null,
      ...overrides,
    },
    meta: { request_id: "req_smoke" },
  };
}

test("dashboard demo smoke: surface is controllable", async ({ page }) => {
  await page.route("**/v1/verification-sessions", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(sessionEnvelope()),
      });
    } else {
      await route.continue();
    }
  });

  await page.goto("/demo");

  const credentialField = page.locator('input[type="password"]');
  await expect(credentialField).toBeVisible();
  await expect(page.getByRole("button", { name: "Start session" })).toBeVisible();

  await credentialField.fill("smoke-credential.secret");
  await page.getByRole("button", { name: "Start session" }).click();

  // The raw <input type="file"> elements are intentionally
  // `display: none` (.capture-row input in styles.css) -- their
  // associated <label> is the real, visible upload affordance a user
  // interacts with. Present in the DOM either way, so `toBeAttached`
  // on the input plus visibility on its label proves both "the control
  // exists" and "the control is actually usable."
  await expect(page.locator("#document-upload")).toBeAttached();
  await expect(page.getByText("Upload document")).toBeVisible();
  await expect(page.locator("#selfie-upload")).toBeAttached();
  await expect(page.getByText("Capture selfie")).toBeVisible();
  await expect(page.getByRole("button", { name: "Use camera" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Submit session/ })).toBeVisible();
});
