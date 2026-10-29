"""Launch the real app (needs a desktop + GL), drive it a little, save screenshots.

    python tests/smoke_app.py <clip> <out_dir> [--render] [--frame N] [--layout single|wipe|side]

Uses an isolated state folder (CKSTUDIO_STATE) unless one is already set.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("out_dir")
    ap.add_argument("--render", action="store_true", help="queue a render and wait for it")
    ap.add_argument("--submit-and-quit", action="store_true", help="queue a render, then close the app at once")
    ap.add_argument("--frame", type=int, default=None)
    ap.add_argument("--range", type=int, nargs=2, default=None, metavar=("IN", "OUT"))
    ap.add_argument("--layout", default="single")
    ap.add_argument("--views", nargs=2, default=None, metavar=("A", "B"))
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--play-seconds", type=float, default=0, help="play back and report achieved fps")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE",
                    help="clip settings, e.g. output_format=exr outputs=alpha,fg despill=0.3")
    args = ap.parse_args()
    os.environ.setdefault("CKSTUDIO_STATE", tempfile.mkdtemp(prefix="ckstate-"))
    os.makedirs(args.out_dir, exist_ok=True)

    from PySide6.QtCore import QRectF, Qt, QTimer
    from PySide6.QtGui import QPainter, QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    from ckapp.app import theme as T
    from ckapp.app.viewer import default_surface_format

    QSurfaceFormat.setDefaultFormat(default_surface_format())
    app = QApplication([])
    T.apply(app)
    from ckapp.app.main_window import MainWindow

    win = MainWindow()
    win.resize(1600, 950)
    # don't steal focus: keystrokes typed elsewhere would hit Space / I / O shortcuts
    win.setAttribute(Qt.WA_ShowWithoutActivating, True)
    win.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
    win.setWindowFlag(Qt.WindowTransparentForInput, True)      # nor stray mouse-wheel zooms
    win.show()
    win.client.connect_engine()
    clips = win.import_paths([args.clip])
    clip = clips[0] if clips else win.clip
    for kv in args.set:
        key, val = kv.split("=", 1)
        cur = getattr(clip.settings, key)
        val = (val.split(",") if isinstance(cur, list) else val.lower() in ("1", "true", "yes")
               if isinstance(cur, bool) else type(cur)(val))
        setattr(clip.settings, key, val)
    if args.set:
        win.inspector.set_clip(clip)
    if args.range:
        win.timeline.ruler.rin, win.timeline.ruler.rout = args.range
        win._timeline_range(*args.range)
    if args.views:
        win.cb_a.setCurrentIndex(win.cb_a.findData(args.views[0]))
        win.cb_b.setCurrentIndex(win.cb_b.findData(args.views[1]))
    win.seg_layout.set_current(args.layout, emit=True)

    state = {"phase": "wait_engine", "t0": time.time(), "shots": 0, "job": None}
    t = QTimer()

    def shot(name: str) -> None:
        # QWidget.grab() leaves GL widgets black, so paint the viewer's framebuffer in ourselves
        t.stop()
        app.processEvents()
        img = win.grab().toImage()
        gl = win.viewer.grabFramebuffer()
        pos = win.viewer.mapTo(win, win.viewer.rect().topLeft())
        p = QPainter(img)
        p.drawImage(QRectF(pos.x(), pos.y(), win.viewer.width(), win.viewer.height()), gl)
        p.end()
        path = os.path.join(args.out_dir, f"{name}.png")
        img.save(path)
        print("screenshot", path, flush=True)
        t.start(250)

    def tick():
        el = time.time() - state["t0"]
        if el > args.timeout:
            print("TIMEOUT in phase", state["phase"], flush=True)
            shot("timeout")
            app.exit(2)
            return
        if state["phase"] == "wait_engine":
            if win.client.connected and el > 3:
                if args.frame is not None:
                    win.set_frame(args.frame)
                state["phase"], state["t2"] = "decode", time.time()
        elif state["phase"] == "decode":
            if time.time() - state["t2"] > 1.5:
                shot("01_imported")
                if args.play_seconds:
                    state["phase"], state["t3"] = "playing", time.time()
                    state["frames_seen"] = 0
                    win.timeline.frameChanged.connect(lambda _: None)
                    orig = win.set_frame

                    def counting(f, _orig=orig):
                        state["frames_seen"] += 1
                        _orig(f)
                    win.set_frame = counting
                    win.toggle_play()
                    return
                if args.submit_and_quit:
                    win._render(clip)
                    state["phase"] = "submitted"
                elif args.render:
                    win._render(clip)
                    state["phase"] = "rendering"
                else:
                    app.exit(0)
        elif state["phase"] == "playing":
            dt = time.time() - state["t3"]
            if dt >= args.play_seconds:
                win.stop()
                print(f"playback: {state['frames_seen'] / dt:.1f} fps achieved "
                      f"(clip {clip.fps:g} fps, {clip.width}x{clip.height})", flush=True)
                app.exit(0)
        elif state["phase"] == "submitted":
            if clip.renders:
                print("submitted job", clip.renders[-1].job_id, "- closing the app", flush=True)
                app.exit(0)
        elif state["phase"] == "rendering":
            r = clip.renders[-1] if clip.renders else None
            if r and r.status == "running" and state["shots"] == 0:
                state["shots"] = 1
                shot("02_rendering")
            if r and r.status in ("done", "error", "cancelled"):
                print("render status:", r.status, r.outputs, flush=True)
                state["phase"] = "settle"
                state["t1"] = time.time()
        elif state["phase"] == "settle":
            if time.time() - state["t1"] > 2.5:
                if args.frame is not None:
                    win.set_frame(args.frame)
                    QTimer.singleShot(1200, lambda: (shot("03_done"), app.exit(0)))
                    state["phase"] = "end"
                else:
                    shot("03_done")
                    app.exit(0)

    t.timeout.connect(tick)
    t.start(250)
    code = app.exec()
    win.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
