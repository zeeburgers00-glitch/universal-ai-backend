"""A complete code editor served by the backend — no npm, no CDN, no build step.

Everything the page needs is in this one string. That is deliberate: the previous
Next.js frontend was deleted, so this must work as a single HTTP response even on a
phone, offline, behind a proxy, or inside a sandbox preview iframe.
"""

EDITOR_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>AI Editor · Universal AI Backend</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --panel2: #1c2129; --line: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff; --ok: #3fb950;
    --warn: #d29922; --bad: #f85149; --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--text);
    font: 13px/1.5 system-ui, -apple-system, Segoe UI, sans-serif;
    display: flex; flex-direction: column; overflow: hidden;
  }
  header {
    display: flex; align-items: center; gap: 8px; padding: 8px 12px;
    background: var(--panel); border-bottom: 1px solid var(--line); flex-wrap: wrap;
  }
  header h1 { font-size: 13px; margin: 0 8px 0 0; font-weight: 600; letter-spacing: .2px; }
  .badge { font-size: 10px; padding: 2px 6px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); }
  .badge.ok { color: var(--ok); border-color: #23863633; }
  button {
    background: var(--panel2); color: var(--text); border: 1px solid var(--line);
    border-radius: 6px; padding: 5px 10px; cursor: pointer; font-size: 12px;
  }
  button:hover { border-color: var(--accent); }
  button.primary { background: #1f6feb; border-color: #1f6feb; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  input, select, textarea { font-family: inherit; }
  input[type=text], input[type=password], select {
    background: var(--bg); color: var(--text); border: 1px solid var(--line);
    border-radius: 6px; padding: 5px 8px; font-size: 12px;
  }
  main { flex: 1; display: flex; min-height: 0; }
  .sidebar { width: 260px; min-width: 180px; background: var(--panel); border-right: 1px solid var(--line); display: flex; flex-direction: column; }
  .sidebar .search { padding: 8px; border-bottom: 1px solid var(--line); }
  .sidebar .search input { width: 100%; }
  #files { flex: 1; overflow: auto; padding: 4px 0; }
  .file { padding: 3px 10px; cursor: pointer; font-family: var(--mono); font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .file:hover { background: var(--panel2); color: var(--text); }
  .file.active { background: #1f6feb33; color: var(--text); border-left: 2px solid var(--accent); }
  .dir { padding: 6px 10px 2px; font-size: 11px; color: #6e7681; text-transform: none; font-family: var(--mono); }
  .center { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .tabs { display: flex; gap: 2px; padding: 6px 8px 0; background: var(--panel); }
  .tab { padding: 4px 10px; border: 1px solid var(--line); border-bottom: none; border-radius: 6px 6px 0 0; cursor: pointer; color: var(--muted); font-size: 12px; }
  .tab.active { background: var(--bg); color: var(--text); }
  .editor-wrap { position: relative; flex: 1; display: flex; min-height: 0; border-top: 1px solid var(--line); }
  #gutter {
    width: 46px; padding: 8px 6px; text-align: right; color: #484f58; font-family: var(--mono);
    font-size: 12px; line-height: 1.55; background: var(--panel); overflow: hidden; user-select: none;
    border-right: 1px solid var(--line);
  }
  #code {
    flex: 1; border: 0; outline: 0; resize: none; background: var(--bg); color: var(--text);
    font-family: var(--mono); font-size: 12.5px; line-height: 1.55; padding: 8px 10px;
    tab-size: 4; white-space: pre; overflow: auto;
  }
  .status {
    display: flex; gap: 14px; padding: 4px 10px; font-size: 11px; color: var(--muted);
    background: var(--panel); border-top: 1px solid var(--line);
  }
  .status .dirty { color: var(--warn); }
  aside { width: 380px; min-width: 260px; background: var(--panel); border-left: 1px solid var(--line); display: flex; flex-direction: column; }
  .panel { flex: 1; overflow: auto; padding: 10px; display: none; }
  .panel.active { display: block; }
  .panel h3 { margin: 0 0 8px; font-size: 12px; color: var(--muted); font-weight: 600; }
  .row { padding: 5px 0; border-bottom: 1px solid #21262d; font-size: 12px; }
  .row b { color: var(--accent); font-weight: 500; }
  .sev-high { color: var(--bad); } .sev-medium { color: var(--warn); } .sev-low { color: var(--muted); }
  pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: var(--mono); font-size: 11.5px; }
  .add { color: var(--ok); } .del { color: var(--bad); } .meta { color: #6e7681; }
  .toast {
    position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
    background: var(--panel2); border: 1px solid var(--line); color: var(--text);
    padding: 8px 14px; border-radius: 8px; font-size: 12px; opacity: 0;
    transition: opacity .2s; pointer-events: none; max-width: 80vw;
  }
  .toast.show { opacity: 1; }
  .keybar { display: flex; gap: 6px; align-items: center; }
  .keybar input { width: 220px; }
  .chat-log { display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }
  .msg { padding: 6px 8px; border-radius: 6px; background: var(--panel2); font-size: 12px; white-space: pre-wrap; }
  .msg.user { background: #1f6feb22; }
  .chat-input { display: flex; gap: 6px; }
  .chat-input input { flex: 1; }
  @media (max-width: 900px) {
    aside { display: none; }
    .sidebar { width: 180px; }
  }
</style>
</head>
<body>
<header>
  <h1>AI Editor</h1>
  <span class="badge" id="engineBadge">deterministic engine · 0 keys</span>
  <span class="badge" id="keyBadge" style="display:none">key needed</span>
  <div class="keybar" id="keybar" style="display:none">
    <input type="password" id="keyInput" placeholder="X-API-Key" autocomplete="off" />
    <button onclick="setKey()">Unlock</button>
  </div>
  <span style="flex:1"></span>
  <button onclick="saveFile()" class="primary" title="Ctrl+S">Save</button>
  <button onclick="loadTree(true)">Reindex</button>
  <button onclick="runReview()">Review</button>
  <button onclick="runTests()">Tests</button>
  <button onclick="runPlan()">Plan</button>
</header>

<main>
  <div class="sidebar">
    <div class="search"><input type="text" id="filter" placeholder="filter files… (Ctrl+P)" oninput="renderFiles()" /></div>
    <div id="files"></div>
  </div>

  <div class="center">
    <div class="tabs">
      <div class="tab active" data-tab="outline" onclick="showTab('outline')">Outline</div>
      <div class="tab" data-tab="review" onclick="showTab('review')">Review</div>
      <div class="tab" data-tab="tests" onclick="showTab('tests')">Tests</div>
      <div class="tab" data-tab="plan" onclick="showTab('plan')">Plan</div>
      <div class="tab" data-tab="diff" onclick="showTab('diff')">Diff</div>
      <div class="tab" data-tab="chat" onclick="showTab('chat')">Chat</div>
      <div class="tab" data-tab="git" onclick="showTab('git'); loadGit()">Git</div>
      <div class="tab" data-tab="tools" onclick="showTab('tools')">Tools</div>
    </div>
    <div class="editor-wrap">
      <div id="gutter"></div>
      <textarea id="code" spellcheck="false" placeholder="Open a file from the left…"></textarea>
    </div>
    <div class="status">
      <span id="stPath">no file</span>
      <span id="stLines">0 lines</span>
      <span id="stPos">1:1</span>
      <span id="stDirty"></span>
    </div>
  </div>

  <aside>
    <div class="panel active" id="panel-outline"><h3>Outline</h3><div id="outlineBody" class="meta">open a file</div></div>
    <div class="panel" id="panel-review"><h3>Static review</h3><div id="reviewBody" class="meta">run Review</div></div>
    <div class="panel" id="panel-tests"><h3>Suggested tests</h3><div id="testsBody" class="meta">run Tests</div></div>
    <div class="panel" id="panel-plan"><h3>Plan</h3><div id="planBody" class="meta">run Plan</div></div>
    <div class="panel" id="panel-diff"><h3>Last change</h3><div id="diffBody" class="meta">save to see the diff</div></div>
    <div class="panel" id="panel-chat">
      <h3>Chat <span class="meta">(needs a local model or free-tier key)</span></h3>
      <div class="chat-log" id="chatLog"></div>
      <div class="chat-input">
        <input type="text" id="chatInput" placeholder="ask about this file…" onkeydown="if(event.key==='Enter')sendChat()" />
        <button onclick="sendChat()">Send</button>
      </div>
    </div>
    <div class="panel" id="panel-git">
      <h3>Git <span class="meta">(local commits only, never pushes)</span></h3>
      <div id="gitStatus" class="meta">open to load…</div>
      <div id="gitFiles"></div>
      <pre id="gitDiff" class="meta" style="white-space:pre-wrap;max-height:200px;overflow:auto;margin:8px 0"></pre>
      <div class="chat-input">
        <input type="text" id="gitMessage" placeholder="commit message…" />
        <button onclick="commitGit()">Commit all</button>
      </div>
    </div>
    <div class="panel" id="panel-tools">
      <h3>Tool search <span class="meta">(BM25 over the repo catalog)</span></h3>
      <div class="chat-input">
        <input type="text" id="toolQuery" placeholder="e.g. text to speech" onkeydown="if(event.key==='Enter')searchTools()" />
        <button onclick="searchTools()">Search</button>
      </div>
      <div id="toolResults" class="meta"></div>
    </div>
  </aside>
</main>

<div class="toast" id="toast"></div>

<script>
const state = { files: [], current: null, original: '', tree: {}, busy: false };

function toast(message) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 2600);
}

function apiKey() {
  return localStorage.getItem('uai_key') || new URLSearchParams(location.search).get('key') || '';
}

function setKey() {
  const value = document.getElementById('keyInput').value.trim();
  if (!value) return;
  localStorage.setItem('uai_key', value);
  document.getElementById('keybar').style.display = 'none';
  document.getElementById('keyBadge').style.display = 'none';
  toast('key saved');
  loadTree(true);
}

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  const key = apiKey();
  if (key) headers['X-API-Key'] = key;
  if (options.body) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, Object.assign({}, options, { headers }));
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { raw: text }; }
  if (response.status === 401 || response.status === 503) {
    document.getElementById('keybar').style.display = 'flex';
    document.getElementById('keyBadge').style.display = 'inline-block';
    throw new Error(response.status === 503 ? 'server has no BACKEND_API_KEY set' : 'invalid key');
  }
  if (!response.ok) {
    throw new Error((data && (data.detail || data.raw)) || ('HTTP ' + response.status));
  }
  return data;
}

async function loadTree(reindex) {
  try {
    if (reindex) {
      toast('indexing…');
      const stats = await api('/v1/code/index', { method: 'POST', body: '{}' });
      toast('indexed ' + stats.file_count + ' files · ' + stats.symbol_count + ' symbols');
    }
    const tree = await api('/v1/code/tree?max_entries=4000');
    state.tree = tree;
    state.files = tree.files;
    renderFiles();
  } catch (error) { toast('index failed: ' + error.message); }
}

function renderFiles() {
  const filter = document.getElementById('filter').value.toLowerCase();
  const container = document.getElementById('files');
  const visible = state.files.filter(f => !filter || f.path.toLowerCase().includes(filter));
  const groups = {};
  for (const file of visible) {
    const dir = file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/')) : '(root)';
    (groups[dir] = groups[dir] || []).push(file);
  }
  let html = '';
  for (const dir of Object.keys(groups).sort()) {
    html += '<div class="dir">' + escapeHtml(dir) + '</div>';
    for (const file of groups[dir]) {
      const name = file.path.split('/').pop();
      const active = state.current === file.path ? ' active' : '';
      html += '<div class="file' + active + '" title="' + escapeHtml(file.path) + '" onclick="openFile(this.dataset.p)" data-p="' + escapeHtml(file.path) + '">' + escapeHtml(name) + '</div>';
    }
  }
  container.innerHTML = html || '<div class="dir">no matches</div>';
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function openFile(path) {
  try {
    const data = await api('/v1/code/read?path=' + encodeURIComponent(path));
    state.current = data.path;
    state.original = data.content;
    const code = document.getElementById('code');
    code.value = data.content;
    document.getElementById('stPath').textContent = data.path;
    document.getElementById('stDirty').textContent = '';
    updateGutter();
    renderFiles();
    showTab('outline');
    const outline = await api('/v1/code/outline', { method: 'POST', body: JSON.stringify({ path: data.path }) });
    renderOutline(outline);
  } catch (error) { toast('open failed: ' + error.message); }
}

function renderOutline(outline) {
  let html = '<div class="meta">' + outline.lines + ' lines · ' + outline.language + ' · ' + outline.todo_count + ' TODOs</div>';
  for (const symbol of outline.symbols.slice(0, 200)) {
    html += '<div class="row" onclick="gotoLine(' + symbol.line + ')"><b>' + escapeHtml(symbol.name) + '</b> <span class="meta">' + symbol.kind + ' · line ' + symbol.line + '</span></div>';
  }
  if (outline.imports.length) {
    html += '<h3 style="margin-top:10px">Imports</h3><pre class="meta">' + escapeHtml(outline.imports.join('\n')) + '</pre>';
  }
  document.getElementById('outlineBody').innerHTML = html;
}

function gotoLine(line) {
  const code = document.getElementById('code');
  const lines = code.value.split('\n');
  let offset = 0;
  for (let i = 0; i < Math.min(line - 1, lines.length); i++) offset += lines[i].length + 1;
  code.focus();
  code.setSelectionRange(offset, offset + (lines[line - 1] || '').length);
  const lineHeight = 19.4;
  code.scrollTop = Math.max(0, (line - 6) * lineHeight);
  updatePos();
}

function updateGutter() {
  const code = document.getElementById('code');
  const total = code.value.split('\n').length;
  document.getElementById('gutter').innerHTML = Array.from({ length: total }, (_, i) => i + 1).join('<br>');
  document.getElementById('stLines').textContent = total + ' lines';
}

function updatePos() {
  const code = document.getElementById('code');
  const upto = code.value.slice(0, code.selectionStart);
  const line = upto.split('\n').length;
  const col = upto.length - upto.lastIndexOf('\n');
  document.getElementById('stPos').textContent = line + ':' + col;
}

function markDirty() {
  const code = document.getElementById('code');
  const dirty = code.value !== state.original;
  document.getElementById('stDirty').textContent = dirty ? '● unsaved' : '';
  document.getElementById('stDirty').className = dirty ? 'dirty' : '';
}

async function saveFile() {
  if (!state.current) return toast('no file open');
  try {
    const data = await api('/v1/code/write', {
      method: 'POST',
      body: JSON.stringify({ path: state.current, content: document.getElementById('code').value, dry_run: false })
    });
    if (!data.changed) return toast('no changes');
    state.original = document.getElementById('code').value;
    markDirty();
    renderDiff(data);
    showTab('diff');
    toast('saved · +' + data.added_lines + ' −' + data.removed_lines + (data.backup ? ' · backup ' + data.backup : ''));
    loadTree(false);
  } catch (error) { toast('save failed: ' + error.message); }
}

function renderDiff(data) {
  const lines = (data.diff || '').split('\n').map(line => {
    const cls = line.startsWith('+++') || line.startsWith('---') ? 'meta' : line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : '';
    return '<span class="' + cls + '">' + escapeHtml(line) + '</span>';
  });
  document.getElementById('diffBody').innerHTML = '<pre>' + lines.join('\n') + '</pre>';
}

async function runReview() {
  showTab('review');
  document.getElementById('reviewBody').textContent = 'reviewing…';
  try {
    const paths = state.current ? [state.current] : null;
    const data = await api('/v1/code/review', { method: 'POST', body: JSON.stringify({ paths }) });
    let html = '<div class="meta">' + data.files_reviewed + ' files · ' + data.total_findings + ' findings</div>';
    for (const finding of data.findings.slice(0, 200)) {
      html += '<div class="row" onclick="openFile(\'' + finding.path.replace(/'/g, "\\'") + '\').then(()=>gotoLine(' + finding.line + '))">' +
        '<span class="sev-' + finding.severity + '">[' + finding.severity + ']</span> ' +
        '<b>' + escapeHtml(finding.rule) + '</b> <span class="meta">' + escapeHtml(finding.path) + ':' + finding.line + '</span>' +
        '<div class="meta">' + escapeHtml(finding.message) + '</div></div>';
    }
    document.getElementById('reviewBody').innerHTML = html;
  } catch (error) { document.getElementById('reviewBody').textContent = error.message; }
}

async function runTests() {
  showTab('tests');
  if (!state.current) return document.getElementById('testsBody').textContent = 'open a file first';
  try {
    const data = await api('/v1/code/tests', { method: 'POST', body: JSON.stringify({ path: state.current }) });
    document.getElementById('testsBody').innerHTML =
      '<div class="meta">suggested: ' + escapeHtml(data.suggested_test_file) + ' · ' + data.tests + ' tests</div>' +
      '<pre>' + escapeHtml(data.content) + '</pre>';
  } catch (error) { document.getElementById('testsBody').textContent = error.message; }
}

async function runPlan() {
  showTab('plan');
  const goal = prompt('What should change?', state.current ? 'improve ' + state.current.split('/').pop() : '');
  if (!goal) return;
  try {
    const data = await api('/v1/code/plan', { method: 'POST', body: JSON.stringify({ goal }) });
    let html = '<div class="meta">model available: ' + (data.model_available ? 'yes' : 'no (deterministic plan)') + '</div>';
    for (const step of data.steps) {
      html += '<div class="row"><b>' + step.step + '. ' + escapeHtml(step.action) + '</b><div class="meta">' + escapeHtml(step.detail) + '</div></div>';
    }
    if (data.related_files.length) {
      html += '<h3 style="margin-top:10px">Related files</h3>';
      for (const hit of data.related_files) {
        html += '<div class="row" onclick="openFile(\'' + hit.path.replace(/'/g, "\\'") + '\')">' + escapeHtml(hit.path) + ' <span class="meta">score ' + hit.score + '</span></div>';
      }
    }
    document.getElementById('planBody').innerHTML = html;
  } catch (error) { document.getElementById('planBody').textContent = error.message; }
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const question = input.value.trim();
  if (!question) return;
  input.value = '';
  const log = document.getElementById('chatLog');
  log.innerHTML += '<div class="msg user">' + escapeHtml(question) + '</div><div class="msg" id="pending">thinking…</div>';

  const context = state.current ? ('\n\nFile ' + state.current + ':\n' + document.getElementById('code').value.slice(0, 12000)) : '';
  try {
    const data = await api('/v1/chat/completions', {
      method: 'POST',
      body: JSON.stringify({
        provider: document.getElementById('provider').value,
        model: document.getElementById('model').value || undefined,
        messages: [
          { role: 'system', content: 'You are a concise senior engineer embedded in a code editor.' },
          { role: 'user', content: question + context }
        ],
        max_tokens: 900
      })
    });
    const text = (data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content) || JSON.stringify(data).slice(0, 2000);
    document.getElementById('pending').textContent = text;
  } catch (error) {
    document.getElementById('pending').textContent = 'No model answered: ' + error.message + '\n\nLocal Ollama chalao (ollama serve) ya free key lagao — phir yahi box kaam karega.';
  }
}

function showTab(name) {
  document.querySelectorAll('.tab').forEach(tab => tab.classList.toggle('active', tab.dataset.tab === name));
  document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('active', panel.id === 'panel-' + name));
}

document.getElementById('code').addEventListener('input', () => { updateGutter(); markDirty(); });
document.getElementById('code').addEventListener('keyup', updatePos);
document.getElementById('code').addEventListener('click', updatePos);
document.getElementById('code').addEventListener('scroll', event => {
  document.getElementById('gutter').scrollTop = event.target.scrollTop;
});
document.getElementById('code').addEventListener('keydown', event => {
  if (event.key === 'Tab') {
    event.preventDefault();
    const code = event.target;
    const start = code.selectionStart;
    code.value = code.value.slice(0, start) + '    ' + code.value.slice(code.selectionEnd);
    code.selectionStart = code.selectionEnd = start + 4;
    updateGutter(); markDirty();
  }
});
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); saveFile(); }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'p') { event.preventDefault(); document.getElementById('filter').focus(); }
});

const chatPanel = document.getElementById('panel-chat');
chatPanel.insertAdjacentHTML('afterbegin',
  '<div style="display:flex;gap:6px;margin-bottom:8px">' +
  '<select id="provider"><option value="ollama">ollama (local)</option><option value="groq">groq</option><option value="gemini">gemini</option><option value="openai">openai</option></select>' +
  '<input type="text" id="model" placeholder="model (optional)" style="flex:1" /></div>');

async function loadGit() {
  const statusBox = document.getElementById('gitStatus');
  const listBox = document.getElementById('gitFiles');
  try {
    const info = await api('/v1/git/status');
    statusBox.textContent = info.branch + ' · ' +
      (info.dirty ? info.file_count + ' changed' : 'clean') +
      (info.ahead ? ' · ahead ' + info.ahead : '');
    listBox.innerHTML = '';
    info.files.forEach(file => {
      const row = document.createElement('div');
      row.className = 'meta';
      row.style.cursor = 'pointer';
      row.textContent = file.code + '  ' + file.path;
      row.onclick = () => showGitDiff(file.path);
      listBox.appendChild(row);
    });
    if (!info.files.length) listBox.textContent = 'nothing to commit';
  } catch (error) {
    statusBox.textContent = 'git: ' + error.message;
  }
}

async function showGitDiff(path) {
  const box = document.getElementById('gitDiff');
  try {
    const data = await api('/v1/git/diff?path=' + encodeURIComponent(path));
    box.textContent = data.diff || '(untracked file — no diff yet)';
  } catch (error) {
    box.textContent = 'diff failed: ' + error.message;
  }
}

async function commitGit() {
  const message = (document.getElementById('gitMessage').value || '').trim();
  if (message.length < 3) { toast('commit message likho (3+ characters)'); return; }
  try {
    const result = await api('/v1/git/commit', { method: 'POST', body: { message, add_all: true } });
    toast('committed ' + (result.sha || ''));
    document.getElementById('gitMessage').value = '';
    loadGit();
    loadTree(false);
  } catch (error) {
    toast('commit failed: ' + error.message);
  }
}

async function searchTools() {
  const query = (document.getElementById('toolQuery').value || '').trim();
  const box = document.getElementById('toolResults');
  if (query.length < 2) { toast('2+ characters chahiye'); return; }
  box.textContent = 'searching…';
  try {
    const data = await api('/v1/tools/search?q=' + encodeURIComponent(query) + '&limit=8');
    box.innerHTML = '';
    data.results.forEach(item => {
      const row = document.createElement('div');
      row.className = 'meta';
      row.style.marginBottom = '8px';
      const title = document.createElement('b');
      title.textContent = item.full_name;
      const meta = document.createTextNode('  ★' + (item.stars || 0) + ' · ' + (item.license || 'no licence'));
      const desc = document.createElement('div');
      desc.textContent = item.description || '';
      row.appendChild(title); row.appendChild(meta); row.appendChild(desc);
      box.appendChild(row);
    });
    if (!data.results.length) box.textContent = 'no matches';
  } catch (error) {
    box.textContent = 'search failed: ' + error.message;
  }
}

loadTree(true);
</script>
</body>
</html>
"""
