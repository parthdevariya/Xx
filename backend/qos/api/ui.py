"""Browser console served at ``GET /``.

A single self-contained page: no CDN, no build step, no framework. It talks to
the same JSON API as the CLI, so anything it can do is scriptable, and it
cannot drift from the API's behaviour.

It exists because the root URL is the first thing anyone opens, and a bare
404 there makes a working service look broken.
"""

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quantum OS</title>
<style>
:root{
  --bg:#f6f7f9; --panel:#fff; --sunk:#eceef1; --ink:#15191f; --muted:#5d6670; --line:#dfe3e8;
  --accent:#5a42c6; --good:#2c7a35; --bad:#b3261e; --warn:#a8650c;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0f1318; --panel:#161b22; --sunk:#1d232b; --ink:#e5e9ed; --muted:#949fab; --line:#2a323c;
  --accent:#a391f2; --good:#63c77a; --bad:#f2837a; --warn:#e8a052; color-scheme:dark;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 56px;display:flex;flex-direction:column;gap:18px}
header{display:flex;flex-direction:column;gap:6px;border-bottom:1px solid var(--line);padding-bottom:14px}
h1{margin:0;font-size:26px;letter-spacing:-.01em}
h2{margin:0;font-size:17px}
.sub{color:var(--muted);font-size:14px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--good);margin-right:6px}
.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}
@media (max-width:820px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;min-width:0}
label{display:flex;flex-direction:column;gap:5px;font-size:12px;font-weight:600;letter-spacing:.05em;
  text-transform:uppercase;color:var(--muted)}
textarea,input,select{font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);
  border-radius:7px;padding:9px 10px;width:100%}
textarea{font-family:var(--mono);font-size:13px;resize:vertical}
textarea:focus,input:focus,select:focus,button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.row{display:flex;gap:10px;flex-wrap:wrap}
.row>*{flex:1 1 130px;min-width:0}
button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--bg);color:var(--ink);
  border-radius:7px;padding:9px 14px;font-weight:500}
button:hover{border-color:var(--muted)}
button.go{background:var(--ink);color:var(--bg);border-color:var(--ink);font-weight:600;flex:0 0 auto}
button.go:disabled{opacity:.55;cursor:progress}
button.ex{padding:5px 10px;font-size:13px;flex:0 0 auto}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.ans{font-family:var(--mono);font-size:13.5px;white-space:pre-wrap;word-break:break-word;margin:0}
.nums{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:8px;overflow:hidden}
.nums div{background:var(--panel);padding:9px 11px;display:flex;flex-direction:column;gap:2px}
.nums span{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.nums b{font-family:var(--mono);font-size:16px;font-weight:600}
.summary{font-size:14.5px;color:var(--ink)}
.pill{display:inline-block;font-size:12px;font-weight:600;padding:3px 9px;border-radius:999px}
.ok{background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good)}
.no{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
.wn{background:color-mix(in srgb,var(--warn) 20%,transparent);color:var(--warn)}
details{border-top:1px solid var(--line);padding-top:10px;margin-top:4px}
summary{cursor:pointer;font-weight:600;font-size:13.5px;color:var(--muted)}
pre{font-family:var(--mono);font-size:12.5px;background:var(--sunk);padding:11px;border-radius:7px;
  overflow:auto;max-height:340px;margin:10px 0 0;white-space:pre-wrap;word-break:break-word}
.err{border-left:3px solid var(--bad);padding-left:12px}
.err h3{margin:0 0 4px;font-size:15px;color:var(--bad)}
.err ul{margin:6px 0 0;padding-left:20px;font-size:14px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
td.m{font-family:var(--mono)}
.muted{color:var(--muted);font-size:13px}
.hint{font-size:12.5px;color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Quantum OS</h1>
  <p class="sub">State a goal in plain language. The platform reads it, encodes it, picks the
  right resource across the major quantum platforms (or a classical solver when that is
  genuinely better), runs it, and explains the choice.</p>
  <p class="sub" id="status"><span class="dot"></span>connecting…</p>
</header>

<div class="grid">
  <div class="panel" style="display:flex;flex-direction:column;gap:14px">
    <h2>Your goal</h2>
    <label>Goal
      <textarea id="goal" rows="2" placeholder="e.g. find the shortest round trip visiting all six depots"></textarea>
    </label>
    <div>
      <p class="hint" style="margin:0 0 6px">Load an example:</p>
      <div class="chips" id="examples"></div>
    </div>
    <label>Problem data (JSON)
      <textarea id="data" rows="9" spellcheck="false" placeholder='{"numbers": [8, 5, 4, 3, 3, 2, 7, 6]}'></textarea>
    </label>
    <div class="row">
      <label>Priority
        <select id="priority">
          <option value="balanced">balanced</option>
          <option value="accuracy">accuracy</option>
          <option value="cheap">cheap</option>
          <option value="fast">fast</option>
        </select>
      </label>
      <label>Budget (USD)<input id="budget" type="number" min="0" step="1" value="0"></label>
      <label>Seed<input id="seed" type="number" placeholder="any"></label>
    </div>
    <div class="row">
      <label>Pin backend (optional)
        <select id="backend"><option value="">let the broker choose</option></select>
      </label>
      <label>Pin algorithm
        <select id="algorithm">
          <option value="">auto</option>
          <option value="qaoa">qaoa</option>
          <option value="vqe">vqe</option>
          <option value="grover">grover</option>
          <option value="quantum_annealing">quantum_annealing</option>
          <option value="tabu">tabu</option>
          <option value="simulated_annealing">simulated_annealing</option>
          <option value="exact">exact</option>
        </select>
      </label>
    </div>
    <label style="flex-direction:row;align-items:center;gap:8px;text-transform:none;font-size:14px;font-weight:500">
      <input type="checkbox" id="hw" style="width:auto"> Allow paid quantum hardware
    </label>
    <div class="row" style="gap:8px">
      <button class="go" id="solve">Solve</button>
      <button id="plan">Estimate cost</button>
      <button id="explain">Explain choice</button>
    </div>
    <p class="hint">Everything runs locally. Paid hardware is never used unless you tick the box
    and set a budget.</p>
  </div>

  <div class="panel" style="display:flex;flex-direction:column;gap:14px">
    <h2>Result</h2>
    <div id="out"><p class="muted">Pick an example or type a goal, then press Solve.</p></div>
  </div>
</div>

<div class="panel">
  <h2>Backends</h2>
  <p class="muted" id="becount">loading…</p>
  <details><summary>Show all backends and what is blocking each</summary>
    <div style="overflow:auto"><table id="betable"></table></div>
  </details>
</div>
</div>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const EXAMPLES = {
  "Delivery route": {
    goal: "find the shortest round trip visiting all six depots",
    data: {distances:[[0,14,22,9,30,18],[14,0,11,20,25,8],[22,11,0,17,12,15],
                      [9,20,17,0,28,24],[30,25,12,28,0,19],[18,8,15,24,19,0]],
           names:["HQ","North","East","South","Far","West"]}},
  "Portfolio": {
    goal: "pick exactly 4 assets with the best risk-adjusted return",
    data: {returns:[0.12,0.10,0.09,0.07,0.05,0.14,0.08,0.11],
           names:["TECH","FIN","HEALTH","UTIL","BOND","CRYPTO","ENERGY","INDUS"],
           budget:4, risk_aversion:2.0}},
  "Split numbers": {
    goal: "split these numbers into two groups with equal sums",
    data: {numbers:[8,5,4,3,3,2,7,6]}},
  "On-call roster": {
    goal: "assign each engineer exactly one on-call shift at minimum cost",
    data: {costs:[[4,2,8,6,5],[4,3,7,5,9],[3,1,6,9,4],[7,5,2,4,6],[8,6,5,3,2]],
           agents:["Ada","Blake","Cruz","Dev","Eve"],
           tasks:["Mon","Tue","Wed","Thu","Fri"]}},
  "Exam timetable": {
    goal: "assign each exam a timeslot so no two conflicting exams clash",
    data: {n:7, k:3, edges:[[0,1],[0,2],[1,2],[1,3],[2,4],[3,4],[3,5],[4,6],[5,6]],
           names:["Algebra","Calculus","Stats","Physics","Chemistry","Biology","History"]}},
  "Network split": {
    goal: "split this network into two groups maximizing connections between them",
    data: {n:12, edges:[[0,1],[1,2],[2,3],[3,4],[4,5],[5,6],[6,7],[7,8],[8,9],[9,10],
                        [10,11],[11,0],[0,5],[2,7],[4,9],[6,11]]}}
};

$('#examples').innerHTML = Object.keys(EXAMPLES)
  .map(k => `<button class="ex" data-ex="${esc(k)}">${esc(k)}</button>`).join('');
$('#examples').addEventListener('click', e => {
  const b = e.target.closest('[data-ex]'); if (!b) return;
  const ex = EXAMPLES[b.dataset.ex];
  $('#goal').value = ex.goal;
  $('#data').value = JSON.stringify(ex.data, null, 2);
});

function policy() {
  const p = {
    priority: $('#priority').value,
    max_cost_usd: parseFloat($('#budget').value) || 0,
    allow_hardware: $('#hw').checked
  };
  const s = $('#seed').value.trim();           if (s)  p.seed = parseInt(s, 10);
  const b = $('#backend').value;               if (b)  p.force_backend = b;
  const a = $('#algorithm').value;             if (a)  p.force_algorithm = a;
  return p;
}

function body() {
  const goal = $('#goal').value.trim();
  if (!goal) throw new Error('Type a goal first, or load an example.');
  const raw = $('#data').value.trim();
  let data = null;
  if (raw) {
    try { data = JSON.parse(raw); }
    catch (e) { throw new Error('The problem data is not valid JSON: ' + e.message); }
  }
  return JSON.stringify({goal, data, policy: policy()});
}

const fmt = v => typeof v === 'number'
  ? (Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined,{maximumFractionDigits:6}))
  : Array.isArray(v) ? v.map(fmt).join(', ') : String(v);

const SKIP = new Set(['assignment','matrix','placement','colors']);

function renderAnswer(a) {
  if (a == null) return '<p class="muted">no answer</p>';
  if (typeof a !== 'object') return `<p class="ans">${esc(String(a))}</p>`;
  const rows = Object.entries(a)
    .filter(([k]) => !SKIP.has(k))
    .map(([k, v]) => {
      const val = (v && typeof v === 'object' && !Array.isArray(v))
        ? JSON.stringify(v) : fmt(v);
      return `<tr><th>${esc(k.replace(/_/g,' '))}</th><td class="m">${esc(val)}</td></tr>`;
    }).join('');
  return `<table>${rows}</table>`;
}

function renderSolution(d) {
  const adv = {better:'ok', parity:'ok', worse:'wn', none:''}[d.quantum_advantage] || '';
  const ex = d.execution || {}, pl = d.plan || {};
  let html = renderAnswer(d.answer);
  html += `<div class="nums" style="margin-top:12px">
    <div><span>objective</span><b>${d.objective_value == null ? '—' : fmt(d.objective_value)}</b></div>
    <div><span>confidence</span><b>${(d.confidence*100).toFixed(0)}%</b></div>
    <div><span>cost</span><b>$${(ex.cost_usd||0).toFixed(2)}</b></div>
    <div><span>time</span><b>${(ex.wall_time_s||0).toFixed(2)}s</b></div>
  </div>
  <p style="margin:12px 0 0">
    ${d.feasible ? '<span class="pill ok">all rules met</span>'
                 : '<span class="pill no">constraint violated</span>'}
    ${d.quantum_advantage !== 'none'
        ? ` <span class="pill ${adv}">vs classical: ${esc(d.quantum_advantage)}</span>` : ''}
  </p>`;
  if (d.violations && d.violations.length)
    html += `<ul style="color:var(--bad);font-size:14px">${
      d.violations.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`;
  html += `<p class="summary" style="margin-top:12px">${esc(d.summary||'')}</p>`;
  if (ex.backend)
    html += `<p class="muted" style="margin-top:8px">Ran <b>${esc(ex.algorithm)}</b> on
      <b>${esc(ex.backend)}</b>${pl.reason ? ' — ' + esc(pl.reason) : ''}</p>`;
  if (pl.considered && pl.considered.length) {
    html += `<details><summary>Every candidate the broker scored (${pl.considered.length})</summary>
      <table><tr><th>score</th><th>candidate</th><th>why</th></tr>${
      pl.considered.map(c=>`<tr><td class="m">${c.score.toFixed(3)}</td>
        <td class="m">${esc(c.candidate)}</td><td>${esc(c.reason)}</td></tr>`).join('')}</table>`;
    if (pl.rejected && pl.rejected.length)
      html += `<table style="margin-top:10px"><tr><th>rejected</th><th>why</th></tr>${
        pl.rejected.map(r=>`<tr><td class="m">${esc(r.candidate)}</td>
          <td>${esc(r.why)}</td></tr>`).join('')}</table>`;
    html += `</details>`;
  }
  if (d.trace && d.trace.length)
    html += `<details><summary>Decision trace</summary><pre>${
      esc(d.trace.join('\n'))}</pre></details>`;
  html += `<details><summary>Raw JSON</summary><pre>${
    esc(JSON.stringify(d, null, 2))}</pre></details>`;
  return html;
}

async function call(path) {
  const out = $('#out');
  let payload;
  try { payload = body(); }
  catch (e) { out.innerHTML = `<div class="err"><h3>${esc(e.message)}</h3></div>`; return; }

  const btns = document.querySelectorAll('button.go, #plan, #explain');
  btns.forEach(b => b.disabled = true);
  out.innerHTML = '<p class="muted">Working…</p>';
  try {
    const r = await fetch(path, {method:'POST', headers:{'content-type':'application/json'}, body:payload});
    const d = await r.json();
    if (r.status === 422 && d.detail && d.detail.error === 'missing_problem_data') {
      out.innerHTML = `<div class="err"><h3>The goal is clear, but data is missing</h3>
        <p class="muted">The platform will not invent numbers — a fabricated answer here would
        look confident and be wrong. Supply these fields in the JSON box:</p>
        <ul>${d.detail.missing.map(m=>`<li>${esc(m)}</li>`).join('')}</ul></div>`;
      return;
    }
    if (!r.ok) {
      out.innerHTML = `<div class="err"><h3>Request failed (${r.status})</h3>
        <pre>${esc(JSON.stringify(d.detail ?? d, null, 2))}</pre></div>`;
      return;
    }
    out.innerHTML = path === '/explain'
      ? `<pre>${esc(d.report)}</pre>`
      : renderSolution(d);
  } catch (e) {
    out.innerHTML = `<div class="err"><h3>Could not reach the server</h3>
      <p class="muted">${esc(e.message)}</p></div>`;
  } finally {
    btns.forEach(b => b.disabled = false);
  }
}

$('#solve').onclick   = () => call('/solve');
$('#plan').onclick    = () => call('/plan');
$('#explain').onclick = () => call('/explain');
$('#goal').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) call('/solve');
});

(async () => {
  try {
    const h = await (await fetch('/health')).json();
    $('#status').innerHTML = `<span class="dot"></span>${h.backends_usable} of
      ${h.backends_known} backends usable · ` +
      Object.entries(h.providers).map(([k,v]) =>
        `${esc(k)} <b style="color:${v==='ready'?'var(--good)':'var(--muted)'}">${esc(v)}</b>`
      ).join(' · ');
    const b = await (await fetch('/backends')).json();
    const usable = b.backends.filter(x => x.usable);
    $('#becount').textContent =
      `${usable.length} usable right now, ${b.backends.length} known across ${b.providers.length} providers.`;
    $('#backend').innerHTML = '<option value="">let the broker choose</option>' +
      usable.map(x => `<option value="${esc(x.id)}">${esc(x.id)} — ${esc(x.name)}</option>`).join('');
    $('#betable').innerHTML =
      '<tr><th>id</th><th>qubits</th><th>type</th><th>cost</th><th>status</th></tr>' +
      b.backends.map(x => {
        const cost = x.cost_per_shot_usd ? `$${x.cost_per_shot_usd}/shot`
                   : x.cost_per_second_usd ? `$${x.cost_per_second_usd}/s` : 'free';
        return `<tr><td class="m">${esc(x.id)}</td><td class="m">${x.max_qubits.toLocaleString()}</td>
          <td>${esc(x.modality)}</td><td class="m">${cost}</td>
          <td>${x.usable ? '<span class="pill ok">ready</span>'
                         : `<span class="muted">${esc(x.unavailable_reason || 'unavailable')}</span>`}</td></tr>`;
      }).join('');
  } catch (e) {
    $('#status').innerHTML = '<span class="dot" style="background:var(--bad)"></span>server unreachable';
  }
})();
</script>
</body>
</html>
"""
