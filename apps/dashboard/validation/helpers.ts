import type { Page } from "@playwright/test";

export const SESSION_ID = "11111111-1111-4111-8111-111111111111";

export function sessionEnvelope(
  overrides: Record<string, unknown> = {},
  metaOverrides: Record<string, unknown> = {},
) {
  return {
    data: {
      id: SESSION_ID,
      tenant_id: "tenant-hostile",
      external_reference: null,
      status: "CREATED",
      assurance_level: "STANDARD",
      created_at: "2026-09-16T00:00:00Z",
      expires_at: "2026-09-16T01:00:00Z",
      completed_at: null,
      decision: null,
      ...overrides,
    },
    meta: { request_id: "req_hostile", ...metaOverrides },
  };
}

export function evidenceEnvelope(
  evidenceType: "DOCUMENT" | "SELFIE" | "LIVENESS",
  overrides: Record<string, unknown> = {},
) {
  return {
    id: `evidence_${evidenceType.toLowerCase()}_${Math.random().toString(36).slice(2)}`,
    session_id: SESSION_ID,
    evidence_type: evidenceType,
    source: "CLIENT",
    checksum: "checksum_test",
    mime_type: "image/jpeg",
    size_bytes: 3,
    metadata: {},
    created_at: "2026-09-16T00:00:00Z",
    retention_until: null,
    ...overrides,
  };
}

export function errorEnvelope(code: string, message = "sensitive-internal-detail") {
  return { error: { code, message }, meta: { request_id: "req_hostile_error" } };
}

/** Mocks POST /v1/verification-sessions only -- callers add their own
 * routes for document/selfie/liveness/submit/GET as each test needs. */
export async function mockSessionCreate(
  page: Page,
  opts: { status?: number; body?: unknown } = {},
) {
  await page.route("**/v1/verification-sessions", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({
      status: opts.status ?? 201,
      contentType: "application/json",
      body: JSON.stringify(opts.body ?? sessionEnvelope()),
    });
  });
}

export async function gotoDemoAndStartSession(page: Page, credential = "hostile-credential.secret") {
  await page.goto("/demo");
  await page.locator('input[type="password"]').fill(credential);
  await page.getByRole("button", { name: "Start session" }).click();
  await page.locator("#document-upload").waitFor({ state: "attached" });
}
