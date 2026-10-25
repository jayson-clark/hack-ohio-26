"""Manual exposure and focus for the USB webcam.

The C920's auto-exposure meters the whole frame, which is mostly dark table,
so the projector-lit board in the middle blows out to white (96% of it clipped
on the real rig). A fixed short exposure keeps the projection readable; the
corner markers still decode down to about half of it.

OpenCV can't set these on macOS (AVFoundation reports every property as -1),
so this talks UVC directly through `uvcc` (Node is already a prereq). Opening
the camera resets the controls, so call apply() after every open.

Manual exposure keeps whatever gain auto-exposure last chose, which after a
dim open can be the maximum (255), washing the board out at any exposure, so
pin the gain too. Auto white balance reads the projector's light as very warm
(about 2800 K) and tints the feed teal; a fixed temperature keeps its colours.

From .env, all optional:
  CAMERA_EXPOSURE       absolute exposure time in 100 us units (10 = 1 ms); empty keeps auto
  CAMERA_GAIN           0 to 255; empty leaves it where auto-exposure put it
  CAMERA_WHITE_BALANCE  colour temperature in kelvin, 2000 to 6500; empty keeps auto
  CAMERA_FOCUS          fixed focus, 0 (far) to 255 (near); empty keeps autofocus
"""

import logging
import os
import subprocess

log = logging.getLogger("vision")

UVCC = ["npx", "-y", "uvcc@8.0.0"]


def settings_from_env() -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for var, auto_ctl, manual, ctl in (
        ("CAMERA_EXPOSURE", "auto_exposure_mode", 1, "absolute_exposure_time"),
        ("CAMERA_GAIN", None, 0, "gain"),
        ("CAMERA_WHITE_BALANCE", "auto_white_balance_temperature", 0, "white_balance_temperature"),
        ("CAMERA_FOCUS", "auto_focus", 0, "absolute_focus"),
    ):
        value = os.environ.get(var, "").strip()
        if not value:
            continue
        try:
            out += [*([(auto_ctl, manual)] if auto_ctl else []), (ctl, int(value))]
        except ValueError:
            log.warning("%s=%r: expected a whole number, ignoring", var, value)
    return out


def apply(settings: list[tuple[str, int]]) -> None:
    """Set UVC controls on the webcam. Failures are logged, never raised: the
    camera still works on auto."""
    for name, value in settings:
        try:
            r = subprocess.run([*UVCC, "set", name, str(value)], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("uvcc: can't set %s (%s); camera stays on auto", name, e)
            return
        if r.returncode != 0:
            log.warning("uvcc: setting %s=%s failed: %s", name, value, r.stderr.strip().splitlines()[-1:] or "?")
            return
    if settings:
        log.info("camera controls: %s", ", ".join(f"{n}={v}" for n, v in settings))
