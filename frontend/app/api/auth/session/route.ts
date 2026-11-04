import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME, verifySessionToken } from "@/lib/session";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const authenticated = verifySessionToken(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  return NextResponse.json(
    { authenticated },
    { headers: { "Cache-Control": "no-store" } }
  );
}
