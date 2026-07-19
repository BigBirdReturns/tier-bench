from __future__ import annotations


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Monster Wrangler</title>
<style>
:root {
  --bg: #0c0d10;
  --panel: #14161b;
  --panel-2: #191c22;
  --panel-3: #20242c;
  --line: #2a2f39;
  --line-soft: #22262e;
  --text: #f3f5f7;
  --muted: #9ba4b2;
  --muted-2: #737d8b;
  --accent: #8dd6c7;
  --accent-2: #b4f1e6;
  --accent-dim: rgba(141,214,199,.12);
  --blue: #8ab4f8;
  --blue-dim: rgba(138,180,248,.12);
  --amber: #efc46b;
  --amber-dim: rgba(239,196,107,.12);
  --red: #ff8a8a;
  --red-dim: rgba(255,138,138,.12);
  --green: #82d69a;
  --green-dim: rgba(130,214,154,.12);
  --violet: #c2a7ff;
  --violet-dim: rgba(194,167,255,.12);
  --shadow: 0 18px 60px rgba(0,0,0,.30);
  --radius: 14px;
  --radius-sm: 9px;
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); }
body {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.45;
  overflow-x: hidden;
}
button, input, textarea, select { font: inherit; }
button { cursor: pointer; }
a { color: var(--accent-2); }
::selection { background: rgba(141,214,199,.28); }
.shell { min-height: 100vh; display: grid; grid-template-columns: 250px minmax(0,1fr); }
.sidebar {
  position: sticky; top: 0; height: 100vh; padding: 22px 16px;
  border-right: 1px solid var(--line-soft); background: #101216;
  display: flex; flex-direction: column; gap: 22px; z-index: 20;
}
.brand { display: flex; align-items: center; gap: 11px; padding: 0 7px; }
.brand-mark {
  width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center;
  background: linear-gradient(145deg, rgba(141,214,199,.22), rgba(194,167,255,.13));
  border: 1px solid rgba(141,214,199,.24); color: var(--accent-2); font-size: 20px;
}
.brand strong { display: block; font-size: 15px; letter-spacing: .01em; }
.brand span { display: block; color: var(--muted-2); font-size: 11px; margin-top: 1px; }
.nav { display: grid; gap: 5px; }
.nav-button {
  width: 100%; border: 0; background: transparent; color: var(--muted); text-align: left;
  border-radius: 9px; padding: 10px 11px; display: flex; align-items: center; gap: 10px;
  transition: background .15s ease, color .15s ease;
}
.nav-button:hover { background: rgba(255,255,255,.035); color: var(--text); }
.nav-button.active { background: var(--accent-dim); color: var(--accent-2); }
.nav-icon { width: 19px; text-align: center; opacity: .9; }
.sidebar-spacer { flex: 1; }
.repo-card {
  background: var(--panel); border: 1px solid var(--line-soft); border-radius: 11px;
  padding: 11px; color: var(--muted); font-size: 11px; overflow: hidden;
}
.repo-card .label { color: var(--muted-2); text-transform: uppercase; letter-spacing: .09em; font-size: 9px; }
.repo-card .path { color: var(--text); margin-top: 5px; overflow-wrap: anywhere; }
.repo-card .server { margin-top: 8px; display: flex; align-items: center; gap: 6px; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 12px rgba(130,214,154,.5); }
.main { min-width: 0; }
.topbar {
  min-height: 72px; border-bottom: 1px solid var(--line-soft); display: flex; align-items: center;
  justify-content: space-between; gap: 16px; padding: 13px 28px; position: sticky; top: 0;
  background: rgba(12,13,16,.88); backdrop-filter: blur(18px); z-index: 15;
}
.top-title h1 { font-size: 17px; line-height: 1.2; margin: 0; font-weight: 650; }
.top-title p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.top-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.content { padding: 26px 28px 64px; max-width: 1600px; margin: 0 auto; }
.view { display: none; }
.view.active { display: block; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.section-head h2 { margin: 0; font-size: 21px; font-weight: 650; letter-spacing: -.015em; }
.section-head p { color: var(--muted); margin: 6px 0 0; max-width: 760px; }
.grid { display: grid; gap: 14px; }
.metrics { grid-template-columns: repeat(6, minmax(0,1fr)); margin-bottom: 18px; }
.metric {
  background: var(--panel); border: 1px solid var(--line-soft); border-radius: var(--radius);
  padding: 15px 16px; min-height: 100px;
}
.metric .kicker { color: var(--muted-2); text-transform: uppercase; letter-spacing: .09em; font-size: 9px; }
.metric .value { font-size: 25px; font-weight: 680; margin-top: 8px; letter-spacing: -.025em; }
.metric .sub { color: var(--muted); font-size: 11px; margin-top: 4px; }
.two-col { grid-template-columns: minmax(0,1.35fr) minmax(300px,.65fr); align-items: start; }
.three-col { grid-template-columns: repeat(3, minmax(0,1fr)); }
.panel {
  background: var(--panel); border: 1px solid var(--line-soft); border-radius: var(--radius);
  box-shadow: 0 1px 0 rgba(255,255,255,.015); overflow: hidden;
}
.panel-head { padding: 15px 17px; border-bottom: 1px solid var(--line-soft); display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.panel-head h3 { font-size: 13px; margin: 0; font-weight: 640; }
.panel-head .hint { color: var(--muted-2); font-size: 10px; }
.panel-body { padding: 15px 17px; }
.panel-body.flush { padding: 0; }
.notice {
  border-radius: var(--radius); padding: 13px 15px; border: 1px solid var(--line);
  background: var(--panel); margin-bottom: 14px; display: flex; gap: 12px; align-items: flex-start;
}
.notice.warn { border-color: rgba(239,196,107,.32); background: var(--amber-dim); }
.notice.danger { border-color: rgba(255,138,138,.33); background: var(--red-dim); }
.notice.good { border-color: rgba(130,214,154,.25); background: var(--green-dim); }
.notice strong { display: block; margin-bottom: 3px; }
.notice p { margin: 0; color: var(--muted); }
.btn {
  border: 1px solid var(--line); background: var(--panel-2); color: var(--text); border-radius: 8px;
  padding: 8px 11px; font-weight: 590; font-size: 12px; line-height: 1; min-height: 34px;
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
}
.btn:hover { border-color: #3b424f; background: var(--panel-3); }
.btn.primary { background: var(--accent); color: #07110f; border-color: var(--accent); }
.btn.primary:hover { background: var(--accent-2); }
.btn.danger { color: var(--red); border-color: rgba(255,138,138,.3); background: var(--red-dim); }
.btn.ghost { background: transparent; }
.btn.small { min-height: 28px; padding: 6px 8px; font-size: 11px; }
.btn:disabled { opacity: .42; cursor: not-allowed; }
.pill, .state-pill {
  display: inline-flex; align-items: center; gap: 5px; padding: 4px 7px; border-radius: 999px;
  border: 1px solid var(--line); color: var(--muted); font-size: 10px; font-weight: 650;
  white-space: nowrap;
}
.state-ACCEPTED { color: var(--green); background: var(--green-dim); border-color: rgba(130,214,154,.24); }
.state-RUNNING { color: var(--blue); background: var(--blue-dim); border-color: rgba(138,180,248,.24); }
.state-QUEUED { color: var(--accent-2); background: var(--accent-dim); border-color: rgba(141,214,199,.23); }
.state-DRAFT { color: var(--muted); }
.state-REJECTED, .state-ERROR { color: var(--red); background: var(--red-dim); border-color: rgba(255,138,138,.24); }
.state-INTERRUPTED { color: var(--amber); background: var(--amber-dim); border-color: rgba(239,196,107,.24); }
.state-CANCELED { color: var(--muted-2); }
.task-list { display: grid; }
.task-row {
  display: grid; grid-template-columns: minmax(220px,1.4fr) 110px 120px minmax(170px,.8fr) 85px;
  gap: 12px; align-items: center; padding: 13px 16px; border-bottom: 1px solid var(--line-soft);
  cursor: pointer; transition: background .12s ease;
}
.task-row:last-child { border-bottom: 0; }
.task-row:hover { background: rgba(255,255,255,.025); }
.task-title { font-weight: 610; min-width: 0; }
.task-title .id { color: var(--muted-2); font-size: 10px; margin-top: 3px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow: hidden; text-overflow: ellipsis; }
.task-route { color: var(--muted); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-when { color: var(--muted-2); font-size: 11px; }
.task-priority { color: var(--muted); font-variant-numeric: tabular-nums; }
.task-head-row {
  display: grid; grid-template-columns: minmax(220px,1.4fr) 110px 120px minmax(170px,.8fr) 85px;
  gap: 12px; padding: 10px 16px; color: var(--muted-2); font-size: 9px;
  text-transform: uppercase; letter-spacing: .08em; border-bottom: 1px solid var(--line-soft);
}
.empty { padding: 30px 20px; text-align: center; color: var(--muted); }
.empty strong { color: var(--text); display: block; margin-bottom: 5px; }
.active-card { padding: 14px; border: 1px solid var(--line-soft); border-radius: 11px; background: var(--panel-2); margin-bottom: 10px; }
.active-card:last-child { margin-bottom: 0; }
.active-top { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
.active-card h4 { margin: 0; font-size: 13px; }
.active-meta { color: var(--muted); font-size: 11px; margin-top: 7px; display: flex; gap: 10px; flex-wrap: wrap; }
.pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--blue); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100% { opacity: .35; transform: scale(.85); } 50% { opacity: 1; transform: scale(1.15); } }
.form-panel { padding: 20px; }
.form-grid { display: grid; grid-template-columns: repeat(12,minmax(0,1fr)); gap: 14px; }
.field { grid-column: span 12; }
.field.half { grid-column: span 6; }
.field.third { grid-column: span 4; }
.field.quarter { grid-column: span 3; }
.field label { display: block; color: var(--muted); font-size: 11px; margin-bottom: 6px; }
.field label strong { color: var(--text); font-weight: 620; }
.input, .textarea, .select {
  width: 100%; border: 1px solid var(--line); background: #101217; color: var(--text);
  border-radius: 8px; padding: 9px 10px; outline: none; min-height: 38px;
}
.textarea { resize: vertical; min-height: 108px; font-family: inherit; line-height: 1.5; }
.textarea.code, .input.code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.input:focus, .textarea:focus, .select:focus { border-color: rgba(141,214,199,.65); box-shadow: 0 0 0 3px rgba(141,214,199,.08); }
.help { color: var(--muted-2); font-size: 10px; margin-top: 5px; }
.check-row { display: flex; align-items: flex-start; gap: 8px; color: var(--muted); }
.check-row input { margin-top: 3px; }
.form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; padding-top: 17px; border-top: 1px solid var(--line-soft); }
.route-editor { border: 1px solid var(--line); border-radius: 11px; padding: 14px; background: rgba(255,255,255,.012); margin-bottom: 11px; }
.route-editor-head { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 12px; }
.route-editor-head strong { font-size: 12px; }
.tank-grid { grid-template-columns: repeat(3,minmax(0,1fr)); }
.tank-card { padding: 16px; }
.tank-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.tank-card h3 { margin: 0; font-size: 14px; }
.tank-card .id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted-2); font-size: 10px; margin-top: 3px; }
.gauge { height: 7px; border-radius: 999px; background: #0c0e12; overflow: hidden; margin-top: 16px; border: 1px solid var(--line-soft); }
.gauge > span { display: block; height: 100%; background: var(--accent); }
.gauge-meta { display: flex; justify-content: space-between; color: var(--muted); font-size: 10px; margin-top: 6px; }
.kv { display: grid; grid-template-columns: 130px minmax(0,1fr); gap: 8px 12px; font-size: 12px; }
.kv dt { color: var(--muted-2); }
.kv dd { margin: 0; color: var(--text); overflow-wrap: anywhere; }
.model-table { width: 100%; border-collapse: collapse; }
.model-table th, .model-table td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line-soft); }
.model-table th { color: var(--muted-2); font-size: 9px; text-transform: uppercase; letter-spacing: .08em; font-weight: 600; }
.model-table td { color: var(--muted); font-size: 11px; }
.model-table td:first-child { color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.event-list { max-height: 650px; overflow: auto; }
.event-row { padding: 11px 14px; border-bottom: 1px solid var(--line-soft); display: grid; grid-template-columns: 135px 170px minmax(0,1fr); gap: 12px; font-size: 11px; }
.event-row:last-child { border-bottom: 0; }
.event-time { color: var(--muted-2); }
.event-kind { color: var(--accent-2); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.event-detail { color: var(--muted); overflow-wrap: anywhere; }
.toolbar { display: flex; gap: 9px; align-items: center; flex-wrap: wrap; }
.search { min-width: 240px; }
.drawer-backdrop, .modal-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,.66); z-index: 50; display: none;
}
.drawer-backdrop.open, .modal-backdrop.open { display: block; }
.drawer {
  position: fixed; top: 0; right: 0; width: min(720px, 94vw); height: 100vh; background: #111318;
  border-left: 1px solid var(--line); z-index: 51; transform: translateX(102%);
  transition: transform .2s ease; display: flex; flex-direction: column; box-shadow: var(--shadow);
}
.drawer.open { transform: translateX(0); }
.drawer-head { padding: 18px 20px; border-bottom: 1px solid var(--line-soft); display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; }
.drawer-head > div { min-width: 0; }
.drawer-head > .btn { flex-shrink: 0; }
.drawer-head h2 { margin: 0; font-size: 19px; }
.drawer-head .id { color: var(--muted-2); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; margin-top: 4px; }
.drawer-body { padding: 18px 20px 50px; overflow: auto; flex: 1; }
.drawer-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 16px; }
.detail-section { border-top: 1px solid var(--line-soft); padding-top: 16px; margin-top: 16px; }
.detail-section h3 { font-size: 12px; margin: 0 0 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .07em; }
.pre {
  background: #0b0d10; border: 1px solid var(--line-soft); border-radius: 9px; padding: 12px;
  overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; color: #d9dee6;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px;
  max-height: 420px;
}
.route-status { padding: 11px 12px; border-radius: 9px; border: 1px solid var(--line-soft); margin-bottom: 8px; }
.route-status:last-child { margin-bottom: 0; }
.route-status .top { display: flex; justify-content: space-between; gap: 10px; }
.route-status .meta { color: var(--muted); font-size: 10px; margin-top: 5px; display: flex; gap: 9px; flex-wrap: wrap; }
.run-card { border: 1px solid var(--line-soft); border-radius: 10px; padding: 12px; margin-bottom: 9px; }
.run-card:last-child { margin-bottom: 0; }
.run-card .run-top { display: flex; justify-content: space-between; gap: 10px; }
.run-card .run-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10px; color: var(--muted); overflow-wrap: anywhere; }
.run-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.modal {
  position: fixed; z-index: 61; left: 50%; top: 50%; transform: translate(-50%,-50%);
  width: min(900px, 92vw); max-height: 88vh; background: #111318; border: 1px solid var(--line);
  border-radius: 14px; box-shadow: var(--shadow); display: none; flex-direction: column;
}
.modal.open { display: flex; }
.modal-head { padding: 14px 16px; border-bottom: 1px solid var(--line-soft); display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.modal-head h3 { margin: 0; font-size: 14px; }
.modal-body { padding: 15px; overflow: auto; }
.toast-stack { position: fixed; right: 18px; bottom: 18px; z-index: 90; display: grid; gap: 8px; width: min(390px, calc(100vw - 36px)); }
.toast { background: #1b1f26; border: 1px solid var(--line); border-radius: 10px; padding: 11px 13px; box-shadow: var(--shadow); color: var(--text); }
.toast.error { border-color: rgba(255,138,138,.35); }
.toast .small { color: var(--muted); font-size: 11px; margin-top: 3px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.muted { color: var(--muted); }
.muted-2 { color: var(--muted-2); }
.good { color: var(--green); }
.warn-text { color: var(--amber); }
.bad { color: var(--red); }
.hidden { display: none !important; }
.mobile-nav { display: none; }
@media (max-width: 1180px) {
  .metrics { grid-template-columns: repeat(3,minmax(0,1fr)); }
  .tank-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
}
@media (max-width: 900px) {
  .shell { grid-template-columns: 1fr; }
  .sidebar { display: none; }
  .mobile-nav { display: flex; gap: 4px; overflow-x: auto; padding: 8px 14px; border-bottom: 1px solid var(--line-soft); position: sticky; top: 72px; z-index: 14; background: rgba(12,13,16,.95); }
  .mobile-nav .nav-button { width: auto; white-space: nowrap; padding: 8px 10px; }
  .topbar { padding: 13px 16px; }
  .content { padding: 20px 15px 50px; }
  .two-col { grid-template-columns: 1fr; }
  .task-row, .task-head-row { grid-template-columns: minmax(180px,1fr) 100px 120px; }
  .task-row > :nth-child(4), .task-row > :nth-child(5), .task-head-row > :nth-child(4), .task-head-row > :nth-child(5) { display: none; }
}
@media (max-width: 620px) {
  .metrics { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .tank-grid, .three-col { grid-template-columns: 1fr; }
  .field.half, .field.third, .field.quarter { grid-column: span 12; }
  .top-title p { display: none; }
  .task-row, .task-head-row { grid-template-columns: minmax(150px,1fr) 92px; }
  .task-row > :nth-child(3), .task-head-row > :nth-child(3) { display: none; }
  .event-row { grid-template-columns: 110px minmax(0,1fr); }
  .event-detail { grid-column: 1 / -1; }
}
</style>
</head>
<body>
<div class="shell">
  <aside class="sidebar">
    <div class="brand"><div class="brand-mark">⌁</div><div><strong>Monster Wrangler</strong><span>controlled agent work</span></div></div>
    <nav class="nav" id="side-nav">
      <button class="nav-button active" data-view="control"><span class="nav-icon">◫</span>Mission control</button>
      <button class="nav-button" data-view="queue"><span class="nav-icon">≋</span>Work queue</button>
      <button class="nav-button" data-view="new"><span class="nav-icon">＋</span>New work</button>
      <button class="nav-button" data-view="cartridges"><span class="nav-icon">◈</span>Cartridges & tanks</button>
      <button class="nav-button" data-view="evidence"><span class="nav-icon">⌘</span>Evidence</button>
      <button class="nav-button" data-view="settings"><span class="nav-icon">⚙</span>Settings</button>
    </nav>
    <div class="sidebar-spacer"></div>
    <div class="repo-card">
      <div class="label">Managed repository</div>
      <div class="path" id="repo-path">Loading…</div>
      <div class="server"><span class="status-dot"></span><span id="server-status">Connecting</span></div>
    </div>
  </aside>
  <main class="main">
    <header class="topbar">
      <div class="top-title"><h1 id="view-title">Mission control</h1><p>Persistent repository work with explicit routes, approval gates, bounded spend, and verified receipts.</p></div>
      <div class="top-actions">
        <span class="pill" id="chain-pill">Evidence chain</span>
        <span class="pill" id="active-pill">0 active</span>
        <button class="btn" id="pause-button">Pause</button>
        <button class="btn danger" id="emergency-button">Emergency stop</button>
      </div>
    </header>
    <nav class="mobile-nav" id="mobile-nav">
      <button class="nav-button active" data-view="control">Control</button>
      <button class="nav-button" data-view="queue">Queue</button>
      <button class="nav-button" data-view="new">New</button>
      <button class="nav-button" data-view="cartridges">Tanks</button>
      <button class="nav-button" data-view="evidence">Evidence</button>
      <button class="nav-button" data-view="settings">Settings</button>
    </nav>
    <div class="content">
      <section class="view active" id="view-control">
        <div id="control-notices"></div>
        <div class="grid metrics" id="metric-grid"></div>
        <div class="grid two-col">
          <div class="panel"><div class="panel-head"><h3>Ready and running work</h3><span class="hint">The scheduler claims only eligible routes</span></div><div class="panel-body" id="active-work"></div></div>
          <div class="panel"><div class="panel-head"><h3>Attention ledger</h3><span class="hint">Operator gates and failures</span></div><div class="panel-body" id="attention-list"></div></div>
        </div>
        <div class="panel" style="margin-top:14px"><div class="panel-head"><h3>Recent work</h3><button class="btn small ghost" data-go="queue">Open queue</button></div><div class="panel-body flush" id="recent-work"></div></div>
      </section>

      <section class="view" id="view-queue">
        <div class="section-head"><div><h2>Work queue</h2><p>The queue is durable in SQLite. Every execution is isolated by the repository runner, and only a verified receipt settles the task.</p></div><div class="toolbar"><input class="input search" id="task-search" placeholder="Search title, ID, state, or route"><select class="select" id="state-filter" style="width:auto"><option value="">All states</option></select><button class="btn primary" data-go="new">Create work</button></div></div>
        <div class="panel"><div class="task-head-row"><div>Work</div><div>State</div><div>Attempt</div><div>Next route</div><div>Priority</div></div><div class="task-list" id="queue-list"></div></div>
      </section>

      <section class="view" id="view-new">
        <div class="section-head"><div><h2>Define controlled work</h2><p>The task envelope freezes file scope and acceptance before dispatch. Routes are ordered executable surfaces, each tied to a committed backend manifest and an optional quota tank.</p></div></div>
        <form class="panel form-panel" id="task-form">
          <div class="form-grid">
            <div class="field third"><label><strong>Task ID</strong> (optional)</label><input class="input code" name="id" placeholder="mw-generated-when-empty"></div>
            <div class="field" style="grid-column:span 8"><label><strong>Title</strong></label><input class="input" name="title" required placeholder="Describe the outcome in one line"></div>
            <div class="field"><label><strong>Instructions</strong></label><textarea class="textarea" name="task" required placeholder="State the requested repository change, relevant constraints, and what must remain untouched."></textarea></div>
            <div class="field half"><label><strong>Allowed file scope</strong></label><textarea class="textarea code" name="files" required placeholder="src/module.py&#10;tests/test_module.py"></textarea><div class="help">One repository-relative file or directory per line. The runner refuses writes outside this scope.</div></div>
            <div class="field half"><label><strong>Frozen acceptance command</strong></label><textarea class="textarea code" name="acceptance" required placeholder="python tests/test_module.py"></textarea><div class="help">This command is operator-supplied and executes in the disposable candidate worktree after the model call.</div></div>
            <div class="field quarter"><label><strong>Priority</strong></label><input class="input" type="number" name="priority" min="0" max="100" value="50"></div>
            <div class="field quarter"><label><strong>Schedule</strong></label><input class="input" type="datetime-local" name="scheduled_for"></div>
            <div class="field quarter"><label><strong>Max attempts</strong></label><input class="input" type="number" name="max_attempts" min="1" max="12" value="1"></div>
            <div class="field quarter"><label><strong>Escalation</strong></label><select class="select" name="escalation_mode"><option value="operator">Operator review</option><option value="next-route-on-error">Next route on infrastructure error</option><option value="next-route-on-failure">Next route on rejection or error</option></select></div>
            <div class="field half"><label><strong>Dependencies</strong></label><input class="input code" name="depends_on" placeholder="task-a, task-b"><div class="help">The task remains blocked until every listed predecessor is ACCEPTED.</div></div>
            <div class="field half" style="display:flex;gap:22px;align-items:center;padding-top:22px"><label class="check-row"><input type="checkbox" name="approval_required"><span><strong>Require approval</strong><br><span class="help">Keep the task gated until an operator approves it.</span></span></label><label class="check-row"><input type="checkbox" name="queue_now" checked><span><strong>Queue after creation</strong><br><span class="help">Approval-required work remains gated.</span></span></label></div>
          </div>
          <div class="detail-section"><div style="display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:12px"><div><h3 style="margin:0">Ordered routes</h3><div class="help">The first eligible route is used. Later routes are available to explicit retries or configured escalation.</div></div><button class="btn small" type="button" id="add-route">Add route</button></div><div id="route-editors"></div></div>
          <div class="form-actions"><button class="btn" type="reset" id="reset-task-form">Clear</button><button class="btn primary" type="submit">Create work envelope</button></div>
        </form>
      </section>

      <section class="view" id="view-cartridges">
        <div class="section-head"><div><h2>Cartridges and quota tanks</h2><p>Committed backend manifests define executable cartridges. Tanks hold operator-observed window headroom and caps. The Desk never receives provider credentials.</p></div><button class="btn primary" id="new-tank-button">Add or update tank</button></div>
        <div class="grid tank-grid" id="tank-grid"></div>
        <div class="panel" style="margin-top:14px"><div class="panel-head"><h3>Model registry</h3><span class="hint">Registry entries are hypotheses unless a measured block cites evidence</span></div><div class="panel-body flush" style="overflow:auto"><table class="model-table"><thead><tr><th>Model</th><th>Provider</th><th>Declared ceiling</th><th>Input / 1M</th><th>Output / 1M</th><th>Evidence</th></tr></thead><tbody id="model-table-body"></tbody></table></div></div>
      </section>

      <section class="view" id="view-evidence">
        <div class="section-head"><div><h2>Evidence and receipts</h2><p>The event ledger is hash-chained. Run verdicts come from `receipt.json` and `tier verify`, while patches remain unapplied until a human or separate host decides what to do with them.</p></div><a class="btn" href="/api/export">Export state</a></div>
        <div class="grid two-col">
          <div class="panel"><div class="panel-head"><h3>Run receipts</h3><span class="hint">Latest attempt per task</span></div><div class="panel-body" id="evidence-runs"></div></div>
          <div class="panel"><div class="panel-head"><h3>Event chain</h3><span class="hint" id="event-chain-summary"></span></div><div class="panel-body flush event-list" id="event-list"></div></div>
        </div>
      </section>

      <section class="view" id="view-settings">
        <div class="section-head"><div><h2>Control policy</h2><p>These limits govern local scheduling. Provider-side limits remain authoritative, so stale or unknown subscription snapshots park the affected routes.</p></div></div>
        <div class="grid two-col">
          <form class="panel form-panel" id="settings-form">
            <div class="form-grid">
              <div class="field half"><label><strong>Concurrent workers</strong></label><input class="input" type="number" name="max_workers" min="1" max="8"></div>
              <div class="field half"><label><strong>Budget timezone</strong></label><input class="input code" name="budget_timezone" placeholder="America/Los_Angeles"></div>
              <div class="field third"><label><strong>Daily run limit</strong></label><input class="input" type="number" name="daily_task_limit" min="1" max="500"></div>
              <div class="field third"><label><strong>Daily cost limit (USD)</strong></label><input class="input" type="number" step="0.01" min="0" name="daily_cost_limit_usd"><div class="help">Zero disables this limit.</div></div>
              <div class="field third"><label><strong>Daily token limit</strong></label><input class="input" type="number" min="0" name="daily_token_limit"><div class="help">Zero disables this limit.</div></div>
              <div class="field half"><label><strong>Scheduler poll interval (ms)</strong></label><input class="input" type="number" min="200" max="5000" name="poll_interval_ms"></div>
              <div class="field half" style="padding-top:27px"><label class="check-row"><input type="checkbox" name="stop_on_failure"><span><strong>Pause after a terminal failure</strong><br><span class="help">Automatic escalation runs first when enabled on the task.</span></span></label></div>
            </div>
            <div class="form-actions"><button class="btn primary" type="submit">Save control policy</button></div>
          </form>
          <div class="panel"><div class="panel-head"><h3>Custody boundary</h3></div><div class="panel-body"><dl class="kv" id="custody-kv"></dl><div class="notice good" style="margin-top:16px;margin-bottom:0"><div>✓</div><div><strong>Disposable interface</strong><p>Closing the browser loses no task state. The daemon, repository, SQLite database, run artifacts, and receipts remain authoritative.</p></div></div></div></div>
        </div>
      </section>
    </div>
  </main>
</div>

<div class="drawer-backdrop" id="drawer-backdrop"></div>
<aside class="drawer" id="task-drawer"><div class="drawer-head"><div><h2 id="drawer-title">Task</h2><div class="id" id="drawer-id"></div></div><button class="btn small" id="close-drawer">Close</button></div><div class="drawer-body" id="drawer-body"></div></aside>
<div class="modal-backdrop" id="modal-backdrop"></div>
<div class="modal" id="artifact-modal"><div class="modal-head"><h3 id="artifact-title">Artifact</h3><button class="btn small" id="close-modal">Close</button></div><div class="modal-body"><pre class="pre" id="artifact-content"></pre></div></div>
<div class="modal" id="tank-modal"><div class="modal-head"><h3>Tank snapshot</h3><button class="btn small" id="close-tank-modal">Close</button></div><div class="modal-body"><form id="tank-form"><div class="form-grid"><div class="field half"><label><strong>Tank ID</strong></label><input class="input code" name="id" required placeholder="claude-subscription"></div><div class="field half"><label><strong>Label</strong></label><input class="input" name="label" required placeholder="Claude subscription"></div><div class="field third"><label><strong>Kind</strong></label><select class="select" name="kind"><option value="subscription">Subscription</option><option value="api">API budget</option><option value="local">Local runtime</option><option value="manual">Manual resource</option></select></div><div class="field third"><label><strong>Headroom remaining (%)</strong></label><input class="input" type="number" step="0.1" min="0" max="100" name="headroom_percent"></div><div class="field third"><label><strong>Hard cap used (%)</strong></label><input class="input" type="number" step="0.1" min="1" max="100" value="80" name="hard_cap_percent"></div><div class="field half"><label><strong>Snapshot max age (minutes)</strong></label><input class="input" type="number" min="1" value="30" name="snapshot_max_age_minutes"></div><div class="field half"><label><strong>Window reset</strong></label><input class="input" type="datetime-local" name="reset_at"></div><div class="field"><label><strong>Notes</strong></label><textarea class="textarea" name="notes" placeholder="Source and interpretation of the snapshot"></textarea></div><div class="field"><label class="check-row"><input type="checkbox" name="enabled" checked><span><strong>Enabled for routing</strong></span></label></div></div><div class="form-actions"><button class="btn primary" type="submit">Save tank</button></div></form></div></div>
<datalist id="manifest-options"></datalist>
<div class="toast-stack" id="toast-stack"></div>

<script>
const TOKEN = "__TIER_DESK_TOKEN__";
let deskState = null;
let currentView = "control";
let selectedTaskId = null;
let routeSerial = 0;
let refreshTimer = null;
let refreshing = false;

const viewNames = {control:"Mission control",queue:"Work queue",new:"New work",cartridges:"Cartridges & tanks",evidence:"Evidence",settings:"Settings"};
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[ch]));
const fmtMoney = (n) => `$${Number(n || 0).toFixed(Number(n || 0) < 10 ? 3 : 2)}`;
const fmtNum = (n) => Number(n || 0).toLocaleString();
const fmtPct = (n) => n == null ? "unknown" : `${Number(n).toFixed(1)}%`;
const fmtTime = (v) => { if (!v) return "not set"; const d = new Date(v); return Number.isNaN(d.valueOf()) ? String(v) : d.toLocaleString(); };
const ago = (v) => { if (!v) return ""; const s=(Date.now()-new Date(v).valueOf())/1000; if(s<60)return `${Math.max(0,Math.floor(s))}s ago`; if(s<3600)return `${Math.floor(s/60)}m ago`; if(s<86400)return `${Math.floor(s/3600)}h ago`; return `${Math.floor(s/86400)}d ago`; };
const statePill = (state) => `<span class="state-pill state-${esc(state)}">${esc(state)}</span>`;
const capabilityPill = (basis) => `<span class="pill">${esc(basis || "unmeasured")}</span>`;

async function api(path, options={}) {
  const init = {method: options.method || "GET", headers: {"Accept":"application/json"}};
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.headers["X-Tier-Desk-Token"] = TOKEN;
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(typeof payload === "string" ? payload : payload.error || `HTTP ${response.status}`);
  return payload;
}

function toast(title, detail="", error=false) {
  const node = document.createElement("div");
  node.className = `toast${error ? " error" : ""}`;
  node.innerHTML = `<strong>${esc(title)}</strong>${detail ? `<div class="small">${esc(detail)}</div>` : ""}`;
  $("#toast-stack").appendChild(node);
  setTimeout(() => node.remove(), 4800);
}

function setView(name) {
  currentView = name;
  $$(".view").forEach(v => v.classList.toggle("active", v.id === `view-${name}`));
  $$(".nav-button[data-view]").forEach(b => b.classList.toggle("active", b.dataset.view === name));
  $("#view-title").textContent = viewNames[name] || name;
  if (name === "new" && !$("#route-editors").children.length) addRouteEditor();
  window.scrollTo({top:0,behavior:"smooth"});
}

function taskAttention(task) {
  if (task.state === "DRAFT" && task.approval_required && !task.approved_at) return "approval required";
  if (task.state === "QUEUED" && task.blocked_by?.length) return `blocked by ${task.blocked_by.map(x=>x.id).join(", ")}`;
  if (task.state === "QUEUED" && task.route_blocked_reason) return task.route_blocked_reason;
  if (["ERROR","REJECTED","INTERRUPTED"].includes(task.state)) return task.last_error || task.state.toLowerCase();
  return null;
}

function renderHeader() {
  const s = deskState;
  $("#repo-path").textContent = s.repo;
  $("#server-status").textContent = `Updated ${ago(s.server_time)}`;
  $("#active-pill").textContent = `${s.active_runs.length} active`;
  const chain = $("#chain-pill");
  chain.textContent = s.event_chain.ok ? "Evidence chain intact" : "Evidence chain error";
  chain.className = `pill ${s.event_chain.ok ? "good" : "bad"}`;
  const pause = $("#pause-button");
  pause.textContent = s.settings.paused ? "Resume" : "Pause";
  pause.className = `btn ${s.settings.paused ? "primary" : ""}`;
}

function renderMetrics() {
  const st = deskState.stats;
  const daily = st.daily;
  const metrics = [
    ["Ready", st.ready, `${st.states.QUEUED || 0} queued`],
    ["Running", st.states.RUNNING || 0, `${deskState.settings.max_workers} worker ceiling`],
    ["Accepted", st.states.ACCEPTED || 0, st.success_rate == null ? "No judged runs" : `${(st.success_rate*100).toFixed(0)}% verified success`],
    ["Needs review", (st.states.REJECTED||0)+(st.states.ERROR||0)+(st.states.INTERRUPTED||0), "Rejected, error, or interrupted"],
    ["Today cost", fmtMoney(daily.cost_usd), `${daily.tasks} started runs`],
    ["Today tokens", fmtNum(daily.total_tokens), `Window ends ${fmtTime(daily.window_end)}`],
  ];
  $("#metric-grid").innerHTML = metrics.map(([k,v,sub]) => `<div class="metric"><div class="kicker">${esc(k)}</div><div class="value">${esc(v)}</div><div class="sub">${esc(sub)}</div></div>`).join("");
}

function renderControlNotices() {
  const box = $("#control-notices");
  let html = "";
  if (deskState.settings.paused) html += `<div class="notice warn"><div>Ⅱ</div><div><strong>Scheduler paused</strong><p>${esc(deskState.settings.pause_reason || "Operator pause")}</p></div></div>`;
  if (!deskState.event_chain.ok) html += `<div class="notice danger"><div>!</div><div><strong>Event chain verification failed</strong><p>${esc(deskState.event_chain.errors.join("; "))}</p></div></div>`;
  const noTanks = deskState.tanks.length === 0;
  const routedToTank = deskState.tasks.some(t => t.routes.some(r => r.tank_id));
  if (noTanks && routedToTank) html += `<div class="notice warn"><div>◈</div><div><strong>Tank-backed routes cannot run</strong><p>Create the named quota tanks and record current headroom before arming those tasks.</p></div></div>`;
  box.innerHTML = html;
}

function renderActiveWork() {
  const running = deskState.tasks.filter(t => t.state === "RUNNING");
  const ready = deskState.tasks.filter(t => t.ready && t.state === "QUEUED").slice(0,8);
  let html = "";
  if (running.length) html += running.map(t => `<div class="active-card" data-task="${esc(t.id)}"><div class="active-top"><h4>${esc(t.title)}</h4><span class="pill"><span class="pulse"></span> running</span></div><div class="active-meta"><span>${esc(t.last_run?.route?.label || "route")}</span><span>attempt ${t.attempt_count}/${t.max_attempts}</span><span>${ago(t.last_run?.started_at)}</span></div></div>`).join("");
  if (ready.length) {
    html += `<div class="muted-2" style="font-size:9px;text-transform:uppercase;letter-spacing:.08em;margin:${running.length?"16px":"0"} 0 8px">Next eligible</div>`;
    html += ready.map(t => `<div class="active-card" data-task="${esc(t.id)}"><div class="active-top"><h4>${esc(t.title)}</h4>${statePill(t.state)}</div><div class="active-meta"><span>${esc(t.next_route?.label || "No route")}</span><span>priority ${t.priority}</span>${t.scheduled_for?`<span>${fmtTime(t.scheduled_for)}</span>`:""}</div></div>`).join("");
  }
  if (!html) html = `<div class="empty"><strong>No active or ready work</strong>Define a task envelope or arm an existing draft.</div>`;
  $("#active-work").innerHTML = html;
}

function renderAttention() {
  const items = deskState.tasks.map(t => [t,taskAttention(t)]).filter(x => x[1]).slice(0,10);
  $("#attention-list").innerHTML = items.length ? items.map(([t,reason]) => `<div class="active-card" data-task="${esc(t.id)}"><div class="active-top"><h4>${esc(t.title)}</h4>${statePill(t.state)}</div><div class="active-meta"><span>${esc(reason)}</span></div></div>`).join("") : `<div class="empty"><strong>No operator intervention required</strong>Gated and failed work will appear here.</div>`;
}

function taskRows(tasks) {
  if (!tasks.length) return `<div class="empty"><strong>No matching work</strong>Adjust the filter or define a task envelope.</div>`;
  return tasks.map(t => {
    const settled = ["ACCEPTED","REJECTED","ERROR","INTERRUPTED","CANCELED"].includes(t.state);
    const routeText = settled ? (t.last_run?.route?.label || "no run route") : (t.next_route?.label || t.route_blocked_reason || "operator");
    return `<div class="task-row" data-task="${esc(t.id)}"><div class="task-title">${esc(t.title)}<div class="id">${esc(t.id)}</div></div><div>${statePill(t.state)}</div><div class="task-when">${t.attempt_count}/${t.max_attempts}</div><div class="task-route" title="${esc(routeText)}">${esc(routeText)}</div><div class="task-priority">${t.priority}</div></div>`;
  }).join("");
}

function renderRecent() { $("#recent-work").innerHTML = taskRows(deskState.tasks.slice(0,9)); }

function renderQueue() {
  const q = $("#task-search").value.trim().toLowerCase();
  const state = $("#state-filter").value;
  const tasks = deskState.tasks.filter(t => {
    const hay = `${t.id} ${t.title} ${t.state} ${t.routes.map(r=>r.label).join(" ")}`.toLowerCase();
    return (!q || hay.includes(q)) && (!state || t.state === state);
  });
  $("#queue-list").innerHTML = taskRows(tasks);
}

function addRouteEditor(route={}) {
  routeSerial += 1;
  const tanks = deskState?.tanks || [];
  const node = document.createElement("div");
  node.className = "route-editor";
  node.dataset.routeSerial = String(routeSerial);
  node.innerHTML = `<div class="route-editor-head"><strong>Route ${routeSerial}</strong><button type="button" class="btn small danger remove-route">Remove</button></div><div class="form-grid"><div class="field half"><label>Label</label><input class="input route-label" value="${esc(route.label || (routeSerial===1?"Primary route":`Fallback ${routeSerial}`))}"></div><div class="field half"><label>Committed backend manifest</label><input class="input code route-manifest" list="manifest-options" value="${esc(route.manifest || deskState?.backend_manifests?.[0]?.path || "pilot_backends.json")}"></div><div class="field quarter"><label>Arm</label><input class="input code route-arm" value="${esc(route.arm || "arm_b")}"></div><div class="field quarter"><label>Quota tank</label><select class="select route-tank"><option value="">No tank gate</option>${tanks.map(t=>`<option value="${esc(t.id)}" ${route.tank_id===t.id?"selected":""}>${esc(t.label)} (${esc(t.id)})</option>`).join("")}</select></div><div class="field quarter"><label>Capability basis</label><select class="select route-capability"><option value="measured" ${route.capability_basis==="measured"?"selected":""}>Measured</option><option value="hypothesis" ${route.capability_basis==="hypothesis"?"selected":""}>Hypothesis</option><option value="unmeasured" ${!route.capability_basis||route.capability_basis==="unmeasured"?"selected":""}>Unmeasured</option></select></div><div class="field quarter"><label>Quota basis</label><select class="select route-quota"><option value="direct" ${route.quota_basis==="direct"?"selected":""}>Direct</option><option value="derived" ${route.quota_basis==="derived"?"selected":""}>Derived</option><option value="operator" ${route.quota_basis==="operator"?"selected":""}>Operator</option><option value="unknown" ${!route.quota_basis||route.quota_basis==="unknown"?"selected":""}>Unknown</option></select></div><div class="field quarter"><label>Estimated max cost (optional)</label><input class="input route-cost" type="number" min="0" step="0.01" value="${esc(route.estimated_max_cost_usd ?? "")}"></div></div>`;
  $("#route-editors").appendChild(node);
  $(".remove-route", node).addEventListener("click", () => { if ($$(".route-editor").length === 1) return toast("At least one route is required", "", true); node.remove(); });
}

function collectRoutes() {
  return $$(".route-editor").map((node,index) => ({
    id: `route-${index+1}`,
    label: $(".route-label",node).value.trim(),
    manifest: $(".route-manifest",node).value.trim(),
    arm: $(".route-arm",node).value.trim(),
    tank_id: $(".route-tank",node).value || null,
    capability_basis: $(".route-capability",node).value,
    quota_basis: $(".route-quota",node).value,
    estimated_max_cost_usd: $(".route-cost",node).value === "" ? null : Number($(".route-cost",node).value),
  }));
}

function resetTaskForm() {
  $("#task-form").reset();
  $("#route-editors").innerHTML = "";
  routeSerial = 0;
  addRouteEditor();
}

function renderTanks() {
  const tanks = deskState.tanks.filter(Boolean);
  $("#manifest-options").innerHTML = (deskState.backend_manifests || []).map(m => `<option value="${esc(m.path)}">${esc(Object.entries(m.arms || {}).map(([a,v])=>`${a}: ${v.model_id || "unknown"}`).join("; "))}</option>`).join("");
  $("#tank-grid").innerHTML = tanks.length ? tanks.map(t => {
    const headroom = t.headroom_percent;
    const width = headroom == null ? 0 : Math.max(0,Math.min(100,headroom));
    const statusClass = t.eligible ? "good" : (t.enabled ? "warn-text" : "muted-2");
    return `<div class="panel tank-card"><div class="tank-top"><div><h3>${esc(t.label)}</h3><div class="id">${esc(t.id)}</div></div><span class="pill ${statusClass}">${esc(t.eligible?"eligible":t.status_reason)}</span></div><div class="gauge"><span style="width:${width}%"></span></div><div class="gauge-meta"><span>${fmtPct(headroom)} remaining</span><span>cap ${fmtPct(t.hard_cap_percent)} used</span></div><dl class="kv" style="margin-top:15px"><dt>Kind</dt><dd>${esc(t.kind)}</dd><dt>Observed</dt><dd>${t.observed_at?`${fmtTime(t.observed_at)} (${ago(t.observed_at)})`:"no snapshot"}</dd><dt>Reset</dt><dd>${fmtTime(t.reset_at)}</dd><dt>Recorded runs</dt><dd>${fmtNum(t.usage?.runs)} · ${fmtMoney(t.usage?.cost_usd)}</dd></dl><div style="margin-top:14px"><button class="btn small edit-tank" data-tank="${esc(t.id)}">Update snapshot</button></div></div>`;
  }).join("") : `<div class="panel empty" style="grid-column:1/-1"><strong>No quota tanks defined</strong>Routes without tanks may run. Subscription and API routes should be tied to a fresh operator-observed tank snapshot.</div>`;

  const models = deskState.models?.models || {};
  $("#model-table-body").innerHTML = Object.entries(models).map(([name,m]) => `<tr><td>${esc(name)}</td><td>${esc(m.provider || "")}</td><td>${esc(m.tier_ceiling || "")}</td><td>${m.input_per_1M == null?"":fmtMoney(m.input_per_1M)}</td><td>${m.output_per_1M == null?"":fmtMoney(m.output_per_1M)}</td><td>${m.measured?'<span class="good">measured block present</span>':'<span class="muted-2">declared only</span>'}</td></tr>`).join("") || `<tr><td colspan="6">No models.json catalog found.</td></tr>`;
}

function evidenceRunCards() {
  const runs = deskState.tasks.map(t => [t,t.last_run]).filter(x=>x[1]);
  return runs.length ? runs.map(([t,r]) => `<div class="run-card"><div class="run-top"><div><strong>${esc(t.title)}</strong><div class="run-id">${esc(r.id)}</div></div>${statePill(r.state)}</div><div class="active-meta"><span>${esc(r.route?.label || "route")}</span><span>${fmtMoney(r.cost_usd)}</span><span>${fmtNum((r.input_tokens||0)+(r.output_tokens||0))} I/O tokens</span><span>${fmtTime(r.completed_at || r.started_at)}</span></div><div class="run-actions"><button class="btn small artifact" data-run="${esc(r.id)}" data-artifact="log">Log</button><button class="btn small artifact" data-run="${esc(r.id)}" data-artifact="receipt" ${r.receipt?"":"disabled"}>Receipt</button><a class="btn small" href="/api/runs/${encodeURIComponent(r.id)}/patch">Patch</a></div></div>`).join("") : `<div class="empty"><strong>No run evidence yet</strong>Receipts appear after the first claimed task settles.</div>`;
}

function renderEvidence() {
  $("#evidence-runs").innerHTML = evidenceRunCards();
  $("#event-chain-summary").textContent = deskState.event_chain.ok ? `${deskState.events.length} recent events, chain intact` : deskState.event_chain.errors.join("; ");
  $("#event-list").innerHTML = deskState.events.length ? deskState.events.map(e => `<div class="event-row"><div class="event-time">${fmtTime(e.ts)}</div><div class="event-kind">${esc(e.kind)}</div><div class="event-detail">${esc(e.task_id || "system")}${e.run_id?` · ${esc(e.run_id)}`:""}<br><span class="muted-2">${esc(JSON.stringify(e.detail))}</span></div></div>`).join("") : `<div class="empty">No events.</div>`;
}

function renderSettings() {
  const s = deskState.settings;
  const form = $("#settings-form");
  for (const key of ["max_workers","budget_timezone","daily_task_limit","daily_cost_limit_usd","daily_token_limit","poll_interval_ms"]) form.elements[key].value = s[key];
  form.elements.stop_on_failure.checked = !!s.stop_on_failure;
  $("#custody-kv").innerHTML = `<dt>Repository</dt><dd>${esc(deskState.repo)}</dd><dt>Control database</dt><dd>${esc(deskState.database)}</dd><dt>Verified evidence root</dt><dd>${esc(deskState.runs_dir)}</dd><dt>Execution authority</dt><dd>Committed backend manifests invoked through <span class="mono">tier run</span></dd><dt>Verdict authority</dt><dd><span class="mono">receipt.json</span> plus <span class="mono">tier verify</span></dd><dt>Patch policy</dt><dd>Never applied or merged automatically</dd>`;
}

function renderAll() {
  if (!deskState) return;
  renderHeader(); renderControlNotices(); renderMetrics(); renderActiveWork(); renderAttention(); renderRecent(); renderQueue(); renderTanks(); renderEvidence(); renderSettings();
  if (selectedTaskId) openTask(selectedTaskId, false);
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const payload = await api("/api/state");
    deskState = payload.state;
    renderAll();
  } catch (error) {
    $("#server-status").textContent = "Connection failed";
    toast("Could not refresh the Desk", error.message, true);
  } finally { refreshing = false; }
}

function taskActionButtons(t) {
  const buttons = [];
  if (t.state === "DRAFT") {
    if (t.approval_required && !t.approved_at) buttons.push(["approve","Approve and queue","primary"]);
    else buttons.push(["arm","Arm task","primary"]);
    buttons.push(["cancel","Cancel","danger"]);
  } else if (t.state === "QUEUED") {
    buttons.push(["hold","Return to draft",""]); buttons.push(["cancel","Cancel","danger"]);
  } else if (t.state === "RUNNING") buttons.push(["cancel","Cancel run","danger"]);
  else if (["REJECTED","ERROR","INTERRUPTED","CANCELED"].includes(t.state) && t.attempt_count < t.max_attempts) buttons.push(["retry","Retry next route","primary"]);
  return buttons.map(([action,label,kind]) => `<button class="btn ${kind}" data-task-action="${action}">${label}</button>`).join("");
}

async function openTask(id, fetchFresh=true) {
  selectedTaskId = id;
  let t = deskState.tasks.find(x=>x.id===id);
  if (fetchFresh) {
    try { t = (await api(`/api/tasks/${encodeURIComponent(id)}`)).task; } catch(error) { return toast("Could not load task", error.message, true); }
  }
  if (!t) return;
  $("#drawer-title").textContent = t.title;
  $("#drawer-id").textContent = t.id;
  const blocked = taskAttention(t);
  const routes = t.route_statuses?.length ? t.route_statuses : (t.routes||[]).map(r=>({route:r,eligible:true,reason:"not currently evaluated"}));
  const runs = t.runs || (t.last_run ? [t.last_run] : []);
  $("#drawer-body").innerHTML = `<div class="drawer-actions">${taskActionButtons(t)}</div>${blocked?`<div class="notice ${["ERROR","REJECTED"].includes(t.state)?"danger":"warn"}"><div>!</div><div><strong>Control condition</strong><p>${esc(blocked)}</p></div></div>`:""}<dl class="kv"><dt>State</dt><dd>${statePill(t.state)}</dd><dt>Priority</dt><dd>${t.priority}</dd><dt>Attempts</dt><dd>${t.attempt_count} of ${t.max_attempts}</dd><dt>Escalation</dt><dd>${esc(t.escalation_mode)}</dd><dt>Scheduled</dt><dd>${fmtTime(t.scheduled_for)}</dd><dt>Approval</dt><dd>${t.approval_required ? (t.approved_at?`approved ${fmtTime(t.approved_at)}`:"required") : "not required"}</dd></dl><div class="detail-section"><h3>Instructions</h3><pre class="pre">${esc(t.task)}</pre></div><div class="detail-section"><h3>File scope</h3><pre class="pre">${esc(t.files.join("\n"))}</pre></div><div class="detail-section"><h3>Frozen acceptance</h3><pre class="pre">${esc(t.acceptance)}</pre></div><div class="detail-section"><h3>Dependencies</h3>${t.dependencies.length?t.dependencies.map(d=>`<span class="pill" style="margin:0 5px 5px 0">${esc(d.id)} · ${esc(d.state)}</span>`).join(""):'<span class="muted">None</span>'}</div><div class="detail-section"><h3>Route plan</h3>${routes.map((s,i)=>`<div class="route-status"><div class="top"><strong>${i+1}. ${esc(s.route.label)}</strong><span class="pill ${s.consumed?"muted-2":s.eligible?"good":"warn-text"}">${s.consumed?"consumed":s.eligible?"eligible":esc(s.reason)}</span></div><div class="meta"><span>${esc(s.route.manifest)} · ${esc(s.route.arm)}</span><span>tank ${esc(s.route.tank_id || "none")}</span><span>${esc(s.route.capability_basis)}</span><span>quota ${esc(s.route.quota_basis)}</span></div></div>`).join("")}</div><div class="detail-section"><h3>Attempts and evidence</h3>${runs.length?runs.map(r=>`<div class="run-card"><div class="run-top"><div><strong>Attempt ${r.attempt}</strong><div class="run-id">${esc(r.id)}</div></div>${statePill(r.state)}</div><div class="active-meta"><span>${esc(r.route?.label || "route")}</span><span>${fmtMoney(r.cost_usd)}</span><span>${fmtTime(r.completed_at || r.started_at)}</span></div>${r.error?`<div class="bad" style="margin-top:8px;font-size:11px">${esc(r.error)}</div>`:""}<div class="run-actions"><button class="btn small artifact" data-run="${esc(r.id)}" data-artifact="log">Log</button><button class="btn small artifact" data-run="${esc(r.id)}" data-artifact="receipt" ${r.receipt?"":"disabled"}>Receipt</button><a class="btn small" href="/api/runs/${encodeURIComponent(r.id)}/patch">Patch</a></div></div>`).join(""):'<span class="muted">No attempts yet.</span>'}</div>`;
  $("#drawer-backdrop").classList.add("open"); $("#task-drawer").classList.add("open");
}

function closeDrawer() { selectedTaskId=null; $("#drawer-backdrop").classList.remove("open"); $("#task-drawer").classList.remove("open"); }

async function performTaskAction(action) {
  if (!selectedTaskId) return;
  if (action === "cancel" && !confirm("Cancel this task or active run?")) return;
  try {
    await api(`/api/tasks/${encodeURIComponent(selectedTaskId)}/${action}`, {method:"POST",body:{}});
    toast("Task updated", action);
    await refresh();
    await openTask(selectedTaskId, true);
  } catch(error) { toast("Task action refused", error.message, true); }
}

async function showArtifact(runId, artifact) {
  const title = `${runId} · ${artifact}`;
  $("#artifact-title").textContent = title;
  $("#artifact-content").textContent = "Loading…";
  $("#modal-backdrop").classList.add("open"); $("#artifact-modal").classList.add("open");
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/${artifact}`);
    const text = await response.text();
    if (!response.ok) throw new Error(text);
    if (artifact === "receipt") {
      try { $("#artifact-content").textContent = JSON.stringify(JSON.parse(text), null, 2); }
      catch { $("#artifact-content").textContent = text; }
    } else $("#artifact-content").textContent = text || "No output.";
  } catch(error) { $("#artifact-content").textContent = error.message; }
}

function closeModal() { $("#modal-backdrop").classList.remove("open"); $$(".modal").forEach(x=>x.classList.remove("open")); }

function openTankModal(tank=null) {
  const form = $("#tank-form"); form.reset();
  form.elements.enabled.checked = tank ? !!tank.enabled : true;
  if (tank) {
    form.elements.id.value=tank.id; form.elements.id.readOnly=true; form.elements.label.value=tank.label; form.elements.kind.value=tank.kind; form.elements.headroom_percent.value=tank.headroom_percent ?? ""; form.elements.hard_cap_percent.value=tank.hard_cap_percent; form.elements.snapshot_max_age_minutes.value=Math.round(tank.snapshot_max_age_seconds/60); form.elements.reset_at.value=tank.reset_at ? new Date(tank.reset_at).toISOString().slice(0,16) : ""; form.elements.notes.value=tank.notes || "";
  } else { form.elements.id.readOnly=false; form.elements.hard_cap_percent.value=80; form.elements.snapshot_max_age_minutes.value=30; }
  $("#modal-backdrop").classList.add("open"); $("#tank-modal").classList.add("open");
}

async function submitTask(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const scheduled = form.elements.scheduled_for.value;
  const payload = {
    id: form.elements.id.value.trim() || undefined,
    title: form.elements.title.value.trim(),
    task: form.elements.task.value.trim(),
    files: form.elements.files.value,
    acceptance: form.elements.acceptance.value.trim(),
    priority: Number(form.elements.priority.value),
    scheduled_for: scheduled ? new Date(scheduled).toISOString() : null,
    max_attempts: Number(form.elements.max_attempts.value),
    escalation_mode: form.elements.escalation_mode.value,
    depends_on: form.elements.depends_on.value,
    approval_required: form.elements.approval_required.checked,
    queue_now: form.elements.queue_now.checked,
    routes: collectRoutes(),
  };
  try {
    const result = await api("/api/tasks", {method:"POST",body:payload});
    toast("Work envelope created", result.task.id);
    resetTaskForm(); await refresh(); setView("queue"); openTask(result.task.id, true);
  } catch(error) { toast("Work envelope refused", error.message, true); }
}

async function submitTank(event) {
  event.preventDefault(); const form=event.currentTarget;
  const reset=form.elements.reset_at.value;
  const payload={id:form.elements.id.value.trim(),label:form.elements.label.value.trim(),kind:form.elements.kind.value,enabled:form.elements.enabled.checked,headroom_percent:form.elements.headroom_percent.value===""?null:Number(form.elements.headroom_percent.value),hard_cap_percent:Number(form.elements.hard_cap_percent.value),snapshot_max_age_seconds:Number(form.elements.snapshot_max_age_minutes.value)*60,reset_at:reset?new Date(reset).toISOString():null,notes:form.elements.notes.value,observed_at:form.elements.headroom_percent.value===""?null:new Date().toISOString()};
  try { await api("/api/tanks",{method:"POST",body:payload}); toast("Tank snapshot saved",payload.id); closeModal(); await refresh(); } catch(error) { toast("Tank update refused",error.message,true); }
}

async function submitSettings(event) {
  event.preventDefault(); const f=event.currentTarget;
  const body={max_workers:Number(f.elements.max_workers.value),budget_timezone:f.elements.budget_timezone.value.trim(),daily_task_limit:Number(f.elements.daily_task_limit.value),daily_cost_limit_usd:Number(f.elements.daily_cost_limit_usd.value),daily_token_limit:Number(f.elements.daily_token_limit.value),poll_interval_ms:Number(f.elements.poll_interval_ms.value),stop_on_failure:f.elements.stop_on_failure.checked};
  try { await api("/api/settings",{method:"POST",body}); toast("Control policy saved"); await refresh(); } catch(error) { toast("Settings refused",error.message,true); }
}

async function togglePause() {
  try { if (deskState.settings.paused) await api("/api/control/resume",{method:"POST",body:{}}); else await api("/api/control/pause",{method:"POST",body:{reason:"operator paused scheduling"}}); await refresh(); } catch(error) { toast("Control action failed",error.message,true); }
}

async function emergencyStop() {
  if (!confirm("Emergency stop cancels every active run and pauses scheduling. Continue?")) return;
  try { await api("/api/control/emergency-stop",{method:"POST",body:{}}); toast("Emergency stop applied"); await refresh(); } catch(error) { toast("Emergency stop failed",error.message,true); }
}

function bindEvents() {
  document.addEventListener("click", event => {
    const nav=event.target.closest("[data-view]"); if(nav) return setView(nav.dataset.view);
    const go=event.target.closest("[data-go]"); if(go) return setView(go.dataset.go);
    const task=event.target.closest("[data-task]"); if(task) return openTask(task.dataset.task,true);
    const action=event.target.closest("[data-task-action]"); if(action) return performTaskAction(action.dataset.taskAction);
    const artifact=event.target.closest(".artifact"); if(artifact) return showArtifact(artifact.dataset.run,artifact.dataset.artifact);
    const editTank=event.target.closest(".edit-tank"); if(editTank) return openTankModal(deskState.tanks.find(t=>t && t.id===editTank.dataset.tank));
  });
  $("#task-search").addEventListener("input",renderQueue); $("#state-filter").addEventListener("change",renderQueue);
  $("#add-route").addEventListener("click",()=>addRouteEditor());
  $("#task-form").addEventListener("submit",submitTask); $("#task-form").addEventListener("reset",()=>setTimeout(()=>{ $("#route-editors").innerHTML=""; routeSerial=0; addRouteEditor(); },0));
  $("#settings-form").addEventListener("submit",submitSettings); $("#tank-form").addEventListener("submit",submitTank);
  $("#pause-button").addEventListener("click",togglePause); $("#emergency-button").addEventListener("click",emergencyStop);
  $("#new-tank-button").addEventListener("click",()=>openTankModal());
  $("#close-drawer").addEventListener("click",closeDrawer); $("#drawer-backdrop").addEventListener("click",closeDrawer);
  $("#close-modal").addEventListener("click",closeModal); $("#close-tank-modal").addEventListener("click",closeModal); $("#modal-backdrop").addEventListener("click",closeModal);
  document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeDrawer();closeModal();}});
}

function populateFilters() {
  $("#state-filter").innerHTML = `<option value="">All states</option>${["DRAFT","QUEUED","RUNNING","ACCEPTED","REJECTED","ERROR","INTERRUPTED","CANCELED"].map(s=>`<option>${s}</option>`).join("")}`;
}

async function boot() {
  bindEvents(); populateFilters();
  await refresh();
  resetTaskForm();
  refreshTimer = setInterval(refresh, 2200);
  document.addEventListener("visibilitychange",()=>{ if(!document.hidden) refresh(); });
}
boot();
</script>
</body>
</html>
'''
