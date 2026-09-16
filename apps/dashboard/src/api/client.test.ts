import { describe, expect, it } from "vitest";

import { PaxliApiClient } from "./client";
import { ApiError } from "./errors";

const session = {
  id: "sess_test",
  tenant_id: "tenant_test",
  external_reference: null,
  status: "CREATED",
  assurance_level: "STANDARD",
  created_at: "2026-09-16T00:00:00Z",
  expires_at: "2026-09-16T01:00:00Z",
  completed_at: null,
  decision: null,
};

const evidence = {
  id: "evidence_test",
  session_id: "sess_test",
  evidence_type: "DOCUMENT",
  source: "CLIENT",
  checksum: "checksum_test",
  mime_type: "application/pdf",
  size_bytes: 3,
  metadata: {},
  created_at: "2026-09-16T00:00:00Z",
  retention_until: null,
};

function response(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("PaxliApiClient", () => {
  it("sends session creation with volatile auth and idempotency metadata", async () => {
    let request: RequestInit | undefined;
    const client = new PaxliApiClient({
      baseUrl: "http://api.test/",
      credential: "credential-id.secret",
      correlationId: "corr_test",
      fetcher: async (_input, init) => {
        request = init;
        return response({ data: session, meta: { request_id: "req_test" } });
      },
    });

    await client.createSession();

    const headers = new Headers(request?.headers);
    expect(request?.method).toBe("POST");
    expect(headers.get("Authorization")).toBe("Bearer credential-id.secret");
    expect(headers.get("X-Correlation-ID")).toBe("corr_test");
    expect(headers.get("X-Request-ID")).toMatch(/^req_/);
    expect(headers.get("Idempotency-Key")).toMatch(/^req_/);
    expect(headers.get("X-Tenant-ID")).toBeNull();
  });

  it("sends media as multipart form data and bounds liveness frames", async () => {
    const requests: RequestInit[] = [];
    const client = new PaxliApiClient({
      baseUrl: "http://api.test",
      credential: "credential-id.secret",
      fetcher: async (_input, init) => {
        if (!init) throw new Error("Request init was not provided.");
        requests.push(init);
        return response({ ...evidence });
      },
    });
    const document = new File(["doc"], "document.pdf", { type: "application/pdf" });

    await client.uploadDocument("sess_test", document);
    expect(requests[0].body).toBeInstanceOf(FormData);
    expect(new Headers(requests[0].headers).get("Content-Type")).toBeNull();
    expect(await (requests[0].body as FormData).get("file")).toBeInstanceOf(File);

    expect(() => client.uploadLiveness("sess_test", [])).toThrowError(/Temporal Liveness Demo requires/);
    expect(() => client.uploadLiveness("sess_test", [document, document, document, document, document, document])).toThrowError(/between 1 and 5 frames/);
  });

  it("normalizes failure responses without retaining the raw body", async () => {
    const client = new PaxliApiClient({
      baseUrl: "http://api.test",
      credential: "credential-id.secret",
      fetcher: async () => response({ error: { code: "SECRET_INTERNAL_DETAIL", message: "sensitive" } }, 503),
    });

    const error = await client.getSession("sess_test").catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ category: "DEPENDENCY", retryable: true, message: "The verification service is temporarily unavailable." });
    expect(String(error)).not.toContain("SECRET_INTERNAL_DETAIL");
    expect(String(error)).not.toContain("sensitive");
  });

  it("rejects malformed successful session responses", async () => {
    const client = new PaxliApiClient({
      baseUrl: "http://api.test",
      credential: "credential-id.secret",
      fetcher: async () => response({ data: { id: "sess_test" }, meta: { request_id: "req_bad" } }),
    });

    await expect(client.getSession("sess_test")).rejects.toMatchObject({ code: "MALFORMED_RESPONSE" });
  });
});