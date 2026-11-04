import { NextRequest, NextResponse } from "next/server";
import { createSessionToken, SESSION_COOKIE_NAME, secureCookieOptions } from "@/lib/session";
import { timingSafeEqual } from "node:crypto";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (!origin || origin !== request.nextUrl.origin) {
    return NextResponse.json({ error: "Cross-origin login is not allowed." }, { status: 403 });
  }

  const configuredPassword = process.env.DASHBOARD_PASSWORD;
  if (!configuredPassword) {
    return NextResponse.json(
      { error: "Dashboard login is not configured on this deployment." },
      { status: 503 }
    );
  }

  let suppliedPassword = "";
  try {
    const body = await request.json() as { password?: unknown };
    suppliedPassword = typeof body.password === "string" ? body.password : "";
  } catch {
    return NextResponse.json({ error: "Invalid request body." }, { status: 400 });
  }

  const supplied = Buffer.from(suppliedPassword);
  const expected = Buffer.from(configuredPassword);
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
    return NextResponse.json({ error: "Incorrect dashboard password." }, { status: 401 });
  }

  try {
    const response = NextResponse.json({ authenticated: true });
    response.cookies.set(SESSION_COOKIE_NAME, createSessionToken(), secureCookieOptions());
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return NextResponse.json({ error: "Dashboard session is not configured." }, { status: 503 });
  }
}
