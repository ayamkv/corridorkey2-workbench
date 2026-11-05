"""Run upstream CorridorKey ``infer.py`` with an optional frame range.

This script runs inside the CorridorKey venv (it imports torch through
``infer``). It changes no upstream files: it swaps a few names inside
``corridorkey.runtime`` / ``corridorkey.video_io`` for range-aware wrappers,
then calls the unmodified ``infer.main()``.

    python ck_run.py --ck-root D:\\CODE\\CorridorKey2.0 [--frame-in N] [--frame-out M] -- <infer.py args>

It also prints ``[ck] written k/T`` as frames are written (upstream is silent
during stage 2), so callers can show real progress.

``--frame-in`` / ``--frame-out`` are 0-based and inclusive. Without them the
run is the same as ``python infer.py <args>``. With them:

* video input starts decoding at ``in`` (upstream already seeks via
  ``CAP_PROP_POS_FRAMES`` for its ``middle`` start mode) and stops after ``out``;
* frame-folder input processes files ``[in..out]`` of the sorted listing;
* hint videos and hint frame folders are offset by the same ``in``;
* EXR outputs are numbered from ``in`` so they line up with the source.

Do not pass ``--num_frames`` / ``--start_mode`` together with a range.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    if "--" in argv:
        split = argv.index("--")
        ours, rest = argv[:split], argv[split + 1:]
    else:
        ours, rest = argv, []
    p = argparse.ArgumentParser(prog="ck_run.py")
    p.add_argument("--ck-root", required=True, help="CorridorKey repo folder (contains infer.py)")
    p.add_argument("--frame-in", type=int, default=None, help="first frame to process (0-based)")
    p.add_argument("--frame-out", type=int, default=None, help="last frame to process (inclusive)")
    args = p.parse_args(ours)
    if args.frame_in is not None and args.frame_in < 0:
        p.error("--frame-in must be >= 0")
    if args.frame_out is not None and args.frame_out < (args.frame_in or 0):
        p.error("--frame-out must be >= --frame-in")
    if (args.frame_in is not None or args.frame_out is not None) and any(
            a in rest for a in ("--num_frames", "--start_mode")):
        p.error("--num_frames / --start_mode cannot be combined with a frame range")
    return args, rest


def _clamp_range(total: int, frame_in: int | None, frame_out: int | None) -> tuple[int, int]:
    if total <= 0:
        raise RuntimeError("input has no frames")
    first = frame_in or 0
    last = total - 1 if frame_out is None else min(frame_out, total - 1)
    if first > total - 1:
        raise ValueError(f"--frame-in {first} is past the last frame ({total - 1})")
    return first, last


def unicode_imread(orig):
    """cv2.imread can't open non-ASCII paths on Windows (a clip folder like "tést" or an emoji name), and upstream
    reads hint images and frame folders with it. Fall back to bytes + imdecode only when the original fails, so
    ASCII paths behave exactly as before."""
    def imread(path, flags=None, *rest):
        img = orig(path, *(() if flags is None else (flags,)), *rest)
        if img is not None:
            return img
        import numpy as np
        try:
            buf = np.fromfile(str(path), np.uint8)
        except OSError:
            return None                              # really missing: same answer as cv2.imread
        import cv2
        return cv2.imdecode(buf, cv2.IMREAD_COLOR if flags is None else flags)
    imread.ck_unicode = True
    return imread


def install_hooks(frame_in: int | None, frame_out: int | None) -> None:
    """Patch the runtime for the next run_inference().

    Always: the first output writer prints ``[ck] written k/T`` per batch, because
    upstream is silent while stage 2 writes frames, and images (hints, frame folders) open from non-ASCII paths. With a range: the run covers
    ``[frame_in..frame_out]`` and EXR frames are numbered from ``frame_in``.
    """
    import cv2
    from corridorkey import runtime, video_io

    if not getattr(cv2.imread, "ck_unicode", False):
        cv2.imread = unicode_imread(cv2.imread)

    orig_probe_video = runtime.probe_video_meta
    orig_probe_dir = runtime.probe_frame_dir_meta
    orig_hint_dir_reader = video_io.SequentialHintFrameDirWindowReader
    orig_exr_writer = runtime.ExrSequenceWriter
    orig_video_writer = runtime.ThreadedVideoWriter
    ranged = frame_in is not None or frame_out is not None
    state = {"first": 0, "total": 0, "reporter": None}

    def _apply_range(meta, total):
        first, last = _clamp_range(total, frame_in, frame_out)
        state["first"] = first
        print(f"  range: frames {first}-{last} ({last - first + 1} frames)", flush=True)
        return first, last

    def probe_video_meta(path, **kw):
        if ranged:
            kw["num_frames"], kw["start_mode"] = -1, "begin"
        meta = orig_probe_video(path, **kw)
        if ranged:
            first, last = _apply_range(meta, int(meta["num_frames"]))
            meta["start_frame"], meta["num_frames"] = first, last - first + 1
        state["total"] = int(meta["num_frames"])
        return meta

    def probe_frame_dir_meta(path, **kw):
        if ranged:
            kw["num_frames"] = -1
        meta = orig_probe_dir(path, **kw)
        if ranged:
            first, last = _apply_range(meta, len(meta["frame_paths"]))
            meta["frame_paths"] = meta["frame_paths"][first:last + 1]
            meta["num_frames"] = len(meta["frame_paths"])
            meta["start_frame"] = first      # only read by the hint readers for frame-dir input
        state["total"] = int(meta["num_frames"])
        return meta

    class HintFrameDirReader(orig_hint_dir_reader):
        def __init__(self, hint_dir_path, meta):
            super().__init__(hint_dir_path, meta)
            first = int(meta.get("start_frame", 0))
            if len(self.paths) < first + int(meta["num_frames"]):
                raise RuntimeError(
                    f"{hint_dir_path}: only {len(self.paths)} hint frames, range needs "
                    f"{first + int(meta['num_frames'])}")
            self.paths = self.paths[first:]

    def _reporting(cls):
        class Reporting(cls):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self._ck_written = 0
                if state["reporter"] is None:      # writers are created in sorted output order
                    state["reporter"] = self

            def write_many(self, frames):
                super().write_many(frames)
                self._ck_written += len(frames)
                if state["reporter"] is self:
                    print(f"  [ck] written {self._ck_written}/{state['total']}", flush=True)
        return Reporting

    class OffsetExrWriter(_reporting(orig_exr_writer)):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.frame_idx = state["first"]

    runtime.probe_video_meta = probe_video_meta
    runtime.probe_frame_dir_meta = probe_frame_dir_meta
    runtime.ExrSequenceWriter = OffsetExrWriter
    runtime.ThreadedVideoWriter = _reporting(orig_video_writer)
    if ranged:
        video_io.SequentialHintFrameDirWindowReader = HintFrameDirReader


def main(argv: list[str] | None = None) -> None:
    args, rest = _parse(sys.argv[1:] if argv is None else argv)
    root = Path(args.ck_root).resolve()
    if not (root / "infer.py").is_file():
        raise SystemExit(f"infer.py not found in {root}")
    sys.path.insert(0, str(root))
    import infer  # upstream entry point; imports torch

    install_hooks(args.frame_in, args.frame_out)
    sys.argv = [str(root / "infer.py"), *rest]
    infer.main()


if __name__ == "__main__":
    main()
