"""Theme: colors and glyphs, JSON-loadable like RaspyJack's gui_conf.json.

Kept as a plain frozen dataclass so a deployment can drop a theme.json beside
the binary and restyle the whole console — LCD and web — without touching code.
The default palette is a dark tactical scheme: near-black surface, amber watch,
red alert, the cyan RudeStorm accent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple

RGB = Tuple[int, int, int]


def _hex(s: str) -> RGB:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


@dataclass(frozen=True)
class Theme:
    """A complete visual theme. All colors are RGB tuples."""

    name: str = "tactical-dark"
    surface: RGB = (10, 12, 16)
    surface_alt: RGB = (18, 22, 28)
    text: RGB = (224, 230, 236)
    text_dim: RGB = (120, 130, 140)
    accent: RGB = (34, 211, 238)       # cyan
    clear: RGB = (52, 199, 120)        # green
    watch: RGB = (245, 176, 66)        # amber
    alert: RGB = (239, 68, 68)         # red
    selection: RGB = (34, 211, 238)
    selection_text: RGB = (6, 8, 10)

    #: Maps FontAwesome-style glyph names to single display characters. On the
    #: LCD these are drawn from a bitmap icon sheet in production; the ASCII
    #: fallback here keeps the renderer dependency-free and testable.
    glyphs: Dict[str, str] = field(default_factory=lambda: {
        "tower-broadcast": "T", "wifi": "W", "shield-halved": "S",
        "person-walking": "P", "helicopter": "A", "fingerprint": "I",
        "diagram-project": "F", "circle": "o",
    })

    def posture_color(self, posture: str) -> RGB:
        return {"clear": self.clear, "watch": self.watch, "alert": self.alert}.get(
            posture, self.text
        )

    def glyph(self, name: str) -> str:
        return self.glyphs.get(name, "o")

    @classmethod
    def from_json(cls, path: str | Path) -> "Theme":
        """Load a theme.json. Color values may be #rrggbb strings or [r,g,b]."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        kwargs: dict = {}
        for key, value in data.items():
            if key in ("name", "glyphs"):
                kwargs[key] = value
            elif isinstance(value, str):
                kwargs[key] = _hex(value)
            elif isinstance(value, (list, tuple)) and len(value) == 3:
                kwargs[key] = tuple(int(c) for c in value)
        return cls(**kwargs)


DEFAULT_THEME = Theme()
