import { describe, it, expect } from "vitest";
import {
  cn,
  formatDateTime,
  formatChartTime,
  formatLatency,
  formatPercent,
  shortId,
} from "@/lib/utils";

describe("cn", () => {
  it("merges class strings", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });
  it("filters falsy values", () => {
    expect(cn("foo", false, undefined, null, "bar")).toBe("foo bar");
  });
  it("handles conditional classes", () => {
    expect(cn("base", true && "on", false && "off")).toBe("base on");
  });
  it("resolves tailwind conflicts", () => {
    expect(cn("px-4 px-8")).toBe("px-8");
  });
  it("returns empty string for no inputs", () => {
    expect(cn()).toBe("");
  });
  it("handles object syntax via clsx", () => {
    expect(cn({ foo: true, bar: false })).toBe("foo");
  });
  it("merges arrays", () => {
    expect(cn(["a", "b"], "c")).toBe("a b c");
  });
});

describe("formatDateTime", () => {
  it("formats valid ISO string", () => {
    expect(formatDateTime("2026-07-22T10:05:33Z")).toBe("2026-07-22 10:05 UTC");
  });
  it("pads single-digit values", () => {
    expect(formatDateTime("2026-01-05T03:07:09Z")).toBe("2026-01-05 03:07 UTC");
  });
  it("handles midnight", () => {
    expect(formatDateTime("2026-01-01T00:00:00Z")).toBe("2026-01-01 00:00 UTC");
  });
  it("returns raw string for invalid date", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
  it("handles end-of-year", () => {
    expect(formatDateTime("2026-12-31T23:59:59Z")).toBe("2026-12-31 23:59 UTC");
  });
});

describe("formatChartTime", () => {
  it("formats compact label", () => {
    expect(formatChartTime("2026-07-22T10:05:33Z")).toBe("07-22 10:05");
  });
  it("handles single-digit month/day", () => {
    expect(formatChartTime("2026-01-01T00:00:00Z")).toBe("01-01 00:00");
  });
  it("returns raw for invalid", () => {
    expect(formatChartTime("invalid")).toBe("invalid");
  });
});

describe("formatLatency", () => {
  it("dash for null", () => { expect(formatLatency(null)).toBe("—"); });
  it("dash for undefined", () => { expect(formatLatency(undefined)).toBe("—"); });
  it("ms under 1000", () => { expect(formatLatency(500)).toBe("500 ms"); });
  it("rounds sub-ms", () => { expect(formatLatency(0.3)).toBe("0 ms"); });
  it("seconds at 1000", () => { expect(formatLatency(1000)).toBe("1.0 s"); });
  it("seconds at 1500", () => { expect(formatLatency(1500)).toBe("1.5 s"); });
  it("large values", () => { expect(formatLatency(10000)).toBe("10.0 s"); });
  it("zero", () => { expect(formatLatency(0)).toBe("0 ms"); });
});

describe("formatPercent", () => {
  it("dash for null", () => { expect(formatPercent(null)).toBe("—"); });
  it("dash for undefined", () => { expect(formatPercent(undefined)).toBe("—"); });
  it("85%", () => { expect(formatPercent(0.85)).toBe("85%"); });
  it("0%", () => { expect(formatPercent(0)).toBe("0%"); });
  it("100%", () => { expect(formatPercent(1)).toBe("100%"); });
  it("rounds 0.999", () => { expect(formatPercent(0.999)).toBe("100%"); });
  it("rounds 0.001", () => { expect(formatPercent(0.001)).toBe("0%"); });
  it("0.5 → 50%", () => { expect(formatPercent(0.5)).toBe("50%"); });
});

describe("shortId", () => {
  it("first 8 chars", () => {
    expect(shortId("019f8787-9609-7ec2-9420-0c1119f3d5ca")).toBe("019f8787");
  });
  it("short string", () => { expect(shortId("abc")).toBe("abc"); });
  it("empty string", () => { expect(shortId("")).toBe(""); });
  it("exactly 8 chars", () => { expect(shortId("12345678")).toBe("12345678"); });
});
