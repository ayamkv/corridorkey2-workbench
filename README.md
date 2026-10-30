# CorridorKey2 Workbench (unofficial)

CorridorKey2 Workbench is a fast native desktop app for [CorridorKey 2.0](https://github.com/nikopueringer/CorridorKey2.0),
Corridor Digital's open-source green/blue-screen keyer. You import clips, set a frame range, render,
and compare the results in a GPU viewer. The layout is inspired by the official Workbench.

Not affiliated with or endorsed by Corridor Digital, whose own paid app is also called Workbench (see corridorkey.com). The model, weights and `infer.py` are theirs; this
app runs the **unmodified** upstream code.

## Features

- **Projects.** A project is a folder: `project.json`, `renders\<clip>\render_NNN\` and `masks\<clip>\`.
  - Paths inside it are stored relative, so the folder can be moved. Clips stay where they are.
  - Switch projects from the top bar (New, Open, Recent, Show in Explorer). The last project reopens on launch.
  - New projects never default to a nearly full system drive.
  - Clips from before projects can be brought into a project once; their old renders stay where they are.
- **Media bin.** Thumbnails, per-clip status (Ready / Held / Queued / % / Done / Error), and drag & drop import of
  videos or EXR/PNG/JPG sequence folders.
- **GPU viewer (OpenGL).** Plate, Composite (foreground over a checkerboard), Matte, Foreground and Checker
  views, in Single, Wipe and Side-by-side layouts.
  - Zoom at the cursor, pan, fit, and pixel-peeping (nearest-neighbour filtering at 200% and above).
  - EXR outputs are shown from scene-linear half floats.
  - Measured real-time playback: 24 fps at 4K and 1080p.
- **Cavalry-style timeline.** An `F` frame field, a numbered ruler, a playhead, and **in/out handles**
  (Entire clip or Custom in/out). The area outside the range is dimmed, and there's a filmstrip and a
  rendered-range marker.
- **Frame ranges are frame-accurate and lossless.** `infer.py` has no start-frame flag, so
  `ckapp/engine/ck_run.py` wraps a few runtime functions and then calls the untouched `infer.main()`.
  - Seeks were verified exact on H.264 (with B-frames), HEVC and ProRes.
  - EXR outputs are numbered by source frame.
  - Hints apply to the in-point.
- **Inspector.** Frame Range, GPU Memory (Auto / Low VRAM / Manual), Alpha Hint (first frame / full hint
  video, strengths, carry), Despill, Image Sequence (linear EXR, fps), Outputs (matte / fg / checker /
  cutout) and Export:
  - EXR half or full float (scene-linear, unclamped).
  - Or video: H.264 / H.265, 10-bit 4:4:4 down to 8-bit 4:2:0, CRF or bitrate, speed preset.
  - Upstream's defaults are marked, and Deliver says in one line exactly what a render writes.
- **VRAM bar** in the status bar and the Inspector, plus an approximate "what fits" line from upstream's
  GPU memory table.
- **Render engine in its own process.**
  - Queue with live progress, ETA, cancel and logs.
  - **Render** starts as soon as the GPU is free. **Add to queue** holds a render until you press Start (or Start all).
  - The queue shows every project's renders. Clicking one from another project opens that project, and a render
    that finishes while another project is open is written into its own project file.
  - Renders keep going after you close the app, and the app picks them up when reopened.
  - Cancel stops the whole process tree, including ffmpeg encoders.
- Each render goes to a new folder: `<project>\renders\<clip>\render_NNN`, or `<chosen folder>\<clip>_ck2\render_NNN`
  if you pick an output folder.

Progress and plans: see [ROADMAP.md](ROADMAP.md).

## Layout on disk

```
D:\CODE\CorridorKey2.0\          upstream clone, unmodified (+ .venv, weights\, vfms\)
D:\CODE\corridorkey2-workbench\  this app (+ its own .venv: no torch)
```

## Install for the studio (no Python needed)

Build a package, send it (or put it on a share), and people run `Setup.bat`:

```
powershell -ExecutionPolicy Bypass -File packaging\make_dist.ps1                         # dist\CorridorKey2 Workbench\
powershell -ExecutionPolicy Bypass -File packaging\make_dist.ps1 -Models <weights> -Zip  # weights inside, plus a .zip
```

`Setup.bat` (`packaging/setup.ps1`) installs everything into the folder it sits in. It sets up a private Python 3.12
with [uv](https://github.com/astral-sh/uv), downloads upstream CorridorKey at the tested commit, installs CUDA PyTorch,
gets ffmpeg if it isn't on PATH, then places the weights. For the weights, people pick **download** (about 5 GB) or
**a folder they already have**. That folder can be one holding `corridorkey_v2.safetensors`, or a CorridorKey 2.0
folder with `weights\` and `vfms\`. Files on the same drive are hard-linked, and anything missing is downloaded. A
`models\` folder shipped in the package is used automatically. Everything is pinned and checksummed where upstream
allows it. Running setup again skips finished steps and repairs broken ones. See `packaging/INSTALL.txt` (shipped as
"READ ME FIRST.txt").

## Setup (development)

1. Clone upstream and set up its venv as its README says: CUDA PyTorch, `requirements.txt`,
   `scripts/download_weights.py`.
2. Create this app's venv:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
3. Run `run_app.bat`, or `.venv\Scripts\python -m ckapp [clips...]`.

Paths are detected automatically: upstream is expected next to this folder. If yours differ, change them
in **Settings**: the CorridorKey folder, its python, the cache/staging folder and ffmpeg.

## Keyboard

| Key | Action |
|---|---|
| Space | Play / pause |
| ← / → (Shift: ×10) | Step frames |
| Home / End | Go to the in / out point |
| I / O | Set in / out at the playhead |
| Alt+I / Alt+O | Clear in / out |
| 1 / 2 / 3 | Single / Wipe / Side by side |
| F, or double-click | Fit the view |
| Timeline: scroll / middle-drag | Zoom / pan (stays on the clip); right-click for Fit to view, Zoom to in/out |
| Timeline: drag the in/out bar | Slide the whole range |
| Right-click the top bar | Icons and labels, or icons only |
| Ctrl+O | Import |
| Ctrl+R | Render |
| Ctrl+Shift+R | Add to queue (held until Start) |
| Ctrl+Shift+N / Ctrl+Shift+O | New project / Open project |
| Delete | Remove the clip (in the media bin) |

## Architecture

- **`ckapp/engine/`** has no Qt and no torch.
  - `jobs.py`: the job spec, the infer command line, the progress parser and a single-GPU queue.
  - `server.py`: the HTTP API (REST plus Server-Sent Events). A token is always required.
  - `ck_run.py`: runs in the CorridorKey venv.
  - The engine writes `engine.json` (port and token) to `%APPDATA%\CorridorKey2Workbench` and exits after
    10 idle minutes.
  - LAN hosting is a later phase. `python -m ckapp.engine --lan` already binds `0.0.0.0` behind the same
    token, but uploading and downloading files to remote apps doesn't exist yet.
- **`ckapp/app/`**: PySide6.
  - `viewer.py`: the GL viewer.
  - `timeline.py`
  - `frames.py`: one decode thread per file, plus a shared LRU cache.
  - `media.py`: frame numbering identical to upstream.
  - `project.py`: the project folder and file, recent projects, where new projects go (no Qt).
  - `inspector.py`, `panels.py`, `start.py`, `main_window.py`

## Tests

```
.venv\Scripts\python -m pytest tests -q                    # engine, app logic, headless UI (no GPU)
D:\CODE\CorridorKey2.0\.venv\Scripts\python tests\test_seek_accuracy.py
.venv\Scripts\python tests\smoke_app.py <clip> <shots dir> --render --range 4 15 --layout wipe
```

`smoke_app.py` drives the real app on the real GPU and saves screenshots.

## Credits

- [Geist and Geist Mono](https://github.com/vercel/geist-font) by Vercel, SIL Open Font License 1.1
  (`ckapp/app/assets/fonts/OFL-Geist.txt`).
- Icons: the Workbench set (drawn for this app), plus [Lucide](https://lucide.dev) (ISC license) for folder-open, plus, x,
  trash-2, scan, circle-alert, hard-drive and cpu.

## License

CorridorKey is under a modified CC BY-NC-SA 4.0 license. Anything built on it that you release must
stay free, keep the CorridorKey name and carry the same license. See upstream `LICENSE`.
