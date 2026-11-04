import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME, verifySessionToken } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ALLOWED_ROOT = "campaigns/content-agency";
const ALLOWED_METHODS = new Set(["GET", "POST"]);

function safePath(segments: string[]): boolean {
  if (segments.length < 3) return false;
  if (segments.slice(0, 2).join("/") !== ALLOWED_ROOT) return false;
  return segments.every((part) => /^[a-zA-Z0-9_-]+$/.test(part));
}

async function proxy(request: NextRequest, pathPromise: Promise<{ path: string[] }>) {
  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!verifySessionToken(token)) {
    return NextResponse.json({ error: "Sign in to access campaign data." }, { status: 401 });
  }

  if (!ALLOWED_METHODS.has(request.method)) {
    return NextResponse.json({ error: "Method not allowed." }, { status: 405 });
  }

  if (request.method === "POST") {
    const origin = request.headers.get("origin");
    if (!origin || origin !== request.nextUrl.origin) {
      return NextResponse.json({ error: "Cross-origin write requests are not allowed." }, { status: 403 });
    }
  }

  const { path } = await pathPromise;
  if (!safePath(path)) {
    return NextResponse.json({ error: "Backend route is not allow-listed." }, { status: 404 });
  }

  const backendUrl = process.env.BACKEND_API_URL?.trim().replace(/\/$/, "");
  const backendKey = process.env.BACKEND_API_KEY;
  if (!backendUrl || !backendKey || !backendUrl.startsWith("https://")) {
    return NextResponse.json({ error: "Backend proxy is not configured." }, { status: 503 });
  }

  const target = new URL(`/v1/${path.join("/")}`, backendUrl);
  target.search = request.nextUrl.search;

  const headers = new Headers({
    "Accept": "application/json",
    "X-API-Key": backendKey
  });

  let body: string | undefined;
  if (request.method === "POST") {
    headers.set("Content-Type", "application/json");
    body = await request.text();
    if (body.length > 20000) {
      return NextResponse.json({ error: "Request body is too large." }, { status: 413 });
    }
  }

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual"
    });
    const responseBody = await upstream.text();
    return new NextResponse(responseBody, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store"
      }
    });
  } catch {
    return NextResponse.json({ error: "Backend API is temporarily unreachable." }, { status: 502 });
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, context.params);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, context.params);
}
