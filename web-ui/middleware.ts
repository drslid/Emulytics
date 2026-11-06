import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const policy = [
    "default-src 'self'", `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline'", "img-src 'self' data:", "font-src 'self'",
    "connect-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"
  ].join("; ");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}

export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon\\.ico$|apple-touch-icon\\.png$|manifest\\.webmanifest$|icons/|brand/).*)"] };
