"""Resolution-independent scene builder for the LCD console.

This is rudestorm's version of RaspyJack's ScaledDraw: layout is authored once in
a normalized 0..1000 coordinate space and scaled to whatever panel is attached —
the ST7735S (128x128), the ST7789 (240x240), or the Cardputer's 240x135. The
renderer emits a `Scene` of primitive ops (`Rect`, `Text`, `Glyph`); a backend
rasterizes it (PIL on a workstation, the panel's own draw calls on hardware).

Keeping the scene as data, not pixels, is what makes the layout testable without
a framebuffer: a test asserts "the banner op is red and says ALERT", not "pixel
(3,3) is 0xEF4444".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Tuple

from rudestorm.ui.model import UIModel
from rudestorm.ui.theme import DEFAULT_THEME, RGB, Theme

#: Authoring space. Every op is expressed in [0, GRID] and scaled at raster time.
GRID = 1000

Align = Literal["left", "center", "right"]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int
    color: RGB
    op: str = "rect"


@dataclass(frozen=True)
class Text:
    x: int
    y: int
    text: str
    color: RGB
    align: Align = "left"
    scale: float = 1.0
    op: str = "text"


@dataclass(frozen=True)
class Glyph:
    x: int
    y: int
    name: str          # theme glyph key
    color: RGB
    op: str = "glyph"


@dataclass(frozen=True)
class Scene:
    """A full frame in normalized coordinates, plus its target dimensions."""

    width: int
    height: int
    ops: List[object] = field(default_factory=list)

    def scaled(self) -> List[object]:
        """Return ops with coordinates mapped from GRID space to pixels."""
        sx = self.width / GRID
        sy = self.height / GRID
        out: List[object] = []
        for op in self.ops:
            if isinstance(op, Rect):
                out.append(Rect(round(op.x * sx), round(op.y * sy),
                                max(1, round(op.w * sx)), max(1, round(op.h * sy)),
                                op.color))
            elif isinstance(op, Text):
                out.append(Text(round(op.x * sx), round(op.y * sy), op.text,
                                op.color, op.align, op.scale))
            elif isinstance(op, Glyph):
                out.append(Glyph(round(op.x * sx), round(op.y * sy), op.name,
                                 op.color))
        return out


# Layout constants in GRID space.
_BANNER_H = 140
_ROW_H = 150
_ROWS_VISIBLE = 5
_PAD = 40


def build_scene(model: UIModel, width: int, height: int,
                theme: Theme = DEFAULT_THEME) -> Scene:
    """Compose the current frame: status banner, breadcrumb, cog rows, feed hint."""
    ops: List[object] = [Rect(0, 0, GRID, GRID, theme.surface)]
    posture = model.posture()

    # --- status banner (Ragnar-style CLEAR / WATCH / ALERT) ---
    banner_color = theme.posture_color(posture.value)
    ops.append(Rect(0, 0, GRID, _BANNER_H, banner_color))
    ops.append(Text(_PAD, _BANNER_H // 2, posture.banner, theme.selection_text,
                    align="left", scale=1.2))
    ops.append(Text(GRID - _PAD, _BANNER_H // 2, " > ".join(model.breadcrumb[-2:]),
                    theme.selection_text, align="right", scale=0.7))

    # --- cog rows with a scrolling window around the cursor ---
    rows = model.current.children
    top = _window_top(model.cursor, len(rows))
    y = _BANNER_H + _PAD
    for i in range(top, min(top + _ROWS_VISIBLE, len(rows))):
        row = rows[i]
        selected = i == model.cursor
        if selected:
            ops.append(Rect(0, y, GRID, _ROW_H, theme.selection))
        fg = theme.selection_text if selected else theme.text
        ops.append(Glyph(_PAD, y + _ROW_H // 2, row.icon, fg))
        ops.append(Text(_PAD + 150, y + _ROW_H // 2, row.label, fg, align="left"))
        if row.detail:
            detail_color = _detail_color(row.detail, theme, selected)
            ops.append(Text(GRID - _PAD, y + _ROW_H // 2, row.detail,
                            detail_color, align="right", scale=0.8))
        y += _ROW_H

    if not rows:
        ops.append(Text(GRID // 2, GRID // 2, "(empty)", theme.text_dim,
                        align="center"))

    # --- footer: most recent event, or a scroll hint ---
    feed = model.feed
    footer_y = GRID - _PAD
    if feed and posture.value == "alert":
        ops.append(Text(_PAD, footer_y, feed[0].threat_class[:22], theme.alert,
                        align="left", scale=0.8))
    else:
        ops.append(Text(GRID - _PAD, footer_y,
                        f"{model.cursor + 1}/{len(rows)}" if rows else "",
                        theme.text_dim, align="right", scale=0.8))

    return Scene(width=width, height=height, ops=ops)


def _window_top(cursor: int, count: int) -> int:
    """Scroll so the cursor stays visible, RaspyJack-style."""
    if count <= _ROWS_VISIBLE:
        return 0
    half = _ROWS_VISIBLE // 2
    return max(0, min(cursor - half, count - _ROWS_VISIBLE))


def _detail_color(detail: str, theme: Theme, selected: bool) -> RGB:
    if selected:
        return theme.selection_text
    if detail == "on":
        return theme.clear
    if detail in ("locked", "n/a hw", "low ram"):
        return theme.watch
    return theme.text_dim


# Named panel geometries, for convenience.
PANELS = {
    "st7735s": (128, 128),   # RaspyJack 1.44"
    "st7789": (240, 240),    # RaspyJack / Ragnar 1.3"
    "cardputer": (240, 135), # M5 Cardputer ADV 1.14"
}
