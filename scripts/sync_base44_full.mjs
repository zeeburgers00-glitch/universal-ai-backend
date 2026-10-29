#!/usr/bin/env node
/**
 * Full end-to-end Base44 App Provisioner for Universal AI Backend.
 *
 * Syncs for every Base44 app accessible to BASE44_ACCESS_TOKEN:
 *   1. App secrets (UNIVERSAL_AI_BACKEND_URL, UNIVERSAL_AI_BACKEND_API_KEY)
 *   2. Backend function `universalAiBackend` (Deno runtime proxy)
 *   3. Native Base44 AI Agent `universal_ai_hub_agent` (/agent-configs, preserving existing agents)
 *   4. Base44 MCP Server inspection / edit attempt (https://app.base44.com/mcp)
 *   5. Full Vite app eject (/eject) -> inject UniversalAiHub page + SDK + floating launcher
 *      -> `VITE_BASE44_APP_ID=<id> npm run build` -> `dist.tar.gz` -> `/deploy-dist`!
 *   6. Structured non-secret run telemetry saved to Supabase `public.uaib_base44_sync_runs`.
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE44_API_URL = (process.env.BASE44_API_URL || "https://app.base44.com").replace(/\/+$/, "");
const BASE44_TOKEN = (process.env.BASE44_ACCESS_TOKEN || "").trim();
const BACKEND_PUBLIC_URL = (
  process.env.UNIVERSAL_AI_BACKEND_PUBLIC_URL || "https://universal-ai-backend.vercel.app"
).replace(/\/+$/, "");
const BACKEND_API_KEY = (process.env.BACKEND_API_KEY || "").trim();
const SUPABASE_URL = (process.env.SUPABASE_URL || "").trim().replace(/\/+$/, "");
const SUPABASE_SERVICE_ROLE_KEY = (process.env.SUPABASE_SERVICE_ROLE_KEY || "").trim();

function log(msg) {
  console.log(`[base44-auto-sync] ${msg}`);
}

function b44Headers(extra = {}) {
  return {
    Authorization: `Bearer ${BASE44_TOKEN}`,
    "User-Agent": "UniversalAIBackend/0.6.0",
    Accept: "application/json",
    ...extra,
  };
}

async function b44Json(method, urlPath, body = undefined, timeoutMs = 45000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const opts = {
      method,
      headers: b44Headers(body !== undefined ? { "Content-Type": "application/json" } : {}),
      signal: controller.signal,
    };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(`${BASE44_API_URL}${urlPath}`, opts);
    const text = await resp.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw: text.slice(0, 400) };
    }
    return { ok: resp.ok, status: resp.status, data };
  } finally {
    clearTimeout(timer);
  }
}

function buildBackendFunctionCode(backendUrl) {
  return `import { createClientFromRequest } from "npm:@base44/sdk";
import { secrets } from "base44:runtime";

const DEFAULT_BACKEND_URL = ${JSON.stringify(backendUrl)};

const PUBLIC_READ_ACTIONS = new Set([
  "health",
  "stats",
  "tools",
  "tool_detail",
  "rea_status",
  "rea_tools",
  "providers",
  "agents",
  "workflows",
  "channels",
  "voice_models",
  "discover_categories",
  "discover_github",
]);

function buildQuery(params) {
  const qs = new URLSearchParams();
  for (const [key, val] of Object.entries(params || {})) {
    if (val !== undefined && val !== null && val !== "") {
      qs.set(key, String(val));
    }
  }
  const rendered = qs.toString();
  return rendered ? \`?\${rendered}\` : "";
}

export default async function (req) {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204 });
  }

  const base44 = createClientFromRequest(req);
  let body = {};
  try {
    body = await req.json();
  } catch {
    body = {};
  }

  const action = String(body.action || "stats").trim();
  const payload = body.payload && typeof body.payload === "object" ? body.payload : body;

  if (!PUBLIC_READ_ACTIONS.has(action)) {
    try {
      const user = await base44.auth.me();
      if (!user) {
        return Response.json({ error: "Authentication required for this backend action." }, { status: 401 });
      }
    } catch {
      return Response.json({ error: "Authentication required for this backend action." }, { status: 401 });
    }
  }

  const backendUrl = String(secrets.get("UNIVERSAL_AI_BACKEND_URL") || DEFAULT_BACKEND_URL).replace(/\\/+$/, "");
  const backendApiKey = String(secrets.get("UNIVERSAL_AI_BACKEND_API_KEY") || "");

  let method = "GET";
  let path = "/v1/catalog/stats";
  let jsonBody = undefined;
  let needsKey = false;

  switch (action) {
    case "health":
      path = "/health";
      break;
    case "stats":
      path = "/v1/catalog/stats";
      break;
    case "tools":
      path = "/v1/tools" + buildQuery({
        q: payload.q,
        category: payload.category,
        kind: payload.mcp_only ? "mcp_server" : payload.kind,
        capability: payload.capability,
        license_status: payload.license_status,
        source_classification: payload.source_classification,
        min_stars: payload.min_stars,
        language: payload.language,
        limit: payload.limit || 60,
        offset: payload.offset || 0,
      });
      break;
    case "tool_detail":
      path = \`/v1/tools/\${encodeURIComponent(String(payload.tool_id || ""))}\`;
      break;
    case "register_tool":
      method = "POST";
      path = "/v1/tools";
      jsonBody = payload.tool || payload;
      needsKey = true;
      break;
    case "rea_status":
      path = "/v1/rea/status";
      break;
    case "rea_tools":
      path = "/v1/rea/tools" + buildQuery({
        q: payload.q,
        family: payload.family,
        limit: payload.limit || 100,
      });
      break;
    case "rea_inspect":
      method = "POST";
      path = "/v1/rea/inspect";
      jsonBody = payload;
      needsKey = true;
      break;
    case "rea_job":
      method = "POST";
      path = "/v1/rea/jobs";
      jsonBody = payload;
      needsKey = true;
      break;
    case "providers":
      path = "/v1/models/providers";
      break;
    case "agents":
      path = "/v1/agents";
      break;
    case "agent_run":
      method = "POST";
      path = \`/v1/agents/\${encodeURIComponent(String(payload.agent_id || "research-agent"))}\` + "/run";
      jsonBody = {
        objective: payload.objective,
        inputs: payload.inputs || {},
        user_approved: Boolean(payload.user_approved),
        dry_run: Boolean(payload.dry_run),
      };
      needsKey = true;
      break;
    case "workflows":
      path = "/v1/workflows";
      break;
    case "workflow_run":
      method = "POST";
      path = \`/v1/workflows/\${encodeURIComponent(String(payload.workflow_id || ""))}\` + "/run";
      jsonBody = {
        inputs: payload.inputs || {},
        user_approved: Boolean(payload.user_approved),
        dry_run: Boolean(payload.dry_run),
      };
      needsKey = true;
      break;
    case "channels":
      path = "/v1/channels";
      break;
    case "channel_action":
      method = "POST";
      path = \`/v1/channels/\${encodeURIComponent(String(payload.channel_id || ""))}\` + "/actions";
      jsonBody = payload;
      needsKey = true;
      break;
    case "voice_models":
      path = "/v1/voice/providers";
      break;
    case "voice_tts":
      method = "POST";
      path = "/v1/voice/tts";
      jsonBody = payload;
      needsKey = true;
      break;
    case "media_job":
      method = "POST";
      path = "/v1/media/jobs";
      jsonBody = payload;
      needsKey = true;
      break;
    case "discover_categories":
      path = "/v1/discover/categories";
      break;
    case "discover_github":
      path = "/v1/discover/github" + buildQuery({
        category_preset: payload.category_preset || payload.preset,
        q: payload.q,
        min_stars: payload.min_stars,
        license_filter: payload.license_filter,
        sort: payload.sort || "stars",
        per_page: payload.per_page || 24,
      });
      break;
    case "chat":
      method = "POST";
      path = "/v1/chat/completions";
      jsonBody = {
        provider: payload.provider || "groq",
        model: payload.model || "",
        messages: payload.messages || [{ role: "user", content: String(payload.prompt || "") }],
        temperature: typeof payload.temperature === "number" ? payload.temperature : 0.7,
        max_tokens: payload.max_tokens || 1024,
      };
      needsKey = true;
      break;
    case "task_status":
      path = \`/v1/tasks/\${encodeURIComponent(String(payload.service || "rea"))}/\${encodeURIComponent(String(payload.task_id || ""))}\`;
      needsKey = true;
      break;
    default:
      return Response.json({ error: \`Unsupported action: \${action}\` }, { status: 400 });
  }

  const headers = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if ((needsKey || backendApiKey) && backendApiKey) {
    headers["X-API-Key"] = backendApiKey;
  }

  const upstream = await fetch(\`\${backendUrl}\${path}\`, {
    method,
    headers,
    body: jsonBody !== undefined ? JSON.stringify(jsonBody) : undefined,
  });

  const rawText = await upstream.text();
  let parsed = null;
  try {
    parsed = rawText ? JSON.parse(rawText) : {};
  } catch {
    parsed = { raw: rawText };
  }
  return Response.json(parsed, { status: upstream.status });
}
`;
}

function buildFrontendSdkCode(hasApiBase44Client, backendUrl) {
  const clientSetup = hasApiBase44Client
    ? `import { base44 } from '@/api/base44Client';`
    : `import { createClient } from '@base44/sdk';
const base44 = createClient({
  appId: import.meta.env.VITE_BASE44_APP_ID,
  serverUrl: import.meta.env.VITE_BASE44_BACKEND_URL,
  requiresAuth: false,
});`;

  return `${clientSetup}

export const BACKEND_PUBLIC_URL = ${JSON.stringify(backendUrl)};

function buildQuery(params = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') {
      qs.set(k, String(v));
    }
  }
  const s = qs.toString();
  return s ? \`?\${s}\` : '';
}

function directReadRoute(action, payload = {}) {
  switch (action) {
    case 'health':
      return '/health';
    case 'stats':
      return '/v1/catalog/stats';
    case 'tools':
      return '/v1/tools' + buildQuery({
        q: payload.q,
        category: payload.category,
        kind: payload.mcp_only ? 'mcp_server' : payload.kind,
        min_stars: payload.min_stars,
        limit: payload.limit || 60,
        offset: payload.offset || 0,
      });
    case 'tool_detail':
      return \`/v1/tools/\${encodeURIComponent(String(payload.tool_id || ''))}\`;
    case 'rea_status':
      return '/v1/rea/status';
    case 'rea_tools':
      return '/v1/rea/tools' + buildQuery({
        q: payload.q,
        family: payload.family,
        limit: payload.limit || 100,
      });
    case 'providers':
      return '/v1/models/providers';
    case 'agents':
      return '/v1/agents';
    case 'workflows':
      return '/v1/workflows';
    case 'channels':
      return '/v1/channels';
    case 'voice_models':
      return '/v1/voice/providers';
    case 'discover_categories':
      return '/v1/discover/categories';
    case 'discover_github':
      return '/v1/discover/github' + buildQuery({
        category_preset: payload.category_preset || payload.preset,
        q: payload.q,
        min_stars: payload.min_stars,
        sort: payload.sort || 'stars',
        per_page: payload.per_page || 24,
      });
    default:
      return null;
  }
}

export async function invokeUniversalBackend(action, payload = {}) {
  try {
    if (base44?.functions?.invoke) {
      const res = await base44.functions.invoke('universalAiBackend', { action, payload });
      const data = res && res.data !== undefined ? res.data : res;
      if (data && !data.error) {
        return data;
      }
    }
  } catch (err) {
    const fallbackRoute = directReadRoute(action, payload);
    if (!fallbackRoute) {
      throw err;
    }
  }

  const fallbackRoute = directReadRoute(action, payload);
  if (fallbackRoute) {
    const resp = await fetch(\`\${BACKEND_PUBLIC_URL}\${fallbackRoute}\`, {
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) {
      throw new Error(\`Backend HTTP \${resp.status}\`);
    }
    return await resp.json();
  }

  const res = await base44.functions.invoke('universalAiBackend', { action, payload });
  return res && res.data !== undefined ? res.data : res;
}

export const universalAiApi = {
  health: () => invokeUniversalBackend('health'),
  stats: () => invokeUniversalBackend('stats'),
  listTools: (filters = {}) => invokeUniversalBackend('tools', filters),
  getTool: (toolId) => invokeUniversalBackend('tool_detail', { tool_id: toolId }),
  registerTool: (tool) => invokeUniversalBackend('register_tool', { tool }),
  reaStatus: () => invokeUniversalBackend('rea_status'),
  listReaTools: (filters = {}) => invokeUniversalBackend('rea_tools', filters),
  inspectWithRea: (payload) => invokeUniversalBackend('rea_inspect', payload),
  providers: () => invokeUniversalBackend('providers'),
  agents: () => invokeUniversalBackend('agents'),
  runAgent: (agentId, objective, extra = {}) =>
    invokeUniversalBackend('agent_run', { agent_id: agentId, objective, ...extra }),
  workflows: () => invokeUniversalBackend('workflows'),
  runWorkflow: (workflowId, inputs = {}, extra = {}) =>
    invokeUniversalBackend('workflow_run', { workflow_id: workflowId, inputs, ...extra }),
  channels: () => invokeUniversalBackend('channels'),
  voiceModels: () => invokeUniversalBackend('voice_models'),
  discoverCategories: () => invokeUniversalBackend('discover_categories'),
  discoverGithub: (params = {}) => invokeUniversalBackend('discover_github', params),
  chat: (prompt, provider = 'groq', model = '') =>
    invokeUniversalBackend('chat', { prompt, provider, model }),
};
`;
}

function buildHubPageCode() {
  return `import React, { useState, useEffect, useCallback } from 'react';
import { universalAiApi, BACKEND_PUBLIC_URL } from '../lib/universalAiBackend';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'tools', label: 'Global AI & MCP Tools' },
  { id: 'rea', label: 'REA 229 Tools' },
  { id: 'models', label: '45 LLM Providers & Chat' },
  { id: 'agents', label: 'Agents, Workflows & Voice' },
  { id: 'discover', label: 'Live GitHub AI Discovery' },
];

export default function UniversalAiHub({ onCloseModal }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState(null);
  const [loadingStats, setLoadingStats] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');

  // Tools tab state
  const [toolQuery, setToolQuery] = useState('');
  const [toolCategory, setToolCategory] = useState('');
  const [mcpOnly, setMcpOnly] = useState(false);
  const [toolsData, setToolsData] = useState({ items: [], total: 0 });
  const [loadingTools, setLoadingTools] = useState(false);

  // REA tab state
  const [reaInfo, setReaInfo] = useState(null);
  const [reaQuery, setReaQuery] = useState('');
  const [reaFamily, setReaFamily] = useState('');
  const [reaTools, setReaTools] = useState({ items: [], total: 0, families: {} });
  const [loadingRea, setLoadingRea] = useState(false);

  // Providers & chat state
  const [providersList, setProvidersList] = useState([]);
  const [chatProvider, setChatProvider] = useState('groq');
  const [chatPrompt, setChatPrompt] = useState('Summarize the top 3 capabilities of Universal AI Backend.');
  const [chatReply, setChatReply] = useState(null);
  const [chatBusy, setChatBusy] = useState(false);

  // Agents, workflows, channels, voice
  const [agentsList, setAgentsList] = useState([]);
  const [workflowsList, setWorkflowsList] = useState([]);
  const [channelsList, setChannelsList] = useState([]);
  const [voiceList, setVoiceList] = useState([]);
  const [dispatchResult, setDispatchResult] = useState(null);

  // Live GitHub discovery
  const [presets, setPresets] = useState([]);
  const [selectedPreset, setSelectedPreset] = useState('mcp-servers');
  const [ghQuery, setGhQuery] = useState('');
  const [ghResults, setGhResults] = useState([]);
  const [loadingGh, setLoadingGh] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingStats(true);
      try {
        const [h, s] = await Promise.all([
          universalAiApi.health().catch(() => ({ status: 'ok' })),
          universalAiApi.stats(),
        ]);
        if (!cancelled) {
          setHealth(h);
          setStats(s);
        }
      } catch (err) {
        if (!cancelled) {
          setErrorMsg(err?.message || 'Unable to reach Universal AI Backend');
        }
      } finally {
        if (!cancelled) setLoadingStats(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchTools = useCallback(async () => {
    setLoadingTools(true);
    try {
      const res = await universalAiApi.listTools({
        q: toolQuery,
        category: toolCategory,
        mcp_only: mcpOnly ? 'true' : '',
        limit: 48,
      });
      setToolsData({
        items: Array.isArray(res?.items) ? res.items : [],
        total: Number(res?.total || 0),
      });
    } catch (err) {
      setErrorMsg(err?.message || 'Failed loading catalog tools');
    } finally {
      setLoadingTools(false);
    }
  }, [toolQuery, toolCategory, mcpOnly]);

  const fetchRea = useCallback(async () => {
    setLoadingRea(true);
    try {
      const [statusRes, toolsRes] = await Promise.all([
        reaInfo ? Promise.resolve(reaInfo) : universalAiApi.reaStatus(),
        universalAiApi.listReaTools({ q: reaQuery, family: reaFamily, limit: 80 }),
      ]);
      if (!reaInfo) setReaInfo(statusRes);
      setReaTools({
        items: Array.isArray(toolsRes?.items) ? toolsRes.items : [],
        total: Number(toolsRes?.total || 0),
        families: toolsRes?.families || statusRes?.family_counts || {},
      });
    } catch (err) {
      setErrorMsg(err?.message || 'Failed loading REA tools');
    } finally {
      setLoadingRea(false);
    }
  }, [reaInfo, reaQuery, reaFamily]);

  useEffect(() => {
    if (activeTab === 'tools') fetchTools();
    if (activeTab === 'rea') fetchRea();
    if (activeTab === 'models' && providersList.length === 0) {
      universalAiApi.providers().then((res) => {
        const items = Array.isArray(res?.items) ? res.items : Array.isArray(res?.providers) ? res.providers : Array.isArray(res) ? res : [];
        setProvidersList(items);
      }).catch(() => {});
    }
    if (activeTab === 'agents' && agentsList.length === 0) {
      Promise.all([
        universalAiApi.agents().catch(() => ({ items: [] })),
        universalAiApi.workflows().catch(() => ({ items: [] })),
        universalAiApi.channels().catch(() => ({ items: [] })),
        universalAiApi.voiceModels().catch(() => ({ items: [] })),
      ]).then(([a, w, c, v]) => {
        setAgentsList(Array.isArray(a?.items) ? a.items : Array.isArray(a) ? a : []);
        setWorkflowsList(Array.isArray(w?.items) ? w.items : Array.isArray(w) ? w : []);
        setChannelsList(Array.isArray(c?.items) ? c.items : Array.isArray(c) ? c : []);
        setVoiceList(Array.isArray(v?.items) ? v.items : Array.isArray(v?.providers) ? v.providers : Array.isArray(v) ? v : []);
      });
    }
    if (activeTab === 'discover' && presets.length === 0) {
      universalAiApi.discoverCategories().then((res) => {
        setPresets(Array.isArray(res?.presets) ? res.presets : []);
      }).catch(() => {});
    }
  }, [activeTab, fetchTools, fetchRea, providersList.length, agentsList.length, presets.length]);

  const runGithubSearch = async (presetOverride) => {
    setLoadingGh(true);
    try {
      const res = await universalAiApi.discoverGithub({
        category_preset: presetOverride !== undefined ? presetOverride : selectedPreset,
        q: ghQuery,
        per_page: 18,
      });
      setGhResults(Array.isArray(res?.items) ? res.items : Array.isArray(res?.repositories) ? res.repositories : []);
    } catch (err) {
      setErrorMsg(err?.message || 'GitHub discovery failed');
    } finally {
      setLoadingGh(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'discover' && ghResults.length === 0) {
      runGithubSearch(selectedPreset);
    }
  }, [activeTab]);

  const handleChatSubmit = async (e) => {
    e.preventDefault();
    if (!chatPrompt.trim()) return;
    setChatBusy(true);
    setChatReply(null);
    try {
      const res = await universalAiApi.chat(chatPrompt, chatProvider);
      setChatReply(res);
    } catch (err) {
      setChatReply({ error: err?.message || 'Chat request failed (ensure provider API key is configured or user is signed in).' });
    } finally {
      setChatBusy(false);
    }
  };

  const handleDryRunAgent = async (agentId) => {
    setDispatchResult({ loading: true, target: agentId });
    try {
      const res = await universalAiApi.runAgent(agentId, 'Verify Universal AI Backend agent dry-run readiness', {
        dry_run: true,
        user_approved: true,
      });
      setDispatchResult({ target: agentId, response: res });
    } catch (err) {
      setDispatchResult({ target: agentId, error: err?.message || 'Agent run requires authenticated session' });
    }
  };

  const categoriesObj = stats?.categories || stats?.by_category || {};
  const categoryEntries = Object.entries(categoriesObj).sort((a, b) => Number(b[1]) - Number(a[1]));
  const totalCatalog = Number(stats?.total_tools || stats?.total || 6122);
  const totalRea = Number(stats?.rea_mcp_tools || 229);

  return (
    <div style={{ minHeight: '100vh', background: '#090d16', color: '#f8fafc', fontFamily: 'Inter, system-ui, sans-serif', padding: '24px' }}>
      <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '16px', padding: '20px 24px', borderRadius: '16px', background: 'linear-gradient(135deg, rgba(30,41,59,0.92), rgba(15,23,42,0.96))', border: '1px solid rgba(99,102,241,0.35)', marginBottom: '20px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
              <span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '999px', background: health ? '#22c55e' : '#eab308', boxShadow: '0 0 10px #22c55e' }} />
              <span style={{ fontSize: '12px', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#818cf8' }}>
                Universal AI Backend v0.6.0 · Connected via Base44
              </span>
            </div>
            <h1 style={{ fontSize: '26px', fontWeight: 800, margin: 0, color: '#ffffff' }}>
              Universal AI Command Hub
            </h1>
            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#94a3b8' }}>
              {totalCatalog.toLocaleString()} Global AI & MCP Tools · {totalRea} REA Reverse-Engineering Tools · 45 LLM Providers · 38 Agents · 27 Workflows
            </p>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <a
              href={\`\${BACKEND_PUBLIC_URL}/explorer\`}
              target="_blank"
              rel="noreferrer"
              style={{ padding: '9px 14px', borderRadius: '10px', background: 'rgba(99,102,241,0.18)', border: '1px solid rgba(99,102,241,0.45)', color: '#c7d2fe', fontSize: '13px', fontWeight: 600, textDecoration: 'none' }}
            >
              Full Explorer ↗
            </a>
            {onCloseModal ? (
              <button
                onClick={onCloseModal}
                style={{ padding: '9px 14px', borderRadius: '10px', background: '#1e293b', border: '1px solid #334155', color: '#f1f5f9', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
              >
                Close ✕
              </button>
            ) : (
              <a
                href="/"
                style={{ padding: '9px 14px', borderRadius: '10px', background: '#1e293b', border: '1px solid #334155', color: '#f1f5f9', fontSize: '13px', fontWeight: 600, textDecoration: 'none' }}
              >
                ← App Home
              </a>
            )}
          </div>
        </div>

        {errorMsg && (
          <div style={{ padding: '12px 16px', borderRadius: '12px', background: 'rgba(239,68,68,0.14)', border: '1px solid rgba(239,68,68,0.4)', color: '#fca5a5', marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>{errorMsg}</span>
            <button onClick={() => setErrorMsg('')} style={{ background: 'transparent', border: 'none', color: '#fca5a5', cursor: 'pointer', fontWeight: 700 }}>✕</button>
          </div>
        )}

        {/* Navigation Tabs */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '20px' }}>
          {TABS.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                style={{
                  padding: '10px 16px',
                  borderRadius: '10px',
                  border: active ? '1px solid #6366f1' : '1px solid #1e293b',
                  background: active ? 'linear-gradient(135deg, #4f46e5, #6366f1)' : '#111827',
                  color: active ? '#ffffff' : '#cbd5e1',
                  fontWeight: 600,
                  fontSize: '13px',
                  cursor: 'pointer',
                }}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* OVERVIEW TAB */}
        {activeTab === 'overview' && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '14px', marginBottom: '22px' }}>
              {[
                { label: 'Global AI & MCP Tools', val: loadingStats ? '...' : totalCatalog.toLocaleString(), sub: \`\${categoryEntries.length || 88} global categories\` },
                { label: 'REA MCP Tools', val: totalRea, sub: 'morluto/rea v6.8.0 (25 families)' },
                { label: 'LLM Providers', val: stats?.llm_providers || 45, sub: 'OpenAI, Anthropic, Gemini, Groq+' },
                { label: 'Autonomous Agents', val: stats?.agents || 38, sub: 'Research, Coding, Ops, Security' },
                { label: 'Messaging Channels', val: stats?.channels || 37, sub: 'WhatsApp, Slack, Discord, Telegram+' },
                { label: 'Voice & Media Engines', val: stats?.voice_media_tools || 51, sub: 'TTS, STT, Video, Music, Avatar' },
              ].map((card) => (
                <div key={card.label} style={{ padding: '18px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
                  <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '6px' }}>{card.label}</div>
                  <div style={{ fontSize: '28px', fontWeight: 800, color: '#f8fafc' }}>{card.val}</div>
                  <div style={{ fontSize: '12px', color: '#6366f1', marginTop: '4px' }}>{card.sub}</div>
                </div>
              ))}
            </div>

            <div style={{ padding: '20px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
              <h3 style={{ margin: '0 0 14px', fontSize: '16px', fontWeight: 700 }}>Top Global AI Tool Categories (Click to Explore)</h3>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {categoryEntries.slice(0, 32).map(([cat, count]) => (
                  <button
                    key={cat}
                    onClick={() => {
                      setToolCategory(cat);
                      setActiveTab('tools');
                    }}
                    style={{ padding: '7px 12px', borderRadius: '999px', background: '#1e293b', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px', cursor: 'pointer' }}
                  >
                    {cat} <span style={{ color: '#818cf8', fontWeight: 700 }}>({count})</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* TOOLS TAB */}
        {activeTab === 'tools' && (
          <div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: '16px', padding: '16px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
              <input
                value={toolQuery}
                onChange={(e) => setToolQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && fetchTools()}
                placeholder="Search 6,122 AI tools, MCP servers, SDKs, frameworks..."
                style={{ flex: '1 1 260px', padding: '10px 14px', borderRadius: '10px', background: '#090d16', border: '1px solid #334155', color: '#f8fafc', fontSize: '14px' }}
              />
              <select
                value={toolCategory}
                onChange={(e) => setToolCategory(e.target.value)}
                style={{ padding: '10px 12px', borderRadius: '10px', background: '#090d16', border: '1px solid #334155', color: '#f8fafc', fontSize: '13px' }}
              >
                <option value="">All Categories ({categoryEntries.length || 88})</option>
                {categoryEntries.map(([cat, count]) => (
                  <option key={cat} value={cat}>{cat} ({count})</option>
                ))}
              </select>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: '#cbd5e1', padding: '0 8px', cursor: 'pointer' }}>
                <input type="checkbox" checked={mcpOnly} onChange={(e) => setMcpOnly(e.target.checked)} />
                MCP Servers Only
              </label>
              <button
                onClick={fetchTools}
                style={{ padding: '10px 18px', borderRadius: '10px', background: '#4f46e5', border: 'none', color: '#fff', fontWeight: 700, cursor: 'pointer' }}
              >
                {loadingTools ? 'Searching...' : 'Search'}
              </button>
            </div>

            <div style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '12px' }}>
              Showing {toolsData.items.length} of {toolsData.total.toLocaleString()} matching tools
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '14px' }}>
              {toolsData.items.map((tool) => (
                <div key={tool.id} style={{ padding: '16px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'flex-start' }}>
                      <div style={{ fontWeight: 700, fontSize: '15px', color: '#f8fafc' }}>{tool.name || tool.id}</div>
                      <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '999px', background: 'rgba(99,102,241,0.18)', color: '#a5b4fc', whiteSpace: 'nowrap' }}>
                        {tool.category || tool.kind || 'ai-tool'}
                      </span>
                    </div>
                    <p style={{ fontSize: '13px', color: '#94a3b8', margin: '8px 0 12px', lineHeight: 1.45 }}>
                      {String(tool.description || 'Indexed AI capability in Universal AI Backend.').slice(0, 150)}
                    </p>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px', color: '#64748b' }}>
                    <span>{tool.stars ? \`★ \${Number(tool.stars).toLocaleString()}\` : (tool.kind || tool.protocol || 'ready')}</span>
                    {(tool.url || tool.repository_url || tool.homepage) && (
                      <a
                        href={tool.url || tool.repository_url || tool.homepage}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: '#818cf8', textDecoration: 'none', fontWeight: 600 }}
                      >
                        Open Source ↗
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* REA TAB */}
        {activeTab === 'rea' && (
          <div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: '16px', padding: '16px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
              <input
                value={reaQuery}
                onChange={(e) => setReaQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && fetchRea()}
                placeholder="Search 229 REA reverse-engineering & AI model/GPU analysis tools..."
                style={{ flex: '1 1 260px', padding: '10px 14px', borderRadius: '10px', background: '#090d16', border: '1px solid #334155', color: '#f8fafc', fontSize: '14px' }}
              />
              <select
                value={reaFamily}
                onChange={(e) => setReaFamily(e.target.value)}
                style={{ padding: '10px 12px', borderRadius: '10px', background: '#090d16', border: '1px solid #334155', color: '#f8fafc', fontSize: '13px' }}
              >
                <option value="">All 25 REA Tool Families</option>
                {Object.entries(reaTools.families || {}).map(([fam, cnt]) => (
                  <option key={fam} value={fam}>{fam} ({cnt})</option>
                ))}
              </select>
              <button
                onClick={fetchRea}
                style={{ padding: '10px 18px', borderRadius: '10px', background: '#4f46e5', border: 'none', color: '#fff', fontWeight: 700, cursor: 'pointer' }}
              >
                {loadingRea ? 'Loading...' : 'Filter REA Tools'}
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: '12px' }}>
              {reaTools.items.map((rt) => (
                <div key={rt.name} style={{ padding: '15px', borderRadius: '12px', background: '#111827', border: '1px solid #1f2937' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <code style={{ fontSize: '13px', fontWeight: 700, color: '#38bdf8' }}>{rt.name}</code>
                    <span style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '999px', background: '#1e293b', color: '#cbd5e1' }}>{rt.family}</span>
                  </div>
                  <p style={{ fontSize: '12px', color: '#94a3b8', margin: 0 }}>{rt.description}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* MODELS & CHAT TAB */}
        {activeTab === 'models' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '18px' }}>
            <div style={{ padding: '20px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
              <h3 style={{ margin: '0 0 12px', fontSize: '16px', fontWeight: 700 }}>Live Multi-Provider AI Chat</h3>
              <form onSubmit={handleChatSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <select
                  value={chatProvider}
                  onChange={(e) => setChatProvider(e.target.value)}
                  style={{ padding: '10px 12px', borderRadius: '10px', background: '#090d16', border: '1px solid #334155', color: '#f8fafc', fontSize: '13px' }}
                >
                  {(providersList.length > 0 ? providersList : [
                    { id: 'groq', name: 'Groq' },
                    { id: 'openai', name: 'OpenAI' },
                    { id: 'anthropic', name: 'Anthropic' },
                    { id: 'gemini', name: 'Google Gemini' },
                    { id: 'deepseek', name: 'DeepSeek' },
                    { id: 'openrouter', name: 'OpenRouter' },
                  ]).map((p) => (
                    <option key={p.id} value={p.id}>{p.name || p.id}</option>
                  ))}
                </select>
                <textarea
                  rows={4}
                  value={chatPrompt}
                  onChange={(e) => setChatPrompt(e.target.value)}
                  style={{ padding: '12px', borderRadius: '10px', background: '#090d16', border: '1px solid #334155', color: '#f8fafc', fontSize: '13px' }}
                />
                <button
                  type="submit"
                  disabled={chatBusy}
                  style={{ padding: '11px 16px', borderRadius: '10px', background: '#4f46e5', border: 'none', color: '#fff', fontWeight: 700, cursor: 'pointer' }}
                >
                  {chatBusy ? 'Running Completion...' : 'Send via universalAiBackend'}
                </button>
              </form>
              {chatReply && (
                <pre style={{ marginTop: '14px', padding: '12px', borderRadius: '10px', background: '#090d16', border: '1px solid #1e293b', color: '#e2e8f0', fontSize: '12px', whiteSpace: 'pre-wrap', overflowX: 'auto' }}>
                  {JSON.stringify(chatReply, null, 2)}
                </pre>
              )}
            </div>

            <div style={{ padding: '20px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937', maxHeight: '540px', overflowY: 'auto' }}>
              <h3 style={{ margin: '0 0 12px', fontSize: '16px', fontWeight: 700 }}>45 Configured LLM Provider Adapters</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '8px' }}>
                {providersList.map((p) => (
                  <div key={p.id} style={{ padding: '10px', borderRadius: '10px', background: '#090d16', border: '1px solid #1e293b', fontSize: '12px' }}>
                    <div style={{ fontWeight: 700, color: '#f8fafc' }}>{p.name || p.id}</div>
                    <div style={{ color: p.configured ? '#22c55e' : '#64748b', fontSize: '11px', marginTop: '2px' }}>
                      {p.configured ? '● API Key Ready' : '○ Adapter Ready'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* AGENTS, WORKFLOWS & VOICE TAB */}
        {activeTab === 'agents' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            {dispatchResult && (
              <pre style={{ padding: '14px', borderRadius: '12px', background: '#111827', border: '1px solid #4f46e5', color: '#e2e8f0', fontSize: '12px', whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(dispatchResult, null, 2)}
              </pre>
            )}
            <div style={{ padding: '18px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
              <h3 style={{ margin: '0 0 12px', fontSize: '16px', fontWeight: 700 }}>Autonomous Agents ({agentsList.length})</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '10px' }}>
                {agentsList.slice(0, 18).map((ag) => (
                  <div key={ag.id} style={{ padding: '12px', borderRadius: '10px', background: '#090d16', border: '1px solid #1e293b', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '8px' }}>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: '13px', color: '#f8fafc' }}>{ag.name || ag.id}</div>
                      <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>{String(ag.description || '').slice(0, 95)}</div>
                    </div>
                    <button
                      onClick={() => handleDryRunAgent(ag.id)}
                      style={{ alignSelf: 'flex-start', padding: '5px 10px', borderRadius: '8px', background: 'rgba(99,102,241,0.2)', border: '1px solid rgba(99,102,241,0.45)', color: '#c7d2fe', fontSize: '11px', fontWeight: 600, cursor: 'pointer' }}
                    >
                      Dry-Run Agent ▶
                    </button>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
              <div style={{ padding: '16px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
                <h4 style={{ margin: '0 0 10px', fontSize: '15px' }}>Workflows ({workflowsList.length})</h4>
                {workflowsList.slice(0, 10).map((wf) => (
                  <div key={wf.id} style={{ padding: '6px 0', borderBottom: '1px solid #1e293b', fontSize: '12px', color: '#cbd5e1' }}>
                    <strong>{wf.name || wf.id}</strong>
                  </div>
                ))}
              </div>
              <div style={{ padding: '16px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
                <h4 style={{ margin: '0 0 10px', fontSize: '15px' }}>Channels ({channelsList.length})</h4>
                {channelsList.slice(0, 10).map((ch) => (
                  <div key={ch.id} style={{ padding: '6px 0', borderBottom: '1px solid #1e293b', fontSize: '12px', color: '#cbd5e1' }}>
                    <strong>{ch.name || ch.id}</strong>
                  </div>
                ))}
              </div>
              <div style={{ padding: '16px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
                <h4 style={{ margin: '0 0 10px', fontSize: '15px' }}>Voice & Media Engines ({voiceList.length})</h4>
                {voiceList.slice(0, 10).map((vm) => (
                  <div key={vm.id} style={{ padding: '6px 0', borderBottom: '1px solid #1e293b', fontSize: '12px', color: '#cbd5e1' }}>
                    <strong>{vm.name || vm.id}</strong> · <span style={{ color: '#818cf8' }}>{vm.modality || vm.category || 'voice/media'}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* LIVE GITHUB DISCOVERY TAB */}
        {activeTab === 'discover' && (
          <div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: '16px', padding: '16px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
              <select
                value={selectedPreset}
                onChange={(e) => {
                  setSelectedPreset(e.target.value);
                  runGithubSearch(e.target.value);
                }}
                style={{ padding: '10px 12px', borderRadius: '10px', background: '#090d16', border: '1px solid #334155', color: '#f8fafc', fontSize: '13px' }}
              >
                {presets.length === 0 && <option value="mcp-servers">MCP Servers</option>}
                {presets.map((p) => (
                  <option key={p.id} value={p.id}>{p.label || p.id}</option>
                ))}
              </select>
              <input
                value={ghQuery}
                onChange={(e) => setGhQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && runGithubSearch()}
                placeholder="Optional extra GitHub search terms..."
                style={{ flex: '1 1 220px', padding: '10px 14px', borderRadius: '10px', background: '#090d16', border: '1px solid #334155', color: '#f8fafc', fontSize: '14px' }}
              />
              <button
                onClick={() => runGithubSearch()}
                style={{ padding: '10px 18px', borderRadius: '10px', background: '#4f46e5', border: 'none', color: '#fff', fontWeight: 700, cursor: 'pointer' }}
              >
                {loadingGh ? 'Searching GitHub...' : 'Discover Live'}
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '14px' }}>
              {ghResults.map((repo) => (
                <div key={repo.full_name || repo.html_url || repo.id} style={{ padding: '16px', borderRadius: '14px', background: '#111827', border: '1px solid #1f2937' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                    <a href={repo.html_url || repo.url} target="_blank" rel="noreferrer" style={{ fontWeight: 700, fontSize: '14px', color: '#818cf8', textDecoration: 'none' }}>
                      {repo.full_name || repo.name} ↗
                    </a>
                    <span style={{ fontSize: '12px', color: '#fbbf24' }}>★ {Number(repo.stargazers_count || repo.stars || 0).toLocaleString()}</span>
                  </div>
                  <p style={{ fontSize: '12px', color: '#94a3b8', margin: '8px 0 0' }}>
                    {String(repo.description || '').slice(0, 140)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
`;
}

function buildFloatingMountCode(hasNativeRoute = false) {
  return `import React, { useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import UniversalAiHub from './pages/UniversalAiHub';

const HAS_NATIVE_ROUTE = ${JSON.stringify(Boolean(hasNativeRoute))};

function UniversalAiFloatingLauncher() {
  const [open, setOpen] = useState(() => {
    if (typeof window === 'undefined') return false;
    if (window.location.hash === '#universal-ai-hub') return true;
    if (!HAS_NATIVE_ROUTE && window.location.pathname.toLowerCase().includes('universalaihub')) return true;
    return false;
  });
  const [pathname, setPathname] = useState(
    typeof window !== 'undefined' ? window.location.pathname : '/'
  );

  useEffect(() => {
    const syncPath = () => {
      const next = window.location.pathname;
      setPathname(next);
      if (!HAS_NATIVE_ROUTE && next.toLowerCase().includes('universalaihub')) {
        setOpen(true);
      }
    };
    window.addEventListener('popstate', syncPath);
    return () => window.removeEventListener('popstate', syncPath);
  }, []);

  if (HAS_NATIVE_ROUTE && pathname.toLowerCase().includes('universalaihub')) {
    return null;
  }

  const openFullRoute = () => {
    window.history.pushState({}, '', '/UniversalAiHub');
    window.dispatchEvent(new PopStateEvent('popstate'));
    setPathname('/UniversalAiHub');
    if (!HAS_NATIVE_ROUTE) {
      setOpen(true);
    }
  };

  const handleClose = () => {
    setOpen(false);
    if (window.location.pathname.toLowerCase().includes('universalaihub')) {
      window.history.pushState({}, '', '/');
      window.dispatchEvent(new PopStateEvent('popstate'));
      setPathname('/');
    }
  };

  return (
    <>
      {!open && (
        <div
          style={{
            position: 'fixed',
            right: '18px',
            bottom: '18px',
            zIndex: 9990,
            display: 'flex',
            gap: '6px',
            alignItems: 'center',
          }}
        >
          <button
            type="button"
            onClick={() => setOpen(true)}
            title="Open Universal AI Command Hub (6,351 AI & MCP Tools)"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 15px',
              borderRadius: '999px',
              border: '1px solid rgba(129, 140, 248, 0.55)',
              background: 'linear-gradient(135deg, #312e81 0%, #4f46e5 100%)',
              color: '#ffffff',
              fontFamily: 'Inter, system-ui, sans-serif',
              fontSize: '13px',
              fontWeight: 700,
              boxShadow: '0 10px 28px rgba(79, 70, 229, 0.45)',
              cursor: 'pointer',
            }}
          >
            <span style={{ width: '8px', height: '8px', borderRadius: '999px', background: '#4ade80', boxShadow: '0 0 8px #4ade80' }} />
            <span>Universal AI Hub</span>
          </button>
          <button
            type="button"
            onClick={openFullRoute}
            title="Open /UniversalAiHub"
            style={{
              padding: '10px 11px',
              borderRadius: '999px',
              border: '1px solid rgba(148, 163, 184, 0.35)',
              background: 'rgba(15, 23, 42, 0.92)',
              color: '#cbd5e1',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            ↗
          </button>
        </div>
      )}

      {open && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            overflowY: 'auto',
            background: 'rgba(5, 8, 17, 0.98)',
          }}
        >
          <UniversalAiHub onCloseModal={handleClose} />
        </div>
      )}
    </>
  );
}

if (typeof document !== 'undefined' && !document.getElementById('uaib-floating-launcher-root')) {
  const host = document.createElement('div');
  host.id = 'uaib-floating-launcher-root';
  document.body.appendChild(host);
  createRoot(host).render(<UniversalAiFloatingLauncher />);
}
`;
}

export function injectUniversalHubIntoViteApp(projectDir, backendUrl) {
  const srcDir = path.join(projectDir, "src");
  fs.mkdirSync(path.join(srcDir, "lib"), { recursive: true });
  fs.mkdirSync(path.join(srcDir, "pages"), { recursive: true });

  const hasApiClient =
    fs.existsSync(path.join(srcDir, "api", "base44Client.js")) ||
    fs.existsSync(path.join(srcDir, "api", "base44Client.ts")) ||
    fs.existsSync(path.join(srcDir, "api", "base44Client.jsx"));

  fs.writeFileSync(
    path.join(srcDir, "lib", "universalAiBackend.js"),
    buildFrontendSdkCode(hasApiClient, backendUrl),
    "utf8"
  );
  fs.writeFileSync(
    path.join(srcDir, "pages", "UniversalAiHub.jsx"),
    buildHubPageCode(),
    "utf8"
  );
  // Patch src/pages.config.(js|jsx|ts|tsx) so /UniversalAiHub is a native route
  let patchedPagesConfig = false;
  for (const candidate of ["pages.config.js", "pages.config.jsx", "pages.config.ts", "pages.config.tsx"]) {
    const cfgPath = path.join(srcDir, candidate);
    if (!fs.existsSync(cfgPath)) continue;
    let content = fs.readFileSync(cfgPath, "utf8");
    if (!content.includes("UniversalAiHub")) {
      const importStmt = "import UniversalAiHub from './pages/UniversalAiHub';\n";
      const pagesMatch = content.match(/(?:export\s+)?const\s+PAGES\s*=\s*\{/);
      if (pagesMatch && pagesMatch.index !== undefined) {
        content =
          content.slice(0, pagesMatch.index) +
          importStmt +
          content.slice(pagesMatch.index).replace(
            /(?:export\s+)?const\s+PAGES\s*=\s*\{/,
            (m) => `${m}\n    "UniversalAiHub": UniversalAiHub,`
          );
        fs.writeFileSync(cfgPath, content, "utf8");
        patchedPagesConfig = true;
      }
    } else {
      patchedPagesConfig = true;
    }
    break;
  }

  fs.writeFileSync(
    path.join(srcDir, "uaib-mount.jsx"),
    buildFloatingMountCode(patchedPagesConfig),
    "utf8"
  );

  // Patch src/main.(jsx|tsx|js|ts) to mount the floating Universal AI Hub launcher
  let patchedEntry = false;
  for (const entryName of ["main.jsx", "main.tsx", "main.js", "main.ts", "index.jsx", "index.tsx"]) {
    const entryPath = path.join(srcDir, entryName);
    if (!fs.existsSync(entryPath)) continue;
    let entryContent = fs.readFileSync(entryPath, "utf8");
    if (!entryContent.includes("uaib-mount")) {
      entryContent = `${entryContent.trimEnd()}\nimport './uaib-mount.jsx';\n`;
      fs.writeFileSync(entryPath, entryContent, "utf8");
    }
    patchedEntry = true;
    break;
  }

  return { hasApiClient, patchedPagesConfig, patchedEntry };
}

async function recordSupabaseSyncRun(row) {
  if (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) return;
  try {
    await fetch(`${SUPABASE_URL}/rest/v1/uaib_base44_sync_runs`, {
      method: "POST",
      headers: {
        apikey: SUPABASE_SERVICE_ROLE_KEY,
        Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify(row),
    });
  } catch (err) {
    log(`Supabase telemetry warning: ${err?.message || err}`);
  }
}

async function syncSingleApp(app) {
  const appId = app.id;
  const appName = app.name || appId;
  log(`=== Provisioning Base44 app: ${appName} (${appId}) ===`);

  const report = {
    app_id: appId,
    app_name: appName,
    secrets_synced: false,
    backend_fn_deployed: false,
    agent_synced: false,
    mcp_status: "skipped",
    eject_status: "pending",
    vite_build_ok: false,
    deploy_dist_status: "pending",
    published_url: null,
    details: {},
  };

  // 1. Secrets
  const secretsPayload = { UNIVERSAL_AI_BACKEND_URL: BACKEND_PUBLIC_URL };
  if (BACKEND_API_KEY) {
    secretsPayload.UNIVERSAL_AI_BACKEND_API_KEY = BACKEND_API_KEY;
  }
  const secRes = await b44Json("POST", `/api/apps/${appId}/secrets`, secretsPayload);
  report.secrets_synced = secRes.ok;
  report.details.secrets_http = secRes.status;

  // 2. Backend Function (universalAiBackend)
  const fnRes = await b44Json("PUT", `/api/apps/${appId}/backend-functions/universalAiBackend`, {
    name: "universalAiBackend",
    entry: "index.ts",
    files: [{ path: "index.ts", content: buildBackendFunctionCode(BACKEND_PUBLIC_URL) }],
  });
  report.backend_fn_deployed = fnRes.ok;
  report.details.backend_fn_http = fnRes.status;

  // 3. Native Base44 Agent Sync (/agent-configs)
  const existingAgentsRes = await b44Json("GET", `/api/apps/${appId}/agent-configs`);
  if (existingAgentsRes.ok) {
    const rawList = Array.isArray(existingAgentsRes.data)
      ? existingAgentsRes.data
      : Array.isArray(existingAgentsRes.data?.items)
      ? existingAgentsRes.data.items
      : [];
    const kept = rawList.filter((a) => a && a.name !== "universal_ai_hub_agent");
    kept.push({
      name: "universal_ai_hub_agent",
      description:
        "Universal AI Hub Agent connected to 6,122+ AI & MCP tools, 229 REA reverse-engineering tools, 45 LLM providers, 38 agents, 27 workflows, and live GitHub AI discovery.",
      instructions:
        "Use the `universalAiBackend` backend function tool (`{ action, payload }`) to search tools (`stats`, `tools`), inspect REA tools (`rea_status`, `rea_tools`), list/run providers, agents, workflows, channels, voice models, and discover GitHub AI repositories (`discover_github`).",
      tool_configs: [
        {
          function_name: "universalAiBackend",
          description:
            "Invoke Universal AI Backend actions: health, stats, tools, tool_detail, rea_status, rea_tools, providers, agents, agent_run, workflows, workflow_run, channels, voice_models, discover_categories, discover_github, chat.",
        },
      ],
    });
    const putAgentsRes = await b44Json("PUT", `/api/apps/${appId}/agent-configs`, kept);
    report.agent_synced = putAgentsRes.ok;
    report.details.agent_sync_http = putAgentsRes.status;
    report.details.total_agents = kept.length;
  } else {
    report.details.agent_get_http = existingAgentsRes.status;
  }

  // 4. Base44 MCP Check
  try {
    const mcpCtrl = new AbortController();
    const mcpTimer = setTimeout(() => mcpCtrl.abort(), 25000);
    const mcpResp = await fetch(`${BASE44_API_URL}/mcp`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${BASE44_TOKEN}`,
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: "1",
        method: "tools/list",
        params: {},
      }),
      signal: mcpCtrl.signal,
    });
    clearTimeout(mcpTimer);
    report.mcp_status = `http_${mcpResp.status}`;
    const mcpText = await mcpResp.text();
    report.details.mcp_preview = mcpText.slice(0, 300);
  } catch (err) {
    report.mcp_status = `err_${err?.name || "timeout"}`;
  }

  // 5. Eject -> Inject UniversalAiHub -> Vite Build -> Deploy Dist!
  const tmpBase = fs.mkdtempSync(path.join(os.tmpdir(), `b44-${appId}-`));
  try {
    const ejectResp = await fetch(`${BASE44_API_URL}/api/apps/${appId}/eject`, {
      method: "GET",
      headers: b44Headers({ Accept: "application/gzip, application/x-tar, */*" }),
    });
    report.details.eject_http = ejectResp.status;

    if (!ejectResp.ok) {
      const errTxt = (await ejectResp.text()).slice(0, 250);
      report.eject_status = `http_${ejectResp.status}`;
      report.details.eject_error = errTxt;
    } else {
      const buf = Buffer.from(await ejectResp.arrayBuffer());
      const archiveFile = path.join(tmpBase, "ejected.bin");
      const extractDir = path.join(tmpBase, "project");
      fs.mkdirSync(extractDir, { recursive: true });
      fs.writeFileSync(archiveFile, buf);

      const isGzip = buf.length >= 2 && buf[0] === 0x1f && buf[1] === 0x8b;
      const isZip = buf.length >= 2 && buf[0] === 0x50 && buf[1] === 0x4b;
      if (isGzip) {
        execFileSync("tar", ["-xzf", archiveFile, "-C", extractDir]);
      } else if (isZip) {
        execFileSync("python3", ["-m", "zipfile", "-e", archiveFile, extractDir]);
      } else {
        execFileSync("tar", ["-xf", archiveFile, "-C", extractDir]);
      }

      let projectDir = extractDir;
      if (!fs.existsSync(path.join(projectDir, "package.json"))) {
        const entries = fs.readdirSync(extractDir, { withFileTypes: true }).filter((d) => d.isDirectory());
        if (entries.length === 1 && fs.existsSync(path.join(extractDir, entries[0].name, "package.json"))) {
          projectDir = path.join(extractDir, entries[0].name);
        }
      }

      report.eject_status = "ok";
      report.details.archive_bytes = buf.length;
      const patchInfo = injectUniversalHubIntoViteApp(projectDir, BACKEND_PUBLIC_URL);
      report.details.patch = patchInfo;

      // Install npm dependencies & build Vite production bundle with VITE_BASE44_APP_ID
      try {
        execFileSync("npm", ["install", "--no-audit", "--no-fund"], {
          cwd: projectDir,
          stdio: "pipe",
          timeout: 120000,
        });
      } catch {
        execFileSync("npm", ["install", "--legacy-peer-deps", "--no-audit", "--no-fund"], {
          cwd: projectDir,
          stdio: "pipe",
          timeout: 120000,
        });
      }

      execFileSync("npm", ["run", "build"], {
        cwd: projectDir,
        env: {
          ...process.env,
          VITE_BASE44_APP_ID: appId,
        },
        stdio: "pipe",
        timeout: 120000,
      });

      const distDir = path.join(projectDir, "dist");
      if (fs.existsSync(path.join(distDir, "index.html"))) {
        report.vite_build_ok = true;
        const distTarGz = path.join(tmpBase, "dist.tar.gz");
        execFileSync("tar", ["-czf", distTarGz, "-C", distDir, "."]);
        const distBytes = fs.readFileSync(distTarGz);
        report.details.dist_bytes = distBytes.length;

        const form = new FormData();
        form.append("file", new Blob([distBytes], { type: "application/gzip" }), "dist.tar.gz");

        const deployResp = await fetch(`${BASE44_API_URL}/api/apps/${appId}/deploy-dist`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${BASE44_TOKEN}`,
            "User-Agent": "UniversalAIBackend/0.6.0",
            Accept: "application/json",
          },
          body: form,
        });
        const deployText = await deployResp.text();
        report.deploy_dist_status = `http_${deployResp.status}`;
        try {
          report.details.deploy_response = deployText ? JSON.parse(deployText) : {};
        } catch {
          report.details.deploy_response = { raw: deployText.slice(0, 250) };
        }
      } else {
        report.deploy_dist_status = "missing_dist_index";
      }
    }
  } catch (err) {
    report.details.build_or_deploy_error = String(err?.stderr?.toString?.() || err?.message || err).slice(0, 500);
    if (report.deploy_dist_status === "pending") {
      report.deploy_dist_status = "error";
    }
  } finally {
    fs.rmSync(tmpBase, { recursive: true, force: true });
  }

  // 6. Published URL
  const pubRes = await b44Json("GET", `/api/apps/${appId}/published-url`);
  if (pubRes.ok && pubRes.data) {
    report.published_url = pubRes.data.url || pubRes.data.published_url || report.details?.deploy_response?.app_url || null;
  }

  await recordSupabaseSyncRun(report);
  log(
    `Finished ${appName} (${appId}): secrets=${report.secrets_synced}, fn=${report.backend_fn_deployed}, agent=${report.agent_synced}, eject=${report.eject_status}, build=${report.vite_build_ok}, deploy=${report.deploy_dist_status}, url=${report.published_url}`
  );
  return report;
}

async function main() {
  if (!BASE44_TOKEN) {
    log("BASE44_ACCESS_TOKEN not set; skipping Base44 auto-sync.");
    return;
  }
  const appsRes = await b44Json(
    "GET",
    "/api/apps?sort=-updated_date&fields=id,name,user_description,is_managed_source_code&limit=20"
  );
  if (!appsRes.ok) {
    log(`Failed listing Base44 apps: HTTP ${appsRes.status}`);
    await recordSupabaseSyncRun({
      app_id: "list_apps_error",
      app_name: "Workspace",
      deploy_dist_status: `http_${appsRes.status}`,
      details: { status: appsRes.status },
    });
    return;
  }

  const rawApps = Array.isArray(appsRes.data)
    ? appsRes.data
    : Array.isArray(appsRes.data?.items)
    ? appsRes.data.items
    : Array.isArray(appsRes.data?.apps)
    ? appsRes.data.apps
    : [];

  log(`Discovered ${rawApps.length} Base44 app(s) to sync.`);
  for (const app of rawApps) {
    if (app && app.id) {
      await syncSingleApp(app);
    }
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error("[base44-auto-sync] Fatal error:", err?.message || err);
  });
}
