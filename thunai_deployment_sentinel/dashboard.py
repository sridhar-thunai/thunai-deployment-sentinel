"""Lightweight HTTP dashboard for the Thunai Deployment Sentinel.

Exposes:
  GET /          → Single-page HTML dashboard (auto-refreshes every 30 s)
  GET /api/status → JSON array of per-application sentinel decisions
  GET /healthz   → Liveness probe endpoint (always 200 {"ok":true})
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .sentinel import SentinelDecision

# ---------------------------------------------------------------------------
# Thread-safe in-memory status store
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_app_statuses: dict[str, dict[str, Any]] = {}


def record_decision(decision: SentinelDecision) -> None:
    """Store the latest sentinel decision for an application."""
    with _lock:
        _app_statuses[decision.rollout.application] = {
            "application": decision.rollout.application,
            "environment": decision.rollout.environment,
            "revision": decision.rollout.revision,
            "health_status": decision.rollout.health_status,
            "sync_status": decision.rollout.status,
            "regression_detected": decision.regression_detected,
            "reasons": list(decision.reasons),
            "error_rate": decision.rollout.error_rate,
            "baseline_error_rate": decision.rollout.baseline_error_rate,
            "latency_ms": decision.rollout.latency_ms,
            "baseline_latency_ms": decision.rollout.baseline_latency_ms,
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "state": "error" if decision.regression_detected else "healthy",
        }


def record_error(app_name: str, error: str) -> None:
    """Record a polling/evaluation error for an application."""
    with _lock:
        existing = _app_statuses.get(app_name, {})
        _app_statuses[app_name] = {
            **existing,
            "application": app_name,
            "state": "error",
            "regression_detected": True,
            "reasons": [f"Sentinel polling error: {error}"],
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }


# ---------------------------------------------------------------------------
# HTML Dashboard (embedded — no static file server needed)
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Thunai Deployment Sentinel</title>
  <style>
    :root {
      --bg: #0f1117;
      --surface: #1a1d27;
      --border: #2a2d3a;
      --green: #22c55e;
      --green-dim: #16a34a22;
      --red: #ef4444;
      --red-dim: #dc262622;
      --yellow: #f59e0b;
      --yellow-dim: #d9770622;
      --text: #e2e8f0;
      --muted: #64748b;
      --accent: #6366f1;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
    }

    /* ── Header ── */
    header {
      background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%);
      border-bottom: 1px solid var(--border);
      padding: 24px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
    }
    .header-left { display: flex; align-items: center; gap: 14px; }
    .logo {
      width: 44px; height: 44px;
      background: var(--accent);
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 22px;
    }
    h1 { font-size: 1.4rem; font-weight: 700; letter-spacing: -0.3px; }
    h1 span { color: #a5b4fc; }
    .sub { font-size: 0.75rem; color: #a5b4fc; margin-top: 2px; }
    .header-right { display: flex; align-items: center; gap: 16px; }
    .refresh-btn {
      background: rgba(99,102,241,0.2);
      border: 1px solid #6366f1;
      color: #a5b4fc;
      padding: 7px 16px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.85rem;
      transition: background 0.2s;
    }
    .refresh-btn:hover { background: rgba(99,102,241,0.35); }
    .countdown { font-size: 0.8rem; color: var(--muted); }

    /* ── Main ── */
    main { padding: 32px; max-width: 1200px; margin: 0 auto; }

    /* ── Summary bar ── */
    .summary-bar {
      display: flex;
      gap: 16px;
      margin-bottom: 28px;
      flex-wrap: wrap;
    }
    .summary-card {
      flex: 1; min-width: 140px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px 20px;
      text-align: center;
    }
    .summary-card .num { font-size: 2rem; font-weight: 800; }
    .summary-card .label { font-size: 0.75rem; color: var(--muted); margin-top: 2px; }
    .num-green { color: var(--green); }
    .num-red { color: var(--red); }
    .num-white { color: var(--text); }

    /* ── App cards grid ── */
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 20px;
    }

    .card {
      background: var(--surface);
      border-radius: 14px;
      border: 1px solid var(--border);
      padding: 24px;
      transition: transform 0.15s, box-shadow 0.15s;
    }
    .card:hover { transform: translateY(-2px); box-shadow: 0 8px 32px rgba(0,0,0,0.4); }

    .card.healthy { border-left: 4px solid var(--green); }
    .card.unhealthy { border-left: 4px solid var(--red); }
    .card.pending { border-left: 4px solid var(--yellow); }

    .card-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      margin-bottom: 16px;
      gap: 8px;
    }
    .app-name {
      font-size: 1.1rem;
      font-weight: 700;
      word-break: break-all;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.5px;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .badge-green { background: var(--green-dim); color: var(--green); border: 1px solid #22c55e44; }
    .badge-red   { background: var(--red-dim);   color: var(--red);   border: 1px solid #ef444444; }
    .badge-yellow{ background: var(--yellow-dim); color: var(--yellow); border: 1px solid #f59e0b44; }
    .dot { width: 7px; height: 7px; border-radius: 50%; }
    .dot-green { background: var(--green); box-shadow: 0 0 6px var(--green); animation: pulse-g 2s infinite; }
    .dot-red   { background: var(--red);   box-shadow: 0 0 6px var(--red);   animation: pulse-r 2s infinite; }
    .dot-yellow{ background: var(--yellow); }

    @keyframes pulse-g { 0%,100%{opacity:1} 50%{opacity:0.4} }
    @keyframes pulse-r { 0%,100%{opacity:1} 50%{opacity:0.4} }

    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
    }
    .chip {
      font-size: 0.72rem;
      padding: 3px 8px;
      border-radius: 6px;
      background: rgba(255,255,255,0.06);
      color: var(--muted);
    }
    .chip strong { color: var(--text); font-weight: 600; }

    /* ── Reasons ── */
    .reasons-header {
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--red);
      text-transform: uppercase;
      letter-spacing: 0.6px;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .reasons-list {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .reason-item {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      font-size: 0.82rem;
      background: var(--red-dim);
      border: 1px solid #ef444422;
      border-radius: 8px;
      padding: 8px 12px;
      line-height: 1.4;
    }
    .reason-icon { color: var(--red); flex-shrink: 0; margin-top: 1px; }

    /* ── Metrics bar ── */
    .metrics {
      display: flex;
      gap: 12px;
      margin-top: 14px;
      flex-wrap: wrap;
    }
    .metric-box {
      flex: 1; min-width: 120px;
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
    }
    .metric-label { font-size: 0.65rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
    .metric-value { font-size: 1rem; font-weight: 700; margin-top: 2px; }
    .metric-baseline { font-size: 0.65rem; color: var(--muted); margin-top: 1px; }

    /* ── Footer ── */
    .card-footer {
      margin-top: 16px;
      padding-top: 12px;
      border-top: 1px solid var(--border);
      font-size: 0.7rem;
      color: var(--muted);
      display: flex;
      justify-content: space-between;
    }

    /* ── Empty / Loading state ── */
    .empty-state {
      text-align: center;
      padding: 64px 24px;
      color: var(--muted);
      grid-column: 1 / -1;
    }
    .empty-state .spinner {
      width: 40px; height: 40px;
      border: 3px solid var(--border);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin: 0 auto 16px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    .last-updated { font-size: 0.75rem; color: var(--muted); }

    /* ── Revision pill ── */
    .revision-pill {
      font-family: 'Courier New', monospace;
      font-size: 0.7rem;
      background: rgba(255,255,255,0.07);
      padding: 2px 6px;
      border-radius: 4px;
      color: #a5b4fc;
    }
  </style>
</head>
<body>
  <header>
    <div class="header-left">
      <div class="logo">&#x1F6E1;</div>
      <div>
        <h1>Thunai <span>Deployment Sentinel</span></h1>
        <div class="sub">Real-time ArgoCD rollout health monitor</div>
      </div>
    </div>
    <div class="header-right">
      <span class="countdown" id="countdown">Next refresh in 30s</span>
      <button class="refresh-btn" onclick="fetchStatus()">&#x21BB; Refresh</button>
    </div>
  </header>

  <main>
    <div class="summary-bar" id="summary-bar" style="display:none;">
      <div class="summary-card">
        <div class="num num-white" id="total-count">0</div>
        <div class="label">Apps Watched</div>
      </div>
      <div class="summary-card">
        <div class="num num-green" id="healthy-count">0</div>
        <div class="label">Healthy</div>
      </div>
      <div class="summary-card">
        <div class="num num-red" id="unhealthy-count">0</div>
        <div class="label">Unhealthy / Degraded</div>
      </div>
    </div>

    <div class="grid" id="grid">
      <div class="empty-state">
        <div class="spinner"></div>
        <div>Loading sentinel status&hellip;</div>
      </div>
    </div>
  </main>

  <script>
    let countdown = 30;
    let timer;

    function fmt(val) {
      return val !== undefined && val !== null ? String(val) : '—';
    }

    function pct(v) {
      return (v * 100).toFixed(2) + '%';
    }

    function renderCard(app) {
      const isHealthy = !app.regression_detected;
      const state = isHealthy ? 'healthy' : 'unhealthy';
      const revShort = app.revision ? app.revision.slice(0, 8) : '—';

      const badgeHtml = isHealthy
        ? `<span class="badge badge-green"><span class="dot dot-green"></span>HEALTHY</span>`
        : `<span class="badge badge-red"><span class="dot dot-red"></span>UNHEALTHY</span>`;

      const reasonsHtml = (!isHealthy && app.reasons && app.reasons.length)
        ? `<div class="reasons-header">
             <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
             Reasons for regression
           </div>
           <ul class="reasons-list">
             ${app.reasons.map(r => `
               <li class="reason-item">
                 <span class="reason-icon">&#x25CF;</span>
                 <span>${escHtml(r)}</span>
               </li>`).join('')}
           </ul>`
        : '';

      const hasMetrics = app.error_rate > 0 || app.latency_ms > 0 || app.baseline_latency_ms > 0;
      const metricsHtml = hasMetrics
        ? `<div class="metrics">
             ${app.error_rate !== undefined ? `
             <div class="metric-box">
               <div class="metric-label">Error Rate</div>
               <div class="metric-value" style="color:${app.error_rate > app.baseline_error_rate ? 'var(--red)' : 'var(--green)'}">
                 ${pct(app.error_rate)}
               </div>
               <div class="metric-baseline">Baseline: ${pct(app.baseline_error_rate)}</div>
             </div>` : ''}
             ${app.latency_ms > 0 ? `
             <div class="metric-box">
               <div class="metric-label">Latency</div>
               <div class="metric-value" style="color:${app.latency_ms > app.baseline_latency_ms * 1.5 ? 'var(--red)' : 'var(--green)'}">
                 ${Math.round(app.latency_ms)} ms
               </div>
               <div class="metric-baseline">Baseline: ${Math.round(app.baseline_latency_ms)} ms</div>
             </div>` : ''}
           </div>`
        : '';

      return `
        <div class="card ${state}">
          <div class="card-header">
            <div class="app-name">${escHtml(app.application)}</div>
            ${badgeHtml}
          </div>
          <div class="meta">
            <span class="chip">Env: <strong>${escHtml(app.environment || '—')}</strong></span>
            <span class="chip">Health: <strong>${escHtml(app.health_status || '—')}</strong></span>
            <span class="chip">Sync: <strong>${escHtml(app.sync_status || '—')}</strong></span>
            ${app.revision ? `<span class="chip">Rev: <span class="revision-pill">${escHtml(revShort)}</span></span>` : ''}
          </div>
          ${reasonsHtml}
          ${metricsHtml}
          <div class="card-footer">
            <span>Last checked: ${app.last_checked ? new Date(app.last_checked).toLocaleString() : '—'}</span>
          </div>
        </div>`;
    }

    function escHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function updateSummary(apps) {
      const healthy = apps.filter(a => !a.regression_detected).length;
      document.getElementById('total-count').textContent = apps.length;
      document.getElementById('healthy-count').textContent = healthy;
      document.getElementById('unhealthy-count').textContent = apps.length - healthy;
      document.getElementById('summary-bar').style.display = 'flex';
    }

    async function fetchStatus() {
      const grid = document.getElementById('grid');
      try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const apps = await res.json();
        if (!apps || apps.length === 0) {
          grid.innerHTML = `<div class="empty-state">
            <div style="font-size:2rem; margin-bottom:12px;">&#x23F3;</div>
            <div>No applications being watched yet.</div>
            <div style="font-size:0.8rem; margin-top:6px;">The sentinel will populate data once it polls ArgoCD.</div>
          </div>`;
          document.getElementById('summary-bar').style.display = 'none';
        } else {
          grid.innerHTML = apps.map(renderCard).join('');
          updateSummary(apps);
        }
      } catch (err) {
        grid.innerHTML = `<div class="empty-state">
          <div style="font-size:2rem; margin-bottom:12px; color:var(--red);">&#x26A0;</div>
          <div style="color:var(--red);">Failed to load sentinel status</div>
          <div style="font-size:0.8rem; margin-top:6px; color:var(--muted);">${escHtml(String(err))}</div>
        </div>`;
      }
      resetCountdown();
    }

    function resetCountdown() {
      countdown = 30;
      clearInterval(timer);
      timer = setInterval(() => {
        countdown--;
        document.getElementById('countdown').textContent = 'Next refresh in ' + countdown + 's';
        if (countdown <= 0) {
          fetchStatus();
        }
      }, 1000);
    }

    fetchStatus();
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]  # strip query string
        if path in ("/", "/index.html"):
            self._respond(200, "text/html; charset=utf-8", _HTML.encode("utf-8"))
        elif path == "/api/status":
            with _lock:
                payload = list(_app_statuses.values())
            body = json.dumps(payload).encode()
            self._respond(200, "application/json", body, extra_headers={"Access-Control-Allow-Origin": "*"})
        elif path == "/healthz":
            self._respond(200, "application/json", b'{"ok":true}')
        else:
            self.send_error(404)

    def _respond(
        self,
        code: int,
        content_type: str,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # suppress default access log noise


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

def start_dashboard(host: str = "0.0.0.0", port: int = 8080) -> HTTPServer:
    """Start the dashboard HTTP server in a daemon background thread."""
    server = HTTPServer((host, port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[sentinel] dashboard listening on http://{host}:{port}", flush=True)
    return server
