"""Click to mask: runs sam_worker.py (SAM 2.1 tiny) in CorridorKey's python, between renders.

One long-lived worker keeps the current frame's embedding, so each click is a quick prompt decode.
A render needs the whole GPU, so the worker is stopped before every render; while one runs, masks are
computed on the CPU instead (slower to open a frame, clicks stay quick).
"""
from __future__ import annotations

import json
import os
import queue as queue_mod
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from .sam_worker import FILES

MODEL_NAME = "sam2.1-hiera-tiny"


class MaskError(RuntimeError):
    pass


class MaskService:
    START_TIMEOUT = 180.0          # first CUDA init can be slow
    CALL_TIMEOUT = 120.0

    def __init__(self, *, ck_python: str, cache_dir: str, gpu_busy: Callable[[], bool],
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 worker_cmd: Optional[list[str]] = None) -> None:
        self.ck_python, self.cache_dir = ck_python, cache_dir
        self.model_dir = str(Path(cache_dir) / "models" / MODEL_NAME)
        self.gpu_busy = gpu_busy
        self.on_event = on_event or (lambda kind, data: None)
        self.worker_cmd = worker_cmd or [ck_python, str(Path(__file__).with_name("sam_worker.py"))]
        self._proc: Optional[subprocess.Popen] = None
        self._lines: "queue_mod.Queue[Optional[str]]" = queue_mod.Queue()
        self.device: Optional[str] = None
        self.downloading = False
        self.error = ""
        self._lock = threading.RLock()

    # -- state -------------------------------------------------------------------------------
    def model_ready(self) -> bool:
        return all((Path(self.model_dir) / f).is_file() for f in FILES)

    def status(self) -> dict:
        return {"model": self.model_ready(), "model_dir": self.model_dir, "downloading": self.downloading,
                "running": self._alive(), "device": self.device if self._alive() else None, "error": self.error}

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _env(self, offline: bool = True) -> dict:
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", TMP=self.cache_dir,
                   TEMP=self.cache_dir, HF_HOME=str(Path(self.cache_dir) / "hf"))
        if offline:
            env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        else:
            env.pop("HF_HUB_OFFLINE", None)
            env.pop("TRANSFORMERS_OFFLINE", None)
        return env

    @staticmethod
    def _flags() -> int:
        return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    # -- download ----------------------------------------------------------------------------
    def download(self) -> bool:
        """Fetch the pinned weights in the background. False if already running."""
        with self._lock:
            if self.downloading:
                return False
            self.downloading, self.error = True, ""
        self.on_event("mask", self.status())

        def work():
            try:
                r = subprocess.run([*self.worker_cmd, "--download", self.model_dir], capture_output=True,
                                   text=True, env=self._env(offline=False), timeout=3600,
                                   creationflags=self._flags())
                if r.returncode != 0 or not self.model_ready():
                    tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or [f"exit code {r.returncode}"]
                    self.error = f"Download failed: {tail[0]}"
            except (OSError, subprocess.SubprocessError) as e:
                self.error = f"Download failed: {e}"
            finally:
                self.downloading = False
                self.on_event("mask", self.status())
        threading.Thread(target=work, daemon=True, name="mask-download").start()
        return True

    # -- worker ------------------------------------------------------------------------------
    def _start(self, device: str) -> None:
        if not self.model_ready():
            raise MaskError("The mask model isn't downloaded yet.")
        log = open(Path(self.cache_dir) / "mask_worker.log", "ab")
        try:
            self._proc = subprocess.Popen(
                [*self.worker_cmd, "--model", self.model_dir, "--device", device], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=log, env=self._env(), creationflags=self._flags(),
                text=True, encoding="utf-8", bufsize=1)
        finally:
            log.close()
        self._lines = queue_mod.Queue()
        lines, out = self._lines, self._proc.stdout

        def pump():
            for line in iter(out.readline, ""):
                lines.put(line)
            lines.put(None)
        threading.Thread(target=pump, daemon=True, name="mask-stdout").start()
        hello = self._read(self.START_TIMEOUT)
        if not hello.get("ok"):
            self.stop()
            raise MaskError(hello.get("error", "the mask worker did not start"))
        self.device = hello.get("device", device)
        self.on_event("mask", self.status())

    def _read(self, timeout: float) -> dict:
        try:
            line = self._lines.get(timeout=timeout)
        except queue_mod.Empty:
            self.stop()
            raise MaskError("the mask worker stopped answering")
        if line is None:
            self.stop()
            raise MaskError("the mask worker exited; see mask_worker.log in the cache folder")
        try:
            return json.loads(line)
        except ValueError:
            return self._read(timeout)            # stray output: skip it

    def _call(self, msg: dict) -> dict:
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except OSError:
            self.stop()
            raise MaskError("the mask worker exited")
        r = self._read(self.CALL_TIMEOUT)
        if not r.get("ok"):
            raise MaskError(r.get("error", "mask request failed"))
        return r

    RELEASE_AFTER = 30.0           # seconds with no app connected before the model's GPU memory is freed
    _alone_since: Optional[float] = None

    def idle_check(self, clients: int, now: float) -> bool:
        """Call every few seconds with the number of connected apps. The model is only useful while an app is
        connected, and an app that is closing can't be relied on to ask for /mask/stop, so the worker stops once
        no app has been connected for RELEASE_AFTER seconds. True when it stopped it."""
        if clients:
            self._alone_since = None
            return False
        if self._alone_since is None:
            self._alone_since = now
            return False
        if now - self._alone_since >= self.RELEASE_AFTER and self._alive():
            self.stop()
            return True
        return False

    def stop(self) -> None:
        with self._lock:
            p, self._proc = self._proc, None
            if p is not None and p.poll() is None:
                try:
                    p.stdin.write('{"cmd": "quit"}\n')
                    p.stdin.flush()
                    p.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired, ValueError):
                    p.kill()
            if p is not None:
                self.device = None
                self.on_event("mask", self.status())

    # -- requests ----------------------------------------------------------------------------
    def open(self, image: str) -> dict:
        """Embed `image` (cached by the worker). GPU when it is free, CPU while a render runs."""
        if not os.path.isfile(image):
            raise MaskError(f"image not found: {image}")
        want = "cpu" if self.gpu_busy() else "cuda"
        with self._lock:
            if self._alive() and want != self._requested:
                self.stop()
            if not self._alive():
                self._requested = want
                self._start(want)
            r = self._call({"cmd": "open", "image": image})
            r["device"] = self.device
            return r

    _requested = ""

    def predict(self, image: str, points: list, box: Optional[list], out: str) -> dict:
        """Mask for `image` from clicks [[x, y, 1 keep | 0 remove]] and/or a box, written to `out`."""
        with self._lock:
            info = self.open(image)          # no-op when already embedded; restarts after a render
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            r = self._call({"cmd": "predict", "points": points, "box": box, "out": out})
            r["device"], r["width"], r["height"] = info["device"], info["width"], info["height"]
            return r
