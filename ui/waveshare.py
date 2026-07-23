"""Waveshare 1.44" LCD HAT binding — the board RaspyJack targets.

Hardware: ST7735S 128x128 SPI panel with an integrated 5-way joystick and three
buttons (KEY1/KEY2/KEY3), the standard Waveshare HAT for the Pi Zero 2 W / 3 / 4.
Pin map below is that HAT's documented BCM layout.

This module is the *only* place in the console that touches GPIO or SPI, and both
are imported lazily. On a workstation without `RPi.GPIO` / `spidev` the input
loop and panel driver simply refuse to start with a clear message, while the rest
of the UI (model, scene, web) runs unchanged. That separation is deliberate: the
whole interface is developed and tested off-target, and only the last mile binds
to the Pi.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from rudestorm.ui.model import Action

# Waveshare 1.44" LCD HAT — BCM pin numbers (joystick + 3 keys).
JOY_UP = 6
JOY_DOWN = 19
JOY_LEFT = 5
JOY_RIGHT = 26
JOY_PRESS = 13
KEY1 = 21
KEY2 = 20
KEY3 = 16

# SPI / control pins for the ST7735S panel on this HAT.
LCD_CS = 8
LCD_DC = 25
LCD_RST = 27
LCD_BL = 24
SPI_BUS = 0
SPI_DEVICE = 0
SPI_HZ = 40_000_000

#: Joystick/button BCM pin -> UI action. KEY1 is a secondary "OK", KEY3 is back,
#: matching RaspyJack's muscle memory (RIGHT/OK confirm, LEFT/KEY3 exit).
PIN_ACTIONS: Dict[int, Action] = {
    JOY_UP: Action.UP,
    JOY_DOWN: Action.DOWN,
    JOY_LEFT: Action.LEFT,
    JOY_RIGHT: Action.RIGHT,
    JOY_PRESS: Action.OK,
    KEY1: Action.OK,
    KEY3: Action.LEFT,
}

PANEL = "st7735s"  # 128x128; index into rudestorm.ui.render.PANELS


@dataclass
class ButtonEvent:
    action: Action
    pin: int


class WaveshareInput:
    """Debounced GPIO reader yielding `Action`s from the HAT controls.

    Polling with a short debounce rather than edge interrupts keeps the driver
    dependency light and behaves identically under the test double below.
    """

    def __init__(self, debounce_s: float = 0.18) -> None:
        self._debounce = debounce_s
        self._last: Dict[int, float] = {}
        self._gpio = None

    def start(self) -> None:
        try:
            import RPi.GPIO as GPIO  # type: ignore
        except ImportError as exc:  # pragma: no cover - hardware path
            raise RuntimeError(
                "RPi.GPIO not available — the Waveshare input loop only runs on "
                "a Pi. Use the web console or a simulated input off-target."
            ) from exc
        GPIO.setmode(GPIO.BCM)
        for pin in PIN_ACTIONS:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._gpio = GPIO

    def poll(self) -> Optional[ButtonEvent]:  # pragma: no cover - hardware path
        """Return one debounced press, or None. Active-low with pull-ups."""
        if self._gpio is None:
            raise RuntimeError("call start() before poll()")
        now = time.monotonic()
        for pin, action in PIN_ACTIONS.items():
            if self._gpio.input(pin) == 0:  # pressed
                if now - self._last.get(pin, 0.0) >= self._debounce:
                    self._last[pin] = now
                    return ButtonEvent(action, pin)
        return None

    def stop(self) -> None:  # pragma: no cover - hardware path
        if self._gpio is not None:
            self._gpio.cleanup()
            self._gpio = None


def run_console(
    model,
    render_frame: Callable[[object], None],
    input_source: Optional[Callable[[], Optional[ButtonEvent]]] = None,
    tick_s: float = 0.05,
    max_ticks: Optional[int] = None,
) -> int:
    """Drive the model from HAT input, rendering on every change.

    `render_frame(scene)` pushes a Scene to the panel (or a test sink).
    `input_source` defaults to a real WaveshareInput; a test passes a callable
    returning queued ButtonEvents so the whole loop is exercised off-target.
    `max_ticks` bounds the loop for tests; None runs until interrupted.

    Returns the number of frames rendered.
    """
    from rudestorm.ui.render import PANELS, build_scene

    if input_source is None:  # pragma: no cover - hardware path
        hw = WaveshareInput()
        hw.start()
        input_source = hw.poll

    w, h = PANELS[PANEL]
    frames = 0
    render_frame(build_scene(model, w, h))  # initial frame
    frames += 1

    ticks = 0
    try:
        while max_ticks is None or ticks < max_ticks:
            event = input_source()
            if event is not None:
                model.dispatch(event.action)
                render_frame(build_scene(model, w, h))
                frames += 1
            ticks += 1
            if max_ticks is None:  # pragma: no cover - hardware path
                time.sleep(tick_s)
    except KeyboardInterrupt:  # pragma: no cover - hardware path
        pass
    return frames
