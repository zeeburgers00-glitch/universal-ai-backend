"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, CheckCircle2, LoaderCircle, LogOut, ShieldCheck, UploadCloud, Youtube } from "lucide-react";

type GoogleTokenResponse = { access_token?: string; error?: string; error_description?: string };
type GoogleTokenClient = { requestAccessToken: (options?: { prompt?: string }) => void };
type GoogleAccounts = {
  oauth2: {
    initTokenClient: (options: {
      client_id: string;
      scope: string;
      callback: (response: GoogleTokenResponse) => void;
      error_callback?: (error: { type?: string; message?: string }) => void;
    }) => GoogleTokenClient;
  };
};
type GoogleWindow = Window & { google?: { accounts?: GoogleAccounts } };
type Channel = { id: string; title: string; thumbnail?: string };

export default function YouTubePublisher() {
  const [clientId, setClientId] = useState("");
  const [gisReady, setGisReady] = useState(false);
  const [token, setToken] = useState("");
  const [channel, setChannel] = useState<Channel | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [scheduleAt, setScheduleAt] = useState("");
  const [privacy, setPrivacy] = useState<"private" | "unlisted" | "public">("private");
  const [madeForKids, setMadeForKids] = useState("no");
  const [syntheticMedia, setSyntheticMedia] = useState("yes");
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState(0);
  const [notice, setNotice] = useState("");
  const [isError, setIsError] = useState(false);
  const [publishedUrl, setPublishedUrl] = useState("");
  const [origin, setOrigin] = useState("");

  const say = useCallback((message: string, error = false) => {
    setNotice(message);
    setIsError(error);
  }, []);

  useEffect(() => {
    setOrigin(window.location.origin);
    const stored = sessionStorage.getItem("youtube_oauth_client_id") || "";
    if (stored) setClientId(stored);
    const scriptId = "google-identity-services";
    if (document.getElementById(scriptId)) {
      setGisReady(Boolean((window as GoogleWindow).google?.accounts?.oauth2));
      return;
    }
    const script = document.createElement("script");
    script.id = scriptId;
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => setGisReady(Boolean((window as GoogleWindow).google?.accounts?.oauth2));
    script.onerror = () => say("Google sign-in library could not load. Check your connection and reload.", true);
    document.head.appendChild(script);
  }, [say]);

  const readChannel = async (accessToken: string) => {
    const response = await fetch("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true&maxResults=5", {
      headers: { Authorization: "Bearer " + accessToken },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error?.message || "Google did not return an authorized YouTube channel.");
    const item = data.items?.[0];
    if (!item?.id) throw new Error("This Google account has no YouTube channel. Create one on YouTube, then reconnect.");
    const value = { id: String(item.id), title: String(item.snippet?.title || "Connected YouTube channel"), thumbnail: String(item.snippet?.thumbnails?.default?.url || "") };
    setChannel(value);
    return value;
  };

  const connect = () => {
    const id = clientId.trim();
    if (!id.endsWith(".apps.googleusercontent.com")) {
      say("Enter a Google OAuth Web Client ID ending in .apps.googleusercontent.com.", true);
      return;
    }
    const google = (window as GoogleWindow).google;
    if (!google?.accounts?.oauth2) {
      say("Google sign-in is still loading. Wait a moment and try again.", true);
      return;
    }
    sessionStorage.setItem("youtube_oauth_client_id", id);
    setBusy("connect");
    const client = google.accounts.oauth2.initTokenClient({
      client_id: id,
      scope: "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
      callback: (response) => {
        if (response.error || !response.access_token) {
          setBusy("");
          say(response.error_description || response.error || "Google authorization failed.", true);
          return;
        }
        setToken(response.access_token);
        void readChannel(response.access_token).then((result) => {
          say("Connected to " + result.title + ". This browser session now has temporary upload permission.");
        }).catch((e) => say(e instanceof Error ? e.message : "Could not read the YouTube channel.", true)).finally(() => setBusy(""));
      },
      error_callback: (error) => {
        setBusy("");
        say(error.message || "Google authorization popup failed.", true);
      },
    });
    client.requestAccessToken({ prompt: "consent" });
  };

  const disconnect = () => {
    setToken("");
    setChannel(null);
    setPublishedUrl("");
    say("YouTube access token cleared from this browser session.");
  };

  const upload = async () => {
    setBusy("upload");
    setProgress(0);
    setPublishedUrl("");
    try {
      if (!token) throw new Error("Connect your YouTube channel first.");
      if (!file) throw new Error("Choose an MP4, WebM or MOV video file.");
      if (!title.trim() || title.trim().length > 100) throw new Error("Video title must contain 1–100 characters.");
      if (description.length > 5000) throw new Error("Description must be 5,000 characters or less.");
      if (scheduleAt && privacy !== "private") throw new Error("Scheduled YouTube videos must be uploaded with Private privacy.");
      const status: Record<string, unknown> = {
        privacyStatus: scheduleAt ? "private" : privacy,
        selfDeclaredMadeForKids: madeForKids === "yes",
        containsSyntheticMedia: syntheticMedia === "yes",
      };
      if (scheduleAt) {
        const publishAt = new Date(scheduleAt);
        if (!Number.isFinite(publishAt.getTime()) || publishAt.getTime() < Date.now() + 120000) {
          throw new Error("Choose a scheduled time at least two minutes in the future.");
        }
        status.publishAt = publishAt.toISOString();
      }
      const metadata = {
        snippet: {
          title: title.trim(),
          description: description.trim(),
          tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean).slice(0, 30),
          categoryId: "27",
        },
        status,
      };
      const boundary = "youtubeStudio" + crypto.randomUUID().replace(/-/g, "");
      const body = new Blob([
        "--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n",
        JSON.stringify(metadata),
        "\r\n--" + boundary + "\r\nContent-Type: " + (file.type || "video/mp4") + "\r\n\r\n",
        file,
        "\r\n--" + boundary + "--",
      ]);
      const response = await fetch("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "multipart/related; boundary=" + boundary,
        },
        body,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.id) throw new Error(data.error?.message || "YouTube upload failed (HTTP " + response.status + "). Check API quota and OAuth permissions.");
      const url = "https://www.youtube.com/watch?v=" + data.id;
      setPublishedUrl(url);
      setProgress(100);
      say(scheduleAt ? "Video uploaded privately and scheduled." : "Video upload completed.");
    } catch (e) {
      say(e instanceof Error ? e.message : "Video upload failed.", true);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-5">
      {notice && <div className={"notice " + (isError ? "error" : "success")}>{notice}<button className="float-right" onClick={() => setNotice("")}>×</button></div>}
      <section className="panel">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><div className="eyebrow">GOOGLE / YOUTUBE</div><h2 className="mt-2">Connect your channel</h2><p className="muted mt-2">Google's OAuth popup grants this browser temporary access. No Gmail password or Google client secret is entered here.</p></div>
          <span className={"status " + (channel ? "ok" : "")}>{channel ? "Connected" : "Not connected"}</span>
        </div>
        {!channel ? (
          <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
            <div className="field">
              <label>Google OAuth Web Client ID</label>
              <input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="123456789.apps.googleusercontent.com" autoComplete="off" />
              <small className="muted">Register this authorized JavaScript origin in Google Cloud:</small>
              <code className="block break-all text-xs text-violet-300">{origin}</code>
              <a className="text-xs text-violet-300 underline" href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer">Open Google Cloud credentials</a>
            </div>
            <div className="flex items-end"><button className="btn w-full" onClick={connect} disabled={!gisReady || busy === "connect"}>{busy === "connect" ? <LoaderCircle size={15} className="animate-spin" /> : <Youtube size={15} />} Continue with Google</button></div>
          </div>
        ) : (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">{channel.thumbnail && <img src={channel.thumbnail} alt="" className="h-12 w-12 rounded-full"/>}<div><b>{channel.title}</b><small className="block muted">{channel.id}</small></div></div>
            <button className="btn secondary" onClick={disconnect}><LogOut size={14}/> Disconnect</button>
          </div>
        )}
        <p className="muted mt-3">YouTube Data API v3 must be enabled for the Google Cloud project. Access is temporary and must be renewed after expiry or page reload.</p>
      </section>

      <section className="panel">
        <div className="flex items-center gap-2"><UploadCloud size={18}/><h2>Upload or schedule a video</h2></div>
        <p className="muted mt-2">Generate a video in AI Studio, save it to your device, then upload it here. Public publishing and scheduling are user-initiated.</p>
        <div className="grid gap-3 md:grid-cols-2 mt-4">
          <div className="field"><label>Video file</label><input type="file" accept="video/mp4,video/webm,video/quicktime" onChange={(e) => setFile(e.target.files?.[0] || null)} /></div>
          <div className="field"><label>Video title (max 100)</label><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Write a clear and accurate title" /></div>
          <div className="field md:col-span-2"><label>Description</label><textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Add an accurate video description and source links..." /></div>
          <div className="field"><label>Tags (comma separated)</label><input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="education, science, explainer" /></div>
          <div className="field"><label>Privacy</label><select value={privacy} onChange={(e) => setPrivacy(e.target.value as typeof privacy)}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></div>
          <div className="field"><label>Schedule time (optional)</label><input type="datetime-local" value={scheduleAt} onChange={(e) => setScheduleAt(e.target.value)} /><small className="muted">Scheduling uploads as Private with a future publish time.</small></div>
          <div className="field"><label>Made for kids?</label><select value={madeForKids} onChange={(e) => setMadeForKids(e.target.value)}><option value="no">No</option><option value="yes">Yes</option></select></div>
          <div className="field"><label>Contains realistic altered / synthetic media?</label><select value={syntheticMedia} onChange={(e) => setSyntheticMedia(e.target.value)}><option value="yes">Yes</option><option value="no">No</option></select></div>
        </div>
        {busy === "upload" && <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-700"><div className="h-full bg-violet-400" style={{ width: progress + "%" }}/></div>}
        <button className="btn mt-4" onClick={upload} disabled={!channel || !file || busy === "upload"}>{busy === "upload" ? <LoaderCircle size={15} className="animate-spin" /> : <UploadCloud size={15}/>} Upload to YouTube</button>
        {publishedUrl && <a className="text-violet-300 underline mt-4 inline-block" href={publishedUrl} target="_blank" rel="noreferrer">Open YouTube video</a>}
      </section>

      <section className="panel">
        <div className="flex items-center gap-2"><ShieldCheck size={18}/><h2>Safety and publishing rules</h2></div>
        <p className="muted mt-2">The upload uses the YouTube channel connected by the Google account above. Confirm ownership and media rights before uploading. AI-generated content disclosures are the channel owner's responsibility; the form records your declaration and does not guess it.</p>
        <div className="callout mt-3"><CalendarClock size={14} className="inline mr-2"/> Scheduled uploads must remain Private and use a future publish time. Google/YouTube quota and policy limits still apply.</div>
      </section>
    </div>
  );
}
