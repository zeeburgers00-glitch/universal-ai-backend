"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AudioLines, CheckCircle2, Copy, Download, Image as ImageIcon, LoaderCircle, LogOut, Play, RefreshCw, Sparkles, Video, WandSparkles } from "lucide-react";

type Model = { id: string; name?: string; description?: string };
type Models = { text: Model[]; image: Model[]; video: Model[]; audio: Model[] };

const API = "https://gen.pollinations.ai";
const AUTH = "https://enter.pollinations.ai";
const DEFAULT_MODELS: Models = {
  text: [{ id: "openai/gpt-5.4-nano" }],
  image: [{ id: "black-forest-labs/flux.1-schnell" }],
  video: [],
  audio: [],
};

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function randomToken(size = 32): string {
  return bytesToBase64Url(crypto.getRandomValues(new Uint8Array(size)));
}

async function pkceChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return bytesToBase64Url(new Uint8Array(digest));
}

function getList(data: unknown): Model[] {
  const raw = Array.isArray(data)
    ? data
    : data && typeof data === "object"
      ? ((data as { data?: unknown[]; models?: unknown[] }).data ?? (data as { models?: unknown[] }).models ?? [])
      : [];
  return raw.flatMap((item) => {
    if (typeof item === "string") return [{ id: item }];
    if (!item || typeof item !== "object") return [];
    const model = item as Record<string, unknown>;
    const id = String(model.id ?? model.name ?? "").trim();
    return id ? [{ id, name: String(model.name ?? ""), description: String(model.description ?? "") }] : [];
  });
}

function safeHttpsUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "https:") throw new Error("Reference media URL must use HTTPS.");
  return url.toString();
}

export default function AIStudio() {
  const [appKey, setAppKey] = useState("");
  const [redirectUri, setRedirectUri] = useState("");
  const [token, setToken] = useState("");
  const [expiresAt, setExpiresAt] = useState(0);
  const [models, setModels] = useState<Models>(DEFAULT_MODELS);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [tab, setTab] = useState<"script" | "thumbnail" | "avatar" | "voice">("avatar");
  const [textModel, setTextModel] = useState(DEFAULT_MODELS.text[0].id);
  const [imageModel, setImageModel] = useState(DEFAULT_MODELS.image[0].id);
  const [videoModel, setVideoModel] = useState("");
  const [audioModel, setAudioModel] = useState("");
  const [budget, setBudget] = useState("5");
  const [topic, setTopic] = useState("");
  const [script, setScript] = useState("");
  const [imagePrompt, setImagePrompt] = useState("");
  const [thumbnailUrl, setThumbnailUrl] = useState("");
  const [videoPrompt, setVideoPrompt] = useState("");
  const [referenceImageUrl, setReferenceImageUrl] = useState("");
  const [referenceAudioUrl, setReferenceAudioUrl] = useState("");
  const [videoDuration, setVideoDuration] = useState("5");
  const [videoUrl, setVideoUrl] = useState("");
  const [speechText, setSpeechText] = useState("");
  const [speechVoice, setSpeechVoice] = useState("nova");
  const [audioUrl, setAudioUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [isError, setIsError] = useState(false);

  const connected = Boolean(token) && expiresAt > Date.now();

  const say = useCallback((message: string, error = false) => {
    setNotice(message);
    setIsError(error);
  }, []);

  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true);
    try {
      const paths = ["text", "image", "video", "audio"] as const;
      const values = await Promise.all(paths.map(async (family) => {
        const response = await fetch(API + "/" + family + "/models", { cache: "no-store" });
        if (!response.ok) return [];
        return getList(await response.json());
      }));
      const next = { text: values[0], image: values[1], video: values[2], audio: values[3] };
      setModels(next);
      if (next.text[0]) setTextModel(next.text[0].id);
      if (next.image[0]) setImageModel(next.image[0].id);
      if (next.video[0]) setVideoModel(next.video[0].id);
      if (next.audio[0]) setAudioModel(next.audio[0].id);
    } catch {
      say("Could not refresh the live model catalogue. You can still use the documented default text and image models.", true);
    } finally {
      setCatalogLoading(false);
    }
  }, [say]);

  useEffect(() => {
    setRedirectUri(window.location.origin + "/ai/connect");
    const storedKey = sessionStorage.getItem("pollinations_app_key") || "";
    const storedToken = sessionStorage.getItem("pollinations_access_token") || "";
    const storedExpiry = Number(sessionStorage.getItem("pollinations_expires_at") || 0);
    if (storedKey) setAppKey(storedKey);
    if (storedToken && storedExpiry > Date.now()) {
      setToken(storedToken);
      setExpiresAt(storedExpiry);
    } else {
      sessionStorage.removeItem("pollinations_access_token");
      sessionStorage.removeItem("pollinations_expires_at");
    }
    void loadCatalog();

    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const returnedState = params.get("state");
    const error = params.get("error");
    if (error) {
      say("AI credit authorization was cancelled or denied: " + error, true);
      window.history.replaceState({}, "", window.location.pathname);
      return;
    }
    if (!code) return;

    const expectedState = sessionStorage.getItem("pollinations_oauth_state") || "";
    const verifier = sessionStorage.getItem("pollinations_pkce_verifier") || "";
    const clientId = sessionStorage.getItem("pollinations_pending_app_key") || "";
    const callback = sessionStorage.getItem("pollinations_redirect_uri") || window.location.origin + "/";
    if (!returnedState || !expectedState || returnedState !== expectedState || !verifier || !clientId) {
      say("AI credit authorization could not be verified. Reconnect and try again.", true);
      window.history.replaceState({}, "", window.location.pathname);
      return;
    }
    sessionStorage.removeItem("pollinations_oauth_state");
    sessionStorage.removeItem("pollinations_pkce_verifier");
    sessionStorage.removeItem("pollinations_pending_app_key");

    void (async () => {
      setBusy("connect");
      try {
        const response = await fetch(AUTH + "/api/oauth/token", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            grant_type: "authorization_code",
            code,
            client_id: clientId,
            redirect_uri: callback,
            code_verifier: verifier,
          }),
        });
        const data = await response.json();
        if (!response.ok || !data.access_token) throw new Error(data.error_description || data.error || "Token exchange failed.");
        const expiry = Date.now() + Math.max(60, Number(data.expires_in || 604800)) * 1000;
        sessionStorage.setItem("pollinations_app_key", clientId);
        sessionStorage.setItem("pollinations_access_token", data.access_token);
        sessionStorage.setItem("pollinations_expires_at", String(expiry));
        setAppKey(clientId);
        setToken(data.access_token);
        setExpiresAt(expiry);
        say("AI credits connected. Generation requests now spend only within the budget you approved.");
      } catch (e) {
        say(e instanceof Error ? e.message : "AI credit connection failed.", true);
      } finally {
        setBusy("");
        window.history.replaceState({}, "", window.location.pathname);
      }
    })();
  }, [loadCatalog, say]);

  const connect = async () => {
    const clientId = appKey.trim();
    if (!/^pk_[A-Za-z0-9_-]{8,}$/.test(clientId)) {
      say("Paste your Pollinations App Key (pk_...) first. Create it in the Pollinations dashboard with this exact redirect URI: " + redirectUri, true);
      return;
    }
    setBusy("connect");
    try {
      const verifier = randomToken(48);
      const state = randomToken(24);
      const challenge = await pkceChallenge(verifier);
      sessionStorage.setItem("pollinations_oauth_state", state);
      sessionStorage.setItem("pollinations_pkce_verifier", verifier);
      sessionStorage.setItem("pollinations_pending_app_key", clientId);
      sessionStorage.setItem("pollinations_redirect_uri", redirectUri);
      sessionStorage.setItem("pollinations_app_key", clientId);
      const url = new URL(AUTH + "/authorize");
      url.searchParams.set("response_type", "code");
      url.searchParams.set("client_id", clientId);
      url.searchParams.set("redirect_uri", redirectUri);
      url.searchParams.set("scope", "usage");
      url.searchParams.set("state", state);
      url.searchParams.set("code_challenge", challenge);
      url.searchParams.set("code_challenge_method", "S256");
      url.searchParams.set("models", "text,image,video,audio");
      url.searchParams.set("budget", String(Math.max(1, Number(budget) || 5)));
      url.searchParams.set("expiry", "7");
      window.location.assign(url.toString());
    } catch (e) {
      setBusy("");
      say(e instanceof Error ? e.message : "Could not start AI credit authorization.", true);
    }
  };

  const disconnect = () => {
    for (const key of ["pollinations_access_token", "pollinations_expires_at", "pollinations_oauth_state", "pollinations_pkce_verifier", "pollinations_pending_app_key"]) {
      sessionStorage.removeItem(key);
    }
    setToken("");
    setExpiresAt(0);
    say("AI credits disconnected from this browser session.");
  };

  const aiRequest = async (path: string, body: unknown, responseType: "json" | "blob" = "json") => {
    if (!connected) throw new Error("Connect your AI credits first.");
    const response = await fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error?.message || data.message || "AI provider request failed (HTTP " + response.status + "). Check your Pollen budget and model access.");
    }
    return responseType === "blob" ? response.blob() : response.json();
  };

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
    } catch (e) {
      say(e instanceof Error ? e.message : "Generation failed.", true);
    } finally {
      setBusy("");
    }
  };

  const generateScript = () => run("script", async () => {
    if (topic.trim().length < 6) throw new Error("Enter a video topic first.");
    const data = await aiRequest("/v1/chat/completions", {
      model: textModel,
      temperature: 0.7,
      max_tokens: 1800,
      messages: [
        { role: "system", content: "You are a professional YouTube showrunner. Write an original, engaging, fact-aware narration script. Use a powerful opening hook, natural spoken language, clear scene breaks and a concise call to action. Never invent statistics or sources. Return the script and a short scene plan." },
        { role: "user", content: "Topic: " + topic + "\nChannel niche: " + "YouTube creator\nLanguage: English\nFormat: Long-form explainer." },
      ],
    });
    setScript(String(data.choices?.[0]?.message?.content || ""));
    say("Script generated.");
  });

  const generateThumbnail = () => run("image", async () => {
    if (imagePrompt.trim().length < 8) throw new Error("Describe the thumbnail you want.");
    const data = await aiRequest("/v1/images/generations", {
      model: imageModel,
      prompt: imagePrompt + ", professional YouTube thumbnail, strong focal point, cinematic lighting, clean composition, mobile readable, 16:9",
      n: 1,
      size: "1280x720",
      response_format: "url",
    });
    const url = data.data?.[0]?.url || (data.data?.[0]?.b64_json ? "data:image/png;base64," + data.data[0].b64_json : "");
    if (!url) throw new Error("The image model returned no thumbnail URL.");
    setThumbnailUrl(url);
    say("Thumbnail generated.");
  });

  const generateVideo = () => run("video", async () => {
    if (!videoModel) throw new Error("No video model is available in the live catalogue yet.");
    if (videoPrompt.trim().length < 8) throw new Error("Describe the video scene.");
    const url = new URL(API + "/video/" + encodeURIComponent(videoPrompt));
    url.searchParams.set("model", videoModel);
    url.searchParams.set("duration", String(Math.min(10, Math.max(3, Number(videoDuration) || 5))));
    if (referenceImageUrl.trim()) url.searchParams.set("image", safeHttpsUrl(referenceImageUrl.trim()));
    if (referenceAudioUrl.trim()) url.searchParams.set("reference_audios", safeHttpsUrl(referenceAudioUrl.trim()));
    const response = await fetch(url.toString(), { headers: { Authorization: "Bearer " + token } });
    if (!response.ok) {
      const body = await response.text();
      throw new Error("Video generation failed (HTTP " + response.status + "): " + body.slice(0, 240));
    }
    const type = response.headers.get("content-type") || "";
    if (type.startsWith("video/") || type.includes("octet-stream")) {
      const blob = await response.blob();
      if (!blob.size) throw new Error("Video provider returned an empty file.");
      setVideoUrl(URL.createObjectURL(blob));
    } else {
      const data = await response.json();
      const urlValue = data.data?.[0]?.url || data.url;
      if (!urlValue) throw new Error("Video model returned no playable MP4 URL.");
      setVideoUrl(String(urlValue));
    }
    say("AI video clip generated. Save it before leaving this page.");
  });

  const generateSpeech = () => run("audio", async () => {
    if (!audioModel) throw new Error("No speech model is available in the live catalogue yet.");
    if (speechText.trim().length < 2) throw new Error("Enter the narration text first.");
    const blob = await aiRequest("/v1/audio/speech", {
      model: audioModel,
      input: speechText,
      voice: speechVoice,
      response_format: "mp3",
    }, "blob") as Blob;
    if (!blob.size) throw new Error("The speech model returned an empty audio file.");
    setAudioUrl(URL.createObjectURL(blob));
    say("Voice-over generated.");
  });

  const tabButton = (value: typeof tab, label: string, icon: ReactNode) => (
    <button key={value} onClick={() => setTab(value)} className={"nav " + (tab === value ? "active" : "")}>{icon}{label}</button>
  );

  const modelSelect = (value: string, onChange: (v: string) => void, list: Model[], placeholder: string) => (
    <select className="w-full rounded-lg border border-line bg-panel p-3 text-sm" value={value} onChange={(e) => onChange(e.target.value)}>
      {!list.length && <option value="">{catalogLoading ? "Loading live models…" : placeholder}</option>}
      {list.map((model) => <option key={model.id} value={model.id}>{model.id}</option>)}
    </select>
  );

  return (
    <div className="space-y-5">
      {notice && <div className={"notice " + (isError ? "error" : "success")}>{notice}<button className="float-right" onClick={() => setNotice("")}>×</button></div>}
      <section className="panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="eyebrow">AI GENERATION PROVIDER</div>
            <h2 className="mt-2">Connect your AI credits</h2>
            <p className="muted mt-2">Use your own Pollinations balance. This app does not store your secret key or use a shared leaked key.</p>
          </div>
          <span className={"status " + (connected ? "ok" : "")}>{connected ? "Connected" : "Not connected"}</span>
        </div>
        {!connected ? (
          <div className="mt-4 grid gap-3 md:grid-cols-[1fr_130px_auto]">
            <div className="field">
              <label>Pollinations App Key (pk_...)</label>
              <input value={appKey} onChange={(e) => setAppKey(e.target.value)} placeholder="pk_..." autoComplete="off" />
              <small className="muted">Create an App Key and register this exact redirect URI:</small>
              <code className="block break-all text-xs text-violet-300">{redirectUri}</code>
            </div>
            <div className="field">
              <label>Consent budget (Pollen)</label>
              <input type="number" min="1" max="1000" value={budget} onChange={(e) => setBudget(e.target.value)} />
            </div>
            <div className="flex items-end"><button className="btn w-full" onClick={connect} disabled={busy === "connect"}>{busy === "connect" ? <LoaderCircle size={15} className="animate-spin" /> : <CheckCircle2 size={15} />} Connect AI credits</button></div>
          </div>
        ) : (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="muted">Connected for this browser tab/session. Authorized key expires {new Date(expiresAt).toLocaleString()}.</p>
            <button className="btn secondary" onClick={disconnect}><LogOut size={14} /> Disconnect</button>
          </div>
        )}
        <p className="muted mt-3">Generation spends Pollen from the budget you approve on the provider's consent screen. Usage and model prices are controlled by Pollinations; this app does not promise free generation.</p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <a className="text-violet-300 underline" href="https://enter.pollinations.ai/keys" target="_blank" rel="noreferrer">Create App Key</a>
          <a className="text-violet-300 underline" href="https://gen.pollinations.ai/" target="_blank" rel="noreferrer">Model catalogue and pricing</a>
          <button className="text-violet-300 underline" onClick={loadCatalog} disabled={catalogLoading}><RefreshCw size={12} className="inline" /> Refresh models</button>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-[210px_1fr]">
        <nav className="panel flex gap-1 overflow-x-auto lg:flex-col">
          {tabButton("avatar", "AI Video / Avatar", <Video size={16} />)}
          {tabButton("script", "Script Writer", <WandSparkles size={16} />)}
          {tabButton("thumbnail", "Thumbnail Studio", <ImageIcon size={16} />)}
          {tabButton("voice", "AI Voice", <AudioLines size={16} />)}
        </nav>
        <section className="panel min-w-0">
          {tab === "script" && <>
            <h2>AI Script Writer</h2><p className="muted mt-2">Create an original narration draft with an opening hook and scene structure.</p>
            <div className="field mt-4"><label>Video topic</label><textarea value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Example: Why the deepest ocean is full of life..." /></div>
            <div className="flex flex-wrap items-end gap-3"><div className="field min-w-[240px] flex-1"><label>Text model</label>{modelSelect(textModel, setTextModel, models.text, "No text models listed")}</div><button className="btn" onClick={generateScript} disabled={!connected || busy === "script"}>{busy === "script" ? <LoaderCircle size={14} className="animate-spin" /> : <Sparkles size={14} />} Generate script</button></div>
            <textarea className="mt-4 min-h-72 w-full rounded-lg border border-line bg-panel p-3 text-sm" value={script} onChange={(e) => setScript(e.target.value)} placeholder="Your generated script will appear here..." />
            <button className="btn secondary mt-2" onClick={() => navigator.clipboard.writeText(script)} disabled={!script}><Copy size={14} /> Copy script</button>
          </>}

          {tab === "thumbnail" && <>
            <h2>AI Thumbnail Studio</h2><p className="muted mt-2">Generate a 16:9 thumbnail image from a prompt. Review claims and rights before use.</p>
            <div className="field mt-4"><label>Thumbnail concept</label><textarea value={imagePrompt} onChange={(e) => setImagePrompt(e.target.value)} placeholder="A dramatic underwater explorer facing a huge mysterious creature..." /></div>
            <div className="flex flex-wrap items-end gap-3"><div className="field min-w-[240px] flex-1"><label>Image model</label>{modelSelect(imageModel, setImageModel, models.image, "No image models listed")}</div><button className="btn" onClick={generateThumbnail} disabled={!connected || busy === "image"}>{busy === "image" ? <LoaderCircle size={14} className="animate-spin" /> : <ImageIcon size={14} />} Generate thumbnail</button></div>
            {thumbnailUrl && <div className="mt-4"><img src={thumbnailUrl} alt="Generated YouTube thumbnail" className="max-h-[480px] w-full rounded-xl border border-line object-contain" /><a className="btn secondary mt-3 inline-flex" href={thumbnailUrl} target="_blank" rel="noreferrer"><Download size={14} /> Open / save thumbnail</a></div>}
          </>}

          {tab === "avatar" && <>
            <h2>AI Video / Avatar Studio</h2><p className="muted mt-2">Generate a short AI video clip. Supply a public HTTPS image or audio reference for models that support those inputs.</p>
            <div className="field mt-4"><label>Video prompt</label><textarea value={videoPrompt} onChange={(e) => setVideoPrompt(e.target.value)} placeholder="A friendly presenter speaking directly to camera in a modern studio, natural facial motion, expressive gestures, cinematic lighting..." /></div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="field"><label>Video model</label>{modelSelect(videoModel, setVideoModel, models.video, "No video models listed in the live catalogue")}</div>
              <div className="field"><label>Clip duration (seconds)</label><select value={videoDuration} onChange={(e) => setVideoDuration(e.target.value)} className="w-full rounded-lg border border-line bg-panel p-3 text-sm"><option value="3">3 seconds</option><option value="5">5 seconds</option><option value="8">8 seconds</option><option value="10">10 seconds</option></select></div>
              <div className="field"><label>Reference image URL (optional)</label><input value={referenceImageUrl} onChange={(e) => setReferenceImageUrl(e.target.value)} placeholder="https://.../avatar.png" /></div>
              <div className="field"><label>Reference audio URL (optional)</label><input value={referenceAudioUrl} onChange={(e) => setReferenceAudioUrl(e.target.value)} placeholder="https://.../voice.mp3" /></div>
            </div>
            <button className="btn mt-3" onClick={generateVideo} disabled={!connected || busy === "video" || !videoModel}>{busy === "video" ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} />} Generate video clip</button>
            {videoUrl && <div className="mt-4"><video src={videoUrl} controls playsInline className="max-h-[540px] w-full rounded-xl border border-line bg-black" /><a className="btn secondary mt-3 inline-flex" href={videoUrl} download="ai-video-clip.mp4"><Download size={14} /> Save video clip</a></div>}
            <p className="muted mt-3">Video model capabilities and maximum length vary. Reference audio is not guaranteed to produce lip-sync; check the selected model's supported inputs.</p>
          </>}

          {tab === "voice" && <>
            <h2>AI Voice Studio</h2><p className="muted mt-2">Generate an MP3 voice-over from your script.</p>
            <div className="field mt-4"><label>Narration text</label><textarea value={speechText} onChange={(e) => setSpeechText(e.target.value || script)} placeholder="Paste your narration here..." /></div>
            <div className="grid gap-3 md:grid-cols-[1fr_180px_auto]">
              <div className="field"><label>Speech model</label>{modelSelect(audioModel, setAudioModel, models.audio, "No audio models listed")}</div>
              <div className="field"><label>Voice</label><input value={speechVoice} onChange={(e) => setSpeechVoice(e.target.value)} placeholder="nova" /></div>
              <div className="flex items-end"><button className="btn" onClick={generateSpeech} disabled={!connected || busy === "audio" || !audioModel}>{busy === "audio" ? <LoaderCircle size={14} className="animate-spin" /> : <AudioLines size={14} />} Generate voice</button></div>
            </div>
            {audioUrl && <div className="mt-4"><audio src={audioUrl} controls className="w-full" /><a className="btn secondary mt-3 inline-flex" href={audioUrl} download="voiceover.mp3"><Download size={14} /> Save voice-over</a></div>}
          </>}
        </section>
      </div>
    </div>
  );
}
