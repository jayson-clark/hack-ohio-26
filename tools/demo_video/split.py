"""The synced table shot: the phone (left) beside the camera view (right),
from one Recordly take with its webcam on (SCRIPT.md, "The synced table
shot"). Recordly records both on one clock, so there's nothing to line up.

    cd engine && uv run python ../tools/demo_video/split.py SCREEN.mp4 SCREEN-webcam.mp4 OUT.mp4 FROM TO

FROM and TO are seconds into the raw recording (pick a stretch where the
phone is still). The camera view's rectangle (CX..CH) is for exercise
control in the 1668x991 Chrome window on a 1728x1117 point screen; check one
frame and adjust if yours differs.
"""
import sys
import cv2
import numpy as np

screen_path, webcam_path, out_path = sys.argv[1:4]
t_from, t_to = float(sys.argv[4]), float(sys.argv[5])
OUT_W, OUT_H, FPS = 1920, 1080, 30
BG = (19, 17, 14)  # #0e1113 in BGR
# The camera view in the screen recording, in its pixels (3456x2234).
CX, CY, CW, CH = 376, 380, 2040, 1528
GAP = 24
half = (OUT_W - 3 * GAP) // 2

scr, cam = cv2.VideoCapture(screen_path), cv2.VideoCapture(webcam_path)
sfps, cfps = scr.get(cv2.CAP_PROP_FPS), cam.get(cv2.CAP_PROP_FPS)
out = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"avc1"), FPS, (OUT_W, OUT_H))

def fit(img, w):
    h = round(img.shape[0] * w / img.shape[1])
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA if img.shape[1] > w else cv2.INTER_CUBIC)

def frame_at(cap, fps, t, state):
    """The frame showing at time t, reading forward only."""
    want = int(t * fps)
    while state["i"] < want or state["f"] is None:
        ok, f = cap.read()
        if not ok:
            break
        state["i"] += 1
        state["f"] = f
    return state["f"]

s_state, c_state = {"i": 0, "f": None}, {"i": 0, "f": None}
n = int((t_to - t_from) * FPS)
for k in range(n):
    t = t_from + k / FPS
    sf = frame_at(scr, sfps, t, s_state)
    cf = frame_at(cam, cfps, t, c_state)
    canvas = np.full((OUT_H, OUT_W, 3), BG, np.uint8)
    left = fit(cv2.flip(cf, 1), half)  # Recordly saves the phone mirrored
    right = fit(sf[CY:CY + CH, CX:CX + CW], half)
    for img, x in ((left, GAP), (right, 2 * GAP + half)):
        y = (OUT_H - img.shape[0]) // 2
        canvas[y:y + img.shape[0], x:x + img.shape[1]] = img
    out.write(canvas)
out.release()
print(f"wrote {out_path}: {n / FPS:.1f} s at {FPS} fps, recording {t_from}-{t_to} s")
