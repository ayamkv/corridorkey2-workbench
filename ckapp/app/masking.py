"""Click to mask: prompt sessions (one per clip frame) and the calls to the engine's SAM 2.1 tiny worker.

MaskSession is Qt-free. MaskController writes the plate frame for SAM, sends prompts to the engine (one request
at a time; edits made meanwhile go out when it answers) and keeps each session's latest mask.
"""
from __future__ import annotations

import itertools
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, Signal

from .media import Frame, display_u8, open_source, read_gray, write_png

_serial = itertools.count(1)


@dataclass(eq=False)
class MaskSession:
    clip_id: str
    frame: int
    width: int
    height: int
    image: str                                   # the plate frame as an sRGB PNG, for SAM
    out: str                                     # where the engine writes the mask
    points: list = field(default_factory=list)   # [[x, y, 1 keep | 0 remove]] in image pixels
    box: Optional[list] = None                   # [x0, y0, x1, y1]
    history: list = field(default_factory=list)  # (points, box) before each edit, for Undo
    gen: int = 0                                 # bumps on every edit
    mask: Optional[np.ndarray] = None            # HxW uint8, 255 = keep
    mask_gen: int = 0                            # the edit the mask belongs to
    mask_key: int = 0                            # changes with every new mask (the viewer re-uploads on it)
    score: float = 0.0
    failed_gen: int = -1                         # the engine refused this edit: don't resend it
    image_ready: bool = False
    image_error: str = ""
    writing: bool = False
    warmed: bool = False                         # asked the engine to embed this frame ahead of the first click
    _frame: Optional[Frame] = field(default=None, repr=False)

    # -- edits ---------------------------------------------------------------------------------
    def _push(self) -> None:
        self.history.append(([list(p) for p in self.points], list(self.box) if self.box else None))
        self.gen += 1

    def add_point(self, x: float, y: float, keep: bool) -> bool:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        self._push()
        self.points.append([round(float(x), 1), round(float(y), 1), 1 if keep else 0])
        self._settle()
        return True

    def set_box(self, x0: float, y0: float, x1: float, y1: float) -> bool:
        x0, x1 = sorted((min(max(0.0, x0), self.width), min(max(0.0, x1), self.width)))
        y0, y1 = sorted((min(max(0.0, y0), self.height), min(max(0.0, y1), self.height)))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return False
        self._push()
        self.box = [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]
        self._settle()
        return True

    def undo(self) -> bool:
        if not self.history:
            return False
        self.points, self.box = self.history.pop()
        self.gen += 1
        self._settle()
        return True

    def clear(self) -> bool:
        if self.empty():
            return False
        self._push()
        self.points, self.box = [], None
        self._settle()
        return True

    def _settle(self) -> None:
        """No prompts: no mask, and nothing to ask the engine (it refuses an empty prompt)."""
        if self.empty():
            self.mask, self.mask_gen, self._frame = None, self.gen, None
            self.mask_key = next(_serial)

    # -- state ---------------------------------------------------------------------------------
    def empty(self) -> bool:
        return not self.points and self.box is None

    def stale(self) -> bool:
        """Edited since the last mask came back."""
        return not self.empty() and self.mask_gen != self.gen

    def fresh(self) -> bool:
        """The mask matches the current prompts."""
        return self.mask is not None and not self.stale()

    def set_mask(self, gen: int, mask: np.ndarray, score: float) -> bool:
        if gen != self.gen or mask.shape != (self.height, self.width):
            return False
        self.mask, self.mask_gen, self.score = mask, gen, score
        self.mask_key, self._frame = next(_serial), None
        return True

    def mask_frame(self) -> Optional[Frame]:
        if self.mask is None:
            return None
        if self._frame is None:
            self._frame = Frame(np.ascontiguousarray(self.mask[..., None]))
        return self._frame

    def summary(self) -> str:
        keep = sum(1 for p in self.points if p[2])
        parts = []
        if keep:
            parts.append(f"{keep} keep")
        if len(self.points) - keep:
            parts.append(f"{len(self.points) - keep} remove")
        if self.box:
            parts.append("box")
        return ", ".join(parts)


def hint_file(masks_dir: str, frame: int) -> str:
    """A new file for a hint drawn on `frame`. Never one that exists: a past render may have used it."""
    base = os.path.join(masks_dir, f"hint_f{frame:06d}")
    path, n = base + ".png", 2
    while os.path.exists(path):
        path, n = f"{base}_{n}.png", n + 1
    return path


class MaskController(QObject):
    """The mask tool's link to the engine. Owns the sessions; the window shows them."""
    changed = Signal()                      # sessions, masks or engine state changed
    _imageDone = Signal(object, str)        # session, error (from the writer thread)

    OLD_ENGINE = ("The running render engine can't make masks. It's replaced by this version once its renders "
                  "finish and you restart the app.")

    def __init__(self, client, frames, cache_dir: str, parent=None):
        super().__init__(parent)
        self.client, self.frames, self.cache_dir = client, frames, cache_dir
        self.sessions: dict[tuple, MaskSession] = {}
        self.current: Optional[MaskSession] = None
        self.active = False
        self.engine: Optional[dict] = None          # the engine's /mask status; None until it answers
        self.unavailable = ""                       # why this engine can't make masks at all
        self.error = ""
        self.device = ""
        self._inflight: Optional[MaskSession] = None
        self._imageDone.connect(self._image_done)
        client.maskStatus.connect(self._on_status)
        self.clean_cache()

    def clean_cache(self, older_than_s: float = 12 * 3600) -> None:
        """Prompt sessions live only while the app runs, so their frame and mask PNGs from earlier runs (several MB
        each at 4K) are left-overs. Hints are saved in the project, never here."""
        import time
        folder = os.path.join(self.cache_dir, "masks")
        try:
            names = os.listdir(folder)
        except OSError:
            return
        cutoff = time.time() - older_than_s
        for n in names:
            p = os.path.join(folder, n)
            try:
                if n.endswith((".png", ".tmp")) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass

    # -- tool on / off --------------------------------------------------------------------------
    def enter(self) -> None:
        self.active, self.error = True, ""
        self.refresh()

    def leave(self) -> None:
        """Free the model's GPU memory and forget frames that never got a prompt. Stop is sent even when the model
        isn't up yet: it may be loading right now (the engine's stop waits for that load, then ends it)."""
        self.active = False
        self.client.mask_stop()
        for key, s in list(self.sessions.items()):
            if s.empty() and not s.history and s is not self._inflight and not s.writing:
                del self.sessions[key]
                try:
                    os.remove(s.image)
                except OSError:
                    pass
        self.current = None

    def refresh(self) -> None:
        self.client.mask_status(self._on_status, self._status_failed)

    def download(self) -> None:
        self.error = ""
        self.client.mask_download(self._on_status, self._status_failed)
        self.changed.emit()

    def _on_status(self, st: dict) -> None:
        if not isinstance(st, dict):
            return
        self.engine, self.unavailable = st, ""
        if st.get("error"):
            self.error = st["error"]
        self.changed.emit()
        self._pump()

    def _status_failed(self, detail: str, code: int) -> None:
        if code in (404, 405, 501):
            self.unavailable = self.OLD_ENGINE
        elif code == 0:
            self.unavailable = "Not connected to the render engine yet."
        else:
            self.error = detail
        self.changed.emit()

    def model_ready(self) -> bool:
        return bool(self.engine and self.engine.get("model"))

    # -- sessions -------------------------------------------------------------------------------
    def session(self, clip, frame: int, create: bool = True) -> Optional[MaskSession]:
        lin = clip.kind == "sequence" and clip.settings.frame_dir_linear
        key = (clip.id, frame, lin)
        s = self.sessions.get(key)
        if s is None and create:
            stem = os.path.join(self.cache_dir, "masks", f"{clip.id}_f{frame:06d}{'_lin' if lin else ''}")
            s = self.sessions[key] = MaskSession(clip.id, frame, clip.width, clip.height, stem + ".png",
                                                 stem + "_mask.png")
        return s

    def focus(self, clip, frame: int) -> MaskSession:
        """The frame on screen: write its plate for SAM, so the first click is quick."""
        s = self.current = self.session(clip, frame)
        self._prepare(clip, s)
        self._pump()
        return s

    def edit(self, clip, frame: int, fn: Callable[[MaskSession], bool]) -> bool:
        s = self.current = self.session(clip, frame)
        if not fn(s):
            return False
        self.error = ""
        self._prepare(clip, s)
        self.changed.emit()
        self._pump()
        return True

    def _prepare(self, clip, s: MaskSession) -> None:
        if s.image_ready or s.writing:
            return
        s.writing, s.image_error = True, ""
        lin = clip.kind == "sequence" and clip.settings.frame_dir_linear
        path, frames = clip.path, self.frames

        def work():
            err = ""
            try:
                fr = frames.get(path, s.frame, linear=lin)       # exactly frame F, never the one still on screen
                if fr is None:
                    src = open_source(path, linear=lin)
                    try:
                        fr = src.read(s.frame)
                    finally:
                        src.close()
                if fr is None:
                    raise ValueError(f"cannot read frame {s.frame}")
                img = display_u8(fr)
                if img.ndim == 3 and img.shape[2] == 1:
                    img = img[..., 0]
                write_png(s.image, img)
            except Exception as e:  # report, don't kill the thread silently
                err = str(e) or type(e).__name__
            self._imageDone.emit(s, err)
        threading.Thread(target=work, daemon=True, name="mask-frame").start()

    def _image_done(self, s: MaskSession, err: str) -> None:
        s.writing = False
        if err:
            s.image_error = self.error = f"Cannot prepare frame {s.frame} for masking: {err}"
        else:
            s.image_ready = True
        self.changed.emit()
        self._pump()

    # -- requests -------------------------------------------------------------------------------
    def busy(self) -> bool:
        return self._inflight is not None

    def loading_model(self) -> bool:
        """The first request starts the worker and loads the model, which can take a while."""
        return self.busy() and not (self.engine and self.engine.get("running"))

    def _pump(self) -> None:
        """Send the next request: the current frame's latest edit first. One at a time, latest edit wins."""
        if not self.active or self._inflight is not None or self.unavailable or not self.model_ready():
            return
        todo = [self.current] if self.current is not None else []
        todo += [s for s in self.sessions.values() if s is not self.current]
        s = next((s for s in todo if s.image_ready and s.stale() and s.failed_gen != s.gen), None)
        if s is None:
            cur = self.current
            if cur is not None and cur.image_ready and cur.empty() and not cur.warmed:
                cur.warmed = True                                      # embed once while the user aims
                self._inflight = cur
                self.client.mask_open(cur.image, lambda r: self._opened(cur, r),
                                      lambda d, c: self._failed(cur, -1, d, c))
                self.changed.emit()
            return
        gen = s.gen
        self._inflight = s
        os.makedirs(os.path.dirname(s.out), exist_ok=True)
        self.client.mask_predict(s.image, s.points, s.box, s.out, lambda r: self._predicted(s, gen, r),
                                 lambda d, c: self._failed(s, gen, d, c))
        self.changed.emit()

    def _answered(self, r: dict) -> None:
        self._inflight = None
        self.device = r.get("device") or self.device
        if not self.active:             # the tool closed while this was loading the model: let it go again
            self.client.mask_stop()

    def _opened(self, s: MaskSession, r: dict) -> None:
        self._answered(r)
        self.changed.emit()
        self._pump()

    def _predicted(self, s: MaskSession, gen: int, r: dict) -> None:
        self._answered(r)
        if gen == s.gen:                       # otherwise edited meanwhile: the next request is about to go
            m = read_gray(s.out)
            if m is None or not s.set_mask(gen, m, float(r.get("score", 0.0))):
                s.failed_gen = gen
                self.error = "The mask came back unreadable or at the wrong size."
        self.changed.emit()
        self._pump()

    def _failed(self, s: MaskSession, gen: int, detail: str, code: int) -> None:
        self._inflight = None
        if gen >= 0:
            s.failed_gen = gen
        if code in (404, 405, 501):
            self.unavailable = self.OLD_ENGINE
        else:
            self.error = detail
            if "downloaded" in detail:
                self.refresh()
        self.changed.emit()
        self._pump()
