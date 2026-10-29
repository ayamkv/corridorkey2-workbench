"""Checks that OpenCV's CAP_PROP_POS_FRAMES seek (what upstream and ck_run.py rely on
for in-points) lands on the exact frame for common delivery/camera codecs.

Run with the CorridorKey venv's python (needs cv2 + ffmpeg on PATH):
    D:\\CODE\\CorridorKey2.0\\.venv\\Scripts\\python.exe tests\\test_seek_accuracy.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

FRAMES = 300
INS = [0, 1, 2, 47, 48, 49, 123, 250, 251, 299]
CODECS = {
    "h264_bframes.mp4": ["-c:v", "libx264", "-g", "48", "-bf", "3", "-pix_fmt", "yuv420p"],
    "hevc.mp4": ["-c:v", "libx265", "-x265-params", "keyint=48:bframes=4:log-level=error", "-pix_fmt", "yuv420p"],
    "prores.mov": ["-c:v", "prores_ks", "-profile:v", "3"],
}


def make_clip(path: Path, codec_args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc2=s=320x180:r=24:d={FRAMES / 24}", *codec_args, str(path)], check=True)


def sequential(path: Path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    out = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(f)
    cap.release()
    return out


def seek_read(path: Path, idx: int) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(path))
    if idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, f = cap.read()
    cap.release()
    return f if ok else None


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as td:
        for name, args in CODECS.items():
            path = Path(td) / name
            make_clip(path, args)
            ref = sequential(path)
            if len(ref) != FRAMES:
                print(f"FAIL {name}: sequential decode gave {len(ref)} frames, expected {FRAMES}")
                failures += 1
                continue
            bad = []
            for i in INS:
                f = seek_read(path, i)
                if f is None or not np.array_equal(f, ref[i]):
                    # which frame did we actually get?
                    got = next((j for j, r in enumerate(ref) if f is not None and np.array_equal(f, r)), None)
                    bad.append(f"{i}->{got}")
            print(f"{'ok  ' if not bad else 'FAIL'} {name}: {len(INS)} seeks" + (f"  wrong: {', '.join(bad)}" if bad else ""))
            failures += bool(bad)
    print("ALL SEEKS FRAME-ACCURATE" if not failures else f"{failures} codec(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
