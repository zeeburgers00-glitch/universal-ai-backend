"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AudioLines, CheckCircle2, Copy, Download, Film, Image as ImageIcon, LoaderCircle, LogOut, Play, RefreshCw, Search, Sparkles, Trash2, UploadCloud, Video, WandSparkles } from "lucide-react";

type Model = { id: string; name?: string; description?: string; video_capabilities?: string[]; input_modalities?: string[]; min_duration?: number; max_duration?: number; paid_only?: boolean; pricing?: Record<string, string> };
type Models = { text: Model[]; image: Model[]; video: Model[]; audio: Model[] };
type GeneratedClip = { id: string; url: string; blob: Blob; seconds: number; format: "longform" | "shorts"; prompt: string };
type CaptionCue = { start: number; end: number; text: string };

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
    return id ? [{
      id,
      name: String(model.name ?? model.title ?? ""),
      description: String(model.description ?? ""),
      video_capabilities: Array.isArray(model.video_capabilities) ? model.video_capabilities.map(String) : [],
      input_modalities: Array.isArray(model.input_modalities) ? model.input_modalities.map(String) : [],
      min_duration: Number(model.min_duration ?? 0) || undefined,
      max_duration: Number(model.max_duration ?? 0) || undefined,
      paid_only: Boolean(model.paid_only),
      pricing: model.pricing && typeof model.pricing === "object" ? model.pricing as Record<string, string> : undefined,
    }] : [];
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
  const [tab, setTab] = useState<"script" | "seo" | "thumbnail" | "avatar" | "voice" | "editor">("avatar");
  const [textModel, setTextModel] = useState(DEFAULT_MODELS.text[0].id);
  const [imageModel, setImageModel] = useState(DEFAULT_MODELS.image[0].id);
  const [videoModel, setVideoModel] = useState("");
  const [audioModel, setAudioModel] = useState("");
  const [budget, setBudget] = useState("5");
  const [topic, setTopic] = useState("");
  const [script, setScript] = useState("");
  const [seoPack, setSeoPack] = useState("");
  const [imagePrompt, setImagePrompt] = useState("");
  const [thumbnailUrl, setThumbnailUrl] = useState("");
  const [videoPrompt, setVideoPrompt] = useState("");
  const [referenceImageUrl, setReferenceImageUrl] = useState("");
  const [referenceImageFile, setReferenceImageFile] = useState<File | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [generatedClips, setGeneratedClips] = useState<GeneratedClip[]>([]);
  const [captionCues, setCaptionCues] = useState<CaptionCue[]>([]);
  const [finalVideoUrl, setFinalVideoUrl] = useState("");
  const [renderProgress, setRenderProgress] = useState(0);
  const [shareReferenceMedia, setShareReferenceMedia] = useState(false);
  const [referenceAudioUrl, setReferenceAudioUrl] = useState("");
  const [videoDuration, setVideoDuration] = useState("5");
  const [videoFormat, setVideoFormat] = useState<"longform" | "shorts">("longform");
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
      const audioDrivenVideo = next.video.find((model) => model.video_capabilities?.includes("reference_audios"));
      if (audioDrivenVideo) setVideoModel(audioDrivenVideo.id);
      else if (next.video[0]) setVideoModel(next.video[0].id);
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

  const uploadReferenceMedia = async (blob: Blob, filename: string): Promise<string> => {
    if (!connected) throw new Error("Connect your AI credits first.");
    if (!shareReferenceMedia) throw new Error("Confirm the public-media notice before uploading a reference file.");
    const form = new FormData();
    form.append("file", blob, filename);
    const response = await fetch("https://media.pollinations.ai/upload", {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
      body: form,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.url) throw new Error(data.error?.message || data.message || "Media upload failed.");
    return safeHttpsUrl(String(data.url));
  };

  const publishVoiceReference = () => run("upload-audio", async () => {
    if (!audioBlob) throw new Error("Generate a voice-over first.");
    const url = await uploadReferenceMedia(audioBlob, "voice-reference.mp3");
    setReferenceAudioUrl(url);
    say("Voice reference uploaded. The video tab can now use this public audio URL for models that support audio-driven video.");
  });

  const publishAvatarReference = () => run("upload-image", async () => {
    if (!referenceImageFile) throw new Error("Choose an avatar image file first.");
    const url = await uploadReferenceMedia(referenceImageFile, referenceImageFile.name || "avatar-reference.png");
    setReferenceImageUrl(url);
    say("Avatar image uploaded. Choose a video model that supports image-reference input.");
  });

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

  const generateSeo = () => run("seo", async () => {
    if (topic.trim().length < 6) throw new Error("Enter a video topic first.");
    const data = await aiRequest("/v1/chat/completions", {
      model: textModel,
      temperature: 0.35,
      max_tokens: 1200,
      messages: [
        { role: "system", content: "You are a careful YouTube SEO specialist. Create an evidence-aware metadata package for the exact video described. Return: one recommended title plus two alternatives (all <=100 characters), primary keyword, supporting keyword cluster, search intent, natural description, concise tags, relevant hashtags, chapters only if timestamps exist in supplied material, and pinned comment. Never invent search volume, trend growth, channel analytics, statistics or sources. Avoid keyword stuffing and clickbait unrelated to the content." },
        { role: "user", content: "Topic: " + topic + "\nScript / video context:\n" + script.slice(0, 12000) },
      ],
    });
    setSeoPack(String(data.choices?.[0]?.message?.content || ""));
    say("SEO metadata package generated.");
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
    if (generatedClips.length >= 20) throw new Error("This browser editor supports up to 20 scenes per project.");
    const selectedModel = models.video.find((model) => model.id === videoModel);
    const requestedSeconds = Number(videoDuration) || 5;
    const minSeconds = selectedModel?.min_duration || 3;
    const maxSeconds = selectedModel?.max_duration || 10;
    const duration = Math.min(maxSeconds, Math.max(minSeconds, requestedSeconds));
    const formatPrompt = videoFormat === "shorts"
      ? "Vertical 9:16 YouTube Shorts framing, clear central subject, safe caption margins. "
      : "Landscape 16:9 composition for a long-form YouTube scene. ";
    const avatarPrompt = referenceAudioUrl.trim()
      ? " Use the supplied reference audio as the speaking performance and synchronize visible mouth movement where this model supports audio-driven generation."
      : "";
    const url = new URL(API + "/video/" + encodeURIComponent(formatPrompt + videoPrompt + avatarPrompt));
    url.searchParams.set("model", videoModel);
    url.searchParams.set("duration", String(duration));
    url.searchParams.set("aspectRatio", videoFormat === "shorts" ? "9:16" : "16:9");
    if (referenceImageUrl.trim()) {
      const ref = safeHttpsUrl(referenceImageUrl.trim());
      if (selectedModel?.video_capabilities?.includes("start_frame")) url.searchParams.set("image", ref);
      else if (selectedModel?.video_capabilities?.includes("reference_images")) url.searchParams.set("reference_images", ref);
      else if (selectedModel?.input_modalities?.includes("image")) url.searchParams.set("image", ref);
      else throw new Error("The selected video model does not advertise image-reference support. Choose a compatible model or remove the reference image.");
    }
    if (referenceAudioUrl.trim()) {
      if (!selectedModel?.video_capabilities?.includes("reference_audios")) throw new Error("The selected video model does not advertise audio-reference support. Choose a model marked as audio-driven in the catalogue.");
      url.searchParams.set("reference_audios", safeHttpsUrl(referenceAudioUrl.trim()));
    }

    const headers = { Authorization: "Bearer " + token, Prefer: "respond-async" };
    let response = await fetch(url.toString(), { headers });
    let reportedDuration = duration;
    let blob: Blob;

    if (response.status === 202) {
      const submitted = await response.json();
      const jobId = String(submitted.id || "");
      if (!jobId) throw new Error("Video provider accepted the request without returning a job ID.");
      say("Video generation queued. Waiting for the rendered scene…");
      let completed = false;
      for (let attempt = 0; attempt < 240; attempt++) {
        await new Promise((resolve) => window.setTimeout(resolve, 5000));
        const statusResponse = await fetch(API + "/v1/jobs/" + encodeURIComponent(jobId), { headers: { Authorization: "Bearer " + token } });
        const status = await statusResponse.json().catch(() => ({}));
        if (!statusResponse.ok) throw new Error(status.error?.message || "Could not check the video job status.");
        if (status.status === "failed") throw new Error(status.error?.message || "The video model failed this generation.");
        if (status.status === "succeeded") {
          const resultResponse = await fetch(API + "/v1/jobs/" + encodeURIComponent(jobId) + "/result", { headers: { Authorization: "Bearer " + token } });
          if (!resultResponse.ok) throw new Error("The completed video job did not return a downloadable result.");
          const resultType = resultResponse.headers.get("content-type") || "";
          if (resultType.startsWith("video/") || resultType.includes("octet-stream")) {
            blob = await resultResponse.blob();
          } else {
            const resultData = await resultResponse.json();
            const resultUrl = resultData.data?.[0]?.url || resultData.url || resultData.result_url;
            if (!resultUrl) throw new Error("The completed video job returned no media URL.");
            const asset = await fetch(safeHttpsUrl(String(resultUrl)));
            if (!asset.ok) throw new Error("Could not download the generated video asset.");
            blob = await asset.blob();
            reportedDuration = Number(resultData.usage?.duration || duration);
          }
          completed = true;
          break;
        }
      }
      if (!completed) throw new Error("Video generation is still running after 20 minutes. Check your provider job history before retrying.");
    } else {
      if (!response.ok) {
        const body = await response.text();
        throw new Error("Video generation failed (HTTP " + response.status + "): " + body.slice(0, 240));
      }
      const type = response.headers.get("content-type") || "";
      if (type.startsWith("video/") || type.includes("octet-stream")) {
        blob = await response.blob();
      } else {
        const data = await response.json();
        const urlValue = data.data?.[0]?.url || data.url;
        if (!urlValue) throw new Error("Video model returned no playable MP4 URL.");
        const asset = await fetch(safeHttpsUrl(String(urlValue)));
        if (!asset.ok) throw new Error("Could not download the generated video asset.");
        blob = await asset.blob();
        reportedDuration = Number(data.usage?.duration || data.data?.[0]?.usage?.duration || duration);
      }
    }

    if (!blob.size) throw new Error("Video provider returned an empty file.");
    if (blob.size > 20 * 1024 * 1024) throw new Error("Generated video exceeds the provider's 20 MB response limit.");
    if (!(blob.type.startsWith("video/") || blob.type === "application/octet-stream")) throw new Error("Generated asset is not a recognizable video file.");
    const objectUrl = URL.createObjectURL(blob);
    setVideoUrl(objectUrl);
    setGeneratedClips((previous) => [...previous, {
      id: crypto.randomUUID(),
      url: objectUrl,
      blob,
      seconds: Math.max(1, reportedDuration),
      format: videoFormat,
      prompt: videoPrompt.trim(),
    }]);
    say("Video scene generated and added to your timeline.");
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
    setAudioBlob(blob);
    setAudioUrl(URL.createObjectURL(blob));
    say("Voice-over generated.");
  });

  const transcribeAudio = () => run("captions", async () => {
    if (!audioBlob) throw new Error("Generate a voice-over before creating captions.");
    const form = new FormData();
    form.append("file", audioBlob, "narration.mp3");
    form.append("model", "openai/whisper-large-v3");
    form.append("response_format", "verbose_json");
    form.append("timestamp_granularities[]", "word");
    const response = await fetch(API + "/v1/audio/transcriptions", {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
      body: form,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error?.message || data.message || "Whisper transcription failed.");
    const words = Array.isArray(data.words) ? data.words : [];
    const segments = Array.isArray(data.segments) ? data.segments : [];
    const cues: CaptionCue[] = words.length
      ? words.flatMap((item: Record<string, unknown>) => {
          const start = Number(item.start);
          const end = Number(item.end);
          const text = String(item.word || item.text || "").trim();
          return text && Number.isFinite(start) && Number.isFinite(end) && end > start ? [{ start, end, text }] : [];
        })
      : segments.flatMap((item: Record<string, unknown>) => {
          const start = Number(item.start);
          const end = Number(item.end);
          const text = String(item.text || "").trim();
          return text && Number.isFinite(start) && Number.isFinite(end) && end > start ? [{ start, end, text }] : [];
        });
    if (!cues.length) throw new Error("Whisper returned no timestamped captions for this audio.");
    setCaptionCues(cues);
    say("Whisper created " + cues.length + " timestamped caption cues.");
  });

  const removeClip = (id: string) => {
    setGeneratedClips((previous) => {
      const removed = previous.find((clip) => clip.id === id);
      if (removed) URL.revokeObjectURL(removed.url);
      return previous.filter((clip) => clip.id !== id);
    });
  };

  const renderTimeline = () => run("render", async () => {
    if (!generatedClips.length) throw new Error("Generate at least one video scene before rendering.");
    if (typeof MediaRecorder === "undefined" || !HTMLCanvasElement.prototype.captureStream) {
      throw new Error("This browser does not support canvas video recording. Use a recent Chrome or Edge browser.");
    }
    if (!audioBlob) throw new Error("Generate a narration voice-over before rendering the final video.");
    if (!captionCues.length) throw new Error("Generate timestamped Whisper captions before rendering the final video.");
    const audioContext = new AudioContext();
    let recorder: MediaRecorder | null = null;
    let stream: MediaStream | null = null;
    const canvas = document.createElement("canvas");
    const isShort = videoFormat === "shorts";
    canvas.width = isShort ? 1080 : 1920;
    canvas.height = isShort ? 1920 : 1080;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Could not create the video rendering canvas.");

    try {
      const audioBuffer = await audioContext.decodeAudioData(await audioBlob.arrayBuffer());
      const sceneSeconds = generatedClips.reduce((sum, clip) => sum + Math.max(1, clip.seconds), 0);
      const totalSeconds = Math.max(sceneSeconds, audioBuffer.duration);
      if (totalSeconds > 300) throw new Error("The browser editor currently caps a render at five minutes. Split longer videos into separate parts.");
      const videoStream = canvas.captureStream(30);
      const audioDestination = audioContext.createMediaStreamDestination();
      stream = new MediaStream([...videoStream.getVideoTracks(), ...audioDestination.stream.getAudioTracks()]);
      const mimeTypes = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"];
      const mimeType = mimeTypes.find((type) => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw new Error("This browser does not provide a supported WebM recording format.");
      recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 8_000_000, audioBitsPerSecond: 192_000 });
      const chunks: BlobPart[] = [];
      const stopped = new Promise<void>((resolve, reject) => {
        if (!recorder) return reject(new Error("Recorder was not initialized."));
        recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
        recorder.onerror = () => reject(new Error("Browser video recorder failed."));
        recorder.onstop = () => resolve();
      });
      await audioContext.resume();
      const narration = audioContext.createBufferSource();
      narration.buffer = audioBuffer;
      narration.connect(audioDestination);
      recorder.start(1000);
      narration.start();

      let elapsed = 0;
      while (elapsed < totalSeconds) {
        for (const clip of generatedClips) {
          if (elapsed >= totalSeconds) break;
          const video = document.createElement("video");
          video.src = clip.url;
          video.muted = true;
          video.playsInline = true;
          video.preload = "auto";
          await new Promise<void>((resolve, reject) => {
            video.onloadeddata = () => resolve();
            video.onerror = () => reject(new Error("A scene video could not be decoded by this browser."));
            video.load();
          });
          const clipLength = Math.max(1, Math.min(clip.seconds, Number.isFinite(video.duration) ? video.duration : clip.seconds));
          await video.play();
          const clipStart = elapsed;
          const clipEnd = Math.min(totalSeconds, clipStart + clipLength);

          while (elapsed < clipEnd) {
            ctx.fillStyle = "#090d18";
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            const sourceWidth = video.videoWidth || canvas.width;
            const sourceHeight = video.videoHeight || canvas.height;
            const scale = Math.max(canvas.width / sourceWidth, canvas.height / sourceHeight);
            const drawWidth = sourceWidth * scale;
            const drawHeight = sourceHeight * scale;
            ctx.drawImage(video, (canvas.width - drawWidth) / 2, (canvas.height - drawHeight) / 2, drawWidth, drawHeight);

            const localSeconds = Math.max(0, video.currentTime);
            const cue = captionCues.find((item) => elapsed >= item.start && elapsed <= item.end);
            if (cue) {
              const fontSize = Math.round(canvas.width * 0.034);
              ctx.font = "700 " + fontSize + "px Arial, sans-serif";
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              const maxWidth = canvas.width * 0.84;
              const wordsInCue = cue.text.split(/\s+/);
              const lines: string[] = [];
              let line = "";
              for (const word of wordsInCue) {
                const next = line ? line + " " + word : word;
                if (ctx.measureText(next).width > maxWidth && line) {
                  lines.push(line);
                  line = word;
                } else line = next;
              }
              if (line) lines.push(line);
              const lineHeight = fontSize * 1.25;
              const boxHeight = lines.length * lineHeight + fontSize;
              const boxY = canvas.height - boxHeight - canvas.height * 0.07;
              ctx.fillStyle = "rgba(0,0,0,0.68)";
              ctx.fillRect(canvas.width * 0.07, boxY, canvas.width * 0.86, boxHeight);
              ctx.fillStyle = "#ffffff";
              lines.forEach((text, index) => ctx.fillText(text, canvas.width / 2, boxY + fontSize * 0.7 + index * lineHeight, maxWidth));
            }

            elapsed = clipStart + localSeconds;
            setRenderProgress(Math.min(99, Math.round((elapsed / totalSeconds) * 100)));
            await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
          }
          video.pause();
          video.removeAttribute("src");
          video.load();
          elapsed = clipEnd;
        }
      }

      await new Promise((resolve) => window.setTimeout(resolve, 250));
      const stopPromise = stopped;
      recorder.stop();
      await stopPromise;
      const finalBlob = new Blob(chunks, { type: mimeType });
      if (!finalBlob.size) throw new Error("Browser rendering finished without creating a video file.");
      const outputUrl = URL.createObjectURL(finalBlob);
      setFinalVideoUrl(outputUrl);
      setRenderProgress(100);
      say("Final video rendered with narration and timestamped captions. Download the WebM file below.");
    } finally {
      if (recorder && recorder.state !== "inactive") {
        try { recorder.stop(); } catch {}
      }
      stream?.getTracks().forEach((track) => track.stop());
      await audioContext.close().catch(() => undefined);
    }
  });

  const tabButton = (value: typeof tab, label: string, icon: ReactNode) => (
    <button key={value} onClick={() => setTab(value)} className={"nav " + (tab === value ? "active" : "")}>{icon}{label}</button>
  );

  const modelSelect = (value: string, onChange: (v: string) => void, list: Model[], placeholder: string) => (
    <select className="w-full rounded-lg border border-line bg-panel p-3 text-sm" value={value} onChange={(e) => onChange(e.target.value)}>
      {!list.length && <option value="">{catalogLoading ? "Loading live models…" : placeholder}</option>}
      {list.map((model) => <option key={model.id} value={model.id}>{model.id}{model.video_capabilities?.includes("reference_audios") ? " · audio-driven" : ""}{model.paid_only ? " · paid Pollen" : ""}</option>)}
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
          {tabButton("seo", "YouTube SEO", <Search size={16} />)}
          {tabButton("thumbnail", "Thumbnail Studio", <ImageIcon size={16} />)}
          {tabButton("voice", "AI Voice", <AudioLines size={16} />)}
          {tabButton("editor", "Video Editor", <Film size={16} />)}
        </nav>
        <section className="panel min-w-0">
          {tab === "script" && <>
            <h2>AI Script Writer</h2><p className="muted mt-2">Create an original narration draft with an opening hook and scene structure.</p>
            <div className="field mt-4"><label>Video topic</label><textarea value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Example: Why the deepest ocean is full of life..." /></div>
            <div className="flex flex-wrap items-end gap-3"><div className="field min-w-[240px] flex-1"><label>Text model</label>{modelSelect(textModel, setTextModel, models.text, "No text models listed")}</div><button className="btn" onClick={generateScript} disabled={!connected || busy === "script"}>{busy === "script" ? <LoaderCircle size={14} className="animate-spin" /> : <Sparkles size={14} />} Generate script</button></div>
            <textarea className="mt-4 min-h-72 w-full rounded-lg border border-line bg-panel p-3 text-sm" value={script} onChange={(e) => setScript(e.target.value)} placeholder="Your generated script will appear here..." />
            <button className="btn secondary mt-2" onClick={() => navigator.clipboard.writeText(script)} disabled={!script}><Copy size={14} /> Copy script</button>
          </>}

          {tab === "seo" && <>
            <h2>YouTube SEO Specialist</h2><p className="muted mt-2">Create search-aware metadata from the topic and actual script, without invented ranking claims.</p>
            <div className="field mt-4"><label>Video topic</label><input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="What is this video about?" /></div>
            <div className="field"><label>Script or final video summary (optional)</label><textarea value={script} onChange={(e) => setScript(e.target.value)} placeholder="Paste the script so titles and keywords accurately match the video..." /></div>
            <div className="flex flex-wrap items-end gap-3"><div className="field min-w-[240px] flex-1"><label>Text model</label>{modelSelect(textModel, setTextModel, models.text, "No text models listed")}</div><button className="btn" onClick={generateSeo} disabled={!connected || busy === "seo"}>{busy === "seo" ? <LoaderCircle size={14} className="animate-spin" /> : <Search size={14} />} Generate SEO package</button></div>
            <textarea className="mt-4 min-h-72 w-full rounded-lg border border-line bg-panel p-3 text-sm" value={seoPack} onChange={(e) => setSeoPack(e.target.value)} placeholder="Title options, description, keywords, tags and hashtags will appear here..." />
            <button className="btn secondary mt-2" onClick={() => navigator.clipboard.writeText(seoPack)} disabled={!seoPack}><Copy size={14} /> Copy SEO package</button>
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
            <div className="callout mt-3"><label className="flex items-center gap-2"><input type="checkbox" checked={shareReferenceMedia} onChange={(e) => setShareReferenceMedia(e.target.checked)} /> I authorize uploading my selected avatar/voice reference to a public media URL</label><p className="mt-2">Anyone who has the resulting URL may be able to access the file. Use only your own media or material you have permission to share. Leave unchecked to use an already-public HTTPS URL instead.</p></div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="field"><label>Video model</label>{modelSelect(videoModel, setVideoModel, models.video, "No video models listed in the live catalogue")}</div>
              <div className="field"><label>Video format</label><select value={videoFormat} onChange={(e) => setVideoFormat(e.target.value as "longform" | "shorts")} className="w-full rounded-lg border border-line bg-panel p-3 text-sm"><option value="longform">Long-form scene · 16:9</option><option value="shorts">Shorts scene · 9:16</option></select></div>
              <div className="field"><label>Clip duration (seconds)</label><select value={videoDuration} onChange={(e) => setVideoDuration(e.target.value)} className="w-full rounded-lg border border-line bg-panel p-3 text-sm"><option value="3">3 seconds</option><option value="5">5 seconds</option><option value="8">8 seconds</option><option value="10">10 seconds</option></select></div>
              <div className="field"><label>Reference image URL (optional)</label><input value={referenceImageUrl} onChange={(e) => setReferenceImageUrl(e.target.value)} placeholder="https://.../avatar.png" /><label className="mt-2">Or choose an avatar photo</label><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setReferenceImageFile(e.target.files?.[0] || null)} /><button className="btn secondary mt-2" onClick={publishAvatarReference} disabled={!connected || !referenceImageFile || busy === "upload-image"}>{busy === "upload-image" ? <LoaderCircle size={14} className="animate-spin" /> : <UploadCloud size={14} />} Upload avatar photo for video</button></div>
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
            {audioUrl && <div className="mt-4"><audio src={audioUrl} controls className="w-full" /><div className="mt-3 flex flex-wrap gap-2"><a className="btn secondary inline-flex" href={audioUrl} download="voiceover.mp3"><Download size={14} /> Save voice-over</a><button className="btn secondary" onClick={publishVoiceReference} disabled={!shareReferenceMedia || busy === "upload-audio"}>{busy === "upload-audio" ? <LoaderCircle size={14} className="animate-spin" /> : <UploadCloud size={14} />} Upload as avatar audio reference</button><button className="btn secondary" onClick={transcribeAudio} disabled={!connected || busy === "captions"}>{busy === "captions" ? <LoaderCircle size={14} className="animate-spin" /> : <Film size={14} />} Generate Whisper captions</button></div><p className="muted mt-2">{captionCues.length ? captionCues.length + " timestamped caption cues ready." : "Captions have not been transcribed yet."}</p></div>}
          {tab === "editor" && <>
            <h2>Final Video Editor</h2>
            <p className="muted mt-2">Combine your generated scenes into one video. Add a narration track and generate Whisper timestamps before rendering to burn captions into the picture.</p>
            <div className="metrics mt-4">
              <div className="metric"><small>Scenes</small><strong>{generatedClips.length}</strong><span>Generated video clips</span></div>
              <div className="metric"><small>Scene duration</small><strong>{generatedClips.reduce((sum, clip) => sum + clip.seconds, 0)}s</strong><span>Approximate combined length</span></div>
              <div className="metric"><small>Narration</small><strong>{audioBlob ? "Ready" : "Missing"}</strong><span>AI voice-over</span></div>
              <div className="metric"><small>Captions</small><strong>{captionCues.length ? "Ready" : "Missing"}</strong><span>Whisper timestamps</span></div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 mt-4">
              <h3>Scene timeline</h3>
              <button className="btn secondary" onClick={() => setTab("avatar")}><Plus size={14}/> Add another scene</button>
            </div>
            {generatedClips.length ? <div className="space-y-2 mt-3">
              {generatedClips.map((clip, index) => <div key={clip.id} className="row items-center gap-3">
                <video src={clip.url} controls playsInline className="h-16 w-28 rounded-md bg-black object-cover"/>
                <div className="flex-1 min-w-0"><b>Scene {index + 1} · {clip.seconds}s</b><small>{clip.format === "shorts" ? "9:16 Shorts" : "16:9 Landscape"} · {clip.prompt}</small></div>
                <button className="btn ghost" onClick={() => removeClip(clip.id)} aria-label={"Remove scene " + (index + 1)}><Trash2 size={14}/></button>
              </div>)}
            </div> : <div className="empty">No scenes yet. Go to AI Video / Avatar and generate your first scene.</div>}
            <div className="callout mt-4">
              <b>Render settings</b>
              <p className="mt-1">Output: {videoFormat === "shorts" ? "1080 × 1920 vertical" : "1920 × 1080 landscape"} WebM. Scenes are fitted to the selected aspect ratio. The narration and captions use their timestamp timeline; short visual sequences repeat to cover longer narration.</p>
              <p className="mt-1">Browser rendering is limited to five minutes per export and depends on your device memory and browser codec support.</p>
            </div>
            <div className="flex flex-wrap gap-2 mt-4">
              <button className="btn" onClick={renderTimeline} disabled={!connected || !generatedClips.length || !audioBlob || !captionCues.length || busy === "render"}>
                {busy === "render" ? <LoaderCircle size={14} className="animate-spin"/> : <Film size={14}/>} Render final video
              </button>
              <span className="muted self-center">{busy === "render" ? renderProgress + "% rendered" : "Requires at least one scene, narration and timestamped captions."}</span>
            </div>
            {busy === "render" && <div className="progress mt-3"><span style={{width: renderProgress + "%"}}/></div>}
            {finalVideoUrl && <div className="mt-5">
              <h3>Rendered video</h3>
              <video src={finalVideoUrl} controls playsInline className="mt-3 max-h-[520px] w-full rounded-xl border border-line bg-black"/>
              <a className="btn secondary mt-3 inline-flex" href={finalVideoUrl} download="youtube-studio-final.webm"><Download size={14}/> Download final WebM</a>
            </div>}
          </>}
          </>}
        </section>
      </div>
    </div>
  );
}
