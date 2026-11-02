export default async function handler(req, res) {
  const base = (process.env.BACKEND_API_URL || "").replace(/\/$/, "");
  const key = process.env.BACKEND_API_KEY || "";
  if (!base || !key) return res.status(503).json({ error: "Backend connection is not configured yet." });
  let path;
  if (req.method === "POST") path = "/v1/chat/tasks";
  else if (req.method === "GET" && req.query.health === "1") path = "/health";
  else if (req.method === "GET" && req.query.task_id) {
    const id = String(req.query.task_id).replace(/[^a-f0-9-]/gi, "");
    path = "/v1/chat/tasks/" + id + (req.query.events === "1" ? "/events" : "");
  } else return res.status(400).json({ error: "Unsupported chat request." });
  try {
    const upstream = await fetch(base + path, {
      method: req.method,
      headers: { "X-API-Key": key, ...(req.method === "POST" ? { "Content-Type": "application/json" } : {}) },
      ...(req.method === "POST" ? { body: JSON.stringify(req.body || {}) } : {}),
    });
    const body = await upstream.text();
    res.status(upstream.status);
    res.setHeader("Content-Type", upstream.headers.get("content-type") || "application/json");
    res.setHeader("Cache-Control", "no-store");
    return res.send(body);
  } catch (error) {
    return res.status(502).json({ error: "Could not reach the backend service." });
  }
}
