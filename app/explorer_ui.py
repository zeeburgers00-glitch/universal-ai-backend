"""Built-in interactive web explorer for Universal AI Backend & REA MCP Catalog.

Uses relative API URLs (/v1/...) only so it works identically locally, on Vercel, and behind reverse proxies.
"""

EXPLORER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Universal AI Backend — Global AI & REA Explorer</title>
  <style>
    :root {
      --bg: #0b1020;
      --panel: #131b33;
      --panel-hover: #192445;
      --border: #25335c;
      --text: #eef2ff;
      --muted: #9aa8cc;
      --accent: #6366f1;
      --accent-2: #22d3ee;
      --good: #34d399;
      --warn: #fbbf24;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: radial-gradient(circle at top right, #172554 0%, var(--bg) 45%);
      color: var(--text);
      line-height: 1.5;
    }
    header {
      padding: 24px 28px 18px;
      border-bottom: 1px solid var(--border);
      background: rgba(11, 16, 32, 0.85);
      backdrop-filter: blur(10px);
      position: sticky;
      top: 0;
      z-index: 20;
    }
    .top-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      max-width: 1360px;
      margin: 0 auto;
    }
    h1 {
      margin: 0;
      font-size: 1.35rem;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .badge {
      font-size: 0.75rem;
      padding: 3px 9px;
      border-radius: 999px;
      background: rgba(99, 102, 241, 0.22);
      border: 1px solid rgba(99, 102, 241, 0.55);
      color: #c7d2fe;
      font-weight: 600;
    }
    .badge-cyan {
      background: rgba(34, 211, 238, 0.14);
      border-color: rgba(34, 211, 238, 0.45);
      color: #a5f3fc;
    }
    .badge-warn {
      background: rgba(251, 191, 36, 0.14);
      border-color: rgba(251, 191, 36, 0.4);
      color: #fde68a;
    }
    .nav-links a {
      color: var(--muted);
      text-decoration: none;
      font-size: 0.88rem;
      margin-left: 14px;
    }
    .nav-links a:hover { color: var(--text); }
    main {
      max-width: 1360px;
      margin: 0 auto;
      padding: 22px 28px 60px;
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }
    .stat-card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
    }
    .stat-val {
      font-size: 1.55rem;
      font-weight: 700;
      color: var(--accent-2);
    }
    .stat-label {
      font-size: 0.8rem;
      color: var(--muted);
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 18px;
    }
    .tab-btn {
      background: var(--panel);
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 9px 15px;
      border-radius: 9px;
      cursor: pointer;
      font-weight: 600;
      font-size: 0.88rem;
    }
    .tab-btn.active {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 16px;
      background: var(--panel);
      padding: 14px;
      border-radius: 12px;
      border: 1px solid var(--border);
    }
    input, select, button.action-btn {
      background: #0d1428;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 9px 12px;
      border-radius: 8px;
      font-size: 0.9rem;
    }
    input[type="search"] { flex: 1 1 260px; }
    button.action-btn {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      font-weight: 600;
      cursor: pointer;
    }
    button.action-btn.secondary {
      background: transparent;
      border-color: var(--border);
      color: var(--text);
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
      gap: 14px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 10px;
      transition: border-color 0.15s, background 0.15s;
    }
    .card:hover {
      background: var(--panel-hover);
      border-color: #3f5596;
    }
    .card h3 {
      margin: 0 0 4px;
      font-size: 1rem;
      word-break: break-word;
    }
    .card p {
      margin: 0;
      font-size: 0.86rem;
      color: #cbd5e1;
    }
    .meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      font-size: 0.76rem;
    }
    .card-links a {
      color: var(--accent-2);
      font-size: 0.82rem;
      text-decoration: none;
      margin-right: 12px;
      font-weight: 600;
    }
    .card-links a:hover { text-decoration: underline; }
    .pager {
      margin-top: 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--muted);
      font-size: 0.88rem;
    }
    .notice {
      margin-top: 24px;
      padding: 12px 16px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: rgba(19, 27, 51, 0.65);
      color: var(--muted);
      font-size: 0.82rem;
    }
    .hidden { display: none !important; }
  </style>
</head>
<body>
  <header>
    <div class="top-row">
      <h1>
        Universal AI Backend
        <span class="badge">Global AI + MCP Control Plane</span>
        <span class="badge badge-cyan">REA v6.8.0 Integrated</span>
      </h1>
      <nav class="nav-links">
        <a href="/docs" target="_blank">OpenAPI /docs</a>
        <a href="/v1/catalog/stats" target="_blank">Stats JSON</a>
        <a href="/v1/rea/status" target="_blank">REA Status</a>
        <a href="/" target="_blank">Root JSON</a>
      </nav>
    </div>
  </header>

  <main>
    <section class="stats-grid" id="statsGrid">
      <div class="stat-card"><div class="stat-val" id="stTools">...</div><div class="stat-label">Cataloged AI & MCP Tools</div></div>
      <div class="stat-card"><div class="stat-val" id="stCategories">...</div><div class="stat-label">AI Categories</div></div>
      <div class="stat-card"><div class="stat-val" id="stReaTools">...</div><div class="stat-label">REA MCP Tools</div></div>
      <div class="stat-card"><div class="stat-val" id="stMcp">...</div><div class="stat-label">MCP Servers & SDKs</div></div>
      <div class="stat-card"><div class="stat-val" id="stProviders">...</div><div class="stat-label">LLM Provider Adapters</div></div>
      <div class="stat-card"><div class="stat-val" id="stAgents">...</div><div class="stat-label">Agents & Workflows</div></div>
    </section>

    <div class="tabs">
      <button class="tab-btn active" data-tab="tools">Global AI Catalog</button>
      <button class="tab-btn" data-tab="rea">REA (morluto/rea) MCP Tools</button>
      <button class="tab-btn" data-tab="providers">LLM Providers (45)</button>
      <button class="tab-btn" data-tab="blueprints">Agents, Workflows & Channels</button>
      <button class="tab-btn" data-tab="discover">Live GitHub AI Discovery</button>
    </div>

    <!-- Tab 1: Global AI Catalog -->
    <section id="tab-tools">
      <div class="controls">
        <input type="search" id="toolQ" placeholder="Search 6,000+ AI tools, MCP servers, models, video, voice, coding..." />
        <select id="toolCategory"><option value="">All Categories</option></select>
        <select id="toolStars">
          <option value="">Any Stars</option>
          <option value="500">500+ GitHub Stars</option>
          <option value="2000">2,000+ GitHub Stars</option>
          <option value="10000">10,000+ GitHub Stars</option>
          <option value="50000">50,000+ GitHub Stars</option>
        </select>
        <input type="text" id="toolLang" placeholder="Language (e.g. Python, TypeScript)" style="width:190px;" />
        <button class="action-btn" id="btnToolSearch">Search</button>
      </div>
      <div class="cards" id="toolCards"></div>
      <div class="pager">
        <span id="toolPageInfo">Loading...</span>
        <div>
          <button class="action-btn secondary" id="toolPrev">Prev</button>
          <button class="action-btn secondary" id="toolNext">Next</button>
        </div>
      </div>
    </section>

    <!-- Tab 2: REA MCP Tools -->
    <section id="tab-rea" class="hidden">
      <div class="controls">
        <input type="search" id="reaQ" placeholder="Search 229 REA MCP tools (e.g. webmcp, model, gguf, gpu, electron, ghidra)..." />
        <select id="reaFamily"><option value="">All REA Tool Families</option></select>
        <label style="display:flex;align-items:center;gap:6px;font-size:0.88rem;color:var(--muted);">
          <input type="checkbox" id="reaAiOnly" /> AI Workflow Highlights Only
        </label>
        <button class="action-btn" id="btnReaSearch">Filter REA Tools</button>
      </div>
      <div class="cards" id="reaCards"></div>
    </section>

    <!-- Tab 3: Providers -->
    <section id="tab-providers" class="hidden">
      <div class="cards" id="providerCards"></div>
    </section>

    <!-- Tab 4: Blueprints -->
    <section id="tab-blueprints" class="hidden">
      <div class="controls">
        <select id="bpKind">
          <option value="agents">Specialist Agent Blueprints</option>
          <option value="workflows">Approval-Gated Workflows</option>
          <option value="channels">Channel Connectors</option>
        </select>
        <input type="search" id="bpQ" placeholder="Filter blueprints..." />
        <button class="action-btn" id="btnBpLoad">Load</button>
      </div>
      <div class="cards" id="bpCards"></div>
    </section>

    <!-- Tab 5: Live GitHub Discovery -->
    <section id="tab-discover" class="hidden">
      <div class="controls">
        <select id="discPreset"><option value="">Select AI Category Preset...</option></select>
        <input type="search" id="discQ" placeholder="Or custom GitHub query (e.g. voice agent)" />
        <button class="action-btn" id="btnDiscRun">Run Live GitHub Search</button>
      </div>
      <div class="cards" id="discCards"></div>
    </section>

    <div class="notice">
      <strong>Safety &amp; Licensing Notice:</strong> Catalog records and live GitHub discovery results are metadata references (<code>catalog_only</code> / <code>review_required</code>), not automatically installed or executed code. Verify each project's current upstream <code>LICENSE</code>, model-weight terms, and vendor Terms of Service before commercial deployment. Use REA (<code>morluto/rea</code>) strictly on software, bundles, websites, and artifacts you own or are authorized to analyze.
    </div>
  </main>

  <script>
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    let toolOffset = 0;
    const toolLimit = 36;
    let toolTotal = 0;

    async function init() {
      const [stats, providers, presets] = await Promise.all([
        fetch('/v1/catalog/stats').then(r => r.json()),
        fetch('/v1/models/providers').then(r => r.json()),
        fetch('/v1/discover/categories').then(r => r.json()),
      ]);
      document.getElementById('stTools').textContent = stats.total_tools.toLocaleString();
      document.getElementById('stCategories').textContent = Object.keys(stats.categories || {}).length;
      document.getElementById('stReaTools').textContent = (stats.separate_manifests?.rea_mcp_tools || 0).toLocaleString();
      document.getElementById('stMcp').textContent = (stats.separate_manifests?.mcp_ecosystem_records || 0).toLocaleString();
      document.getElementById('stProviders').textContent = providers.total;
      document.getElementById('stAgents').textContent =
        ((stats.separate_manifests?.agent_blueprints || 0) + (stats.separate_manifests?.workflows || 0)).toLocaleString();

      const catSel = document.getElementById('toolCategory');
      Object.entries(stats.categories || {})
        .sort((a, b) => b[1] - a[1])
        .forEach(([cat, count]) => {
          const opt = document.createElement('option');
          opt.value = cat;
          opt.textContent = `${cat} (${count})`;
          catSel.appendChild(opt);
        });

      const presetSel = document.getElementById('discPreset');
      (presets.presets || []).forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = `${p.label} [catalog: ${p.catalog_count}]`;
        presetSel.appendChild(opt);
      });

      renderProviders(providers.items || []);
      await loadTools();
      await loadRea(true);
      await loadBlueprints();
    }

    async function loadTools() {
      const params = new URLSearchParams({ limit: toolLimit, offset: toolOffset });
      const q = document.getElementById('toolQ').value.trim();
      const cat = document.getElementById('toolCategory').value;
      const stars = document.getElementById('toolStars').value;
      const lang = document.getElementById('toolLang').value.trim();
      if (q) params.set('q', q);
      if (cat) params.set('category', cat);
      if (stars) params.set('min_stars', stars);
      if (lang) params.set('language', lang);

      const data = await fetch('/v1/tools?' + params.toString()).then(r => r.json());
      toolTotal = data.total || 0;
      document.getElementById('toolPageInfo').textContent =
        `Showing ${data.items.length ? toolOffset + 1 : 0}–${toolOffset + data.items.length} of ${toolTotal.toLocaleString()} tools`;
      document.getElementById('toolCards').innerHTML = (data.items || []).map(it => `
        <article class="card">
          <div>
            <div class="meta-row" style="margin-bottom:6px;">
              <span class="badge">${esc(it.category)}</span>
              ${it.stars_snapshot ? `<span class="badge badge-cyan">★ ${Number(it.stars_snapshot).toLocaleString()}</span>` : ''}
              ${it.primary_language ? `<span class="badge badge-warn">${esc(it.primary_language)}</span>` : ''}
            </div>
            <h3>${esc(it.name)}</h3>
            <p>${esc((it.description || '').slice(0, 200))}</p>
          </div>
          <div>
            <div class="meta-row" style="color:var(--muted);margin-bottom:6px;">
              <span>ID: <code>${esc(it.id)}</code></span>
            </div>
            <div class="card-links">
              ${it.repository_url ? `<a href="${esc(it.repository_url)}" target="_blank" rel="noopener">GitHub Repo ↗</a>` : ''}
              ${it.docs_url ? `<a href="${esc(it.docs_url)}" target="_blank" rel="noopener">Website / Docs ↗</a>` : ''}
            </div>
          </div>
        </article>
      `).join('');
    }

    async function loadRea(populateFamilies = false) {
      const params = new URLSearchParams({ limit: 250 });
      const q = document.getElementById('reaQ').value.trim();
      const fam = document.getElementById('reaFamily').value;
      const aiOnly = document.getElementById('reaAiOnly').checked;
      if (q) params.set('q', q);
      if (fam) params.set('family', fam);
      if (aiOnly) params.set('ai_only', 'true');
      const data = await fetch('/v1/rea/tools?' + params.toString()).then(r => r.json());
      if (populateFamilies && data.families) {
        const sel = document.getElementById('reaFamily');
        Object.entries(data.families).forEach(([f, cnt]) => {
          const opt = document.createElement('option');
          opt.value = f;
          opt.textContent = `${f} (${cnt})`;
          sel.appendChild(opt);
        });
      }
      document.getElementById('reaCards').innerHTML = (data.items || []).map(t => `
        <article class="card">
          <div>
            <div class="meta-row" style="margin-bottom:6px;">
              <span class="badge">${esc(t.family)}</span>
              ${t.ai_workflow_highlight ? `<span class="badge badge-cyan">AI Highlight</span>` : ''}
              ${t.read_only ? `<span class="badge">Read-Only</span>` : `<span class="badge badge-warn">Side-Effect / Active</span>`}
            </div>
            <h3>${esc(t.name)}</h3>
            <p>${esc((t.description || '').slice(0, 220))}</p>
          </div>
          <div class="meta-row" style="color:var(--muted);">
            <span>Title: ${esc(t.title)}</span>
          </div>
        </article>
      `).join('');
    }

    function renderProviders(items) {
      document.getElementById('providerCards').innerHTML = items.map(p => `
        <article class="card">
          <div>
            <div class="meta-row" style="margin-bottom:6px;">
              <span class="badge">${esc(p.api_mode)}</span>
              <span class="badge ${p.runtime_status?.ready ? 'badge-cyan' : 'badge-warn'}">
                ${p.runtime_status?.ready ? 'Configured' : 'Set Env Key'}
              </span>
            </div>
            <h3>${esc(p.name)} (<code>${esc(p.id)}</code>)</h3>
            <p>${esc(p.notes)}</p>
          </div>
          <div class="meta-row" style="color:var(--muted);">
            <code>${esc(p.api_key_env)}</code> · <code>${esc(p.base_url_env)}</code>
          </div>
        </article>
      `).join('');
    }

    async function loadBlueprints() {
      const kind = document.getElementById('bpKind').value;
      const q = document.getElementById('bpQ').value.trim();
      const params = q ? '?q=' + encodeURIComponent(q) : '';
      const data = await fetch(`/v1/${kind}${params}`).then(r => r.json());
      document.getElementById('bpCards').innerHTML = (data.items || []).map(x => `
        <article class="card">
          <div>
            <div class="meta-row" style="margin-bottom:6px;">
              <span class="badge">${esc(x.risk_level || x.auth_type || kind)}</span>
              <span class="badge badge-cyan">${esc(x.status || x.integration_status || '')}</span>
            </div>
            <h3>${esc(x.name)}</h3>
            <p>${esc(x.mission || x.description || x.purpose || '')}</p>
          </div>
          <div class="meta-row" style="color:var(--muted);">
            <code>${esc(x.id)}</code>
          </div>
        </article>
      `).join('');
    }

    async function runDiscovery() {
      const preset = document.getElementById('discPreset').value;
      const q = document.getElementById('discQ').value.trim();
      const params = new URLSearchParams({ per_page: 18 });
      if (preset) params.set('category_preset', preset);
      if (q) params.set('q', q);
      const wrap = document.getElementById('discCards');
      wrap.innerHTML = '<div class="stat-label">Querying GitHub Search API...</div>';
      const resp = await fetch('/v1/discover/github?' + params.toString());
      const data = await resp.json();
      if (!resp.ok) {
        wrap.innerHTML = `<div class="notice">${esc(data.detail || 'Discovery error')}</div>`;
        return;
      }
      wrap.innerHTML = (data.items || []).map(it => `
        <article class="card">
          <div>
            <div class="meta-row" style="margin-bottom:6px;">
              <span class="badge badge-cyan">★ ${Number(it.stars || 0).toLocaleString()}</span>
              ${it.language ? `<span class="badge">${esc(it.language)}</span>` : ''}
              <span class="badge badge-warn">${esc(it.license)}</span>
            </div>
            <h3>${esc(it.full_name)}</h3>
            <p>${esc(it.description || '')}</p>
          </div>
          <div class="card-links">
            <a href="${esc(it.repository_url)}" target="_blank" rel="noopener">Open on GitHub ↗</a>
          </div>
        </article>
      `).join('');
    }

    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        ['tools', 'rea', 'providers', 'blueprints', 'discover'].forEach(id => {
          document.getElementById('tab-' + id).classList.toggle('hidden', id !== btn.dataset.tab);
        });
      });
    });

    document.getElementById('btnToolSearch').addEventListener('click', () => { toolOffset = 0; loadTools(); });
    document.getElementById('toolQ').addEventListener('keydown', e => { if (e.key === 'Enter') { toolOffset = 0; loadTools(); } });
    document.getElementById('toolCategory').addEventListener('change', () => { toolOffset = 0; loadTools(); });
    document.getElementById('toolStars').addEventListener('change', () => { toolOffset = 0; loadTools(); });
    document.getElementById('toolPrev').addEventListener('click', () => { if (toolOffset >= toolLimit) { toolOffset -= toolLimit; loadTools(); } });
    document.getElementById('toolNext').addEventListener('click', () => { if (toolOffset + toolLimit < toolTotal) { toolOffset += toolLimit; loadTools(); } });
    document.getElementById('btnReaSearch').addEventListener('click', () => loadRea(false));
    document.getElementById('reaAiOnly').addEventListener('change', () => loadRea(false));
    document.getElementById('reaFamily').addEventListener('change', () => loadRea(false));
    document.getElementById('btnBpLoad').addEventListener('click', loadBlueprints);
    document.getElementById('bpKind').addEventListener('change', loadBlueprints);
    document.getElementById('btnDiscRun').addEventListener('click', runDiscovery);

    init();
  </script>
</body>
</html>
"""
