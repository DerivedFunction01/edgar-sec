import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { revisions, runSql, type SqlResult } from "./api";

const SAMPLE: SqlResult = {
  columns: ["n"],
  rows: [{ n: 1 }],
  elapsed_ms: 1,
  truncated: false,
};

let originalFetch: typeof globalThis.fetch;

function mockFetchOnce(handler: () => Response) {
  globalThis.fetch = (async () => handler()) as typeof globalThis.fetch;
}

describe("runSql memory LRU", () => {
  beforeEach(() => {
    revisions.clear();
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("serves a repeat query from the LRU without a second call", async () => {
    let calls = 0;
    mockFetchOnce(() => {
      calls++;
      return new Response(JSON.stringify(SAMPLE), { status: 200 });
    });
    revisions.set("d1", "r1");
    const first = await runSql("d1", "SELECT 1");
    const second = await runSql("d1", "SELECT 1");
    expect(first).toEqual(SAMPLE);
    expect(second).toEqual(SAMPLE);
    expect(calls).toBe(1);
  });

  it("invalidates the cache when the artifact revision changes", async () => {
    let calls = 0;
    mockFetchOnce(() => {
      calls++;
      return new Response(JSON.stringify(SAMPLE), { status: 200 });
    });
    revisions.set("d2", "r1");
    await runSql("d2", "SELECT 1");
    revisions.set("d2", "r2");
    await runSql("d2", "SELECT 1");
    expect(calls).toBe(2);
  });

  it("treats differing queries as distinct cache entries", async () => {
    let calls = 0;
    mockFetchOnce(() => {
      calls++;
      return new Response(JSON.stringify(SAMPLE), { status: 200 });
    });
    revisions.set("d3", "r1");
    await runSql("d3", "SELECT 90");
    await runSql("d3", "SELECT 91");
    expect(calls).toBe(2);
  });
});
