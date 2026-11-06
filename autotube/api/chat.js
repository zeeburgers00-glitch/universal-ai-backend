export default async function handler(req, res) {
  const base = (process.env.BACKEND_API_URL || "").replace(/\/$/, "");
  const key = process.env.BACKEND_API_KEY || "";
  if (!base || !key) return res.status(503).json({ error: "Backend connection is not configured yet." });

  const headers = { "X-API-Key": key, "Accept": "application/json" };
  const requestJson = async (path, method = "GET", body) => {
    const upstream = await fetch(base + path, {
      method,
      headers: { ...headers, ...(body ? { "Content-Type": "application/json" } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
      cache: "no-store"
    });
    return upstream;
  };

  try {
    if (req.method === "GET" && req.query.health === "1") {
      const upstream = await requestJson("/health");
      const data = await upstream.json();
      return res.status(upstream.status).json({ ...data, backend: upstream.ok ? "reachable" : "unavailable" });
    }

    if (req.method === "POST") {
      const message = typeof req.body?.message === "string" ? req.body.message.trim() : "";
      if (message.length < 3 || message.length > 4000) {
        return res.status(400).json({ error: "Write a command between 3 and 4,000 characters." });
      }
      const upstream = await requestJson("/v1/command", "POST", {
        command: message,
        render: true,
        captions: true,
        seo: true,
        grade: "cinematic",
        caption_style: "bold"
      });
      const data = await upstream.json();
      if (!upstream.ok) return res.status(upstream.status).json({ error: data.detail || data.error || "Video job could not be created." });
      return res.status(202).json({ task_id: data.job_id, status: data.status || "queued" });
    }

    if (req.method === "GET" && req.query.task_id) {
      const id = String(req.query.task_id);
      if (!/^cmd-[a-f0-9]{16}$/i.test(id)) return res.status(400).json({ error: "Invalid job id." });

      if (req.query.video === "1") {
        const upstream = await requestJson("/v1/command/" + id + "/video");
        if (!upstream.ok) {
          const body = await upstream.text();
          return res.status(upstream.status).json({ error: body || "Video is not ready." });
        }
        const bytes = Buffer.from(await upstream.arrayBuffer());
        res.status(200);
        res.setHeader("Content-Type", "video/mp4");
        res.setHeader("Content-Disposition", 'attachment; filename="' + id + '.mp4"');
        res.setHeader("Content-Length", String(bytes.length));
        res.setHeader("Cache-Control", "no-store");
        return res.send(bytes);
      }

      const upstream = await requestJson("/v1/command/" + id);
      const job = await upstream.json();
      if (!upstream.ok) return res.status(upstream.status).json({ error: job.detail || "Could not read video job." });
      const status = job.status === "completed" ? "completed"
        : job.status === "failed" ? "failed"
        : job.status === "planned" ? "planned"
        : "running";
      const message = job.stage || (status === "completed" ? "MP4 render completed" : "Preparing your video");
      const events = [{ stage: "video-render", status: status === "completed" ? "completed" : status === "failed" ? "failed" : "running", message }];
      return res.status(200).json({
        task: {
          status,
          progress: job.progress ?? 0,
          stage: job.stage,
          error_message: job.error || job.hint || null,
          result: status === "completed" ? {
            answer: "Your MP4 is ready. Download it below. This build uses generated scene cards and captions; connect stock-footage and voice services for full production.",
            video_url: "/api/chat?task_id=" + id + "&video=1",
            seo: job.seo,
            plan: job.plan,
            output: job.output
          } : null
        },
        events
      });
    }
    return res.status(400).json({ error: "Unsupported request." });
  } catch {
    return res.status(502).json({ error: "Could not reach the backend service." });
  }
}
