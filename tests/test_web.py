"""Web dashboard: routing, SSE broadcast, and a live end-to-end server check."""

from __future__ import annotations

import json
import queue
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pytest

from rudestorm.cogs import PI_4B, CogRegistry, PrivacyClass
from rudestorm.cogs.catalog import STARTER_CATALOG
from rudestorm.events import Detection, Modality, ThreatEvent
from rudestorm.governance import ProvenanceLog
from rudestorm.ui import UIModel
from rudestorm.ui.web import DashboardApp, serve


def _app(ceiling=PrivacyClass.COARSE_PRESENCE) -> DashboardApp:
    reg = CogRegistry(PI_4B, log=ProvenanceLog(), privacy_ceiling=ceiling)
    reg.load_all(STARTER_CATALOG, source_id="node-01")
    return DashboardApp(UIModel(reg))


def _event(threat_class="presence_intrusion") -> ThreatEvent:
    ts = datetime.now(timezone.utc)
    return ThreatEvent(threat_class, 0.82, ts, 4.0, [
        Detection(Modality.WIFI_CSI, "n1", ts, 0.7, "presence"),
        Detection(Modality.REMOTE_ID, "n1", ts, 0.8, "drone_broadcast"),
    ])


class TestRouting:
    def test_index_serves_html_with_theme(self):
        status, headers, body = _app().handle("GET", "/")
        assert status == 200
        assert "text/html" in headers["Content-Type"]
        page = body.decode()
        assert "RudeStorm" in page
        assert "--surface:" in page  # theme injected as CSS vars

    def test_snapshot_shape(self):
        status, _, body = _app().handle("GET", "/api/snapshot")
        data = json.loads(body)
        assert status == 200
        assert data["posture"] == "clear"
        assert data["breadcrumb"] == ["RudeStorm"]
        assert data["rows"] and "label" in data["rows"][0]

    def test_snapshot_exposes_provenance_head(self):
        _, _, body = _app().handle("GET", "/api/snapshot")
        head = json.loads(body)["provenance_head"]
        assert head and len(head) == 64

    def test_catalog_reports_loaded_and_blocked_with_reasons(self):
        _, _, body = _app().handle("GET", "/api/catalog")
        data = json.loads(body)
        assert data["node"]["tier"] == "pi_4b"
        assert data["privacy_ceiling"] == "coarse_presence"
        blocked = [c for c in data["cogs"] if not c["loaded"]]
        assert any("privacy class" in c["reason"] for c in blocked)
        assert all(c["limits"] for c in data["cogs"]), "every cog states its limits"

    def test_unknown_route_404s(self):
        status, _, _ = _app().handle("GET", "/nope")
        assert status == 404

    def test_input_dispatches_and_returns_snapshot(self):
        app = _app()
        status, _, body = app.handle("POST", "/api/input", b'{"action":"ok"}')
        assert status == 200
        assert len(json.loads(body)["snapshot"]["breadcrumb"]) == 2

    def test_bad_action_is_rejected(self):
        status, _, _ = _app().handle("POST", "/api/input", b'{"action":"launch"}')
        assert status == 400

    def test_malformed_body_is_rejected(self):
        status, _, _ = _app().handle("POST", "/api/input", b"not json")
        assert status == 400


class TestBroadcast:
    def test_subscriber_receives_event(self):
        app = _app()
        q = app.subscribe()
        assert app.publish_event(_event()) == 1
        payload = json.loads(q.get_nowait())
        assert payload["type"] == "event"
        assert payload["posture"] == "alert"

    def test_navigation_broadcasts_to_subscribers(self):
        app = _app()
        q = app.subscribe()
        app.handle("POST", "/api/input", b'{"action":"down"}')
        assert json.loads(q.get_nowait())["type"] == "nav"

    def test_unsubscribe_stops_delivery(self):
        app = _app()
        q = app.subscribe()
        app.unsubscribe(q)
        assert app.publish_event(_event()) == 0

    def test_slow_client_is_dropped_not_blocking(self):
        """A stalled browser tab must never block the sensor loop."""
        app = _app()
        q = app.subscribe()
        for _ in range(q.maxsize):
            q.put_nowait("filler")
        assert app.publish_event(_event()) == 0   # dropped, did not raise
        assert app.publish_event(_event()) == 0   # and is gone from the list

    def test_event_reaches_the_model_feed(self):
        app = _app()
        app.publish_event(_event("uas_cooperative_intrusion"))
        _, _, body = app.handle("GET", "/api/snapshot")
        feed = json.loads(body)["feed"]
        assert feed[0]["threat_class"] == "uas_cooperative_intrusion"


class TestLiveServer:
    """Bind a real ephemeral port and exercise the socket adapter."""

    @pytest.fixture
    def server(self):
        app = _app()
        srv = serve(app, host="127.0.0.1", port=0)
        yield app, srv, srv.server_address[1]
        srv.shutdown()

    def test_index_over_http(self, server):
        _, _, port = server
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r:
            assert r.status == 200
            assert b"RudeStorm" in r.read()

    def test_post_input_over_http(self, server):
        app, _, port = server
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/input",
            data=b'{"action":"down"}',
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["snapshot"]["cursor"] == 1
        assert app.model.cursor == 1

    def test_404_over_http(self, server):
        _, _, port = server
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/missing")
        assert exc.value.code == 404

    def test_serve_binds_loopback_by_default(self, server):
        _, srv, _ = server
        assert srv.server_address[0] == "127.0.0.1"
