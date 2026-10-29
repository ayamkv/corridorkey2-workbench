"""Clips, their per-clip settings and renders, and the saved session. Qt-free."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

from ..engine.jobs import JobSpec
from .media import ClipInfo


@dataclass
class ClipSettings:
    range_mode: str = "all"           # all | custom
    frame_in: int = 0
    frame_out: int = -1               # -1 = last frame
    hint_mode: str = "none"           # none | first | video
    hint_path: str = ""
    hint_quality: float = 0.95
    carry_hint: bool = True
    carry_hint_quality: float = 0.95
    despill: float = 0.5
    outputs: list = field(default_factory=lambda: ["alpha", "fg", "checker"])
    output_format: str = "video"      # video | exr
    exr_dtype: str = "half"
    cutout_linear: bool = False
    frame_dir_linear: bool = False
    frame_dir_fps: float = 24.0
    memory: str = "auto"              # auto | low | manual
    manual_low_vram: bool = True
    hann_chunk: int = 24
    hann_stride: int = 12
    output_root: str = ""             # '' = next to the clip
    video_codec: str = "libx264"      # video encoding: defaults are infer.py's own
    pix_fmt: str = "yuv444p10le"
    rate_mode: str = "crf"            # crf | bitrate
    crf: int = 12
    bitrate_mbps: float = 40.0
    preset: str = "medium"

    @classmethod
    def from_dict(cls, d: dict) -> "ClipSettings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


CODEC_NAMES = {"libx264": "H.264", "libx265": "H.265"}
PIX_NAMES = {"yuv444p10le": "10-bit 4:4:4", "yuv422p10le": "10-bit 4:2:2", "yuv420p10le": "10-bit 4:2:0",
             "yuv420p": "8-bit 4:2:0"}
VIDEO_DEFAULTS = {"video_codec": "libx264", "pix_fmt": "yuv444p10le", "rate_mode": "crf", "crf": 12,
                  "preset": "medium"}


def describe_export(s: "ClipSettings") -> str:
    """One line saying exactly what the render writes."""
    if s.output_format == "exr":
        return f"OpenEXR {'half' if s.exr_dtype == 'half' else 'full'} float, scene-linear, one folder per output"
    rate = f"{s.bitrate_mbps:g} Mb/s" if s.rate_mode == "bitrate" else f"CRF {s.crf}"
    text = f"{CODEC_NAMES.get(s.video_codec, s.video_codec)} {PIX_NAMES.get(s.pix_fmt, s.pix_fmt)}, {rate}, .mp4"
    if "cutout" in s.outputs:
        text += "; cutout ProRes 4444 + alpha, .mov"
    return text


@dataclass
class Render:
    job_id: str
    out_dir: str
    frame_in: int
    frame_out: int
    output_format: str
    status: str = "queued"
    outputs: dict = field(default_factory=dict)   # key -> path
    label: str = ""


@dataclass
class Clip:
    path: str
    kind: str
    frames: int
    fps: float
    width: int
    height: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    settings: ClipSettings = field(default_factory=ClipSettings)
    renders: list = field(default_factory=list)   # [Render], oldest first
    error: str = ""

    @classmethod
    def from_info(cls, info: ClipInfo) -> "Clip":
        c = cls(info.path, info.kind, info.frames, info.fps, info.width, info.height)
        c.settings.frame_dir_fps = info.fps
        return c

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip("/\\"))

    @property
    def stem(self) -> str:
        return os.path.splitext(self.name)[0] if self.kind == "video" else self.name

    @property
    def last_frame(self) -> int:
        return max(0, self.frames - 1)

    def frame_range(self) -> tuple[int, int]:
        s = self.settings
        if s.range_mode != "custom":
            return 0, self.last_frame
        first = min(max(0, s.frame_in), self.last_frame)
        last = self.last_frame if s.frame_out < 0 else min(max(first, s.frame_out), self.last_frame)
        return first, last

    @property
    def label(self) -> str:
        return f"{self.width}×{self.height}   {self.fps:g} fps   {self.frames} f"

    def latest_render(self, done_only: bool = True) -> Optional[Render]:
        for r in reversed(self.renders):
            if not done_only or r.status == "done":
                return r
        return None

    def render_root(self) -> str:
        base = self.settings.output_root or os.path.dirname(self.path.rstrip("/\\"))
        return os.path.join(base, f"{self.stem}_ck2")

    def next_render_dir(self) -> tuple[str, str]:
        root = self.render_root()
        n = 1
        while os.path.exists(os.path.join(root, f"render_{n:03d}")) or any(
                os.path.normcase(r.out_dir) == os.path.normcase(os.path.join(root, f"render_{n:03d}"))
                for r in self.renders):
            n += 1
        return os.path.join(root, f"render_{n:03d}"), f"Render {n}"

    def to_spec(self, out_dir: str) -> JobSpec:
        s = self.settings
        first, last = self.frame_range()
        whole = first == 0 and last == self.last_frame
        return JobSpec(
            input=self.path, output_dir=out_dir, name=self.name,
            frame_in=None if whole else first, frame_out=None if whole else last,
            hint_mode=s.hint_mode if s.hint_path else "none", hint_path=s.hint_path,
            hint_quality=s.hint_quality, carry_hint=s.carry_hint, carry_hint_quality=s.carry_hint_quality,
            outputs=list(s.outputs), despill=s.despill, output_format=s.output_format,
            exr_dtype=s.exr_dtype, cutout_linear=s.cutout_linear,
            frame_dir_linear=s.frame_dir_linear, frame_dir_fps=s.frame_dir_fps,
            auto_vram=s.memory == "auto",
            low_vram=s.memory == "low" or (s.memory == "manual" and s.manual_low_vram),
            hann_chunk=s.hann_chunk, hann_stride=s.hann_stride,
            video_codec=s.video_codec, pix_fmt=s.pix_fmt, crf=s.crf, preset=s.preset,
            bitrate=f"{s.bitrate_mbps:g}M" if s.rate_mode == "bitrate" else "")


class Session:
    def __init__(self, path: Path):
        self.path = path
        self.clips: list[Clip] = []

    def find(self, clip_id: str) -> Optional[Clip]:
        return next((c for c in self.clips if c.id == clip_id), None)

    def find_job(self, job_id: str) -> tuple[Optional[Clip], Optional[Render]]:
        for c in self.clips:
            for r in c.renders:
                if r.job_id == job_id:
                    return c, r
        return None, None

    def save(self) -> None:
        data = {"version": 1, "clips": [asdict(c) for c in self.clips]}
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in data.get("clips", []):
            try:
                settings = ClipSettings.from_dict(d.pop("settings", {}))
                renders = [Render(**r) for r in d.pop("renders", [])]
                known = {f.name for f in fields(Clip)}
                clip = Clip(**{k: v for k, v in d.items() if k in known})
                clip.settings, clip.renders = settings, renders
            except TypeError:
                continue
            if not os.path.exists(clip.path):
                clip.error = "missing"
            self.clips.append(clip)
