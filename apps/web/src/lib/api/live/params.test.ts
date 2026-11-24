import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../client";

/** Regression: every client method must supply the path parameters its endpoint declares
 *  (a mismatch surfaced as 'Missing path param "projectId" for projects.uploads.complete'). */
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
});
afterEach(() => vi.unstubAllGlobals());

describe("client path parameters", () => {
  it("never reports a missing path param", async () => {
    const failures: string[] = [];
    for (const [group, methods] of Object.entries(api)) {
      for (const [name, fn] of Object.entries(methods as Record<string, (...a: unknown[]) => Promise<unknown>>)) {
        const args = Array.from({ length: fn.length || 1 }, () => "x");
        try {
          await fn(...args);
        } catch (e) {
          if (e instanceof Error && /Missing path param/.test(e.message)) failures.push(`${group}.${name}: ${e.message}`);
        }
      }
    }
    expect(failures).toEqual([]);
  });
});
