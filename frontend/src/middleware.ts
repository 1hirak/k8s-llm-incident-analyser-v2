import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const start = performance.now();
  const { method, nextUrl } = request;

  const response = NextResponse.next();

  const durationMs = Math.round(performance.now() - start);

  console.log(JSON.stringify({
    msg: "request",
    method,
    path: nextUrl.pathname,
    status: response.status,
    durationMs,
  }));

  return response;
}

export const config = {
  matcher: "/:path*",
};
