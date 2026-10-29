"""Background frame decoding with a shared LRU cache.

One worker thread per open file, so the plate, foreground and matte of a clip
decode in parallel. Requests are "latest wins": a new request for a source
replaces what that worker had pending, so scrubbing never builds a backlog.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .media import Frame, open_source

Key = tuple  # (path, gray, linear, frame)


class FrameCache:
    def __init__(self, budget_bytes: int):
        self.budget = budget_bytes
        self.used = 0
        self._d: "OrderedDict[Key, Frame]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Key) -> Optional[Frame]:
        with self._lock:
            fr = self._d.get(key)
            if fr is not None:
                self._d.move_to_end(key)
            return fr

    def has(self, key: Key) -> bool:
        with self._lock:
            return key in self._d

    def put(self, key: Key, fr: Frame) -> None:
        with self._lock:
            if key in self._d:
                return
            self._d[key] = fr
            self.used += fr.nbytes
            while self.used > self.budget and len(self._d) > 1:
                _, old = self._d.popitem(last=False)
                self.used -= old.nbytes

    def drop_path(self, path: str) -> None:
        with self._lock:
            for k in [k for k in self._d if k[0] == path]:
                self.used -= self._d.pop(k).nbytes


class _Worker(threading.Thread):
    def __init__(self, provider: "FrameProvider", path: str, gray: bool, linear: bool):
        super().__init__(daemon=True, name=f"decode:{path[-40:]}")
        self.p, self.path, self.gray, self.linear = provider, path, gray, linear
        self.wanted: list[int] = []
        self.cv = threading.Condition()
        self.stop = False
        self.src = None
        self.error = ""

    def want(self, frames: list[int]) -> None:
        with self.cv:
            self.wanted = list(frames)
            self.cv.notify()

    def run(self) -> None:
        try:
            self.src = open_source(self.path, linear=self.linear, gray=self.gray)
        except Exception as e:  # unreadable file: report once, then idle
            self.error = str(e)
            self.p.sourceError.emit(self.path, self.error)
        while True:
            with self.cv:
                while not self.wanted and not self.stop:
                    self.cv.wait()
                if self.stop:
                    break
                i = self.wanted.pop(0)
            key = (self.path, self.gray, self.linear, i)
            if self.src is None or self.p.cache.has(key):
                continue
            try:
                fr = self.src.read(i)
            except Exception:   # a corrupt frame must not kill the worker
                fr = None
            if fr is not None:
                self.p.cache.put(key, fr)
                self.p.frameReady.emit(self.path, i)
        if self.src is not None:
            self.src.close()


class FrameProvider(QObject):
    frameReady = Signal(str, int)       # path, frame (emitted from worker threads; queued to the GUI)
    sourceError = Signal(str, str)

    def __init__(self, budget_mb: int = 1536, parent=None):
        super().__init__(parent)
        self.cache = FrameCache(budget_mb * 1024 * 1024)
        self._workers: dict[tuple, _Worker] = {}
        self._lock = threading.Lock()

    def _worker(self, path: str, gray: bool, linear: bool) -> _Worker:
        k = (path, gray, linear)
        with self._lock:
            w = self._workers.get(k)
            if w is None:
                w = self._workers[k] = _Worker(self, path, gray, linear)
                w.start()
            return w

    def get(self, path: str, i: int, *, gray: bool = False, linear: bool = False) -> Optional[Frame]:
        return self.cache.get((path, gray, linear, i))

    def request(self, path: str, i: int, *, gray: bool = False, linear: bool = False,
                ahead: int = 0, last: Optional[int] = None) -> Optional[Frame]:
        """Returns the frame if cached; otherwise schedules it (plus `ahead` frames after it)."""
        fr = self.get(path, i, gray=gray, linear=linear)
        frames = [i] if fr is None else []
        for j in range(i + 1, i + 1 + ahead):
            if last is not None and j > last:
                break
            if not self.cache.has((path, gray, linear, j)):
                frames.append(j)
        if frames:
            self._worker(path, gray, linear).want(frames)
        return fr

    def error(self, path: str) -> str:
        with self._lock:
            return next((w.error for (p, _, _), w in self._workers.items() if p == path and w.error), "")

    def release(self, path: str) -> None:
        """Close a source (e.g. a render folder that is about to be rewritten)."""
        with self._lock:
            for k in [k for k in self._workers if k[0] == path]:
                w = self._workers.pop(k)
                with w.cv:
                    w.stop = True
                    w.cv.notify()
        self.cache.drop_path(path)

    def shutdown(self) -> None:
        with self._lock:
            ws, self._workers = list(self._workers.values()), {}
        for w in ws:
            with w.cv:
                w.stop = True
                w.cv.notify()
