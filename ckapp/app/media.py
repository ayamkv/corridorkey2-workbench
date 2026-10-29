"""Clip probing and frame decoding. Qt-free.

Frame numbering follows upstream exactly (``CAP_PROP_FRAME_COUNT`` for video,
``sorted(glob(exr/png/jpg/jpeg))`` for folders), so frame N here is frame N in
infer.py and in ck_run.py ranges.
"""
from __future__ import annotations

import glob
import os

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")   # must be set before cv2 is imported

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

SEQ_EXTS = ("*.exr", "*.png", "*.jpg", "*.jpeg")          # what upstream's frame_paths() accepts
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".mxf", ".m4v", ".webm")


def frame_paths(frame_dir: str) -> list[str]:
    """Same listing as corridorkey.video_io.frame_paths()."""
    paths: list[str] = []
    for ext in SEQ_EXTS:
        paths.extend(glob.glob(os.path.join(frame_dir, ext)))
    return sorted(paths)


@dataclass
class Frame:
    # HxWxC, C in (1, 3), uint8 (display-coded) or float16. 3-channel data stays in OpenCV's BGR
    # order: the viewer uploads it as GL_BGR, which saves a full-frame copy per frame (4x faster at 4K).
    data: np.ndarray
    linear: bool = False    # float data in scene-linear (shown through an sRGB encode)

    @property
    def nbytes(self) -> int:
        return self.data.nbytes

    @property
    def size(self) -> tuple[int, int]:
        return self.data.shape[1], self.data.shape[0]


@dataclass
class ClipInfo:
    path: str
    kind: str               # video | sequence
    frames: int
    fps: float
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.frames} frames, {self.width}×{self.height}, {self.fps:g} fps"


def is_media(path: str) -> bool:
    if os.path.isdir(path):
        return bool(frame_paths(path))
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def probe(path: str, seq_fps: float = 24.0) -> ClipInfo:
    if os.path.isdir(path):
        paths = frame_paths(path)
        if not paths:
            raise ValueError(f"no EXR/PNG/JPG frames in {path}")
        img = _imread(paths[0])
        if img is None:
            raise ValueError(f"cannot read {paths[0]}")
        return ClipInfo(path, "sequence", len(paths), seq_fps, img.shape[1], img.shape[0])
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise ValueError(f"cannot open video {path}")
        return ClipInfo(path, "video", int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                        float(cap.get(cv2.CAP_PROP_FPS) or 24.0),
                        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    finally:
        cap.release()


def _imread(path: str) -> Optional[np.ndarray]:
    # np.fromfile + imdecode survives non-ASCII Windows paths; cv2.imread does not
    try:
        buf = np.fromfile(path, np.uint8)
    except OSError:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH)


def to_frame(img: np.ndarray, *, linear: bool = False) -> Frame:
    """BGR(A)/gray from OpenCV -> Frame (BGR order kept, uint8 or float16)."""
    if img.ndim == 2:
        img = img[..., None]
    if img.shape[2] == 4:
        img = img[..., :3]
    if img.dtype == np.uint8:
        return Frame(np.ascontiguousarray(img), False)
    if img.dtype == np.uint16:
        return Frame(np.ascontiguousarray((img >> 8).astype(np.uint8)), False)
    data = np.ascontiguousarray(np.clip(img, -65504, 65504).astype(np.float16))
    return Frame(data, linear)


class VideoSource:
    """Sequential reads are cheap; anything else seeks (frame-accurate, see tests)."""

    def __init__(self, path: str, *, gray: bool = False):
        self.path, self.gray = path, gray
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise ValueError(f"cannot open video {path}")
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.next = 0

    def read(self, i: int) -> Optional[Frame]:
        if not 0 <= i < self.count:
            return None
        if i != self.next:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, img = self.cap.read()
        if not ok:
            self.next = -1
            return None
        self.next = i + 1
        if self.gray:                     # mattes: keep one channel (a third of the memory)
            img = img[..., 1]
        return to_frame(img)

    def close(self) -> None:
        self.cap.release()


class SequenceSource:
    def __init__(self, path: str, *, linear: bool = False, gray: bool = False):
        self.path, self.linear, self.gray = path, linear, gray
        self.paths = frame_paths(path)
        self.count = len(self.paths)

    def read(self, i: int) -> Optional[Frame]:
        if not 0 <= i < self.count:
            return None
        img = _imread(self.paths[i])
        if img is None:
            return None
        if self.gray and img.ndim == 3:
            img = img[..., 1]
        return to_frame(img, linear=self.linear and self.paths[i].lower().endswith(".exr"))

    def close(self) -> None:
        pass


class ExrOutputSource(SequenceSource):
    """An infer.py EXR output folder. Files are numbered by source frame (ck_run.py
    numbers them from the in-point), so read(i) takes the *source* frame number."""

    def __init__(self, path: str, *, gray: bool = False):
        super().__init__(path, linear=True, gray=gray)
        self.by_frame = {}
        for p in self.paths:
            stem = os.path.splitext(os.path.basename(p))[0]
            num = stem.rsplit("_", 1)[-1]
            if num.isdigit():
                self.by_frame[int(num)] = p

    def read(self, i: int) -> Optional[Frame]:
        p = self.by_frame.get(i)
        if p is None:
            return None
        img = _imread(p)
        if img is None:
            return None
        if self.gray and img.ndim == 3:
            img = img[..., 1]
        return to_frame(img, linear=True)


def open_source(path: str, *, linear: bool = False, gray: bool = False):
    if os.path.isdir(path):
        if path.rstrip("/\\").lower().endswith("_exr"):
            return ExrOutputSource(path, gray=gray)
        return SequenceSource(path, linear=linear, gray=gray)
    return VideoSource(path, gray=gray)


def thumbnail(path: str, *, at: float = 0.5, width: int = 192, linear: bool = False) -> Optional[np.ndarray]:
    """uint8 RGB thumbnail of the frame at `at` (0..1) of the clip, or None."""
    try:
        src = open_source(path, linear=linear)
    except ValueError:
        return None
    try:
        fr = src.read(int(max(0, src.count - 1) * at))
    finally:
        src.close()
    if fr is None:
        return None
    return to_display_u8(fr, width)


def to_display_u8(fr: Frame, width: int) -> np.ndarray:
    """Small display-referred uint8 RGB copy (thumbnails, filmstrip)."""
    data = fr.data
    if data.dtype != np.uint8:
        x = np.clip(data.astype(np.float32), 0, None)
        if fr.linear:
            x = np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
        data = (np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8)
    h = max(1, round(data.shape[0] * width / data.shape[1]))
    small = cv2.resize(data, (width, h), interpolation=cv2.INTER_AREA)
    if small.ndim == 2:
        small = small[..., None]
    if small.shape[2] == 1:
        return np.ascontiguousarray(np.repeat(small, 3, axis=2))
    return np.ascontiguousarray(small[..., ::-1])          # BGR -> RGB for QImage
