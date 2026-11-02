import { NextResponse } from "next/server";
import team from "./manifest.json";

export const dynamic = "force-static";

export function GET() {
  return NextResponse.json(team, {
    headers: { "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400" },
  });
}
