"""UI model, menu derivation, navigation, posture, and scene rendering."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rudestorm.cogs import PI_4B, PI_ZERO_2W, CogRegistry, PrivacyClass
from rudestorm.cogs.catalog import STARTER_CATALOG
from rudestorm.events import Detection, GeoPoint, Modality, ThreatEvent
from rudestorm.ui import Action, Posture, UIModel, build_scene
from rudestorm.ui.render import PANELS, Glyph, Rect, Text
from rudestorm.ui.theme import DEFAULT_THEME, Theme


def _registry(node=PI_4B, ceiling=PrivacyClass.COARSE_PRESENCE) -> CogRegistry:
    reg = CogRegistry(node, privacy_ceiling=ceiling)
    reg.load_all(STARTER_CATALOG, source_id="node-01")
    return reg


def _event(threat_class="presence_intrusion", when=None) -> ThreatEvent:
    ts = when or datetime.now(timezone.utc)
    dets = [
        Detection(Modality.WIFI_CSI, "n1", ts, 0.7, "presence"),
        Detection(Modality.REMOTE_ID, "n1", ts, 0.8, "drone_broadcast"),
    ]
    return ThreatEvent(threat_class, 0.82, ts, 4.0, dets,
                       geolocation=GeoPoint(44.6, -63.5))


class TestMenuDerivation:
    def test_menu_reflects_loaded_and_rejected_cogs(self):
        ui = UIModel(_registry())
        labels = [c.label for c in ui.current.children]
        assert "Physical" in labels and "RF Hygiene" in labels

    def test_category_detail_counts_loaded(self):
        ui = UIModel(_registry())
        physical = next(c for c in ui.current.children if c.label == "Physical")
        # Presence + Motion load at coarse ceiling; Fall/Breathing/Heart are
        # biometric and rejected -> "2/5".
        loaded, total = physical.detail.split("/")
        assert int(total) == 5 and int(loaded) == 2

    def test_rejected_cog_shows_reason_detail(self):
        ui = UIModel(_registry())
        ui.dispatch(Action.OK)  # into Physical (first category)
        # Find the physical submenu regardless of ordering.
        while ui.current.label != "Physical":
            ui._stack = [ui._stack[0]]
            ui._cursor = [0]
            idx = [c.label for c in ui.current.children].index("Physical")
            for _ in range(idx):
                ui.dispatch(Action.DOWN)
            ui.dispatch(Action.OK)
        details = {c.label: c.detail for c in ui.current.children}
        assert details["Heart rate"] == "locked"    # biometric, gated
        assert details["Presence"] == "on"

    def test_csi_cogs_show_hardware_gap_on_zero_2w(self):
        ui = UIModel(_registry(node=PI_ZERO_2W, ceiling=PrivacyClass.BIOMETRIC))
        # Descend into Physical.
        idx = [c.label for c in ui.current.children].index("Physical")
        for _ in range(idx):
            ui.dispatch(Action.DOWN)
        ui.dispatch(Action.OK)
        details = {c.label: c.detail for c in ui.current.children}
        assert details["Presence"] == "n/a hw"  # no CSI on CYW43438


class TestNavigation:
    def test_down_wraps(self):
        ui = UIModel(_registry())
        n = len(ui.current.children)
        for _ in range(n):
            ui.dispatch(Action.DOWN)
        assert ui.cursor == 0

    def test_up_wraps_backwards(self):
        ui = UIModel(_registry())
        ui.dispatch(Action.UP)
        assert ui.cursor == len(ui.current.children) - 1

    def test_descend_and_ascend(self):
        ui = UIModel(_registry())
        assert ui.breadcrumb == ["RudeStorm"]
        ui.dispatch(Action.OK)
        assert len(ui.breadcrumb) == 2
        ui.dispatch(Action.LEFT)
        assert ui.breadcrumb == ["RudeStorm"]

    def test_left_at_root_is_noop(self):
        ui = UIModel(_registry())
        ui.dispatch(Action.LEFT)
        assert ui.breadcrumb == ["RudeStorm"]

    def test_leaf_action_fires(self):
        reg = _registry()
        ui = UIModel(reg)
        fired = []
        from rudestorm.ui.model import MenuItem
        ui.current.children.append(
            MenuItem("t", "Test", "circle", action=lambda: fired.append(1) or "ran")
        )
        # Move cursor to the appended leaf.
        ui._cursor[-1] = len(ui.current.children) - 1
        assert ui.dispatch(Action.OK) == "ran"
        assert fired == [1]

    def test_refresh_preserves_breadcrumb_by_key(self):
        reg = CogRegistry(PI_4B)  # coarse ceiling
        reg.load_all(STARTER_CATALOG, source_id="n")
        ui = UIModel(reg)
        idx = [c.label for c in ui.current.children].index("Physical")
        for _ in range(idx):
            ui.dispatch(Action.DOWN)
        ui.dispatch(Action.OK)
        assert ui.current.label == "Physical"
        reg.unlock_privacy_class(PrivacyClass.BIOMETRIC, authorization="CHG-1")
        reg.load_all(STARTER_CATALOG, source_id="n")
        ui.refresh_menu()
        assert ui.current.label == "Physical"  # stayed put across refresh


class TestPosture:
    def test_clear_by_default(self):
        assert UIModel(_registry()).posture() == Posture.CLEAR

    def test_watch_on_single_modality(self):
        ui = UIModel(_registry())
        ui.note_single_modality()
        assert ui.posture() == Posture.WATCH

    def test_alert_on_corroborated_event(self):
        ui = UIModel(_registry())
        ui.note_single_modality()
        ui.ingest_event(_event())
        assert ui.posture() == Posture.ALERT  # alert outranks watch

    def test_posture_decays_to_clear(self):
        ui = UIModel(_registry(), watch_window=timedelta(seconds=30))
        old = datetime.now(timezone.utc) - timedelta(seconds=90)
        ui.ingest_event(_event(when=old))
        assert ui.posture() == Posture.CLEAR

    def test_feed_is_capped(self):
        ui = UIModel(_registry(), feed_limit=3)
        for _ in range(5):
            ui.ingest_event(_event())
        assert len(ui.feed) == 3


class TestScene:
    @pytest.mark.parametrize("panel", ["st7735s", "st7789", "cardputer"])
    def test_scene_fills_panel(self, panel):
        w, h = PANELS[panel]
        scene = build_scene(UIModel(_registry()), w, h)
        assert scene.width == w and scene.height == h
        bg = scene.scaled()[0]
        assert isinstance(bg, Rect)
        assert bg.w == w and bg.h == h  # background covers the whole panel

    def test_banner_color_tracks_posture(self):
        ui = UIModel(_registry())
        theme = DEFAULT_THEME

        clear = build_scene(ui, 240, 240, theme)
        banners = [o for o in clear.ops if isinstance(o, Rect)]
        assert any(o.color == theme.clear for o in banners)

        ui.ingest_event(_event())
        alert = build_scene(ui, 240, 240, theme)
        assert any(o.color == theme.alert for o in alert.ops if isinstance(o, Rect))

    def test_banner_text_is_present(self):
        scene = build_scene(UIModel(_registry()), 240, 240)
        texts = [o.text for o in scene.ops if isinstance(o, Text)]
        assert "CLEAR" in texts

    def test_selected_row_is_highlighted(self):
        ui = UIModel(_registry())
        scene = build_scene(ui, 240, 240)
        # The selection bar is a full-width Rect in the accent/selection color.
        sel = [o for o in scene.ops
               if isinstance(o, Rect) and o.color == DEFAULT_THEME.selection]
        assert sel, "no selection highlight drawn"

    def test_alert_footer_shows_threat_class(self):
        ui = UIModel(_registry())
        ui.ingest_event(_event(threat_class="uas_cooperative_intrusion"))
        scene = build_scene(ui, 240, 240)
        texts = [o.text for o in scene.ops if isinstance(o, Text)]
        assert any("uas_cooperative" in t for t in texts)

    def test_long_menu_scrolls_to_keep_cursor_visible(self):
        ui = UIModel(_registry())
        for _ in range(4):
            ui.dispatch(Action.DOWN)
        scene = build_scene(ui, 240, 240)
        glyphs = [o for o in scene.ops if isinstance(o, Glyph)]
        assert glyphs, "cursor row should still render after scrolling"


class TestTheme:
    def test_from_json_parses_hex_and_rgb(self, tmp_path):
        p = tmp_path / "theme.json"
        p.write_text('{"name":"x","alert":"#ff0000","clear":[0,255,0]}')
        theme = Theme.from_json(p)
        assert theme.alert == (255, 0, 0)
        assert theme.clear == (0, 255, 0)
        assert theme.name == "x"

    def test_posture_color_maps(self):
        t = DEFAULT_THEME
        assert t.posture_color("alert") == t.alert
        assert t.posture_color("watch") == t.watch


class TestWaveshareConsole:
    """The RaspyJack hardware loop, driven off-target via an injected input."""

    def test_console_loop_dispatches_queued_input(self):
        from rudestorm.ui.waveshare import ButtonEvent, run_console
        from rudestorm.ui.model import Action

        ui = UIModel(_registry())
        queue = [ButtonEvent(Action.DOWN, 19), ButtonEvent(Action.OK, 13), None]
        rendered = []

        def source():
            return queue.pop(0) if queue else None

        frames = run_console(ui, render_frame=rendered.append,
                             input_source=source, max_ticks=5)
        # initial frame + one per non-None event = 3
        assert frames == 3
        assert len(ui.breadcrumb) == 2  # OK descended into a category

    def test_pin_map_covers_joystick_and_keys(self):
        from rudestorm.ui.waveshare import PIN_ACTIONS, JOY_PRESS, KEY1, KEY3
        from rudestorm.ui.model import Action

        assert PIN_ACTIONS[JOY_PRESS] == Action.OK
        assert PIN_ACTIONS[KEY1] == Action.OK
        assert PIN_ACTIONS[KEY3] == Action.LEFT

    def test_panel_is_st7735s_128(self):
        from rudestorm.ui.waveshare import PANEL
        from rudestorm.ui.render import PANELS
        assert PANEL == "st7735s"
        assert PANELS[PANEL] == (128, 128)
