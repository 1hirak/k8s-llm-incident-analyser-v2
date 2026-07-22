import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { NextResponse, NextRequest } from "next/server";
import { middleware, config } from "@/middleware";

describe("middleware", () => {
  it("returns a NextResponse", () => {
    const request = new NextRequest(new URL("http://localhost:3000/"));
    const response = middleware(request);
    expect(response).toBeInstanceOf(NextResponse);
  });

  it("logs request info", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    const request = new NextRequest(new URL("http://localhost:3000/api/health"));
    middleware(request);
    const logged = spy.mock.calls[0]?.[0] as string | undefined;
    expect(logged).toBeTruthy();
    if (logged) {
      const data = JSON.parse(logged);
      expect(data.msg).toBe("request");
      expect(data.method).toBe("GET");
      expect(data.path).toBe("/api/health");
      expect(typeof data.durationMs).toBe("number");
    }
    spy.mockRestore();
  });

  it("has matcher config", () => {
    expect(config).toBeDefined();
    expect(config.matcher).toBe("/:path*");
  });
});
