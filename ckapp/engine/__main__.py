"""Start the render engine:  python -m ckapp.engine [--port N] [--idle-exit MIN]

Writes ``engine.json`` (host, port, token, pid) into the state folder so the app
can find and reuse a running engine. Runs until idle (no jobs, no connected
apps) for ``--idle-exit`` minutes, so renders keep going after the app closes.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time

import uvicorn

from ..config import load_settings, state_dir
from .jobs import JobQueue
from .server import EventBus, create_app


def discovery_path():
    return state_dir() / "engine.json"


def _free_port(host: str, start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket() as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"no free port in {start}..{start + 19}")


def main(argv: list[str] | None = None) -> None:
    s = load_settings().resolved()
    p = argparse.ArgumentParser(prog="ckapp.engine")
    p.add_argument("--port", type=int, default=s.engine_port)
    p.add_argument("--lan", action="store_true", default=s.lan_enabled, help="listen on all interfaces")
    p.add_argument("--idle-exit", type=float, default=10.0, help="minutes idle before exiting (0 = never)")
    args = p.parse_args(argv)

    if not s.ck_python or not os.path.isfile(s.ck_python):
        print(f"CorridorKey python not found (ck_root={s.ck_root!r}); set it in Settings.", file=sys.stderr)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    port = _free_port(host, args.port)
    token = secrets.token_urlsafe(24)

    bus = EventBus()
    queue = JobQueue(ck_python=s.ck_python, ck_root=s.ck_root, cache_dir=s.cache_dir, ffmpeg=s.ffmpeg,
                     history_path=state_dir() / "jobs.json", on_event=bus.publish)
    app = create_app(queue, bus, token)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning",
                                           access_log=False))

    info = {"host": "127.0.0.1", "port": port, "token": token, "pid": os.getpid(), "lan": args.lan}
    discovery_path().write_text(json.dumps(info), encoding="utf-8")
    print(f"engine listening on {host}:{port} (pid {os.getpid()})", flush=True)

    if args.idle_exit > 0:
        def idle_watch():
            idle_since = time.time()
            while not server.should_exit:
                time.sleep(5)
                if queue.busy() or bus.count():
                    idle_since = time.time()
                elif time.time() - idle_since > args.idle_exit * 60:
                    server.should_exit = True
        threading.Thread(target=idle_watch, daemon=True).start()

    try:
        server.run()
    finally:
        queue.shutdown()
        try:
            if json.loads(discovery_path().read_text(encoding="utf-8")).get("pid") == os.getpid():
                discovery_path().unlink()
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    main()
