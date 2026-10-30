"""Talks to the render engine: finds or starts it, sends commands, follows its event stream."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Callable, Optional
from urllib.parse import quote

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..config import APP_ROOT, load_settings, state_dir


def _discovery() -> Optional[dict]:
    try:
        return json.loads((state_dir() / "engine.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _health(info: dict, timeout: float = 1.5) -> Optional[dict]:
    req = urllib.request.Request(f"http://{info['host']}:{info['port']}/health",
                                 headers={"X-CK-Token": info["token"]})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            h = json.loads(r.read())
            return h if h.get("ok") else None
    except (OSError, ValueError):
        return None


def _healthy(info: dict, timeout: float = 1.5) -> bool:
    return _health(info, timeout) is not None


def _stop_engine(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.kill(pid, 15)
    time.sleep(0.5)


def start_engine(wait_s: float = 20.0) -> dict:
    """Return a healthy engine's discovery info, starting a detached engine if needed.
    An idle engine left running by another app version is replaced, since it may not know newer job
    settings; a busy one is kept so its renders finish."""
    from .. import __version__
    info = _discovery()
    h = _health(info) if info else None
    if h and (h.get("version") == __version__ or h.get("busy")):
        return dict(info, version=h.get("version", ""))
    if h and h.get("pid"):
        _stop_engine(int(h["pid"]))
    s = load_settings().resolved()
    os.makedirs(s.cache_dir, exist_ok=True)
    py = sys.executable
    if os.name == "nt" and py.lower().endswith("python.exe"):
        cand = py[:-10] + "pythonw.exe"
        py = cand if os.path.exists(cand) else py
    env = dict(os.environ, TMP=s.cache_dir, TEMP=s.cache_dir, TMPDIR=s.cache_dir)
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    log = open(state_dir() / "engine.log", "ab")
    subprocess.Popen([py, "-m", "ckapp.engine"], cwd=str(APP_ROOT), env=env, stdin=subprocess.DEVNULL,
                     stdout=log, stderr=log, creationflags=flags, start_new_session=(os.name != "nt"),
                     close_fds=True)
    end = time.time() + wait_s
    while time.time() < end:
        time.sleep(0.25)
        info = _discovery()
        if info and _healthy(info, timeout=1.0):
            return dict(info, version=__version__)
    raise RuntimeError(f"the render engine did not start; see {state_dir() / 'engine.log'}")


class EngineClient(QObject):
    connectedChanged = Signal(bool)
    jobsReset = Signal(list)            # full list (on connect)
    jobUpdated = Signal(dict)
    jobRemoved = Signal(str)
    logLine = Signal(str, str)
    system = Signal(dict)
    requestFailed = Signal(str)
    _started = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._starting = False
        self._started.connect(self._on_started)
        self.nam = QNetworkAccessManager(self)
        self.info: Optional[dict] = None
        self.connected = False
        self._sse: Optional[QNetworkReply] = None
        self._buf = b""
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self.connect_engine)
        self._sys_timer = QTimer(self)
        self._sys_timer.timeout.connect(self.poll_system)
        self.disk_path = ""

    # -- lifecycle -------------------------------------------------------------------------
    def connect_engine(self) -> None:
        """Find or start the engine on a worker thread (starting one takes a few seconds)."""
        if self._starting:
            return
        self._starting = True

        def work():
            try:
                self._started.emit(start_engine())
            except RuntimeError as e:
                self._started.emit({"error": str(e)})
        threading.Thread(target=work, daemon=True, name="engine-start").start()

    def _on_started(self, info: dict) -> None:
        self._starting = False
        if "error" in info:
            self._set_connected(False)
            self.requestFailed.emit(info["error"])
            self._retry.start(5000)
            return
        self.info = info
        self._open_events()
        self._sys_timer.start(2000)

    def close(self) -> None:
        self._retry.stop()
        self._sys_timer.stop()
        if self._sse is not None:
            self._sse.abort()

    def _set_connected(self, on: bool) -> None:
        if on != self.connected:
            self.connected = on
            self.connectedChanged.emit(on)

    def _url(self, path: str) -> QUrl:
        return QUrl(f"http://{self.info['host']}:{self.info['port']}{path}")

    def _request(self, path: str) -> QNetworkRequest:
        r = QNetworkRequest(self._url(path))
        r.setRawHeader(b"X-CK-Token", self.info["token"].encode())
        return r

    # -- events ----------------------------------------------------------------------------
    def _open_events(self) -> None:
        if self._sse is not None:
            self._sse.abort()
        req = self._request("/events")
        req.setRawHeader(b"Accept", b"text/event-stream")
        req.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.AlwaysNetwork)
        self._buf = b""
        reply = self.nam.get(req)
        reply.readyRead.connect(lambda r=reply: self._on_sse(r))
        reply.finished.connect(lambda r=reply: self._sse_closed(r))
        self._sse = reply

    def _on_sse(self, reply: QNetworkReply) -> None:
        self._buf += bytes(reply.readAll())
        while b"\n\n" in self._buf:
            block, self._buf = self._buf.split(b"\n\n", 1)
            kind, data = "message", []
            for line in block.decode("utf-8", errors="replace").splitlines():
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
            if not data:
                continue
            try:
                payload = json.loads("\n".join(data))
            except ValueError:
                continue
            self._dispatch(kind, payload)

    def _dispatch(self, kind: str, payload: dict) -> None:
        if kind == "hello":
            self._set_connected(True)
            self.jobsReset.emit(payload.get("jobs", []))
        elif kind == "job":
            self.jobUpdated.emit(payload)
        elif kind == "removed":
            self.jobRemoved.emit(payload["id"])
        elif kind == "log":
            self.logLine.emit(payload["id"], payload["line"])

    def _sse_closed(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        if reply is not self._sse:
            return
        self._sse = None
        self._set_connected(False)
        self._retry.start(1500)        # engine restarted or went idle: reconnect (starts it if needed)

    # -- commands --------------------------------------------------------------------------
    def _send(self, method: str, path: str, body: Optional[dict] = None,
              done: Optional[Callable[[dict], None]] = None, quiet: bool = False) -> None:
        if not self.info:
            if not quiet:
                self.requestFailed.emit("not connected to the render engine")
            return
        req = self._request(path)
        if body is not None:
            req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        data = QByteArray(json.dumps(body).encode()) if body is not None else QByteArray()
        reply = self.nam.sendCustomRequest(req, method.encode(), data)

        def finished():
            raw = bytes(reply.readAll())
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0
            try:
                payload = json.loads(raw) if raw else {}
            except ValueError:
                payload = {}
            if reply.error() != QNetworkReply.NoError and not (200 <= int(status) < 300):
                detail = payload.get("detail") if isinstance(payload, dict) else None
                if not quiet:
                    self.requestFailed.emit(detail or reply.errorString())
            elif done:
                done(payload)
            reply.deleteLater()
        reply.finished.connect(finished)

    @property
    def engine_version(self) -> str:
        return (self.info or {}).get("version", "")

    def can_hold(self) -> bool:
        """Engines before 0.4.0 ignore "hold" and would start the job at once."""
        from .. import __version__
        return self.engine_version == __version__

    def submit(self, spec: dict, done: Callable[[dict], None], hold: bool = False) -> None:
        self._send("POST", "/jobs", dict(spec, hold=True) if hold else spec, done)

    def list_jobs(self, done: Callable[[list], None]) -> None:
        self._send("GET", "/jobs", None, done, quiet=True)

    def start(self, job_id: str) -> None:
        self._send("POST", f"/jobs/{job_id}/start")

    def start_all(self) -> None:
        self._send("POST", "/jobs/start")

    def cancel(self, job_id: str) -> None:
        self._send("POST", f"/jobs/{job_id}/cancel")

    def remove(self, job_id: str) -> None:
        self._send("DELETE", f"/jobs/{job_id}")

    def fetch_log(self, job_id: str, done: Callable[[dict], None]) -> None:
        self._send("GET", f"/jobs/{job_id}?log=true", None, done)

    def poll_system(self) -> None:
        if self.info and self.connected:
            q = f"?path={quote(self.disk_path)}" if self.disk_path else ""
            self._send("GET", f"/system{q}", None, self.system.emit, quiet=True)
