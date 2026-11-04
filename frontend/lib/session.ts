import { createHmac, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE_NAME = "uaib_admin_session";
const SESSION_TTL_SECONDS = 60 * 60 * 8;

function sessionSecret(): string {
  const secret = process.env.DASHBOARD_SESSION_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error("DASHBOARD_SESSION_SECRET must contain at least 32 characters.");
  }
  return secret;
}

export function createSessionToken(): string {
  const payload = Buffer.from(
    JSON.stringify({
      sub: "dashboard-admin",
      exp: Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS
    })
  ).toString("base64url");

  const signature = createHmac("sha256", sessionSecret())
    .update(payload)
    .digest("base64url");

  return `${payload}.${signature}`;
}

export function verifySessionToken(token?: string): boolean {
  if (!token) return false;

  try {
    const [payload, suppliedSignature, extra] = token.split(".");
    if (!payload || !suppliedSignature || extra) return false;

    const expected = createHmac("sha256", sessionSecret())
      .update(payload)
      .digest();
    const actual = Buffer.from(suppliedSignature, "base64url");

    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
      return false;
    }

    const parsed = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as {
      sub?: string;
      exp?: number;
    };

    return parsed.sub === "dashboard-admin" &&
      typeof parsed.exp === "number" &&
      parsed.exp > Math.floor(Date.now() / 1000);
  } catch {
    return false;
  }
}

export function secureCookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict" as const,
    path: "/",
    maxAge: SESSION_TTL_SECONDS
  };
}
