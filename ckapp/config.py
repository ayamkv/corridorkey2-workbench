"""Paths and user settings shared by the app and the engine."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = Path(__file__).resolve().parent / "engine"


def state_dir() -> Path:
    """Small files only (settings, engine discovery, job history)."""
    env = next((os.environ[k] for k in ("CK2WB_STATE", "CKDESK_STATE", "OPENDECK_STATE", "CKSTUDIO_STATE")
                if os.environ.get(k)), "")
    if env:
        p = Path(env)
    else:
        from . import APP_ID
        root = Path(os.environ.get("APPDATA") or Path.home())
        p = root / APP_ID
        for old_name in ("CorridorKeyDesk", "OpenDeck", "CorridorKeyStudio"):     # earlier names
            old = root / old_name
            if p.exists() or not old.is_dir():
                continue
            try:
                old.rename(p)
            except OSError:              # a running old engine keeps engine.log open: copy instead
                shutil.copytree(old, p, ignore=shutil.ignore_patterns("engine.*"), dirs_exist_ok=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _default_ck_root() -> str:
    for cand in (APP_ROOT.parent / "CorridorKey2.0", APP_ROOT.parent / "CorridorKey"):
        if (cand / "infer.py").is_file():
            return str(cand)
    return ""


def venv_python(root: str | Path) -> str:
    """The python inside a repo's venv, or '' if there is none."""
    for name in (".venv", "venv", "env"):
        for rel in (("Scripts", "python.exe"), ("bin", "python")):
            p = Path(root, name, *rel)
            if p.is_file():
                return str(p)
    return ""


@dataclass
class Settings:
    ck_root: str = ""            # CorridorKey 2.0 repo (contains infer.py)
    ck_python: str = ""          # its venv python ('' = auto)
    cache_dir: str = ""          # low-VRAM staging + temp files ('' = <app>/.cache)
    ffmpeg: str = ""             # '' = ffmpeg on PATH
    engine_port: int = 8765
    lan_enabled: bool = False    # later phase: bind 0.0.0.0 (token always required)

    def resolved(self) -> "Settings":
        s = Settings(**asdict(self))
        s.ck_root = s.ck_root or _default_ck_root()
        s.ck_python = s.ck_python or (venv_python(s.ck_root) if s.ck_root else "")
        s.cache_dir = s.cache_dir or str(APP_ROOT / ".cache")
        s.ffmpeg = s.ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
        return s


def settings_path() -> Path:
    return state_dir() / "settings.json"


def load_settings() -> Settings:
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save_settings(s: Settings) -> None:
    settings_path().write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
