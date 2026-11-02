"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle, ShieldCheck } from "lucide-react";

const AUTH = "https://enter.pollinations.ai";
const APP_BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";

export default function PollinationsConnectCallback() {
  const router = useRouter();
  const [message, setMessage] = useState("Completing secure AI credit connection…");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const params = new URLSearchParams(window.location.search);
        const oauthError = params.get("error");
        if (oauthError) throw new Error("AI credit authorization was denied: " + oauthError);

        const code = params.get("code") || "";
        const returnedState = params.get("state") || "";
        const expectedState = sessionStorage.getItem("pollinations_oauth_state") || "";
        const verifier = sessionStorage.getItem("pollinations_pkce_verifier") || "";
        const clientId = sessionStorage.getItem("pollinations_pending_app_key") || "";
        const redirectUri = sessionStorage.getItem("pollinations_redirect_uri") || window.location.origin + APP_BASE_PATH + "/ai/connect";

        if (!code || !returnedState || !expectedState || returnedState !== expectedState || !verifier || !clientId) {
          throw new Error("The AI credit authorization could not be verified. Return to AI Studio and reconnect.");
        }

        sessionStorage.removeItem("pollinations_oauth_state");
        sessionStorage.removeItem("pollinations_pkce_verifier");
        sessionStorage.removeItem("pollinations_pending_app_key");

        const response = await fetch(AUTH + "/api/oauth/token", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            grant_type: "authorization_code",
            code,
            client_id: clientId,
            redirect_uri: redirectUri,
            code_verifier: verifier,
          }),
        });
        const data = await response.json();
        if (!response.ok || !data.access_token) {
          throw new Error(data.error_description || data.error || "Pollinations did not return an access token.");
        }
        const expiry = Date.now() + Math.max(60, Number(data.expires_in || 604800)) * 1000;
        sessionStorage.setItem("pollinations_app_key", clientId);
        sessionStorage.setItem("pollinations_access_token", data.access_token);
        sessionStorage.setItem("pollinations_expires_at", String(expiry));
        sessionStorage.removeItem("pollinations_redirect_uri");
        if (active) {
          setMessage("AI credits connected. Opening your studio…");
          window.history.replaceState({}, "", window.location.pathname);
          router.replace("/?ai=connected");
        }
      } catch (error) {
        if (active) {
          setMessage(error instanceof Error ? error.message : "AI credit connection failed.");
        }
      }
    })();
    return () => { active = false; };
  }, [router]);

  return (
    <main className="min-h-screen flex items-center justify-center p-5">
      <div className="panel w-full max-w-lg">
        <div className="logo mb-5"><ShieldCheck size={20}/></div>
        <h1 className="text-2xl font-extrabold">AI credits connection</h1>
        <p className="muted mt-3">{message}</p>
        <div className="mt-5 flex items-center gap-2 text-violet-300">
          <LoaderCircle size={16} className="animate-spin"/><span className="text-sm">Secure authorization</span>
        </div>
        <a className="text-violet-300 underline text-sm inline-block mt-6" href={APP_BASE_PATH + "/"}>Return to AI YouTube Studio</a>
      </div>
    </main>
  );
}
