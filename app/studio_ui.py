"""Single-page Universal AI Studio UI served by the FastAPI control plane.

The page is intentionally dependency-free (no CDN, no bundler) so it works
behind the same origin as the API, including offline and in restricted
preview environments. All requests are relative, so no CORS configuration is
needed and the backend key never has to travel to a third party.
"""

STUDIO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Universal AI Studio</title>
<style>
  :root{
    --bg:#080a10; --bg2:#0d1018; --panel:#11141e; --panel2:#161a26;
    --line:#232838; --line2:#2e3550;
    --text:#e8eaf2; --muted:#8b93a9; --dim:#5f6780;
    --accent:#7c6cf5; --accent2:#22d3ee; --ok:#34d399; --warn:#fbbf24; --bad:#f87171;
    --radius:14px;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{
    margin:0; background:var(--bg); color:var(--text);
    font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  body::before{
    content:""; position:fixed; inset:0; pointer-events:none; z-index:0;
    background:
      radial-gradient(720px 420px at 12% -8%, rgba(124,108,245,.20), transparent 60%),
      radial-gradient(680px 420px at 92% 4%, rgba(34,211,238,.13), transparent 62%);
  }
  a{color:inherit; text-decoration:none}
  ::selection{background:rgba(124,108,245,.35)}

  .shell{position:relative; z-index:1; display:flex; min-height:100vh}

  /* ---------- sidebar ---------- */
  .side{
    width:242px; flex:0 0 242px; border-right:1px solid var(--line);
    background:linear-gradient(180deg, rgba(17,20,30,.92), rgba(10,12,18,.92));
    display:flex; flex-direction:column; position:sticky; top:0; height:100vh;
  }
  .brand{display:flex; align-items:center; gap:10px; padding:18px 18px 14px}
  .mark{
    width:30px; height:30px; border-radius:9px; flex:0 0 30px;
    background:linear-gradient(135deg,var(--accent),var(--accent2));
    display:grid; place-items:center; font-weight:800; color:#080a10; font-size:15px;
    box-shadow:0 6px 18px rgba(124,108,245,.35);
  }
  .brand b{font-size:14px; letter-spacing:.2px; display:block; line-height:1.2}
  .brand span{font-size:11px; color:var(--dim); letter-spacing:.04em}
  nav{padding:6px 10px; display:flex; flex-direction:column; gap:2px; overflow:auto}
  nav a{
    display:flex; align-items:center; gap:10px; padding:9px 11px; border-radius:9px;
    color:var(--muted); font-size:13.5px; border:1px solid transparent; transition:.15s;
  }
  nav a i{font-style:normal; width:17px; text-align:center; font-size:13px; opacity:.8}
  nav a:hover{background:rgba(255,255,255,.04); color:var(--text)}
  nav a.active{
    background:linear-gradient(90deg, rgba(124,108,245,.20), rgba(124,108,245,.05));
    color:#fff; border-color:rgba(124,108,245,.34);
  }
  nav a.active i{opacity:1; color:var(--accent2)}
  .side .foot{margin-top:auto; padding:12px 16px 16px; border-top:1px solid var(--line); font-size:11.5px; color:var(--dim)}
  .dot{width:7px;height:7px;border-radius:50%;display:inline-block;background:var(--dim);margin-right:6px}
  .dot.on{background:var(--ok); box-shadow:0 0 0 3px rgba(52,211,153,.16)}
  .dot.off{background:var(--bad)}

  /* ---------- main ---------- */
  .main{flex:1; min-width:0; display:flex; flex-direction:column}
  .top{
    display:flex; align-items:center; justify-content:space-between; gap:16px;
    padding:16px 26px; border-bottom:1px solid var(--line);
    background:rgba(8,10,16,.72); backdrop-filter:blur(10px); position:sticky; top:0; z-index:5;
  }
  .top h1{margin:0; font-size:17px; letter-spacing:.1px}
  .top p{margin:2px 0 0; font-size:12px; color:var(--dim)}
  .top .actions{display:flex; gap:8px; align-items:center}
  .view{padding:24px 26px 60px; max-width:1220px; width:100%}

  /* ---------- primitives ---------- */
  button,select,input,textarea{font:inherit; color:inherit}
  .btn{
    display:inline-flex; align-items:center; gap:7px; padding:8px 13px; border-radius:9px;
    border:1px solid var(--line2); background:var(--panel2); color:var(--text);
    cursor:pointer; font-size:13px; transition:.15s; white-space:nowrap;
  }
  .btn:hover{background:#1d2230; border-color:#3a4360}
  .btn.primary{
    background:linear-gradient(135deg,var(--accent),#5b4ddb); border-color:transparent;
    box-shadow:0 6px 18px rgba(124,108,245,.28); font-weight:600;
  }
  .btn.primary:hover{filter:brightness(1.08)}
  .btn.ghost{background:transparent}
  .btn:disabled{opacity:.5; cursor:not-allowed}
  .input,select.input{
    padding:9px 12px; border-radius:9px; border:1px solid var(--line2);
    background:#0c0f17; color:var(--text); outline:none; transition:.15s; width:100%;
  }
  .input:focus{border-color:var(--accent); box-shadow:0 0 0 3px rgba(124,108,245,.16)}
  .card{
    background:linear-gradient(180deg,var(--panel),#0f121b);
    border:1px solid var(--line); border-radius:var(--radius); padding:16px;
  }
  .grid{display:grid; gap:14px}
  .muted{color:var(--muted)} .dim{color:var(--dim)}
  .chip{
    display:inline-flex; align-items:center; gap:5px; padding:2px 8px; border-radius:999px;
    border:1px solid var(--line2); background:rgba(255,255,255,.03);
    font-size:11px; color:var(--muted); white-space:nowrap;
  }
  .chip.ok{color:#8ef0c4; border-color:rgba(52,211,153,.32); background:rgba(52,211,153,.10)}
  .chip.warn{color:#ffd88a; border-color:rgba(251,191,36,.32); background:rgba(251,191,36,.10)}
  .chip.bad{color:#ffa8a8; border-color:rgba(248,113,113,.32); background:rgba(248,113,113,.10)}
  .chip.acc{color:#c9c1ff; border-color:rgba(124,108,245,.34); background:rgba(124,108,245,.12)}
  h2.sec{font-size:13px; text-transform:uppercase; letter-spacing:.10em; color:var(--dim); margin:26px 0 12px; font-weight:600}
  .row{display:flex; gap:10px; flex-wrap:wrap; align-items:center}

  /* ---------- stat cards ---------- */
  .stats{display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px}
  .stat{padding:15px 16px; border-radius:var(--radius); border:1px solid var(--line); background:linear-gradient(180deg,var(--panel),#0e111a); position:relative; overflow:hidden}
  .stat::after{content:""; position:absolute; inset:0 auto 0 0; width:2px; background:linear-gradient(180deg,var(--accent),var(--accent2)); opacity:.85}
  .stat b{display:block; font-size:26px; line-height:1.15; letter-spacing:-.02em}
  .stat span{font-size:11.5px; color:var(--dim); text-transform:uppercase; letter-spacing:.07em}

  /* ---------- bars ---------- */
  .bars{display:flex; flex-direction:column; gap:9px}
  .bar{display:grid; grid-template-columns:190px 1fr 52px; gap:12px; align-items:center; font-size:12.5px}
  .bar .track{height:7px; border-radius:999px; background:#1a1f2c; overflow:hidden}
  .bar .fill{height:100%; border-radius:999px; background:linear-gradient(90deg,var(--accent),var(--accent2))}
  .bar .num{text-align:right; color:var(--muted); font-variant-numeric:tabular-nums}

  /* ---------- catalog ---------- */
  .filters{display:grid; grid-template-columns:1.7fr 1fr 1fr 1fr; gap:10px; margin-bottom:6px}
  .tool-card{display:flex; flex-direction:column; gap:8px; transition:.15s}
  .tool-card:hover{border-color:var(--line2); transform:translateY(-1px)}
  .tool-card h3{margin:0; font-size:14.5px; display:flex; align-items:center; gap:8px; flex-wrap:wrap}
  .tool-card p{margin:0; color:var(--muted); font-size:12.5px; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden}
  .tool-card .meta{display:flex; gap:6px; flex-wrap:wrap; margin-top:auto; padding-top:4px}
  /* ---------- chat ---------- */
  .chat-wrap{display:grid; grid-template-columns:290px 1fr; gap:14px; height:calc(100vh - 210px); min-height:460px}
  .chat-side{display:flex; flex-direction:column; gap:12px; overflow:auto}
  .chat-main{display:flex; flex-direction:column; border:1px solid var(--line); border-radius:var(--radius); background:var(--panel); overflow:hidden}
  .msgs{flex:1; overflow:auto; padding:18px; display:flex; flex-direction:column; gap:14px}
  .msg{display:flex; gap:10px; max-width:100%}
  .msg .who{width:26px;height:26px;border-radius:8px;flex:0 0 26px;display:grid;place-items:center;font-size:11px;font-weight:700}
  .msg.user .who{background:#1d2230; color:#c9c1ff}
  .msg.assistant .who{background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#080a10}
  .msg .body{background:#131722; border:1px solid var(--line); border-radius:12px; padding:10px 13px; white-space:pre-wrap; word-break:break-word; font-size:13.5px}
  .msg.user .body{background:#171c2a}
  .composer{border-top:1px solid var(--line); padding:12px; display:flex; gap:9px; align-items:flex-end; background:#0c0f17}
  .composer textarea{resize:none; min-height:44px; max-height:170px; padding:11px 13px; border-radius:10px; border:1px solid var(--line2); background:#0a0d14; color:var(--text); outline:none; flex:1; font-size:13.5px}
  .composer textarea:focus{border-color:var(--accent)}
  .empty{display:grid; place-items:center; height:100%; text-align:center; color:var(--dim); gap:8px; padding:30px}

  /* ---------- lists ---------- */
  .prov{display:flex; align-items:center; justify-content:space-between; gap:12px; padding:11px 14px; border:1px solid var(--line); border-radius:11px; background:var(--panel); transition:.15s}
  .prov:hover{border-color:var(--line2)}
  .prov .name{font-size:13.5px; display:flex; align-items:center; gap:8px; flex-wrap:wrap}
  .prov code{font-size:11px; color:var(--dim); background:#0c0f17; padding:1px 6px; border-radius:5px; border:1px solid var(--line)}

  .banner{display:flex; gap:11px; align-items:flex-start; padding:12px 14px; border-radius:11px; border:1px solid rgba(251,191,36,.28); background:rgba(251,191,36,.07); font-size:12.5px; color:#f0d79a}
  .banner b{color:#ffe6ae}
  .banner.err{border-color:rgba(248,113,113,.30); background:rgba(248,113,113,.07); color:#ffb4b4}
  .banner.ok{border-color:rgba(52,211,153,.28); background:rgba(52,211,153,.07); color:#9defc8}

  /* ---------- modal ---------- */
  .modal-bg{position:fixed; inset:0; background:rgba(4,6,10,.72); backdrop-filter:blur(4px); display:none; place-items:center; z-index:50; padding:20px}
  .modal-bg.show{display:grid}
  .modal{width:min(480px,100%); background:var(--panel); border:1px solid var(--line2); border-radius:16px; padding:20px; box-shadow:0 30px 80px rgba(0,0,0,.6)}
  .modal h3{margin:0 0 4px; font-size:16px}
  .modal p{margin:0 0 14px; font-size:12.5px; color:var(--dim)}

  .skel{height:74px; border-radius:11px; background:linear-gradient(90deg,#12151f,#1a1f2c,#12151f); background-size:200% 100%; animation:sh 1.2s infinite}
  @keyframes sh{0%{background-position:200% 0}100%{background-position:-200% 0}}
  .spin{display:inline-block; width:13px;height:13px;border-radius:50%;border:2px solid rgba(255,255,255,.25);border-top-color:#fff;animation:sp .7s linear infinite}
  @keyframes sp{to{transform:rotate(360deg)}}

  @media (max-width:980px){
    .shell{flex-direction:column}
    .side{width:100%; flex:none; height:auto; position:relative; flex-direction:column}
    nav{flex-direction:row; overflow-x:auto; padding:0 10px 10px}
    nav a{white-space:nowrap}
    .side .foot{display:none}
    .chat-wrap{grid-template-columns:1fr; height:auto}
    .chat-main{height:66vh}
    .filters{grid-template-columns:1fr 1fr}
    .bar{grid-template-columns:130px 1fr 44px}
    .view{padding:18px 16px 50px}
    .top{padding:14px 16px}
  }
</style>
</head>
<body>
<div class="shell">
  <aside class="side">
    <div class="brand">
      <div class="mark">U</div>
      <div><b>Universal AI</b><span>STUDIO · v0.6</span></div>
    </div>
    <nav id="nav">
      <a href="#/overview" data-r="overview"><i>◎</i>Overview</a>
      <a href="#/catalog" data-r="catalog"><i>⌕</i>Catalog</a>
      <a href="#/chat" data-r="chat"><i>✦</i>Chat</a>
      <a href="#/providers" data-r="providers"><i>◈</i>Providers</a>
      <a href="#/agents" data-r="agents"><i>⚙</i>Agents</a>
      <a href="#/workflows" data-r="workflows"><i>⇄</i>Workflows</a>
      <a href="#/discovery" data-r="discovery"><i>↗</i>Discovery</a>
      <a href="#/finance" data-r="finance"><i>▤</i>Finance</a>
    </nav>
    <div class="foot">
      <div><span class="dot" id="healthDot"></span><span id="healthText">checking API…</span></div>
      <div style="margin-top:6px"><a href="/docs" target="_blank">OpenAPI docs ↗</a> · <a href="/explorer" target="_blank">Explorer ↗</a></div>
    </div>
  </aside>

  <div class="main">
    <header class="top">
      <div>
        <h1 id="title">Overview</h1>
        <p id="subtitle">Live control plane for the AI catalog, providers and workers</p>
      </div>
      <div class="actions">
        <button class="btn ghost" id="keyBtn" title="Set backend API key">⚿ API key</button>
        <a class="btn" href="/docs" target="_blank">Docs</a>
      </div>
    </header>
    <main class="view" id="view"></main>
  </div>
</div>

<div class="modal-bg" id="modal">
  <div class="modal">
    <h3>Backend API key</h3>
    <p>Sent as the <code>X-API-Key</code> header to protected routes (chat, finance, campaigns). Stored only in this browser's localStorage — never sent anywhere else.</p>
    <input class="input" id="keyInput" type="password" placeholder="Paste BACKEND_API_KEY" autocomplete="off" />
    <div class="row" style="margin-top:12px; justify-content:flex-end">
      <button class="btn ghost" id="keyClear">Clear</button>
      <button class="btn primary" id="keySave">Save</button>
    </div>
  </div>
</div>

<script>
"use strict";
const $ = (s, r) => (r || document).querySelector(s);
const view = $("#view");
const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n) => (n == null ? "—" : Number(n).toLocaleString());
const getKey = () => { try { return localStorage.getItem("uai_key") || ""; } catch (e) { return ""; } };

async function api(path, opts) {
  const o = Object.assign({ headers: {} }, opts || {});
  o.headers = Object.assign({}, o.headers);
  const k = getKey();
  if (k) o.headers["X-API-Key"] = k;
  if (o.body) o.headers["Content-Type"] = "application/json";
  const res = await fetch(path, o);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    const detail = data && (data.detail || data.error) ? (data.detail || data.error) : ("HTTP " + res.status);
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

/* ---------------- health ---------------- */
async function checkHealth() {
  try {
    await api("/health");
    $("#healthDot").className = "dot on";
    $("#healthText").textContent = "API online";
  } catch (e) {
    $("#healthDot").className = "dot off";
    $("#healthText").textContent = "API unreachable";
  }
}

/* ---------------- router ---------------- */
const ROUTES = ["overview", "catalog", "chat", "providers", "agents", "workflows", "discovery", "finance"];
const TITLES = {
  overview: ["Overview", "Live control plane for the AI catalog, providers and workers"],
  catalog: ["Catalog", "6,000+ AI tools, MCP servers and agent projects — metadata only, nothing is executed"],
  chat: ["Chat", "Multi-provider chat proxy — 48 adapters, key stays server-side"],
  providers: ["Providers", "LLM & multimodal adapters and whether each one is configured"],
  agents: ["Agents", "Bounded agent blueprints with risk levels and approval rules"],
  workflows: ["Workflows", "Multi-step pipelines and the services they require"],
  discovery: ["Discovery", "Live GitHub search across AI category presets"],
  finance: ["Finance", "Earning fleet blueprint and the revenue ledger boundary"]
};

function currentRoute() {
  const r = (location.hash || "").replace(/^#\//, "");
  return ROUTES.includes(r) ? r : "overview";
}

function render() {
  const r = currentRoute();
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.r === r));
  $("#title").textContent = TITLES[r][0];
  $("#subtitle").textContent = TITLES[r][1];
  view.innerHTML = '<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>';
  const fn = { overview: renderOverview, catalog: renderCatalog, chat: renderChat, providers: renderProviders,
               agents: renderAgents, workflows: renderWorkflows, discovery: renderDiscovery, finance: renderFinance }[r];
  Promise.resolve().then(fn).catch(err => {
    view.innerHTML = '<div class="banner err"><div><b>Could not load this view.</b><br>' + esc(err.message) + '</div></div>';
  });
}
window.addEventListener("hashchange", render);

/* ---------------- overview ---------------- */
async function renderOverview() {
  const [stats, prov, caps] = await Promise.all([
    api("/v1/catalog/stats").catch(() => null),
    api("/v1/models/providers").catch(() => null),
    api("/v1/runtime/capabilities").catch(() => null)
  ]);
  const total = stats ? stats.total_tools : null;
  const cats = stats && stats.categories ? Object.entries(stats.categories).sort((a, b) => b[1] - a[1]) : [];
  const max = cats.length ? cats[0][1] : 1;
  const workers = caps ? caps.workers || [] : [];
  const readyWorkers = caps ? caps.ready_workers : 0;
  const readyProv = prov && prov.items ? prov.items.filter(p => p.runtime_status && p.runtime_status.ready).length : 0;

  view.innerHTML =
    '<div class="stats">' +
      statCard(num(total), "Catalog entries") +
      statCard(cats.length, "Categories") +
      statCard(readyProv + " / " + (prov ? prov.total : "—"), "Providers configured") +
      statCard(readyWorkers + " / " + (caps ? caps.total_worker_types : "—"), "Workers ready") +
    '</div>' +

    '<div class="grid" style="grid-template-columns:1.35fr 1fr; margin-top:16px" id="ovGrid">' +
      '<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:12px">' +
        '<b style="font-size:13px">Catalog distribution</b><span class="chip">' + cats.length + ' categories</span></div>' +
        '<div class="bars">' + cats.slice(0, 11).map(([c, n]) =>
          '<div class="bar"><div class="muted" title="' + esc(c) + '" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(c) + '</div>' +
          '<div class="track"><div class="fill" style="width:' + Math.max(2, Math.round(n / max * 100)) + '%"></div></div>' +
          '<div class="num">' + num(n) + '</div></div>').join("") + '</div>' +
        '<div style="margin-top:14px"><button class="btn" onclick="location.hash=\'#/catalog\'">Browse catalog →</button></div>' +
      '</div>' +

      '<div class="card"><b style="font-size:13px">What actually works right now</b>' +
        '<div style="display:flex;flex-direction:column;gap:9px;margin-top:12px;font-size:12.5px">' +
          readyLine(true, "Catalog &amp; search", num(total) + " entries indexed") +
          readyLine(!!prov, "Provider adapters", readyProv + " of " + (prov ? prov.total : "—") + " have credentials") +
          readyLine(readyWorkers > 0, "Worker fleet", readyWorkers + " of " + (caps ? caps.total_worker_types : "—") + " reachable") +
          readyLine(!!getKey(), "Protected routes", getKey() ? "API key saved in this browser" : "No API key stored yet") +
        '</div>' +
        '<div class="banner" style="margin-top:14px"><div><b>Honest scope:</b> a catalog entry is a reference, not an installed or running tool. GPU, voice and desktop jobs need a deployed worker.</div></div>' +
      '</div>' +
    '</div>';

  if (window.innerWidth < 860) $("#ovGrid").style.gridTemplateColumns = "1fr";
}

const statCard = (v, label) => '<div class="stat"><b>' + esc(v) + '</b><span>' + esc(label) + '</span></div>';
const readyLine = (ok, title, sub) =>
  '<div class="row" style="gap:8px"><span class="dot ' + (ok ? 'on' : '') + '" style="margin:0"></span>' +
  '<div style="flex:1"><div>' + title + '</div><div class="dim" style="font-size:11.5px">' + sub + '</div></div>' +
  '<span class="chip ' + (ok ? 'ok' : 'warn') + '">' + (ok ? "ready" : "not set") + '</span></div>';

/* ---------------- catalog ---------------- */
let catState = { q: "", category: "", min_stars: "", language: "", offset: 0, items: [], total: 0 };

async function renderCatalog() {
  const cats = await api("/v1/tools/categories").catch(() => ({ categories: [] }));
  const list = (cats.categories || []).map(c => typeof c === "string" ? c : (c.name || c.id || JSON.stringify(c))).sort();

  view.innerHTML =
    '<div class="filters">' +
      '<input class="input" id="fq" placeholder="Search 6,000+ tools, MCP servers, agents…" autocomplete="off" />' +
      '<select class="input" id="fcat"><option value="">All categories</option>' +
        list.map(c => '<option value="' + esc(c) + '">' + esc(c) + '</option>').join("") + '</select>' +
      '<select class="input" id="fstars"><option value="">Any stars</option><option value="100">100+</option><option value="500">500+</option><option value="1000">1k+</option><option value="5000">5k+</option><option value="10000">10k+</option></select>' +
      '<input class="input" id="flang" placeholder="Language (e.g. Python)" autocomplete="off" />' +
    '</div>' +
    '<div class="row" style="justify-content:space-between;margin:14px 0 12px">' +
      '<div class="dim" id="catCount">Loading…</div>' +
      '<button class="btn ghost" id="catReset">Reset filters</button>' +
    '</div><div class="grid" id="catGrid" style="grid-template-columns:repeat(auto-fill,minmax(310px,1fr))"></div>' +
    '<div style="margin-top:18px;text-align:center"><button class="btn" id="catMore" style="display:none">Load more</button></div>';

  const run = async (append) => {
    if (!append) { catState.offset = 0; catState.items = []; $("#catGrid").innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>'; }
    const p = new URLSearchParams();
    if (catState.q) p.set("q", catState.q);
    if (catState.category) p.set("category", catState.category);
    if (catState.min_stars) p.set("min_stars", catState.min_stars);
    if (catState.language) p.set("language", catState.language);
    p.set("limit", "24"); p.set("offset", String(catState.offset));
    try {
      const data = await api("/v1/tools?" + p.toString());
      catState.total = data.total;
      catState.items = catState.items.concat(data.items);
      catState.offset += data.items.length;
      $("#catCount").textContent = num(data.total) + " result" + (data.total === 1 ? "" : "s");
      if (!append) $("#catGrid").innerHTML = "";
      if (!data.items.length) {
        $("#catGrid").innerHTML = '<div class="card" style="grid-column:1/-1;text-align:center;color:var(--dim)">No matches. Try a broader query or clear the filters.</div>';
      }
      $("#catGrid").insertAdjacentHTML("beforeend", data.items.map(toolCard).join(""));
      $("#catMore").style.display = catState.offset < data.total ? "inline-flex" : "none";
    } catch (e) {
      $("#catGrid").innerHTML = '<div class="banner err" style="grid-column:1/-1">' + esc(e.message) + '</div>';
    }
  };

  let t;
  $("#fq").addEventListener("input", e => { catState.q = e.target.value.trim(); clearTimeout(t); t = setTimeout(() => run(false), 280); });
  $("#fcat").addEventListener("change", e => { catState.category = e.target.value; run(false); });
  $("#fstars").addEventListener("change", e => { catState.min_stars = e.target.value; run(false); });
  $("#flang").addEventListener("input", e => { catState.language = e.target.value.trim(); clearTimeout(t); t = setTimeout(() => run(false), 320); });
  $("#catReset").addEventListener("click", () => {
    catState = { q: "", category: "", min_stars: "", language: "", offset: 0, items: [], total: 0 };
    $("#fq").value = ""; $("#fcat").value = ""; $("#fstars").value = ""; $("#flang").value = "";
    run(false);
  });
  $("#catMore").addEventListener("click", () => run(true));
  run(false);
}

function toolCard(t) {
  const lic = t.license_status;
  const licCls = lic === "permissive" || lic === "mit" ? "ok" : (lic ? "warn" : "");
  return '<div class="card tool-card">' +
    '<h3>' + esc(t.name || t.id) + (t.kind ? '<span class="chip acc">' + esc(t.kind) + '</span>' : '') + '</h3>' +
    '<p>' + esc(t.description || "No description recorded.") + '</p>' +
    '<div class="meta">' +
      (t.category ? '<span class="chip">' + esc(t.category) + '</span>' : '') +
      (t.stars_snapshot ? '<span class="chip">★ ' + num(t.stars_snapshot) + '</span>' : '') +
      (t.primary_language ? '<span class="chip">' + esc(t.primary_language) + '</span>' : '') +
      (lic ? '<span class="chip ' + licCls + '">' + esc(lic) + '</span>' : '') +
    '</div>' +
    (t.repository_url ? '<a class="dim" style="font-size:11.5px;margin-top:6px;word-break:break-all" href="' + esc(t.repository_url) + '" target="_blank" rel="noopener">' + esc(t.repository_url) + ' ↗</a>' : '') +
    '</div>';
}

/* ---------------- chat ---------------- */
async function renderChat() {
  const prov = await api("/v1/models/providers").catch(() => ({ items: [] }));
  const items = prov.items || [];
  view.innerHTML =
    '<div class="chat-wrap">' +
      '<div class="chat-side">' +
        '<div class="card"><b style="font-size:13px">Model route</b>' +
          '<label class="dim" style="font-size:11.5px;display:block;margin:10px 0 4px">Provider</label>' +
          '<select class="input" id="cProv">' + items.map(p =>
            '<option value="' + esc(p.id) + '">' + esc(p.name) + (p.runtime_status && p.runtime_status.ready ? ' ✓' : '') + '</option>').join("") + '</select>' +
          '<label class="dim" style="font-size:11.5px;display:block;margin:10px 0 4px">Model</label>' +
          '<input class="input" id="cModel" placeholder="e.g. llama-3.3-70b-versatile" autocomplete="off" />' +
          '<div class="dim" style="font-size:11px;margin-top:10px" id="cProvHint"></div>' +
        '</div>' +
        '<div class="banner" id="keyWarn" style="display:none"><div><b>Chat needs a key.</b> Add <code>BACKEND_API_KEY</code> to the server <code>.env</code>, then save the same value here.</div></div>' +
        '<button class="btn ghost" id="cClear">Clear conversation</button>' +
      '</div>' +
      '<div class="chat-main">' +
        '<div class="msgs" id="msgs"><div class="empty"><div style="font-size:26px">✦</div><div>Ask anything — the request is proxied server-side to the selected provider.</div></div></div>' +
        '<div class="composer"><textarea id="cInput" placeholder="Message the model…  (Enter to send, Shift+Enter for newline)"></textarea>' +
        '<button class="btn primary" id="cSend">Send</button></div>' +
      '</div>' +
    '</div>';

  const sel = $("#cProv");
  const hint = () => {
    const p = items.find(x => x.id === sel.value);
    if (!p) return;
    $("#cProvHint").innerHTML = "env: <code>" + esc(p.api_key_env || "—") + "</code><br>default model env: <code>" + esc(p.default_model_env || "—") + "</code>";
  };
  sel.addEventListener("change", hint); hint();
  if (!getKey()) $("#keyWarn").style.display = "flex";

  let history = [];
  const addMsg = (role, text) => {
    const box = $("#msgs");
    if (box.querySelector(".empty")) box.innerHTML = "";
    box.insertAdjacentHTML("beforeend",
      '<div class="msg ' + role + '"><div class="who">' + (role === "user" ? "You" : "AI") + '</div><div class="body">' + esc(text) + '</div></div>');
    box.scrollTop = box.scrollHeight;
  };

  const send = async () => {
    const ta = $("#cInput");
    const text = ta.value.trim();
    if (!text) return;
    ta.value = ""; addMsg("user", text);
    history.push({ role: "user", content: text });
    const btn = $("#cSend"); btn.disabled = true; btn.innerHTML = '<span class="spin"></span>';
    const box = $("#msgs");
    const pending = document.createElement("div");
    pending.className = "msg assistant";
    pending.innerHTML = '<div class="who">AI</div><div class="body dim">Thinking…</div>';
    box.appendChild(pending); box.scrollTop = box.scrollHeight;
    try {
      const data = await api("/v1/chat/completions", {
        method: "POST",
        body: JSON.stringify({
          provider: sel.value,
          model: $("#cModel").value.trim(),
          messages: history,
          temperature: 0.7,
          max_tokens: 1024
        })
      });
      const content = data && data.choices && data.choices[0] && data.choices[0].message
        ? data.choices[0].message.content
        : (data && data.content) || JSON.stringify(data);
      pending.remove();
      addMsg("assistant", content);
      history.push({ role: "assistant", content: String(content) });
    } catch (e) {
      pending.remove();
      box.insertAdjacentHTML("beforeend", '<div class="banner err" style="align-self:stretch">' + esc(e.message) + '</div>');
      box.scrollTop = box.scrollHeight;
    } finally {
      btn.disabled = false; btn.textContent = "Send";
    }
  };

  $("#cSend").addEventListener("click", send);
  $("#cInput").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("#cClear").addEventListener("click", () => {
    history = [];
    $("#msgs").innerHTML = '<div class="empty"><div style="font-size:26px">✦</div><div>Conversation cleared.</div></div>';
  });
}

/* ---------------- providers ---------------- */
async function renderProviders() {
  const data = await api("/v1/models/providers");
  const items = data.items || [];
  const ready = items.filter(p => p.runtime_status && p.runtime_status.ready).length;
  view.innerHTML =
    '<div class="row" style="justify-content:space-between;margin-bottom:14px">' +
      '<div class="dim">' + num(ready) + ' of ' + num(data.total) + ' adapters have credentials configured</div>' +
      '<span class="chip ' + (ready ? 'ok' : 'warn') + '">' + (ready ? 'partially configured' : 'no credentials') + '</span>' +
    '</div>' +
    '<div class="grid" id="provGrid" style="grid-template-columns:repeat(auto-fill,minmax(320px,1fr))">' +
    items.map(p => {
      const r = p.runtime_status || {};
      return '<div class="card" style="display:flex;flex-direction:column;gap:8px">' +
        '<div class="row" style="justify-content:space-between"><b style="font-size:13.5px">' + esc(p.name) + '</b>' +
          '<span class="chip ' + (r.ready ? 'ok' : '') + '">' + (r.ready ? 'ready' : 'not configured') + '</span></div>' +
        '<div class="dim" style="font-size:11.5px">' + esc(p.api_mode || '') + ' · ' + esc(p.readiness || '') + '</div>' +
        '<div class="row" style="gap:6px">' + (p.capabilities || []).slice(0, 3).map(c => '<span class="chip">' + esc(c) + '</span>').join("") + '</div>' +
        '<div class="dim" style="font-size:11px;margin-top:auto">key env: <code>' + esc(p.api_key_env || '—') + '</code>' +
          (p.base_url_env ? ' · base: <code>' + esc(p.base_url_env) + '</code>' : '') + '</div>' +
        '</div>';
    }).join("") + '</div>';
}

/* ---------------- agents ---------------- */
async function renderAgents() {
  const data = await api("/v1/agents");
  const items = data.items || [];
  view.innerHTML =
    '<div class="banner"><div><b>' + num(data.total) + ' agent blueprints.</b> A blueprint is a bounded role definition — not a running process. Execution needs the agent worker deployed and approved.</div></div>' +
    '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(330px,1fr));margin-top:14px">' +
    items.map(a => {
      const risk = (a.risk_level || '').toLowerCase();
      const cls = risk === 'high' ? 'bad' : risk === 'medium' ? 'warn' : 'ok';
      return '<div class="card" style="display:flex;flex-direction:column;gap:9px">' +
        '<div class="row" style="justify-content:space-between"><b style="font-size:13.5px">' + esc(a.name) + '</b>' +
          (risk ? '<span class="chip ' + cls + '">' + esc(risk) + ' risk</span>' : '') + '</div>' +
        '<p class="muted" style="margin:0;font-size:12.5px">' + esc(a.mission || '') + '</p>' +
        '<div class="row" style="gap:5px">' + (a.capabilities || []).slice(0, 4).map(c => '<span class="chip">' + esc(c) + '</span>').join("") + '</div>' +
        (a.human_approval_rules ? '<div class="dim" style="font-size:11.5px;border-top:1px solid var(--line);padding-top:8px">✋ ' + esc(a.human_approval_rules) + '</div>' : '') +
        '</div>';
    }).join("") + '</div>';
}

/* ---------------- workflows ---------------- */
async function renderWorkflows() {
  const data = await api("/v1/workflows");
  const items = data.items || [];
  view.innerHTML =
    '<div class="banner"><div><b>' + num(data.total) + ' workflow templates.</b> Each step that causes an external side effect requires human approval and a configured worker.</div></div>' +
    '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(340px,1fr));margin-top:14px">' +
    items.map(w =>
      '<div class="card" style="display:flex;flex-direction:column;gap:9px">' +
        '<div class="row" style="justify-content:space-between"><b style="font-size:13.5px">' + esc(w.name) + '</b>' +
        (w.requires_human_approval ? '<span class="chip warn">approval</span>' : '<span class="chip ok">auto</span>') + '</div>' +
        '<p class="muted" style="margin:0;font-size:12.5px">' + esc(w.description || '') + '</p>' +
        '<div class="row" style="gap:5px">' + (w.category ? '<span class="chip acc">' + esc(w.category) + '</span>' : '') +
          (w.required_services || []).map(s => '<span class="chip">' + esc(s) + '</span>').join("") + '</div>' +
        '<div class="dim" style="font-size:11.5px">' + (w.steps ? w.steps.length : 0) + ' steps</div>' +
      '</div>').join("") + '</div>';
}

/* ---------------- discovery ---------------- */
async function renderDiscovery() {
  const presets = await api("/v1/discover/categories").catch(() => ({ presets: [] }));
  view.innerHTML =
    '<div class="card">' +
      '<div class="filters" style="grid-template-columns:1.6fr 1.4fr 1fr">' +
        '<input class="input" id="dq" placeholder="Search live GitHub repositories…" />' +
        '<select class="input" id="dpre"><option value="">Any category</option>' +
          (presets.presets || []).map(p => '<option value="' + esc(p.id) + '">' + esc(p.label) + '</option>').join("") + '</select>' +
        '<select class="input" id="dstars"><option value="100">100+ stars</option><option value="500" selected>500+</option><option value="1000">1k+</option><option value="5000">5k+</option></select>' +
      '</div>' +
      '<div class="row" style="justify-content:flex-end;margin-top:10px"><button class="btn primary" id="dgo">Search GitHub</button></div>' +
    '</div>' +
    '<div id="dout" style="margin-top:14px"></div>' +
    '<div class="banner" style="margin-top:14px"><div>Live discovery calls the GitHub API from the server. If <code>GITHUB_TOKEN</code> is unset or the network is blocked, this panel shows the upstream error instead of fake results.</div></div>';

  $("#dgo").addEventListener("click", async () => {
    const out = $("#dout");
    const pre = $("#dpre").value;
    const q = $("#dq").value.trim();
    if (!pre && q.length < 2) {
      out.innerHTML = '<div class="banner"><div><b>Pick a category or type at least 2 characters.</b> Live discovery needs a search query or a built-in category preset.</div></div>';
      return;
    }
    out.innerHTML = '<div class="skel"></div><div class="skel" style="margin-top:10px"></div>';
    const p = new URLSearchParams();
    if (pre) p.set("category_preset", pre);
    if (q) p.set("q", q);
    p.set("min_stars", $("#dstars").value);
    try {
      const data = await api("/v1/discover/github?" + p.toString());
      const items = data.items || data.repositories || [];
      if (!items.length) {
        out.innerHTML = '<div class="card dim">No repositories returned. ' + esc(JSON.stringify(data).slice(0, 300)) + '</div>';
        return;
      }
      out.innerHTML = '<div class="dim" style="margin-bottom:10px">' + num(data.total || items.length) + ' repositories</div>' +
        '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(320px,1fr))">' +
        items.map(r =>
          '<div class="card tool-card"><h3>' + esc(r.name || r.full_name || r.id) + '</h3>' +
          '<p>' + esc(r.description || '') + '</p>' +
          '<div class="meta"><span class="chip">★ ' + num(r.stargazers_count || r.stars) + '</span>' +
          (r.language ? '<span class="chip">' + esc(r.language) + '</span>' : '') + '</div>' +
          (r.html_url ? '<a class="dim" style="font-size:11.5px" href="' + esc(r.html_url) + '" target="_blank" rel="noopener">' + esc(r.html_url) + ' ↗</a>' : '') +
          '</div>').join("") + '</div>';
    } catch (e) {
      out.innerHTML = '<div class="banner err"><div><b>Discovery unavailable.</b><br>' + esc(e.message) +
        '<br><span class="dim">Set GITHUB_TOKEN on the server for higher rate limits.</span></div></div>';
    }
  });
}

/* ---------------- finance ---------------- */
async function renderFinance() {
  const fleet = await api("/v1/earning/fleet").catch(() => null);
  view.innerHTML =
    (fleet ?
      '<div class="stats">' +
        statCard(num(fleet.agent_slots), "Agent slots") +
        statCard(num(fleet.department_count), "Departments") +
        statCard("$" + num(fleet.monthly_budget_usd), "Monthly budget") +
        statCard(num(fleet.default_max_parallel), "Max parallel") +
      '</div>' +
      '<div class="card" style="margin-top:14px"><b style="font-size:13px">Execution policy</b>' +
        '<p class="muted" style="font-size:12.5px;margin:8px 0 0">' + esc(fleet.execution_policy) + '</p></div>' +
      '<h2 class="sec">Departments</h2>' +
      '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">' +
        (fleet.departments || []).map(d =>
          '<div class="card"><div class="row" style="justify-content:space-between"><b style="font-size:13px">' + esc(d.name) + '</b>' +
          '<span class="chip">' + num(d.capacity) + ' slots</span></div>' +
          '<p class="dim" style="font-size:12px;margin:7px 0 0">' + esc(d.mission || '') + '</p></div>').join("") +
      '</div>'
    : '<div class="banner err">Fleet manifest unavailable.</div>') +
    '<h2 class="sec">Revenue ledger</h2>' +
    '<div class="card"><div class="row" style="justify-content:space-between"><b style="font-size:13px">Supabase-backed ledger</b>' +
      '<span class="chip" id="ledgerBadge">checking…</span></div>' +
      '<p class="dim" style="font-size:12.5px;margin:8px 0 0">Entries, payout requests and approvals live at <code>/v1/finance/*</code>. They require <code>SUPABASE_URL</code>, a service-role key and the ledger migration.</p>' +
      '<div id="ledgerOut" style="margin-top:12px"></div></div>';

  try {
    const s = await api("/v1/finance/summary");
    $("#ledgerBadge").className = "chip ok"; $("#ledgerBadge").textContent = "connected";
    $("#ledgerOut").innerHTML = '<pre class="dim" style="font-size:11.5px;overflow:auto;margin:0">' + esc(JSON.stringify(s, null, 2)) + '</pre>';
  } catch (e) {
    $("#ledgerBadge").className = "chip warn"; $("#ledgerBadge").textContent = "not configured";
    $("#ledgerOut").innerHTML = '<div class="banner"><div>' + esc(e.message) + '</div></div>';
  }
}

/* ---------------- modal / boot ---------------- */
$("#keyBtn").addEventListener("click", () => {
  $("#keyInput").value = getKey();
  $("#modal").classList.add("show");
  setTimeout(() => $("#keyInput").focus(), 30);
});
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") $("#modal").classList.remove("show"); });
$("#keySave").addEventListener("click", () => {
  try { localStorage.setItem("uai_key", $("#keyInput").value.trim()); } catch (e) {}
  $("#modal").classList.remove("show");
  render();
});
$("#keyClear").addEventListener("click", () => {
  try { localStorage.removeItem("uai_key"); } catch (e) {}
  $("#keyInput").value = "";
  $("#modal").classList.remove("show");
  render();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") $("#modal").classList.remove("show");
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); location.hash = "#/catalog"; setTimeout(() => { const f = $("#fq"); if (f) f.focus(); }, 60); }
});

checkHealth();
setInterval(checkHealth, 30000);
render();
</script>
</body>
</html>
"""
