import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { streamJob } from "@/lib/sse";

describe("streamJob", () => {
  let closeSpy = vi.fn();
  const originalEventSource = globalThis.EventSource;

  beforeEach(() => {
    closeSpy = vi.fn();
    globalThis.EventSource = vi.fn().mockImplementation(function(this: unknown, url: string) {
      return { url, readyState: 1, close: closeSpy, addEventListener: vi.fn(), onerror: null };
    }) as unknown as typeof EventSource;
  });

  afterEach(() => { globalThis.EventSource = originalEventSource; });

  it("returns unsubscribe function", () => {
    const unsub = streamJob("test-job", () => {});
    expect(typeof unsub).toBe("function");
    unsub();
    expect(closeSpy).toHaveBeenCalled();
  });

  it("constructs correct URL with job ID", () => {
    streamJob("test-job", () => {});
    expect(globalThis.EventSource).toHaveBeenCalledWith(expect.stringContaining("/api/jobs/test-job/stream"));
  });

  it("calls addEventListener for stage, done, failed", () => {
    streamJob("test-job", () => {});
    const es = (globalThis.EventSource as unknown as { mock: { results: { value: { addEventListener: ReturnType<typeof vi.fn> } }[] } }).mock.results[0]?.value;
    expect(es.addEventListener).toHaveBeenCalledWith("stage", expect.any(Function));
    expect(es.addEventListener).toHaveBeenCalledWith("done", expect.any(Function));
    expect(es.addEventListener).toHaveBeenCalledWith("failed", expect.any(Function));
  });

  it("close on unsubscribe calls source.close", () => {
    const unsub = streamJob("test-job", () => {});
    unsub();
    expect(closeSpy).toHaveBeenCalledTimes(1);
  });
});
