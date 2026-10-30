"""A project is a folder: project.json, renders/<clip folder>/render_NNN/ and masks/<clip folder>/. Qt-free.

In memory every path is absolute. On disk, paths inside the project folder are stored relative to it, so
the folder can be moved; paths outside it (renders from before projects, custom output folders) stay absolute.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Optional

from .model import Clip, Render

FILE = "project.json"
VERSION = 1                       # project.json format; bump when old builds must not open newer files
MIN_FREE_GB = 20                  # Documents is only a default when its drive has this much room
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class ProjectError(Exception):
    pass


def safe_name(name: str, fallback: str = "clip") -> str:
    """A folder name Windows accepts: no illegal characters, reserved names or trailing dots/spaces."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(". ")
    if not name:
        name = fallback
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name[:80]


def _rel(path: str, root: str) -> str:
    """Path relative to root (with forward slashes) when it is inside root; else unchanged."""
    if not path or not os.path.isabs(path):
        return path
    try:
        if os.path.commonpath([os.path.normcase(os.path.abspath(path)), os.path.normcase(root)]) \
                != os.path.normcase(root):
            return path
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:                 # another drive
        return path


def _abs(path: str, root: str) -> str:
    if not path or os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(root, path))


class Project:
    def __init__(self, path: str | Path):
        self.path = Path(os.path.abspath(path))
        self.root = str(self.path.parent)
        self.name = self.path.parent.name
        self.created = ""
        self.clips: list[Clip] = []

    # -- create / open ---------------------------------------------------------------------------
    @classmethod
    def create(cls, folder: str | Path) -> "Project":
        folder = Path(folder)
        if (folder / FILE).exists():
            raise ProjectError(f"{folder} already has a project")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ProjectError(f"cannot create {folder}: {e.strerror or e}")
        p = cls(folder / FILE)
        p.created = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not p.save():
            raise ProjectError(f"cannot write {p.path}")
        return p

    @classmethod
    def open(cls, path: str | Path) -> "Project":
        """`path` is a project.json or the folder holding one."""
        path = Path(path)
        if path.is_dir():
            path = path / FILE
        p = cls(path)
        p.load()
        return p

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as e:
            raise ProjectError(f"cannot read {self.path}: {e.strerror or e}")
        except ValueError:
            raise ProjectError(f"{self.path} is not a valid project file")
        if not isinstance(data, dict):
            raise ProjectError(f"{self.path} is not a valid project file")
        if int(data.get("version", 1)) > VERSION:
            raise ProjectError(f"{self.path.parent.name} was saved by a newer version of the app; update to open it")
        self.created = data.get("created", "")
        self.clips = []
        for d in data.get("clips", []):
            try:
                clip = Clip.from_dict(d)
            except (TypeError, KeyError):
                continue
            for r in clip.renders:
                r.out_dir = _abs(r.out_dir, self.root)
                r.outputs = {k: _abs(v, self.root) for k, v in r.outputs.items()}
            clip.base = self.root
            if not clip.folder:
                self.assign_folder(clip)
            self.clips.append(clip)

    def to_dict(self) -> dict:
        clips = []
        for c in self.clips:
            d = {k: getattr(c, k) for k in Clip.SAVED}
            d["settings"] = asdict(c.settings)
            d["renders"] = []
            for r in c.renders:
                rd = asdict(r)
                rd["out_dir"] = _rel(r.out_dir, self.root)
                rd["outputs"] = {k: _rel(v, self.root) for k, v in r.outputs.items()}
                d["renders"].append(rd)
            clips.append(d)
        return {"app": "CorridorKey2 Workbench", "version": VERSION, "created": self.created, "clips": clips}

    def save(self) -> bool:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    # -- clips -----------------------------------------------------------------------------------
    def find(self, clip_id: str) -> Optional[Clip]:
        return next((c for c in self.clips if c.id == clip_id), None)

    def find_job(self, job_id: str) -> tuple[Optional[Clip], Optional[Render]]:
        for c in self.clips:
            for r in c.renders:
                if r.job_id == job_id:
                    return c, r
        return None, None

    def add(self, clip: Clip) -> None:
        clip.base = self.root
        if not clip.folder:
            self.assign_folder(clip)
        self.clips.append(clip)

    def assign_folder(self, clip: Clip) -> str:
        """A folder name no other clip uses and that isn't on disk yet (a removed clip's renders stay its own)."""
        taken = {c.folder.lower() for c in self.clips if c is not clip and c.folder}
        for sub in ("renders", "masks"):
            try:
                taken.update(n.lower() for n in os.listdir(os.path.join(self.root, sub)))
            except OSError:
                pass
        base = safe_name(clip.stem)
        name, n = base, 2
        while name.lower() in taken:
            name, n = f"{base}_{n}", n + 1
        clip.folder = name
        return name

    def busy(self) -> bool:
        return any(c.busy() for c in self.clips)

    # -- the old single session ------------------------------------------------------------------
    def bring_in(self, session_path: Path) -> int:
        """Add the clips of a pre-project session.json (renders stay where they are), save, then rename the
        session file so it's offered only once. Returns how many clips came in."""
        clips = session_clips(session_path)
        known = {os.path.normcase(os.path.abspath(c.path)) for c in self.clips}
        n = 0
        for c in clips:
            if os.path.normcase(os.path.abspath(c.path)) in known:
                continue
            c.folder = ""
            self.add(c)
            n += 1
        if not self.save():
            raise ProjectError(f"cannot write {self.path}")
        try:
            os.replace(session_path, session_path.with_name("session.migrated.json"))
        except OSError:
            pass
        return n


def session_clips(path: Path) -> list[Clip]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for d in data.get("clips", []) if isinstance(data, dict) else []:
        try:
            out.append(Clip.from_dict(d))
        except (TypeError, KeyError):
            continue
    return out


# --------------------------------------------------------------------------- recent projects
class Recent:
    """recent.json in the state folder: recently opened project files and the last parent folder used."""
    LIMIT = 12

    def __init__(self, path: Path):
        self.path = path
        self.projects: list[str] = []
        self.last_parent = ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.projects = [str(p) for p in data.get("projects", [])][: self.LIMIT]
            self.last_parent = str(data.get("last_parent", ""))
        except (OSError, ValueError, AttributeError):
            pass

    def existing(self) -> list[str]:
        return [p for p in self.projects if os.path.isfile(p)]

    def add(self, project_file: str) -> None:
        key = os.path.normcase(os.path.abspath(project_file))
        self.projects = [project_file] + [p for p in self.projects if os.path.normcase(os.path.abspath(p)) != key]
        self.projects = self.projects[: self.LIMIT]
        self.save()

    def remove(self, project_file: str) -> None:
        key = os.path.normcase(os.path.abspath(project_file))
        self.projects = [p for p in self.projects if os.path.normcase(os.path.abspath(p)) != key]
        self.save()

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps({"projects": self.projects, "last_parent": self.last_parent}, indent=1),
                                 encoding="utf-8")
        except OSError:
            pass


# --------------------------------------------------------------------------- where new projects go
def fixed_drives() -> list[tuple[str, float]]:
    """[(root, free GB)] for local fixed disks."""
    out = []
    if os.name == "nt":
        import ctypes
        import string
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if not mask >> i & 1:
                continue
            root = f"{letter}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) != 3:     # DRIVE_FIXED
                continue
            try:
                out.append((root, shutil.disk_usage(root).free / 1e9))
            except OSError:
                pass
    else:
        try:
            out.append(("/", shutil.disk_usage("/").free / 1e9))
        except OSError:
            pass
    return out


def free_gb(path: str) -> Optional[float]:
    """Free space on the drive holding `path` (or its nearest existing parent)."""
    p = os.path.abspath(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    try:
        return shutil.disk_usage(p).free / 1e9
    except OSError:
        return None


def documents_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents")


def default_location(last_parent: str, documents: str, docs_free_gb: Optional[float],
                     drives: Iterable[tuple[str, float]]) -> str:
    """Where the New Project dialog starts. Renders live inside the project, so never a nearly full system drive:
    the last folder used; else Documents if its drive has MIN_FREE_GB free; else the fixed drive with the most room."""
    if last_parent and os.path.isdir(last_parent):
        return last_parent
    if docs_free_gb is not None and docs_free_gb >= MIN_FREE_GB:
        return os.path.join(documents, "CorridorKey2 Projects")
    best = max(drives, key=lambda d: d[1], default=None)
    if best is None:
        return os.path.join(documents, "CorridorKey2 Projects")
    return os.path.join(best[0], "CorridorKey2 Projects")


def suggest_name(parent: str, base: str = "Untitled project") -> str:
    name, n = base, 2
    while os.path.exists(os.path.join(parent, name)):
        name, n = f"{base} {n}", n + 1
    return name
