export default async function handler(req, res) {
  const base = (process.env.BACKEND_API_URL || "").replace(/\/$/, "");
  const key = process.env.BACKEND_API_KEY || "";
  if (!base || !key) return res.status(503).json({ error: "Backend connection is not configured yet." });
  const headers = { "X-API-Key": key, "Accept": "application/json" };
  const requestJson = async (path, method = "GET", body) => fetch(base + path, {
    method, headers: { ...headers, ...(body ? { "Content-Type": "application/json" } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}), cache: "no-store"
  });
  try {
    if (req.method === "GET" && req.query.health === "1") {
      const upstream = await requestJson("/health");
      const data = await upstream.json();
      return res.status(upstream.status).json({ ...data, backend: upstream.ok ? "reachable" : "unavailable" });
    }
    if (req.method === "POST") {
      const message = typeof req.body?.message === "string" ? req.body.message.trim() : "";
      if (message.length < 3 || message.length > 4000) return res.status(400).json({ error: "Write a command between 3 and 4,000 characters." });
      const requestedMode = req.body?.mode === "video" || req.body?.mode === "chat" ? req.body.mode : "";
      const videoIntent = /\b(video|shorts?|mp4|render|montage|b-roll|footage)\b/i.test(message)
        && /\b(create|make|generate|render|produce|build|bana|bnao|tayyar|video)\b/i.test(message);
      const mode = requestedMode || (videoIntent ? "video" : "chat");
      if (mode === "chat") {
        const upstream = await requestJson("/v1/chat/tasks", "POST", {
          message, conversation_id: typeof req.body?.conversation_id === "string" ? req.body.conversation_id : undefined
        });
        const data = await upstream.json();
        if (!upstream.ok) return res.status(upstream.status).json({
          error: data.detail || data.error || "Chat task could not be queued.",
          hint: "Durable chat requires Supabase, Redis/Celery and an active AI model provider."
        });
        return res.status(202).json({ task_id: data.task_id, conversation_id: data.conversation_id, kind: "chat", status: data.status || "queued" });
      }
      const upstream = await requestJson("/v1/command", "POST", {
        command: message, render: true, captions: true, seo: true, grade: "cinematic", caption_style: "bold"
      });
      const data = await upstream.json();
      if (!upstream.ok) return res.status(upstream.status).json({ error: data.detail || data.error || "Video job could not be created." });
      return res.status(202).json({ task_id: data.job_id, kind: "video", status: data.status || "queued" });
    }
    if (req.method === "GET" && req.query.task_id) {
      const id = String(req.query.task_id);
      const kind = req.query.kind === "chat" ? "chat" : "video";
      if (kind === "chat") {
        if (!/^[0-9a-f-]{36}$/i.test(id)) return res.status(400).json({ error: "Invalid chat task id." });
        const upstream = await requestJson("/v1/chat/tasks/" + id);
        const data = await upstream.json();
        if (!upstream.ok) return res.status(upstream.status).json({ error: data.detail || "Could not read chat task." });
        const run = data.task || {};
        const status = run.status === "completed" ? "completed" : run.status === "failed" ? "failed" : run.status === "queued" ? "queued" : "running";
        const events = (data.events || []).map(event => ({
          stage: event.stage, agent_id: event.agent_id, status: event.status, message: event.message, created_at: event.created_at
        }));
        return res.status(200).json({
          task: {
            status, progress: status === "completed" ? 100 : status === "queued" ? 5 : 50,
            stage: events.length ? events[events.length - 1].message : "AI team is starting",
            error_message: run.error_message || null,
            result: status === "completed" ? (run.result || { answer: "Your request is complete." }) : null
          }, events
        });
      }
      if (!/^cmd-[a-f0-9]{16}$/i.test(id)) return res.status(400).json({ error: "Invalid video job id." });
      if (req.query.video === "1") {
        const upstream = await requestJson("/v1/command/" + id + "/video");
        if (!upstream.ok) return res.status(upstream.status).json({ error: await upstream.text() || "Video is not ready." });
        const bytes = Buffer.from(await upstream.arrayBuffer());
        res.status(200); res.setHeader("Content-Type", "video/mp4");
        res.setHeader("Content-Disposition", 'attachment; filename="' + id + '.mp4"');
        res.setHeader("Content-Length", String(bytes.length)); res.setHeader("Cache-Control", "no-store");
        return res.send(bytes);
      }
      const upstream = await requestJson("/v1/command/" + id);
      const job = await upstream.json();
      if (!upstream.ok) return res.status(upstream.status).json({ error: job.detail || "Could not read video job." });
      const status = job.status === "completed" ? "completed" : job.status === "failed" ? "failed" : job.status === "planned" ? "planned" : "running";
      const events = [{ stage: "video-render", status: status === "completed" ? "completed" : status === "failed" ? "failed" : "running", message: job.stage || "Preparing your video" }];
      let videoUrl = "/api/chat?task_id=" + id + "&video=1";
      const stockFootage = job.stock_footage || null;
      if (status === "completed") {
        try {
          const signed = await requestJson("/v1/command/" + id + "/download-token");
          if (signed.ok) {
            const token = await signed.json();
            if (typeof token.path === "string" && token.path.startsWith("/v1/command/" + id + "/download?")) videoUrl = base + token.path;
          }
        } catch {}
      }
      return res.status(200).json({
        task: {
          status, progress: job.progress ?? 0, stage: job.stage, error_message: job.error || job.hint || null,
          result: status === "completed" ? {
            answer: stockFootage?.provider === "pexels"
              ? "Your MP4 is ready with Pexels stock footage and captions. Download it below."
              : "Your MP4 is ready. Download it below. Check the job's stock_footage details for the media source used.",
            video_url: videoUrl, seo: job.seo, plan: job.plan, output: job.output,
            stock_footage: stockFootage, media_warnings: job.media_warnings || []
          } : null
        }, events
      });
    }
    return res.status(400).json({ error: "Unsupported request." });
  } catch {
    return res.status(502).json({ error: "Could not reach the backend service." });
  }
}