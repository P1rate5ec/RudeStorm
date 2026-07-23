"""Headless UI model shared by the LCD console and the web dashboard.

RaspyJack and Ragnar each hard-wire their interface to one surface — RaspyJack to
a Waveshare LCD HAT, Ragnar to a Flask dashboard. rudestorm has two surfaces (a
128x128 / 240x240 HAT on a field node, and a browser served from the Pi brain),
and duplicating navigation and status logic across both is how they drift.

So the model is a single headless state machine. It owns:

  * the menu tree, derived from the live cog registry rather than hardcoded,
  * the CLEAR / WATCH / ALERT posture, derived from recent events,
  * cursor and breadcrumb navigation via five joystick actions.

The LCD renderer and the web renderer are both pure functions of this model.
Everything here is testable without a screen, a browser, or a GPIO pin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence

from rudestorm.cogs.base import CogCategory
from rudestorm.cogs.registry import CogRegistry
from rudestorm.events import ThreatEvent


class Posture(str, Enum):
    """Operational posture, mixing Ragnar's CLEAR/WARNING/UNDER-ATTACK banner
    with rudestorm's corroboration discipline."""

    CLEAR = "clear"      # nothing recent
    WATCH = "watch"      # single-modality activity; below the corroboration gate
    ALERT = "alert"      # a corroborated ThreatEvent fired

    @property
    def banner(self) -> str:
        return {"clear": "CLEAR", "watch": "WATCH", "alert": "ALERT"}[self.value]


class Action(str, Enum):
    """The five inputs a Waveshare joystick HAT provides."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"     # back / up a level
    RIGHT = "right"   # into / confirm
    OK = "ok"         # confirm (center press)


@dataclass(frozen=True)
class MenuItem:
    """One selectable row. `action` runs on OK/RIGHT for leaf items."""

    key: str
    label: str
    icon: str                       # FontAwesome-style glyph name, theme maps it
    children: "List[MenuItem]" = field(default_factory=list)
    action: Optional[Callable[[], str]] = None
    detail: str = ""                # right-aligned status, e.g. "3 loaded"

    @property
    def is_leaf(self) -> bool:
        return not self.children


#: Icon per cog category, resolved by the renderer's glyph table.
CATEGORY_ICONS: Dict[CogCategory, str] = {
    CogCategory.RF_HYGIENE: "wifi",
    CogCategory.SENSING_DEFENSE: "shield-halved",
    CogCategory.PHYSICAL: "person-walking",
    CogCategory.AIRSPACE: "helicopter",
    CogCategory.INTEGRITY: "fingerprint",
    CogCategory.FLEET: "diagram-project",
}

#: Human-facing category names, ordered for the top menu.
CATEGORY_LABELS: Dict[CogCategory, str] = {
    CogCategory.PHYSICAL: "Physical",
    CogCategory.AIRSPACE: "Airspace",
    CogCategory.RF_HYGIENE: "RF Hygiene",
    CogCategory.SENSING_DEFENSE: "Sensing Defense",
    CogCategory.INTEGRITY: "Integrity",
    CogCategory.FLEET: "Fleet",
}


def build_menu(registry: CogRegistry) -> MenuItem:
    """Derive the menu tree from what this node is actually running.

    A category with no loaded cogs still appears, but its rows carry the
    rejection reason as detail text — so an operator scrolling the LCD sees
    *why* a capability is dark, not just that it is missing. This is the
    honest-limits rule surfaced in the UI: the interface never implies a
    capability the hardware cannot deliver.
    """
    loaded = {c.manifest.cog_id for c in registry.active}
    reasons = {r.cog_id: r.reason for r in registry.results if not r.loaded}

    by_cat: Dict[CogCategory, List[MenuItem]] = {c: [] for c in CATEGORY_LABELS}

    for cog_id, manifest in registry.manifests.items():
        live = cog_id in loaded
        by_cat.setdefault(manifest.category, []).append(
            MenuItem(
                key=cog_id,
                label=manifest.name,
                icon=CATEGORY_ICONS.get(manifest.category, "circle"),
                detail="on" if live else _short_reason(reasons.get(cog_id, "off")),
            )
        )

    children = [
        MenuItem(
            key=cat.value,
            label=CATEGORY_LABELS[cat],
            icon=CATEGORY_ICONS[cat],
            children=sorted(rows, key=lambda m: m.label),
            detail=f"{sum(1 for m in rows if m.detail == 'on')}/{len(rows)}",
        )
        for cat, rows in by_cat.items()
        if rows
    ]
    return MenuItem(key="root", label="RudeStorm", icon="tower-broadcast",
                    children=children)


def _short_reason(reason: str) -> str:
    if "privacy" in reason:
        return "locked"
    if "capability" in reason or "lacks" in reason:
        return "n/a hw"
    if "RAM" in reason:
        return "low ram"
    return "off"


class UIModel:
    """Live UI state: posture, menu, cursor, and a rolling event feed."""

    def __init__(
        self,
        registry: CogRegistry,
        watch_window: timedelta = timedelta(seconds=30),
        feed_limit: int = 50,
    ) -> None:
        self._registry = registry
        self._root = build_menu(registry)
        self._stack: List[MenuItem] = [self._root]
        self._cursor: List[int] = [0]
        self._feed: List[ThreatEvent] = []
        self._single_modality_at: Optional[datetime] = None
        self._watch_window = watch_window
        self._feed_limit = feed_limit

    # ------------------------------------------------------------- navigation

    @property
    def current(self) -> MenuItem:
        return self._stack[-1]

    @property
    def cursor(self) -> int:
        return self._cursor[-1]

    @property
    def breadcrumb(self) -> List[str]:
        return [m.label for m in self._stack]

    @property
    def selected(self) -> Optional[MenuItem]:
        rows = self.current.children
        return rows[self.cursor] if rows else None

    def dispatch(self, action: Action) -> Optional[str]:
        """Apply an input. Returns an action result string if a leaf fired."""
        rows = self.current.children
        if action is Action.UP and rows:
            self._cursor[-1] = (self.cursor - 1) % len(rows)
        elif action is Action.DOWN and rows:
            self._cursor[-1] = (self.cursor + 1) % len(rows)
        elif action is Action.LEFT:
            self._ascend()
        elif action in (Action.RIGHT, Action.OK):
            return self._descend_or_run()
        return None

    def _ascend(self) -> None:
        if len(self._stack) > 1:
            self._stack.pop()
            self._cursor.pop()

    def _descend_or_run(self) -> Optional[str]:
        item = self.selected
        if item is None:
            return None
        if item.is_leaf:
            return item.action() if item.action else None
        self._stack.append(item)
        self._cursor.append(0)
        return None

    def refresh_menu(self) -> None:
        """Rebuild after a cog load/unlock, preserving the breadcrumb by key."""
        keys = [m.key for m in self._stack]
        self._root = build_menu(self._registry)
        self._stack = [self._root]
        self._cursor = [0]
        for key in keys[1:]:
            match = next((c for c in self.current.children if c.key == key), None)
            if match is None or match.is_leaf:
                break
            self._stack.append(match)
            self._cursor.append(0)

    # ----------------------------------------------------------------- events

    def ingest_event(self, event: ThreatEvent) -> None:
        """A corroborated ThreatEvent -> ALERT and prepend to the feed."""
        self._feed.insert(0, event)
        del self._feed[self._feed_limit:]

    def note_single_modality(self, at: Optional[datetime] = None) -> None:
        """Sub-threshold activity: one modality, no corroboration yet -> WATCH."""
        self._single_modality_at = at or datetime.now(timezone.utc)

    @property
    def feed(self) -> List[ThreatEvent]:
        return list(self._feed)

    def posture(self, now: Optional[datetime] = None) -> Posture:
        now = now or datetime.now(timezone.utc)
        if self._feed and (now - self._feed[0].timestamp) <= self._watch_window:
            return Posture.ALERT
        if (
            self._single_modality_at is not None
            and (now - self._single_modality_at) <= self._watch_window
        ):
            return Posture.WATCH
        return Posture.CLEAR

    def snapshot(self, now: Optional[datetime] = None) -> dict:
        """Serializable state for the web dashboard's initial render."""
        return {
            "posture": self.posture(now).value,
            "breadcrumb": self.breadcrumb,
            "cursor": self.cursor,
            "rows": [
                {"key": m.key, "label": m.label, "icon": m.icon,
                 "detail": m.detail, "leaf": m.is_leaf}
                for m in self.current.children
            ],
            "feed": [e.to_dict() for e in self._feed],
            "provenance_head": self._registry.log.head
            if getattr(self._registry, "log", None) else None,
        }
