export default async function handler(req, res) {
  const base = (process.env.BACKEND_API_URL || "").replace(/\\/$/, "");
  const key = process.env.BACKEND_API_KEY || "";
  if (!base || !key) return res.status(503).json({ error: "Backend connection is not configured." });

  const method = req.method || "GET";
  if (!["GET", "POST", "DELETE"].includes(method)) {
    res.setHeader("Allow", "GET, POST, DELETE");
    return res.status(405).json({ error: "Method not allowed." });
  }

  const path = method === "GET" ? String(req.query?.path || "") : String(req.body?.path || "");
  const pathname = path.split("?")[0];
  const allowed = [
    /^\\/v1\\/(tools|skills|tools\\/categories|catalog\\/(stats|sources)|providers|models\\/providers|workers\\/status|runtime\\/capabilities|workflows|agents|voice\\/providers|vault\\/status|channels|agent-fleet|youtube\\/team|rea\\/(status|tools)|discover\\/(categories|github))$/,
    /^\\/v1\\/(agents\\/[a-zA-Z0-9_.:-]+\\/run|workflows\\/[a-zA-Z0-9_.:-]+\\/run|vault\\/secrets|voice\\/(tts|clone)|media\\/jobs|youtube\\/publish|rea\\/inspect)$/,
    /^\\/v1\\/vault\\/secrets\\/[A-Z][A-Z0-9_]{1,95}$/
  ];
  if (!pathname.startsWith("/v1/") || pathname.includes("..") || !allowed.some((pattern) => pattern.test(pathname))) {
    return res.status(400).json({ error: "This backend route is not available through the Studio proxy." });
  }

  try {
    const upstream = await fetch(base + path, {
      method,
      headers: {
        "X-API-Key": key,
        "Accept": "application/json",
        ...(method !== "GET" ? { "Content-Type": "application/json" } : {})
      },
      ...(method === "POST" ? { body: JSON.stringify(req.body?.payload || {}) } : {}),
      cache: "no-store"
    });
    const raw = await upstream.text();
    res.status(upstream.status);
    res.setHeader("Content-Type", upstream.headers.get("content-type") || "application/json");
    res.setHeader("Cache-Control", "no-store");
    return res.send(raw);
  } catch {
    return res.status(502).json({ error: "Could not reach the backend service." });
  }
}
