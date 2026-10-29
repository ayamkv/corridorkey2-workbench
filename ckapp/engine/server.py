"""HTTP API for the job queue.

REST for commands, Server-Sent Events (``GET /events``) for live updates. Every
request needs the engine token (``X-CK-Token`` header or ``?token=``), so binding
to the LAN later only changes the host, not the security model.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import subprocess
import threading
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import __version__
from .jobs import JobQueue, JobSpec
from .masks import MaskError, MaskService


class EventBus:
    """Fan-out from the job worker thread to any number of async SSE clients."""

    def __init__(self) -> None:
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        with self._lock:
            self._subs.append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [(l, s) for l, s in self._subs if s is not q]

    def count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, kind: str, data: dict) -> None:
        msg = f"event: {kind}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            def put(q=q):
                if q.full():           # a stalled client must not grow memory forever
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(msg)
            try:
                loop.call_soon_threadsafe(put)
            except RuntimeError:       # loop closed
                pass


def gpu_info() -> Optional[dict]:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        name, used, total, util = [s.strip() for s in r.stdout.splitlines()[0].split(",")]
        return {"name": name, "used_mb": int(used), "total_mb": int(total), "util": int(util)}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def create_app(queue: JobQueue, bus: EventBus, token: str, masks: Optional[MaskService] = None) -> FastAPI:
    app = FastAPI(title="CorridorKey2 Workbench engine", version=__version__)

    def auth(request: Request) -> None:
        got = request.headers.get("x-ck-token") or request.query_params.get("token") or ""
        if not secrets.compare_digest(got, token):
            raise HTTPException(status_code=401, detail="bad token")

    @app.get("/health", dependencies=[Depends(auth)])
    def health() -> dict:
        return {"ok": True, "version": __version__, "pid": os.getpid(), "busy": queue.busy(),
                "ck_root": queue.ck_root, "ck_python": queue.ck_python}

    @app.get("/system", dependencies=[Depends(auth)])
    def system(path: str = "") -> dict:
        disk = None
        target = path or queue.cache_dir
        try:
            u = shutil.disk_usage(target if os.path.exists(target) else os.path.dirname(target) or ".")
            disk = {"path": target, "free_gb": round(u.free / 1e9, 1), "total_gb": round(u.total / 1e9, 1)}
        except OSError:
            pass
        return {"gpu": gpu_info(), "disk": disk}

    @app.get("/jobs", dependencies=[Depends(auth)])
    def jobs() -> list:
        return queue.list()

    @app.post("/jobs", dependencies=[Depends(auth)], status_code=201)
    def submit(body: dict) -> dict:
        """The body is a JobSpec; "hold": true parks the job until /jobs/{id}/start (Add to queue)."""
        try:
            job = queue.submit(JobSpec.from_dict(body), hold=bool(body.get("hold")))
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return job.to_dict()

    @app.post("/jobs/start", dependencies=[Depends(auth)])
    def start_all() -> dict:
        return {"started": queue.start()}

    @app.post("/jobs/{job_id}/start", dependencies=[Depends(auth)])
    def start(job_id: str) -> dict:
        if not queue.start(job_id):
            raise HTTPException(status_code=409, detail="job is not waiting for Start")
        return {"ok": True}

    @app.get("/jobs/{job_id}", dependencies=[Depends(auth)])
    def job(job_id: str, log: bool = False) -> dict:
        j = queue.get(job_id)
        if j is None:
            raise HTTPException(status_code=404, detail="no such job")
        return j.to_dict(with_log=log)

    @app.post("/jobs/{job_id}/cancel", dependencies=[Depends(auth)])
    def cancel(job_id: str) -> dict:
        if not queue.cancel(job_id):
            raise HTTPException(status_code=409, detail="job is not queued or running")
        return {"ok": True}

    @app.delete("/jobs/{job_id}", dependencies=[Depends(auth)])
    def remove(job_id: str) -> dict:
        if not queue.remove(job_id):
            raise HTTPException(status_code=409, detail="only finished jobs can be removed")
        return {"ok": True}

    # -- click to mask ------------------------------------------------------------------------
    def _masks() -> MaskService:
        if masks is None:
            raise HTTPException(status_code=501, detail="masks are not available in this engine")
        return masks

    @app.get("/mask", dependencies=[Depends(auth)])
    def mask_status() -> dict:
        return _masks().status()

    @app.post("/mask/download", dependencies=[Depends(auth)], status_code=202)
    def mask_download() -> dict:
        _masks().download()
        return _masks().status()

    @app.post("/mask/open", dependencies=[Depends(auth)])
    def mask_open(body: dict) -> dict:
        try:
            return _masks().open(str(body.get("image", "")))
        except MaskError as e:
            raise HTTPException(status_code=409, detail=str(e))

    @app.post("/mask/predict", dependencies=[Depends(auth)])
    def mask_predict(body: dict) -> dict:
        try:
            return _masks().predict(str(body.get("image", "")), list(body.get("points") or []),
                                    body.get("box") or None, str(body.get("out", "")))
        except MaskError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/mask/stop", dependencies=[Depends(auth)])
    def mask_stop() -> dict:
        _masks().stop()
        return {"ok": True}

    @app.get("/events", dependencies=[Depends(auth)])
    async def events(request: Request) -> StreamingResponse:
        q = bus.subscribe()

        async def stream():
            try:
                yield f"event: hello\ndata: {json.dumps({'jobs': queue.list()})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        msg = ": keepalive\n\n"
                    yield msg
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    return app
