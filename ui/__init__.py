"""Shared console UI: one headless model, two renderers (LCD + web).

    from rudestorm.cogs import PI_4B, CogRegistry, PrivacyClass
    from rudestorm.cogs.catalog import STARTER_CATALOG
    from rudestorm.ui import UIModel, Action, build_scene, PANELS

    reg = CogRegistry(PI_4B)
    reg.load_all(STARTER_CATALOG, source_id="node-01")
    ui = UIModel(reg)
    ui.dispatch(Action.DOWN)
    scene = build_scene(ui, *PANELS["st7789"])   # -> a resolution-scaled Scene
"""

from rudestorm.ui.model import (
    Action,
    CATEGORY_ICONS,
    CATEGORY_LABELS,
    MenuItem,
    Posture,
    UIModel,
    build_menu,
)
from rudestorm.ui.render import PANELS, Glyph, Rect, Scene, Text, build_scene
from rudestorm.ui.theme import DEFAULT_THEME, Theme

__all__ = [
    "Action",
    "CATEGORY_ICONS",
    "CATEGORY_LABELS",
    "DEFAULT_THEME",
    "Glyph",
    "MenuItem",
    "PANELS",
    "Posture",
    "Rect",
    "Scene",
    "Text",
    "Theme",
    "UIModel",
    "build_menu",
    "build_scene",
]
