"""Stands in for ck_run.py in tests: prints the runtime's progress lines and writes
dummy outputs. Usage: fake_ck_run.py <output_dir> <mode> [pidfile]
mode: ok | fail | hang (hang starts a grandchild and records its pid in pidfile)."""
import os
import subprocess
import sys
import time

out_dir, mode = sys.argv[1], sys.argv[2]
lines = [
    "Loading CorridorKey v2 runtime weights: weights/corridorkey_v2.safetensors",
    "  loaded weights; omitted frozen foundation tensors=982",
    "  probed 24 frames @ 1280x768 (native 1280x720, fps 24.00, start=0, pad=(0, 0, 24, 24))",
    "  range: frames 5-14 (10 frames)",
    "    RVM continuous prepass: T=10, chunk=8, input=320x192, grid=20x12",
    "    frozen VFM prepass: T=10, grid=20x12, chunk=4",
    "    Hann stage1: chunk=8, stride=4, windows=2, baton_grid=80x48",
    "      window 1/2 [0:8]",
    "      window 2/2 [4:10]",
]
for line in lines:
    print(line, flush=True)
    time.sleep(0.02)
if mode == "fail":
    print("RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB", flush=True)
    sys.exit(1)
if mode == "hang":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(sys.argv[3], "w") as f:
        f.write(str(child.pid))
    print("  [ck] written 2/10", flush=True)
    time.sleep(120)
for k in (4, 8, 10):
    print(f"  [ck] written {k}/10", flush=True)
os.makedirs(out_dir, exist_ok=True)
for name in ("clip_alpha.mp4", "clip_fg.mp4", "clip_checker_comp_despill050.mp4", "clip_settings.txt"):
    open(os.path.join(out_dir, name), "w").close()
print("  wrote 3 output video(s) for clip (10 frames @ 1280x720)", flush=True)
