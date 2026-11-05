# CorridorKey 2.0: native desktop UI plan

> Progress is tracked as checklists in **ROADMAP.md**. This file records design decisions.
> Names: OpenDeck (2026-10-23), then **CorridorKey2 Workbench** (2026-10-29; repo and folder `corridorkey2-workbench`). The license requires keeping the CorridorKey name.
> Phase 2.1 (polish) is done. The design direction:
> - slate amber `#F0B429` on near-black `#161718` / `#121214` / `#0F1010` (Phase 2.2)
> - Geist (bundled) with tabular figures; the Workbench icon set plus Lucide
> - the frame readout as the one bold element
>
> Phase 3 (projects) and Phase 4 (click to mask with SAM 2.1 tiny) are done on branch `phase-3-4`. Next is Phase 5 (LAN hosting).

## Context
CorridorKey 2.0 (github.com/nikopueringer/CorridorKey2.0) is Corridor Digital's open-source ML green/blue-screen keyer. The repo has no GUI, only `infer.py`, a terminal Q&A script and a drag-and-drop `.bat`. The official Workbench app is a separate paid product.

The user wants a fast, native desktop app laid out like the official Workbench (similar, not a copy, with no Corridor branding). Optionally, one PC should be able to host the GPU for other PCs on the LAN.

Decisions made:
- **Stack:** PySide6 + OpenGL viewer. The user rejected Gradio's look. Rust/GPUI and Tauri were weighed and dropped: inference is about 99% of the wait, and the model needs Python anyway.
- **LAN hosting:** the engine/app split is designed in now; the LAN toggle is enabled in a later phase.
- **First step is an audit of sceledrus/CorridorKey2.0-GUI**, a PySide6 app that wraps `infer.py`. It's at v0.3.0 with 21 commits. It's a **test drive only**. We clone it to try it out; we don't fork it.
- **Our own app:** a separate repo (`D:\CODE\corridorkey2-workbench`) that calls an **unmodified upstream clone** (`D:\CODE\CorridorKey2.0`) through `infer.py`. That way upstream updates are just a `git pull`. Fork upstream only if we ever need to patch the engine. We may borrow ideas or code from sceledrus; its license (CC BY-NC-SA) allows that with attribution and the same license.

## Audit summary (done 2026-10-21)
**`infer.py` interface:**
- Main flags:
  - `--input` / `--output_dir`
  - `--hint_first_frame` / `--hint_video` / `--no_carry_hint`
  - `--hint_quality`, `--carry_hint_quality`
  - `--outputs alpha fg checker cutout`
  - `--despill_strength`
  - `--output_format video|exr`, `--exr_dtype`
  - `--low_vram`, `--hann_chunk` / `--hann_stride`
  - `--num_frames`, `--start_mode`
  - `--frame_dir_linear`, `--cutout_linear`
  - `--linear_brightness` / `--linear_contrast`
- Output files are `{clip}_alpha.mp4`, `_fg.mp4`, `_checker_comp_despill050.mp4`, `_cutout.mov`, `_settings.txt`, or `{clip}_{x}_exr/` folders.
- Progress comes from plain prints. Parse `window i/N`, `Auto VRAM: ...` and `wrote N output video(s)`.
- `run_interactive.py` is the reference pattern: `subprocess.Popen([python, infer.py, ...])` without a shell, with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` set.

**Security:**
- ✅ No shell, eval or `trust_remote_code`. Runtime is offline and loads safetensors.
- ⚠ The CorridorKey weights download is unpinned.
- ⚠ MoGe `model.pt` is a pickle checkpoint.
- ⚠ Ctrl+C in `run_interactive.py` orphans the child process.

**License:** Modified CC BY-NC-SA 4.0.
- Use is free, including on commercial footage.
- No selling and no paid API.
- Derivatives must be free, keep the license and keep the CorridorKey name.

**Controls the open CLI does not have** (seen in the Workbench screenshot): Despill Color, Despill Method, and "Time Awareness" beyond the hann window. Verify during the sceledrus audit and leave out anything unsupported.

## Machine fit
| Item | Status |
|---|---|
| GPU | RTX 3050 Ti Laptop, **4 GB**, the bare minimum. Target 720p and use low-VRAM mode by default. 1080p is borderline. |
| Python | 3.12.4 |
| ffmpeg | on PATH |
| git | ✅ |
| D: free | about 66 GB |
| Weights | Already at `C:\Users\itk\Downloads\CORRIDOR KEY 2 WEIGHTS\`. Verified: `corridorkey_v2.safetensors` is 2,661,698,720 B with 738 tensors and the correct format tag; `foundation_stats.safetensors` is 18,864 B. |

## Phase 0: audit and install sceledrus/CorridorKey2.0-GUI (current step: the user wants to test it)
**Remote audit so far (2026-10-23):**
- Fork = upstream `485f5e9` (upstream's current head) + 16 commits.
- **All engine files are byte-identical to upstream:** `corridorkey/*`, `infer.py`, `scripts/*`, `requirements.txt`, `run_interactive.py`. The blob SHAs match.
- Fork adds:
  - `ck2_gui/`: about 9k lines of PySide6
  - `run_gui.py`
  - `launcher/launcher.c`: native launcher that finds a venv's python and runs `pythonw run_gui.py`; its header says no network or registry use
  - `build_exe.py`, tests, CI
- `ck2_gui/runner.py` runs `infer.py` in a `QProcess` with the HF offline env vars. Cancel does terminate, then kill after 4 s. `GpuMonitor` polls `nvidia-smi` every 2 s.
- Release v0.3.0 (pre-release): the zips are built in CI from tagged source, with no secrets and with SHA256SUMS. The exes are unsigned, so **run from source and skip the prebuilt exe**.
- Viewer is `QPainter` + 8-bit `QImage` on a `QWidget`. No GL; EXR is shown as 8-bit. This is the main gap against our performance goal.

**Progress (2026-10-23):**
- Steps 1–4 are DONE:
  - Cloned at `137a80c`.
  - Local audit PASSED:
    - no network; no shell; the only processes it starts are `infer.py`, `nvidia-smi`, a torch check and ffmpeg (custom sound only)
    - `build_command` maps 1:1 to `infer.py` flags
    - Minor issues: Stop kills only `infer.py` (its ffmpeg child can be left behind), and the viewer decodes frames on the UI thread in 8-bit.
  - The venv has torch 2.9.1+cu128 with CUDA available (3050 Ti, bf16 OK), plus PySide6 6.12, numpy 1.26.4, transformers 4.57.6 and pytest.
  - Weights are copied with sizes verified.
- **C: has only 3.8 GB free.** The first pip install failed with ENOSPC, so TMP, TEMP and PIP_CACHE_DIR now point to `D:\CODE\_tmp`.
- **Remaining:** steps 5–8, below. Set `HF_HOME=D:\CODE\_tmp\hf` and TMP/TEMP to D: for the weights download. In the GUI, set the temp/cache dir to `D:\CODE\_tmp\ck2` so low-VRAM staging doesn't fill C:.

**Local steps:**
1. `git clone https://github.com/sceledrus/CorridorKey2.0-GUI D:\CODE\CorridorKey2.0-GUI` and record the commit SHA.
2. Local audit:
   - Grep `ck2_gui/`, `run_gui.py` and `build_exe.py` for `subprocess|QProcess|os.system|eval|exec|pickle|urllib|requests|http|socket|winreg|shell=True`, and review each hit.
   - Read `runner.py` and `params.py` (command construction), `media.py` (decoding, temp files) and `exports.py` (Nuke/AE script writing).
3. Create the venv `D:\CODE\CorridorKey2.0-GUI\.venv`, which the launcher and bat file auto-detect, using Python 3.12.4:
   - `pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128`
   - `pip install -r requirements.txt -r requirements-gui.txt`
4. Copy `corridorkey_v2.safetensors` and `foundation_stats.safetensors` from `C:\Users\itk\Downloads\CORRIDOR KEY 2 WEIGHTS\` into `weights\`.
5. Run `python scripts/download_weights.py --skip_corridorkey`. This downloads about 2.4 GB (C-RADIOv4, MoGe-2, RVM, revision-pinned).
6. Checks:
   - `python -c "import torch; print(torch.cuda.is_available())"`
   - `python run_gui.py --check`
   - `python run_gui.py --selftest`
   - `pytest tests -q` (offscreen, uses `fake_infer.py`)
7. CLI smoke test: `infer.py` on a short clip with `--num_frames 10 --low_vram`. If the user has no clip, generate a 720p green test clip with ffmpeg.
8. Hand over: the user launches via `CorridorKey_GUI.bat` or `python run_gui.py` and tests it. In the GUI, set GPU memory to Low.

**After the user tests it:** build our own app (Phase 2) against the unmodified upstream clone, borrowing whatever worked well in sceledrus. The test clone can be deleted afterwards. Its `.venv` can also be reused if we point our app at it.

## Phase 1: environment + engine runner (DONE 2026-10-23)
- **Upstream clone:** `D:\CODE\CorridorKey2.0` at `485f5e9`. `git status` is clean.
  - `.venv` has torch 2.9.1+cu128 and `requirements.txt`; CUDA OK. It installed from the pip cache on D:.
  - `weights\` and `vfms\` are **hardlinked** from the sceledrus clone, so they take no extra disk. Don't edit those files in place.
- **Project repo:** `D:\CODE\corridorkey2-workbench`, `git init`'d on `main`, no commits yet.
- **`ckapp/engine/ck_run.py`:** the in/out wrapper, which runs in the upstream venv. Usage: `ck_run.py --ck-root <repo> [--frame-in N --frame-out M] -- <infer.py args>`. It wraps these names in `corridorkey.runtime` / `video_io`, then calls the unmodified `infer.main()`:
  - `probe_video_meta` sets `start_frame` / `num_frames`.
  - `probe_frame_dir_meta` slices `frame_paths` and sets `start_frame` (used by the hint readers).
  - `SequentialHintFrameDirWindowReader` is offset by `in`.
  - `ExrSequenceWriter` numbers frames from `in`.
  - No hardlink folders are needed.
- **`tests/test_seek_accuracy.py`:** 30 seeks across H.264 with B-frames, HEVC and ProRes, all frame-exact.
- **End-to-end test:** frames 5–14 of the 720p test clip rendered as EXR in 39 s. Files are named `alpha_000005..14`. The box positions match source frames 5, 8, 11 and 14 to within 2 px, where one frame off would be 8 px.

## Phase 2 status: DONE 2026-10-23 (code uncommitted; see README.md)
- **Built:**
  - `ckapp/engine` (`jobs.py`, `server.py`, `ck_run.py`, `__main__`)
  - `ckapp/app` (`viewer`, `timeline`, `inspector`, `panels`, `frames`, `media`, `model`, `client`, `main_window`, `icons`, `theme`)
  - `run_app.bat`, README
- **Changes from the original design:**
  - The event stream is **SSE**, not WebSocket, so QtNetwork alone is enough (Essentials has no QtWebSockets).
  - Frames stay **BGR** and are uploaded as `GL_BGR`. That makes decode 4× faster at 4K (82 fps).
  - App OpenCV is pinned **<5**, because 5.x wheels lack EXR.
- **Verified:**
  - 50 pytest tests: engine, app logic, headless UI, and frame listing that matches upstream.
  - Real GPU smoke runs:
    - Range render with progress; wipe and side-by-side views.
    - EXR render in low-VRAM mode, viewed as scene-linear.
    - First-frame hint at the in-point.
  - Engine behaviour:
    - Cancel mid-keying killed 2 python + 8 ffmpeg processes, with none left over.
    - A render finished with the app closed, and the relaunch showed it.
  - Playback: 24.2 fps at 1080p, 23.7 fps at 4K.
- **Deferred:**
  - LAN uploads and downloads. `--lan` with a token exists, but remote file transfer does not.
  - A cutout-with-alpha view (cv2 can't read ProRes 4444 alpha).
  - 10-bit display; video plates are shown in 8-bit.

## Phase 2: app (`D:\CODE\corridorkey2-workbench\`, in its own venv with PySide6 + numpy + opencv + PyOpenGL)
**Architecture: an engine and an app as separate processes.**
- `engine/`: Python, no Qt, the only part that touches the GPU.
  - Job queue with one GPU worker. Runs `infer.py` via `Popen`, without a shell, with the offline env vars, and kills the whole process tree on cancel.
  - Parses stdout into progress events.
  - API is FastAPI/uvicorn with REST + WebSocket on `127.0.0.1:<port>`:
    - `POST /jobs`, `GET /jobs`, `DELETE /jobs/{id}`
    - `WS /events`
    - `GET /files/...`
  - The app starts the engine automatically. Renders survive closing the UI.
- `app/`: PySide6, laid out like the Workbench:
  - Left rail plus **Media** bin. Clip thumbnails come from ffprobe/ffmpeg, with a status badge and frame count / resolution / fps.
  - **Queue** panel.
  - Center **viewer**:
    - `QOpenGLWidget` that uploads frames as textures, with a decode thread and a small frame cache.
    - Single, Wipe and Side-by-side modes, comparing the plate with the composite, alpha, fg or checker.
    - Fit/zoom/pan.
    - Transport controls plus a **Cavalry-style timeline** (user reference screenshot 2026-10-23):
      - A ruler with frame numbers, where the tick density adapts to zoom.
      - A playhead with a triangle marker and a line, plus an editable current-frame field (`F 32`) on the left.
      - **In/out handles** at the ends that you drag to trim. Keys `I`/`O` set them at the playhead; `Alt+I`/`Alt+O` clear them. Range modes: "Entire clip" or "Custom in/out", stored per clip.
      - The area outside the range is dimmed; a filmstrip sits under the ruler.
      - Rendering is cheap: QPainter on a plain widget, separate from the GL viewer.
    - **How in/out reaches the engine.** `infer.py` has no start-frame flag: only `--num_frames` with start `begin|middle|random_middle`, and frame dirs always start at file 0 (checked in `video_io.py:212-223, 258-265`).
      - **Video:** our own `engine/ck_run.py` imports `corridorkey` and wraps `video_io.probe_video_meta` so `start_frame = in`, `num_frames = out - in + 1`. Then it calls the normal entry point. This is frame-accurate and lossless, with no upstream edits; upstream already seeks via `CAP_PROP_POS_FRAMES`. Verify the frame accuracy on long-GOP files and fall back to a lossless ffmpeg pre-trim if it drifts.
      - **Frame dirs:** handled inside `ck_run.py` by slicing `frame_paths`, so no hardlink folders are needed. Done in Phase 1.
      - **Hints:** the first-frame hint and "set current frame as reference" apply to the **in** frame.
      - **Outputs:** offset the output frame numbers to match the source (EXR files named from `in`), so they line up in comp apps.
    - EXR and 10-bit frames are read via OpenCV into float textures.
  - Right **Inspector**, with collapsible sections:
    - GPU memory (Auto / Low)
    - Alpha Hint: file, first frame or all frames, hint strength, carry strength, "set current frame as reference" (exports that frame for a first-frame hint)
    - Despill amount
    - Output: outputs, format, EXR dtype
    - Deliver: output folder, Add to queue, Render
  - Status bar showing GPU VRAM and free disk space (via `nvidia-smi`/NVML).
  - Dark theme in our own colours, a different accent and no Corridor logo, so it is "similar, not a copy".
- **LAN (later phase):**
  - A settings toggle rebinds the engine to `0.0.0.0` and requires a bearer token.
  - Remote apps upload clips with chunked transfer and download the outputs.
  - Off by default.

## Phase 3 decisions: projects (2026-10-30)
- **The last project reopens on launch.** That matches the old behaviour, where the single session always
  loaded. The start page appears only when there's no project, or after Close project.
- **Paths: relative inside the project, absolute outside.** In memory every path is absolute; `project.py`
  converts on save and load. Renders from before projects, custom output folders and other drives stay absolute.
  The engine's job history keeps the absolute paths it wrote to, so outputs it reports are re-rooted onto the
  render's current `out_dir` (`_reroot` in `main_window.py`) in case the project moved.
- **Clip folder names are fixed once** and never reuse a folder that already exists on disk. A removed and
  re-added clip gets a new folder, so its renders never mix with the old ones.
- **Add to queue is refused when the engine is older than the app.** Older engines ignore `"hold"` and would start
  the render at once. A busy older engine is kept running so its renders finish, so this can happen.
- **Renders that finish for a project that isn't open are written into that project's file**: on live events,
  and on the engine's hello after a relaunch. Otherwise Clear finished could make the engine forget them first.
- **`project.json` has its own format version.** A newer file is refused rather than opened and saved over.

## Phase 4 decisions: click to mask (2026-11-04)
- **SAM runs in the engine, not the app.** The app never imports torch. The worker uses CorridorKey's venv, which
  already has torch and transformers, so the installer gets no new dependencies. The weights come only from an
  explicit Download button.
- **The image SAM sees is the frame on screen, in display colours.** The plate frame is decoded again for exactly
  frame F (the viewer may still show the previous frame while decoding). It is sRGB-encoded like the viewer and
  written atomically, because the worker keys its embedding cache on the file's mtime.
- **The mask is a prompt result, not the hint itself, until "Use as hint".** That writes a new file in
  `masks/<clip>/` and never overwrites one, because a past render may have used it.
- **A first-frame hint applies at the in-point**, so Use as hint moves the in-point to the mask's frame. If the
  out-point was before it, the range runs to the end of the clip, never a one-frame render. Moving the in-point
  later only warns; it doesn't block (`hint_frame` records where the hint was drawn).
- **One request in flight, latest edit wins.** Edits made while a request is out go out together when it answers.
  Answers for an older edit are dropped, so a stale mask can't be used as a hint.
- **The engine frees the model 30 s after the last app disconnects.** The app also asks on Done/Esc, but an app that
  is closing can't be relied on to deliver that request.
- **Non-ASCII paths: `ck_run.py` wraps `cv2.imread`** with a bytes + `imdecode` fallback that is used only when the
  original returns None. Upstream reads hint images and frame folders with `cv2.imread`, which fails on non-ASCII
  Windows paths, and drawn hints live under the project and clip folder names. Video input through
  `cv2.VideoCapture` is a separate question and wasn't changed.
- **Version 0.5.0**, so an idle 0.4.0 engine (without the release-on-disconnect) is replaced. Holding jobs needs
  an engine of at least 0.4.0, compared by version number.

## Verification
- Phase 1: the CLI smoke test writes `_alpha.mp4` and `_fg.mp4`. `nvidia-smi` shows peak VRAM under 4 GB.
- Phase 2:
  - Import a clip and confirm the thumbnail and metadata appear.
  - Scrub the viewer on 4K footage and check it stays smooth.
  - Render 10 frames and confirm progress events and the outputs show up in the viewer through wipe.
  - Cancel mid-render and confirm no python process is left in `nvidia-smi`.
  - Close the app mid-render and confirm the job still finishes.
- LAN phase: from a second PC, connect with the token, render, and download the outputs.

This plan is kept at `D:\CODE\corridorkey2-workbench\PLAN.md`.
