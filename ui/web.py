"""Web console — the Ragnar-style dashboard, rendered from the same UIModel.

Deliberately dependency-free: stdlib `http.server` plus Server-Sent Events rather
than Flask + Socket.IO. Event flow here is one-way (server -> browser) and the
few control actions are plain POSTs, so a WebSocket stack buys nothing and costs
a Pi Zero real memory. SSE also reconnects on its own, which matters on a field
node whose backhaul comes and goes.

Request handling lives in `DashboardApp.handle`, a pure
(method, path, body) -> (status, headers, body) function. The socket server is a
thin adapter over it, so every route is tested without binding a port.

The palette is derived from the same `Theme` the LCD renders with, so restyling
`theme.json` restyles both surfaces at once.
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple

from rudestorm.ui.model import Action, UIModel
from rudestorm.ui.theme import DEFAULT_THEME, RGB, Theme

Response = Tuple[int, Dict[str, str], bytes]

JSON_HEADERS = {"Content-Type": "application/json"}


def _css_rgb(c: RGB) -> str:
    return f"rgb({c[0]},{c[1]},{c[2]})"


def _theme_css(theme: Theme) -> str:
    """Emit the theme as CSS custom properties, so both surfaces share a palette."""
    return "\n".join(
        f"      --{name.replace('_', '-')}: {_css_rgb(getattr(theme, name))};"
        for name in ("surface", "surface_alt", "text", "text_dim", "accent",
                     "clear", "watch", "alert", "selection", "selection_text")
    )


class DashboardApp:
    """Routing and state for the web console."""

    def __init__(self, model: UIModel, theme: Theme = DEFAULT_THEME) -> None:
        self.model = model
        self.theme = theme
        self._subscribers: List["queue.Queue[str]"] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------- broadcast

    def subscribe(self) -> "queue.Queue[str]":
        q: "queue.Queue[str]" = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[str]") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def broadcast(self, payload: dict) -> int:
        """Push a payload to every live SSE client. Returns delivery count.

        A slow client is dropped rather than allowed to block the sensor loop —
        a browser tab must never be able to stall detection.
        """
        blob = json.dumps(payload, separators=(",", ":"))
        delivered = 0
        with self._lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(blob)
                    delivered += 1
                except queue.Full:
                    self._subscribers.remove(q)
        return delivered

    def publish_event(self, event) -> int:
        """Ingest a ThreatEvent into the model and push it to the browser."""
        self.model.ingest_event(event)
        return self.broadcast({"type": "event", "event": event.to_dict(),
                               "posture": self.model.posture().value})

    # ---------------------------------------------------------------- routes

    def handle(self, method: str, path: str, body: bytes = b"") -> Response:
        if method == "GET" and path in ("/", "/index.html"):
            return 200, {"Content-Type": "text/html; charset=utf-8"}, \
                self.render_page().encode("utf-8")

        if method == "GET" and path == "/api/snapshot":
            return self._json(self.model.snapshot())

        if method == "GET" and path == "/api/catalog":
            registry = self.model._registry
            return self._json({
                "node": {"tier": registry.node.tier, "ram_mb": registry.node.ram_mb,
                         "notes": registry.node.notes},
                "privacy_ceiling": registry.privacy_ceiling.label,
                "cogs": [
                    {**registry.manifests[r.cog_id].to_dict(),
                     "loaded": r.loaded, "reason": r.reason}
                    for r in registry.results if r.cog_id in registry.manifests
                ],
            })

        if method == "POST" and path == "/api/input":
            return self._input(body)

        return 404, JSON_HEADERS, b'{"error":"not found"}'

    def _input(self, body: bytes) -> Response:
        try:
            action = Action(json.loads(body or b"{}").get("action", ""))
        except (ValueError, json.JSONDecodeError):
            return 400, JSON_HEADERS, b'{"error":"unknown action"}'
        result = self.model.dispatch(action)
        snapshot = self.model.snapshot()
        self.broadcast({"type": "nav", "snapshot": snapshot})
        return self._json({"result": result, "snapshot": snapshot})

    @staticmethod
    def _json(payload: dict) -> Response:
        return 200, JSON_HEADERS, json.dumps(payload).encode("utf-8")

    # ------------------------------------------------------------------ page

    def render_page(self) -> str:
        return _PAGE.replace("__THEME__", _theme_css(self.theme))


class _Handler(BaseHTTPRequestHandler):
    """Socket adapter. All logic lives in DashboardApp.handle."""

    app: DashboardApp  # injected by serve()
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args) -> None:  # quiet by default
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/stream":
            self._stream()
            return
        self._respond(*self.app.handle("GET", self.path))

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self._respond(*self.app.handle("POST", self.path, body))

    def _respond(self, status: int, headers: Dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self) -> None:  # pragma: no cover - long-lived connection
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.app.subscribe()
        try:
            while True:
                try:
                    blob = q.get(timeout=15)
                    self.wfile.write(f"data: {blob}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")  # hold the connection
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.app.unsubscribe(q)


def serve(app: DashboardApp, host: str = "127.0.0.1", port: int = 8000
          ) -> ThreadingHTTPServer:
    """Start the dashboard. Binds loopback by default — a field node's console
    should be reached over an explicit tunnel, not exposed on every interface."""
    handler = type("BoundHandler", (_Handler,), {"app": app})
    server = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RudeStorm</title>
<style>
    :root {
__THEME__
      --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; background: var(--surface); color: var(--text);
      font-family: var(--mono); font-size: 14px; line-height: 1.5;
    }
    header {
      display: flex; align-items: center; gap: 16px;
      padding: 14px 20px; border-bottom: 1px solid var(--surface-alt);
      position: sticky; top: 0; background: var(--surface); z-index: 2;
    }
    h1 { font-size: 15px; margin: 0; letter-spacing: .14em; text-transform: uppercase; }
    h1 span { color: var(--accent); }
    #posture {
      padding: 4px 14px; border-radius: 3px; font-weight: 700;
      letter-spacing: .18em; font-size: 12px; color: var(--selection-text);
      background: var(--clear); transition: background .25s ease;
    }
    #posture.watch { background: var(--watch); }
    #posture.alert { background: var(--alert); animation: pulse 1.4s infinite; }
    @keyframes pulse { 50% { opacity: .55; } }
    @media (prefers-reduced-motion: reduce) {
      #posture.alert { animation: none; }
    }
    #head { margin-left: auto; color: var(--text-dim); font-size: 11px; }
    nav { display: flex; gap: 2px; padding: 0 20px; border-bottom: 1px solid var(--surface-alt); overflow-x: auto; }
    nav button {
      background: none; border: 0; border-bottom: 2px solid transparent;
      color: var(--text-dim); font: inherit; padding: 10px 14px; cursor: pointer;
      white-space: nowrap;
    }
    nav button[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); }
    main { padding: 20px; max-width: 1100px; }
    section[hidden] { display: none; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--surface-alt); }
    th { color: var(--text-dim); font-weight: 400; font-size: 11px;
         text-transform: uppercase; letter-spacing: .1em; }
    .pill { padding: 2px 8px; border-radius: 3px; font-size: 11px; }
    .on { background: var(--clear); color: var(--selection-text); }
    .off { background: var(--surface-alt); color: var(--text-dim); }
    .locked { background: var(--watch); color: var(--selection-text); }
    .limits { color: var(--text-dim); font-size: 12px; }
    .row { display: flex; gap: 10px; padding: 9px 10px; border-bottom: 1px solid var(--surface-alt); }
    .row.sel { background: var(--selection); color: var(--selection-text); }
    .row .detail { margin-left: auto; }
    .empty { color: var(--text-dim); padding: 24px 0; }
    .keys { display: flex; gap: 6px; margin-bottom: 16px; flex-wrap: wrap; }
    .keys button {
      background: var(--surface-alt); border: 1px solid transparent; color: var(--text);
      font: inherit; padding: 6px 14px; border-radius: 3px; cursor: pointer;
    }
    .keys button:hover, .keys button:focus-visible { border-color: var(--accent); }
</style>

<header>
  <h1>⛈ Rude<span>Storm</span></h1>
  <div id="posture">CLEAR</div>
  <div id="head"></div>
</header>

<nav id="tabs">
  <button aria-selected="true" data-tab="live">Live</button>
  <button data-tab="console">Console</button>
  <button data-tab="cogs">Cogs</button>
  <button data-tab="node">Node</button>
</nav>

<main>
  <section id="live">
    <table>
      <thead><tr><th>Time</th><th>Threat class</th><th>Conf</th><th>Modalities</th></tr></thead>
      <tbody id="feed"></tbody>
    </table>
    <div id="feed-empty" class="empty">No corroborated events. A single modality never raises one.</div>
  </section>

  <section id="console" hidden>
    <div class="keys">
      <button data-a="up">▲ Up</button><button data-a="down">▼ Down</button>
      <button data-a="left">◀ Back</button><button data-a="ok">● OK</button>
    </div>
    <div id="crumb" class="limits"></div>
    <div id="rows"></div>
  </section>

  <section id="cogs" hidden>
    <table>
      <thead><tr><th>Cog</th><th>Category</th><th>Privacy</th><th>State</th></tr></thead>
      <tbody id="coglist"></tbody>
    </table>
  </section>

  <section id="node" hidden><div id="nodeinfo"></div></section>
</main>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

document.getElementById('tabs').onclick = e => {
  const tab = e.target.dataset.tab; if (!tab) return;
  for (const b of document.querySelectorAll('#tabs button'))
    b.setAttribute('aria-selected', String(b.dataset.tab === tab));
  for (const s of document.querySelectorAll('main section')) s.hidden = s.id !== tab;
};

function setPosture(p) {
  const el = $('#posture');
  el.className = p; el.textContent = p.toUpperCase();
}

function renderSnapshot(s) {
  setPosture(s.posture);
  $('#head').textContent = s.provenance_head ? 'chain ' + s.provenance_head.slice(0, 12) : '';
  $('#crumb').textContent = s.breadcrumb.join('  ›  ');
  $('#rows').innerHTML = s.rows.map((r, i) =>
    `<div class="row ${i === s.cursor ? 'sel' : ''}">
       <span>${esc(r.label)}</span><span class="detail">${esc(r.detail)}</span></div>`
  ).join('') || '<div class="empty">(empty)</div>';
  renderFeed(s.feed);
}

function renderFeed(feed) {
  $('#feed-empty').hidden = feed.length > 0;
  $('#feed').innerHTML = feed.map(e =>
    `<tr><td>${esc(e.timestamp.slice(11, 19))}</td>
         <td>${esc(e.threat_class)}</td>
         <td>${(e.confidence * 100).toFixed(0)}%</td>
         <td>${esc(e.modalities.join(', '))}</td></tr>`).join('');
}

async function send(action) {
  const r = await fetch('/api/input', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action})
  });
  if (r.ok) renderSnapshot((await r.json()).snapshot);
}
for (const b of document.querySelectorAll('.keys button')) b.onclick = () => send(b.dataset.a);
addEventListener('keydown', e => {
  const map = {ArrowUp:'up', ArrowDown:'down', ArrowLeft:'left', ArrowRight:'right', Enter:'ok'};
  if (map[e.key]) { e.preventDefault(); send(map[e.key]); }
});

async function loadCatalog() {
  const c = await (await fetch('/api/catalog')).json();
  $('#coglist').innerHTML = c.cogs.map(g => `
    <tr><td>${esc(g.name)}<div class="limits">${esc(g.limits || '')}</div></td>
        <td>${esc(g.category)}</td><td>${esc(g.privacy_class)}</td>
        <td><span class="pill ${g.loaded ? 'on' : (g.reason.includes('privacy') ? 'locked' : 'off')}">
          ${g.loaded ? 'loaded' : 'blocked'}</span>
          <div class="limits">${esc(g.reason || '')}</div></td></tr>`).join('');
  $('#nodeinfo').innerHTML =
    `<p><b>${esc(c.node.tier)}</b> · ${c.node.ram_mb} MB RAM</p>
     <p class="limits">${esc(c.node.notes)}</p>
     <p>Privacy ceiling: <span class="pill locked">${esc(c.privacy_ceiling)}</span></p>`;
}

const stream = new EventSource('/api/stream');
stream.onmessage = m => {
  const d = JSON.parse(m.data);
  if (d.type === 'nav') renderSnapshot(d.snapshot);
  else if (d.type === 'event') { setPosture(d.posture); fetch('/api/snapshot')
    .then(r => r.json()).then(s => renderFeed(s.feed)); }
};

fetch('/api/snapshot').then(r => r.json()).then(renderSnapshot);
loadCatalog();
</script>
"""
