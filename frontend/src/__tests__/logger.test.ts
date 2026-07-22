import { describe, it, expect, vi, beforeEach } from "vitest";
import { logger } from "@/lib/logger";

describe("logger", () => {
  let infoCalls: string[] = [];
  let errorCalls: string[] = [];
  let warnCalls: string[] = [];
  let debugCalls: string[] = [];

  beforeEach(() => {
    infoCalls = []; errorCalls = []; warnCalls = []; debugCalls = [];
    console.info = vi.fn((...args: unknown[]) => { infoCalls.push(String(args[0])); });
    console.error = vi.fn((...args: unknown[]) => { errorCalls.push(String(args[0])); });
    console.warn = vi.fn((...args: unknown[]) => { warnCalls.push(String(args[0])); });
    console.debug = vi.fn((...args: unknown[]) => { debugCalls.push(String(args[0])); });
  });

  it("has all four levels", () => {
    for (const level of ["info", "error", "warn", "debug"] as const) {
      expect(typeof logger[level]).toBe("function");
    }
  });

  it("info logs message", () => {
    logger.info({ msg: "test" });
    expect(infoCalls[0]).toBe("test");
  });

  it("error logs message", () => {
    logger.error({ msg: "fail" });
    expect(errorCalls[0]).toBe("fail");
  });

  it("warn logs message", () => {
    logger.warn({ msg: "hmm" });
    expect(warnCalls[0]).toBe("hmm");
  });

  it("debug logs message", () => {
    logger.debug({ msg: "detail" });
    expect(debugCalls[0]).toBe("detail");
  });

  it("includes extra fields as JSON", () => {
    logger.info({ msg: "hello", status: 200 });
    expect(infoCalls[0]).toBe('hello {"status":200}');
  });

  it("omits JSON when no extra fields", () => {
    logger.info({ msg: "simple" });
    expect(infoCalls[0]).toBe("simple");
  });

  it("handles empty object", () => {
    logger.info({});
    expect(infoCalls[0]).toBe("");
  });

  it("handles multiple extra fields", () => {
    logger.info({ msg: "x", a: 1, b: "two" });
    expect(infoCalls[0]).toContain("x {");
    expect(infoCalls[0]).toContain('"a":1');
    expect(infoCalls[0]).toContain('"b":"two"');
  });
});
