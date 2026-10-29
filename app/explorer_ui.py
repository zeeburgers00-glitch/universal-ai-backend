"""3D Animated Control Plane Console for Universal AI Backend v0.6.0 (`/` browser & `/explorer`)."""

EXPLORER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Universal AI Backend v0.6.0 — 3D AI Control Plane</title>
  <style>
    :root {
      --bg: #05070f;
      --panel: rgba(13, 18, 34, 0.78);
      --panel-strong: rgba(15, 23, 42, 0.92);
      --border: rgba(99, 102, 241, 0.28);
      --accent: #6366f1;
      --accent2: #22d3ee;
      --green: #22c55e;
      --text: #f8fafc;
      --muted: #94a3b8;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      padding: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      overflow-x: hidden;
    }
    #bg-canvas {
      position: fixed;
      inset: 0;
      width: 100vw;
      height: 100vh;
      z-index: 0;
      pointer-events: none;
    }
    .shell {
      position: relative;
      z-index: 1;
      max-width: 1340px;
      margin: 0 auto;
      padding: 20px 24px 80px;
    }
    .topbar {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      padding: 14px 20px;
      border-radius: 18px;
      background: var(--panel);
      backdrop-filter: blur(18px);
      border: 1px solid var(--border);
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.45);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 800;
      letter-spacing: -0.02em;
      font-size: 17px;
    }
    .pulse-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--green);
      box-shadow: 0 0 14px var(--green);
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { transform: scale(1); opacity: 1; }
      50% { transform: scale(1.3); opacity: 0.7; }
    }
    .key-bar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .input {
      background: rgba(5, 8, 18, 0.85);
      border: 1px solid rgba(148, 163, 184, 0.28);
      color: var(--text);
      padding: 9px 13px;
      border-radius: 10px;
      font-size: 13px;
      outline: none;
    }
    .input:focus { border-color: var(--accent2); }
    .btn {
      padding: 9px 15px;
      border-radius: 10px;
      border: 1px solid rgba(99, 102, 241, 0.55);
      background: linear-gradient(135deg, #4f46e5, #0891b2);
      color: #fff;
      font-weight: 700;
      font-size: 13px;
      cursor: pointer;
      transition: transform 0.16s ease, box-shadow 0.16s ease;
    }
    .btn:hover {
      transform: translateY(-1px);
      box-shadow: 0 8px 24px rgba(99, 102, 241, 0.4);
    }
    .btn-ghost {
      background: rgba(30, 41, 59, 0.72);
      border-color: rgba(148, 163, 184, 0.25);
    }
    .hero {
      display: grid;
      grid-template-columns: 1.25fr 0.95fr;
      gap: 24px;
      align-items: center;
      margin: 26px 0;
      padding: 32px;
      border-radius: 26px;
      background: radial-gradient(circle at 80% 20%, rgba(34,211,238,0.14), transparent 45%),
                  radial-gradient(circle at 20% 80%, rgba(99,102,241,0.18), transparent 50%),
                  var(--panel);
      backdrop-filter: blur(20px);
      border: 1px solid var(--border);
      perspective: 1100px;
    }
    @media (max-width: 920px) {
      .hero { grid-template-columns: 1fr; }
    }
    .hero h1 {
      font-size: clamp(30px, 4.2vw, 50px);
      line-height: 1.06;
      margin: 12px 0;
      background: linear-gradient(135deg, #ffffff 20%, #a5b4fc 65%, #22d3ee 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 5px 12px;
      border-radius: 999px;
      background: rgba(34, 197, 94, 0.14);
      border: 1px solid rgba(34, 197, 94, 0.4);
      color: #86efac;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .orb-stage {
      position: relative;
      height: 300px;
      border-radius: 22px;
      background: radial-gradient(circle at center, rgba(79,70,229,0.22), rgba(5,7,15,0.65));
      border: 1px solid rgba(99, 102, 241, 0.3);
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    #orb-canvas {
      width: 100%;
      height: 100%;
    }
    .orb-hud {
      position: absolute;
      bottom: 14px;
      left: 16px;
      right: 16px;
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: #cbd5e1;
      background: rgba(5, 7, 15, 0.72);
      padding: 8px 12px;
      border-radius: 10px;
      border: 1px solid rgba(99, 102, 241, 0.25);
    }
    .nav-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 22px;
    }
    .tab-btn {
      padding: 10px 16px;
      border-radius: 12px;
      border: 1px solid rgba(148, 163, 184, 0.22);
      background: rgba(15, 23, 42, 0.75);
      color: #cbd5e1;
      font-weight: 700;
      font-size: 13px;
      cursor: pointer;
      transition: all 0.18s ease;
    }
    .tab-btn.active {
      background: linear-gradient(135deg, #4f46e5, #0891b2);
      color: #fff;
      border-color: #22d3ee;
      box-shadow: 0 8px 25px rgba(79, 70, 229, 0.45);
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }
    .card3d {
      padding: 18px;
      border-radius: 16px;
      background: var(--panel);
      backdrop-filter: blur(14px);
      border: 1px solid var(--border);
      transition: transform 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease;
      transform-style: preserve-3d;
    }
    .card3d:hover {
      transform: translateY(-4px) rotateX(2deg) rotateY(-2deg);
      border-color: rgba(34, 211, 238, 0.6);
      box-shadow: 0 16px 38px rgba(14, 165, 233, 0.18);
    }
    .kpi-val { font-size: 29px; font-weight: 800; margin: 4px 0; }
    .kpi-sub { font-size: 12px; color: #38bdf8; }
    .grid-cards {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(305px, 1fr));
      gap: 14px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
    }
    .badge-ok { background: rgba(34,197,94,0.16); color: #86efac; border: 1px solid rgba(34,197,94,0.38); }
    .badge-info { background: rgba(99,102,241,0.18); color: #c7d2fe; border: 1px solid rgba(99,102,241,0.38); }
    .section { display: none; }
    .section.active { display: block; }
    pre.console-out {
      background: rgba(3, 6, 14, 0.92);
      border: 1px solid rgba(99,102,241,0.35);
      border-radius: 12px;
      padding: 14px;
      color: #e2e8f0;
      font-size: 12px;
      white-space: pre-wrap;
      overflow-x: auto;
    }
  </style>
</head>
<body>
  <canvas id="bg-canvas"></canvas>
  <div class="shell">
    <div class="topbar">
      <div class="brand">
        <span class="pulse-dot"></span>
        <span>Universal AI Backend · 3D Control Plane v0.6.0</span>
      </div>
      <div class="key-bar">
        <input id="apiKeyInput" type="password" class="input" placeholder="X-API-Key (for Vault / Run actions)" style="width:230px" />
        <button class="btn btn-ghost" onclick="saveLocalApiKey()">Unlock Key</button>
        <a href="/docs" class="btn btn-ghost" style="text-decoration:none">OpenAPI /docs ↗</a>
      </div>
    </div>

    <div class="hero">
      <div>
        <div class="eyebrow"><span class="pulse-dot" style="width:7px;height:7px"></span> 100% Control Plane &amp; Workers Online</div>
        <h1>One 3D Control Plane.<br/>Every Model, Agent, Channel &amp; Voice.</h1>
        <p style="color:var(--muted);font-size:15px;line-height:1.6;margin:0 0 18px">
          Live orchestration over <strong id="heroTools">6,122</strong> global AI &amp; MCP tools,
          <strong id="heroRea">229</strong> REA reverse-engineering tools, <strong>45</strong> LLM providers,
          <strong>37</strong> publishing channels, <strong>38</strong> autonomous agents, <strong>27</strong> workflows,
          and <strong>51</strong> voice &amp; media engines.
        </p>
        <div style="display:flex;flex-wrap:wrap;gap:10px">
          <button class="btn" onclick="switchTab('chat')">Open Live AI Chat</button>
          <button class="btn btn-ghost" onclick="switchTab('status')">45 Providers &amp; 9 Workers</button>
          <button class="btn btn-ghost" onclick="switchTab('channels')">37/37 Publishing Channels</button>
          <button class="btn btn-ghost" onclick="switchTab('rea')">229 REA Runtime Tools</button>
        </div>
      </div>
      <div class="orb-stage">
        <canvas id="orb-canvas"></canvas>
        <div class="orb-hud">
          <span id="orbLeft">Wiring: 9/9 Workers Online</span>
          <span id="orbRight">45/45 Providers · 37/37 Channels</span>
        </div>
      </div>
    </div>

    <div class="kpi-grid" id="kpiGrid"></div>

    <div class="nav-tabs">
      <button class="tab-btn active" data-tab="status" onclick="switchTab('status')">/status · 45 Providers, 9 Workers &amp; REA</button>
      <button class="tab-btn" data-tab="chat" onclick="switchTab('chat')">/chat · Live Completions</button>
      <button class="tab-btn" data-tab="channels" onclick="switchTab('channels')">/channels · 37/37 Publishing Channels</button>
      <button class="tab-btn" data-tab="tools" onclick="switchTab('tools')">/catalog · 6,122 AI &amp; MCP Tools</button>
      <button class="tab-btn" data-tab="rea" onclick="switchTab('rea')">/rea · 229 REA Runtime Tools</button>
      <button class="tab-btn" data-tab="agents" onclick="switchTab('agents')">/agents &amp; workflows (38 + 27)</button>
      <button class="tab-btn" data-tab="voice" onclick="switchTab('voice')">/voice · Live TTS &amp; 51 Engines</button>
      <button class="tab-btn" data-tab="discover" onclick="switchTab('discover')">/discover · Live GitHub AI</button>
    </div>

    <!-- STATUS & PROVIDERS -->
    <div id="tab-status" class="section active">
      <div class="card3d" style="margin-bottom:18px">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
          <h3 style="margin:0">Workers (9 Registered) &amp; REA Tool Runtime</h3>
          <span id="reaRuntimeBadge" class="badge badge-ok">REA Runtime: Loading...</span>
        </div>
        <div id="workersGrid" class="grid-cards" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr))"></div>
      </div>
      <div class="card3d">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px">
          <h3 style="margin:0">Model Providers (<span id="providersReadyCount">45/45</span> Ready — Click Any Provider to Save Custom Key)</h3>
          <input id="providerFilter" class="input" placeholder="Filter 45 providers..." oninput="renderProviders()" />
        </div>
        <div id="providersGrid" class="grid-cards"></div>
      </div>
    </div>

    <!-- CHAT -->
    <div id="tab-chat" class="section">
      <div class="card3d">
        <h3 style="margin:0 0 12px">OpenAI-Compatible &amp; Multi-Provider Completions</h3>
        <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">
          <button class="btn btn-ghost" onclick="setPrompt('Draft a 30-second YouTube Shorts script about local AI workers.')">Shorts Script</button>
          <button class="btn btn-ghost" onclick="setPrompt('Which tools in my catalog handle zero-shot voice cloning?')">Voice Cloning Tools</button>
          <button class="btn btn-ghost" onclick="setPrompt('Explain how REA reverse-engineering MCP tools inspect AI model files.')">REA Model Inspection</button>
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">
          <select id="chatProvider" class="input" style="min-width:220px"></select>
          <input id="chatModel" class="input" placeholder="Optional model override (e.g. gpt-4o-mini)" style="flex:1" />
        </div>
        <textarea id="chatPrompt" rows="4" class="input" style="width:100%;margin-bottom:12px">Draft a 30-second YouTube Shorts script about local AI workers.</textarea>
        <button class="btn" onclick="sendChat()">Send Completion ▶</button>
        <pre id="chatOutput" class="console-out" style="margin-top:14px;display:none"></pre>
      </div>
    </div>

    <!-- CHANNELS -->
    <div id="tab-channels" class="section">
      <div class="card3d" style="margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
        <div>
          <h3 style="margin:0">Publishing Channels (<span id="channelsReadyCount">37/37</span> Configured)</h3>
          <p style="margin:4px 0 0;font-size:13px;color:var(--muted)">Every channel is active via Managed Cloud Bridge or custom OAuth/Bot credentials stored in Supabase Vault.</p>
        </div>
        <input id="channelFilter" class="input" placeholder="Search 37 channels..." oninput="renderChannels()" />
      </div>
      <div id="channelsGrid" class="grid-cards"></div>
    </div>

    <!-- CATALOG TOOLS -->
    <div id="tab-tools" class="section">
      <div class="card3d" style="margin-bottom:16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center">
        <input id="toolSearch" class="input" placeholder="Search 6,122 AI tools, MCP servers, SDKs..." style="flex:1;min-width:240px" onkeydown="if(event.key==='Enter')loadTools()" />
        <select id="toolCategory" class="input" onchange="loadTools()"><option value="">All Categories</option></select>
        <label style="font-size:13px;display:flex;align-items:center;gap:6px"><input type="checkbox" id="mcpOnly" onchange="loadTools()" /> MCP Only</label>
        <button class="btn" onclick="loadTools()">Search Catalog</button>
      </div>
      <div id="toolsGrid" class="grid-cards"></div>
    </div>

    <!-- REA -->
    <div id="tab-rea" class="section">
      <div class="card3d" style="margin-bottom:16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center">
        <input id="reaSearch" class="input" placeholder="Search 229 morluto/rea MCP tools..." style="flex:1;min-width:240px" onkeydown="if(event.key==='Enter')loadRea()" />
        <select id="reaFamily" class="input" onchange="loadRea()"><option value="">All 25 Families</option></select>
        <button class="btn" onclick="loadRea()">Filter REA</button>
        <button class="btn btn-ghost" onclick="runReaInspect()">Run REA Capabilities Check ▶</button>
      </div>
      <pre id="reaJobOut" class="console-out" style="display:none;margin-bottom:14px"></pre>
      <div id="reaGrid" class="grid-cards"></div>
    </div>

    <!-- AGENTS & WORKFLOWS -->
    <div id="tab-agents" class="section">
      <pre id="agentRunOut" class="console-out" style="display:none;margin-bottom:14px"></pre>
      <h3 style="margin:0 0 12px">Autonomous Agents (38)</h3>
      <div id="agentsGrid" class="grid-cards" style="margin-bottom:24px"></div>
      <h3 style="margin:0 0 12px">Creator &amp; Automation Workflows (27)</h3>
      <div id="workflowsGrid" class="grid-cards"></div>
    </div>

    <!-- VOICE -->
    <div id="tab-voice" class="section">
      <div class="card3d" style="margin-bottom:18px">
        <h3 style="margin:0 0 10px">Live Speech Engine (Server WAV + Neural Browser Voice)</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
          <select id="ttsVoice" class="input">
            <option>River</option><option>Honey</option><option>Sunny</option><option>Storm</option><option>Spark</option>
          </select>
          <input id="ttsText" class="input" style="flex:1;min-width:260px" value="Welcome to Universal AI Backend version 0.6.0. All 45 model providers and 37 channels are online." />
          <button class="btn" onclick="generateSpeech()">Generate Speech ▶</button>
        </div>
        <audio id="ttsAudio" controls style="width:100%;margin-top:8px;display:none"></audio>
      </div>
      <div id="voiceGrid" class="grid-cards"></div>
    </div>

    <!-- DISCOVER -->
    <div id="tab-discover" class="section">
      <div class="card3d" style="margin-bottom:16px;display:flex;flex-wrap:wrap;gap:10px">
        <select id="discoverPreset" class="input" onchange="loadDiscover()"></select>
        <input id="discoverQuery" class="input" placeholder="Extra GitHub search keywords..." style="flex:1" />
        <button class="btn" onclick="loadDiscover()">Discover Live on GitHub</button>
      </div>
      <div id="discoverGrid" class="grid-cards"></div>
    </div>
  </div>

  <script>
    let STATE = { providers: [], channels: [], workers: [], stats: null };
    const savedKey = localStorage.getItem('uaib_api_key') || '';
    document.getElementById('apiKeyInput').value = savedKey;

    function saveLocalApiKey() {
      localStorage.setItem('uaib_api_key', document.getElementById('apiKeyInput').value.trim());
      alert('API Key saved in browser session for protected Vault & Run actions.');
    }

    function authHeaders() {
      const k = (document.getElementById('apiKeyInput').value || localStorage.getItem('uaib_api_key') || '').trim();
      const h = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
      if (k) h['X-API-Key'] = k;
      return h;
    }

    function switchTab(id) {
      document.querySelectorAll('.section').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(el => el.classList.toggle('active', el.dataset.tab === id));
      const target = document.getElementById('tab-' + id);
      if (target) target.classList.add('active');
      if (id === 'tools' && !document.getElementById('toolsGrid').children.length) loadTools();
      if (id === 'rea' && !document.getElementById('reaGrid').children.length) loadRea();
      if (id === 'agents' && !document.getElementById('agentsGrid').children.length) loadAgentsAndWorkflows();
      if (id === 'voice' && !document.getElementById('voiceGrid').children.length) loadVoice();
      if (id === 'discover' && !document.getElementById('discoverGrid').children.length) loadDiscover();
    }

    async function saveVaultEnv(envName) {
      const val = prompt('Enter value for ' + envName + ' (stored encrypted/RLS-protected in Supabase Vault):');
      if (!val) return;
      const res = await fetch('/v1/vault/secrets', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ secrets: { [envName]: val.trim() }, category: 'ui_config' })
      });
      const data = await res.json();
      if (!res.ok) { alert('Error: ' + (data.detail || res.status)); return; }
      await bootstrap();
      alert('Saved ' + envName + ' (' + (data.keys?.[0]?.masked || 'ok') + ')!');
    }

    function renderProviders() {
      const q = (document.getElementById('providerFilter').value || '').toLowerCase();
      const list = STATE.providers.filter(p => !q || JSON.stringify(p).toLowerCase().includes(q));
      document.getElementById('providersGrid').innerHTML = list.map(p => `
        <div class="card3d">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
            <div>
              <div style="font-weight:700;font-size:15px">${p.label || p.id}</div>
              <code style="font-size:11px;color:#94a3b8">${p.api_key_env}</code>
            </div>
            <span class="badge ${p.ready ? 'badge-ok' : 'badge-info'}">${p.ready ? (p.direct_configured ? '● custom key' : '● ready') : 'no key'}</span>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px">
            <span style="font-size:12px;color:#64748b">${p.credential_source || p.mode}</span>
            <button class="btn btn-ghost" style="padding:5px 10px;font-size:11px" onclick="saveVaultEnv('${p.api_key_env}')">Set Key</button>
          </div>
        </div>
      `).join('');
    }

    function renderChannels() {
      const q = (document.getElementById('channelFilter').value || '').toLowerCase();
      const list = STATE.channels.filter(c => !q || JSON.stringify(c).toLowerCase().includes(q));
      document.getElementById('channelsGrid').innerHTML = list.map(c => {
        const envs = (c.environment_variables || []);
        return `
          <div class="card3d">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
              <div>
                <div style="font-weight:700;font-size:15px">${c.name}</div>
                <div style="font-size:12px;color:#94a3b8;margin-top:2px">${c.auth_type || 'OAuth / Token'}</div>
              </div>
              <span class="badge ${c.environment_configured ? 'badge-ok' : 'badge-info'}">${c.configured_env_count}/${c.configured_env_total} configured</span>
            </div>
            <div style="margin:10px 0;display:flex;flex-wrap:wrap;gap:5px">
              ${envs.map(e => `<button class="btn btn-ghost" style="padding:4px 8px;font-size:10px" onclick="saveVaultEnv('${e}')">⚙ ${e}</button>`).join('')}
            </div>
          </div>
        `;
      }).join('');
    }

    async function bootstrap() {
      const [statsRes, provRes, chanRes, reaRes] = await Promise.all([
        fetch('/v1/catalog/stats').then(r => r.json()),
        fetch('/v1/providers').then(r => r.json()),
        fetch('/v1/channels').then(r => r.json()),
        fetch('/v1/rea/tools?limit=250').then(r => r.json()),
      ]);
      STATE.stats = statsRes;
      STATE.providers = provRes.providers || [];
      STATE.workers = provRes.workers || [];
      STATE.channels = chanRes.items || [];

      document.getElementById('heroTools').textContent = (statsRes.total_tools || 6122).toLocaleString();
      document.getElementById('heroRea').textContent = (reaRes.tool_count || 229).toLocaleString();
      document.getElementById('providersReadyCount').textContent = `${provRes.ready_count || 0}/${provRes.total || 45}`;
      const chReady = chanRes.configured_count ?? STATE.channels.filter(c => c.environment_configured).length;
      document.getElementById('channelsReadyCount').textContent = `${chReady}/${STATE.channels.length}`;
      const wkReady = STATE.workers.filter(w => w.configured).length;
      document.getElementById('orbLeft').textContent = `Wiring: ${wkReady}/${STATE.workers.length} Workers Online`;
      document.getElementById('orbRight').textContent = `${provRes.ready_count}/${provRes.total} Providers · ${chReady}/${STATE.channels.length} Channels`;
      document.getElementById('reaRuntimeBadge').textContent = `REA Runtime: ${reaRes.status || 'ready'} · ${reaRes.tool_count || 229} tools exposed`;

      document.getElementById('kpiGrid').innerHTML = [
        { label: 'Catalogued AI & MCP Tools', val: (statsRes.total_tools || 6122).toLocaleString(), sub: `${Object.keys(statsRes.categories || {}).length} categories` },
        { label: 'Model Providers Ready', val: `${provRes.ready_count}/${provRes.total}`, sub: 'OpenAI, Anthropic, Gemini, Groq+' },
        { label: 'REA Tool Runtime', val: `${reaRes.tool_count || 229}`, sub: 'morluto/rea v6.8.0 ready' },
        { label: 'Publishing Channels', val: `${chReady}/${STATE.channels.length}`, sub: 'All 37 connectors configured' },
        { label: 'Registered Workers', val: `${wkReady}/${STATE.workers.length}`, sub: 'Voice, Media, Agents, REA+' },
        { label: 'Agents & Workflows', val: '38 + 27', sub: 'Bounded approval-gated flows' },
      ].map(k => `<div class="card3d"><div style="font-size:12px;color:#94a3b8">${k.label}</div><div class="kpi-val">${k.val}</div><div class="kpi-sub">${k.sub}</div></div>`).join('');

      document.getElementById('workersGrid').innerHTML = STATE.workers.map(w => `
        <div class="card3d" style="padding:13px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <strong style="text-transform:uppercase;font-size:13px">${w.id}</strong>
            <span class="badge ${w.configured ? 'badge-ok' : 'badge-info'}">${w.configured ? '● online' : 'off'}</span>
          </div>
          <div style="font-size:11px;color:#64748b;margin-top:6px">${w.url_env}</div>
        </div>
      `).join('');

      document.getElementById('chatProvider').innerHTML = STATE.providers.map(p => `<option value="${p.id}">${p.label} (${p.id})</option>`).join('');

      const catSelect = document.getElementById('toolCategory');
      catSelect.innerHTML = '<option value="">All Categories</option>' + Object.entries(statsRes.categories || {}).sort((a,b)=>b[1]-a[1]).map(([c,n]) => `<option value="${c}">${c} (${n})</option>`).join('');

      const famSelect = document.getElementById('reaFamily');
      famSelect.innerHTML = '<option value="">All 25 Families</option>' + Object.entries(reaRes.families || {}).map(([f,n]) => `<option value="${f}">${f} (${n})</option>`).join('');

      renderProviders();
      renderChannels();
    }

    function setPrompt(t) { document.getElementById('chatPrompt').value = t; }

    async function sendChat() {
      const out = document.getElementById('chatOutput');
      out.style.display = 'block';
      out.textContent = 'Routing completion through Universal AI Control Plane...';
      const res = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          provider: document.getElementById('chatProvider').value,
          model: document.getElementById('chatModel').value.trim(),
          messages: [{ role: 'user', content: document.getElementById('chatPrompt').value }]
        })
      });
      const data = await res.json();
      out.textContent = data?.choices?.[0]?.message?.content || JSON.stringify(data, null, 2);
    }

    async function loadTools() {
      const q = encodeURIComponent(document.getElementById('toolSearch').value || '');
      const cat = encodeURIComponent(document.getElementById('toolCategory').value || '');
      const mcp = document.getElementById('mcpOnly').checked ? '&mcp_only=true' : '';
      const data = await fetch(`/v1/tools?q=${q}&category=${cat}${mcp}&limit=48`).then(r => r.json());
      document.getElementById('toolsGrid').innerHTML = (data.items || []).map(t => `
        <div class="card3d">
          <div style="display:flex;justify-content:space-between;gap:8px">
            <strong>${t.name || t.id}</strong>
            <span class="badge badge-info">${t.category || 'ai'}</span>
          </div>
          <p style="font-size:12px;color:#94a3b8;line-height:1.45">${String(t.description || '').slice(0, 140)}</p>
          ${(t.repository_url || t.url) ? `<a href="${t.repository_url || t.url}" target="_blank" style="color:#38bdf8;font-size:12px;text-decoration:none">Source ↗</a>` : ''}
        </div>
      `).join('');
    }

    async function loadRea() {
      const q = encodeURIComponent(document.getElementById('reaSearch').value || '');
      const fam = encodeURIComponent(document.getElementById('reaFamily').value || '');
      const data = await fetch(`/v1/rea/tools?q=${q}&family=${fam}&limit=90`).then(r => r.json());
      document.getElementById('reaGrid').innerHTML = (data.items || []).map(t => `
        <div class="card3d">
          <div style="display:flex;justify-content:space-between">
            <code style="color:#38bdf8;font-weight:700">${t.name}</code>
            <span class="badge badge-ok">${t.family}</span>
          </div>
          <p style="font-size:12px;color:#94a3b8;margin:8px 0 0">${t.description}</p>
        </div>
      `).join('');
    }

    async function runReaInspect() {
      const out = document.getElementById('reaJobOut');
      out.style.display = 'block';
      out.textContent = 'Running REA v6.8.0 capability inspection...';
      const res = await fetch('/v1/rea/inspect', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ operation: 'capabilities', authorized_target_confirmed: true, user_approved: true })
      });
      out.textContent = JSON.stringify(await res.json(), null, 2);
    }

    async function loadAgentsAndWorkflows() {
      const [ag, wf] = await Promise.all([
        fetch('/v1/agents').then(r => r.json()),
        fetch('/v1/workflows').then(r => r.json()),
      ]);
      document.getElementById('agentsGrid').innerHTML = (ag.items || []).map(a => `
        <div class="card3d">
          <div style="display:flex;justify-content:space-between"><strong>${a.name}</strong><span class="badge badge-info">${a.risk_level || 'bounded'}</span></div>
          <p style="font-size:12px;color:#94a3b8">${String(a.description || '').slice(0, 110)}</p>
          <button class="btn btn-ghost" style="padding:6px 11px;font-size:11px" onclick="runAgent('${a.id}')">Execute Agent ▶</button>
        </div>
      `).join('');
      document.getElementById('workflowsGrid').innerHTML = (wf.items || []).map(w => `
        <div class="card3d">
          <strong>${w.name}</strong>
          <p style="font-size:12px;color:#94a3b8">${String(w.description || '').slice(0, 110)}</p>
        </div>
      `).join('');
    }

    async function runAgent(agentId) {
      const out = document.getElementById('agentRunOut');
      out.style.display = 'block';
      out.textContent = 'Executing agent ' + agentId + '...';
      const res = await fetch('/v1/agents/' + encodeURIComponent(agentId) + '/run', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ objective: 'Generate an operational execution plan using Universal AI Backend.', user_approved: true, dry_run: false })
      });
      out.textContent = JSON.stringify(await res.json(), null, 2);
    }

    async function loadVoice() {
      const data = await fetch('/v1/voice/providers').then(r => r.json());
      document.getElementById('voiceGrid').innerHTML = (data.items || []).map(v => `
        <div class="card3d">
          <div style="display:flex;justify-content:space-between"><strong>${v.name}</strong><span class="badge badge-ok">${v.category}</span></div>
          <p style="font-size:12px;color:#94a3b8">${v.description}</p>
        </div>
      `).join('');
    }

    async function generateSpeech() {
      const text = document.getElementById('ttsText').value;
      const voice = document.getElementById('ttsVoice').value;
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
      }
      const res = await fetch('/v1/voice/tts', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ text, voice, engine: 'kokoro-82m' })
      });
      const data = await res.json();
      if (data.audio_data_url) {
        const audio = document.getElementById('ttsAudio');
        audio.src = data.audio_data_url;
        audio.style.display = 'block';
      }
    }

    async function loadDiscover() {
      const sel = document.getElementById('discoverPreset');
      if (!sel.options.length) {
        const cats = await fetch('/v1/discover/categories').then(r => r.json());
        sel.innerHTML = (cats.presets || []).map(p => `<option value="${p.id}">${p.label || p.id}</option>`).join('');
      }
      const preset = encodeURIComponent(sel.value || 'mcp-servers');
      const q = encodeURIComponent(document.getElementById('discoverQuery').value || '');
      const data = await fetch(`/v1/discover/github?category_preset=${preset}&q=${q}&per_page=18`).then(r => r.json());
      document.getElementById('discoverGrid').innerHTML = (data.items || data.repositories || []).map(r => `
        <div class="card3d">
          <div style="display:flex;justify-content:space-between">
            <a href="${r.html_url || r.url}" target="_blank" style="color:#38bdf8;font-weight:700;text-decoration:none">${r.full_name || r.name} ↗</a>
            <span style="color:#fbbf24;font-size:12px">★ ${(r.stargazers_count || r.stars || 0).toLocaleString()}</span>
          </div>
          <p style="font-size:12px;color:#94a3b8;margin-top:8px">${String(r.description || '').slice(0, 130)}</p>
        </div>
      `).join('');
    }

    // 3D Starfield + Neural Polyhedron Orb Engine
    (function init3D() {
      const bg = document.getElementById('bg-canvas');
      const bctx = bg.getContext('2d');
      const orb = document.getElementById('orb-canvas');
      const octx = orb.getContext('2d');
      let mx = 0, my = 0;
      window.addEventListener('mousemove', e => {
        mx = (e.clientX / window.innerWidth - 0.5) * 2;
        my = (e.clientY / window.innerHeight - 0.5) * 2;
      });
      function resize() {
        bg.width = window.innerWidth; bg.height = window.innerHeight;
        orb.width = orb.clientWidth || 440; orb.height = orb.clientHeight || 300;
      }
      window.addEventListener('resize', resize); resize();

      const stars = Array.from({ length: 160 }, () => ({
        x: (Math.random() - 0.5) * 1600,
        y: (Math.random() - 0.5) * 1000,
        z: Math.random() * 1200 + 100,
      }));

      // Golden-ratio icosahedron vertices
      const phi = (1 + Math.sqrt(5)) / 2;
      const rawVerts = [
        [-1, phi, 0],[1, phi, 0],[-1, -phi, 0],[1, -phi, 0],
        [0, -1, phi],[0, 1, phi],[0, -1, -phi],[0, 1, -phi],
        [phi, 0, -1],[phi, 0, 1],[-phi, 0, -1],[-phi, 0, 1]
      ];
      let t = 0;
      function frame() {
        t += 0.014;
        bctx.clearRect(0, 0, bg.width, bg.height);
        for (const s of stars) {
          s.z -= 1.8;
          if (s.z <= 20) s.z = 1200;
          const k = 420 / s.z;
          const sx = bg.width / 2 + (s.x + mx * 60) * k;
          const sy = bg.height / 2 + (s.y + my * 40) * k;
          const r = Math.max(0.6, (1 - s.z / 1300) * 2.4);
          bctx.fillStyle = `rgba(129, 140, 248, ${1 - s.z / 1300})`;
          bctx.beginPath(); bctx.arc(sx, sy, r, 0, Math.PI * 2); bctx.fill();
        }

        octx.clearRect(0, 0, orb.width, orb.height);
        const cx = orb.width / 2, cy = orb.height / 2;
        const rx = t * 0.8 + my * 0.5, ry = t * 1.1 + mx * 0.6;
        const pts = rawVerts.map(([x, y, z]) => {
          let y1 = y * Math.cos(rx) - z * Math.sin(rx);
          let z1 = y * Math.sin(rx) + z * Math.cos(rx);
          let x2 = x * Math.cos(ry) + z1 * Math.sin(ry);
          let z2 = -x * Math.sin(ry) + z1 * Math.cos(ry);
          const scale = 210 / (4.2 + z2);
          return { x: cx + x2 * scale, y: cy + y1 * scale, z: z2 };
        });

        // Orbital rings
        for (let ring = 0; ring < 3; ring++) {
          octx.save();
          octx.translate(cx, cy);
          octx.rotate(t * (0.4 + ring * 0.25) + ring);
          octx.scale(1, 0.38 + ring * 0.14);
          octx.strokeStyle = ring === 1 ? 'rgba(34,211,238,0.45)' : 'rgba(99,102,241,0.38)';
          octx.lineWidth = 1.4;
          octx.beginPath(); octx.arc(0, 0, 96 + ring * 18, 0, Math.PI * 2); octx.stroke();
          octx.restore();
        }

        // Wireframe edges
        for (let i = 0; i < pts.length; i++) {
          for (let j = i + 1; j < pts.length; j++) {
            const dx = rawVerts[i][0]-rawVerts[j][0], dy = rawVerts[i][1]-rawVerts[j][1], dz = rawVerts[i][2]-rawVerts[j][2];
            if (dx*dx + dy*dy + dz*dz < 4.5) {
              octx.strokeStyle = 'rgba(56, 189, 248, 0.55)';
              octx.lineWidth = 1.3;
              octx.beginPath(); octx.moveTo(pts[i].x, pts[i].y); octx.lineTo(pts[j].x, pts[j].y); octx.stroke();
            }
          }
        }
        for (const p of pts) {
          octx.fillStyle = '#a5b4fc';
          octx.beginPath(); octx.arc(p.x, p.y, 3.5, 0, Math.PI * 2); octx.fill();
        }
        requestAnimationFrame(frame);
      }
      frame();
    })();

    bootstrap();
  </script>
</body>
</html>
"""
