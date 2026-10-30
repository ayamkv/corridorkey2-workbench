# CorridorKey2 Workbench roadmap

CorridorKey2 Workbench: an unofficial native desktop app for
[CorridorKey 2.0](https://github.com/nikopueringer/CorridorKey2.0).
Check items off as they land. Decisions and the reasons for them live in `PLAN.md`.

## Where we left off (2026-10-30)

Read this first when picking the work back up.

**State of the code**
- `main` is at `5649c8a` (0.3.0), and the private repo https://github.com/ayamkv/corridorkey2-workbench is pushed up to that commit.
- On top of `main` there are **uncommitted** changes that make up 0.3.1, the studio installer:
  - `packaging/`: `setup.ps1`, `Setup.bat`, `make_dist.ps1` and `INSTALL.txt`.
  - The app icon `ckapp/app/assets/app.ico`.
  - ffmpeg detection in `tools\ffmpeg`.
  - The version bump, plus README and ROADMAP updates.
  - `dist/` is in `.gitignore`.
  - Commit and push them when the user says so.
- Branch **`phase-3-4`** is local only and not pushed. It holds one WIP commit, `776b81e`, cut from 0.3.0 (before the installer work):
  - Held jobs in `ckapp/engine/jobs.py`: `HELD`, `submit(hold=)`, `start()`, and a `before_run` hook.
  - The SAM 2.1 tiny worker, `ckapp/engine/sam_worker.py`.
  - `MaskService` in `ckapp/engine/masks.py`.
  - Engine endpoints: `/jobs/start`, `/jobs/{id}/start` and `/mask*`.
  - Tests, including `tests/fake_sam_worker.py`.
  - Of the tests, 70 pass on that branch and 66 on `main`. Rebase the branch onto `main` before continuing.
- The SAM weights are already downloaded to `.cache/models/sam2.1-hiera-tiny`. They are pinned to revision `de431c40…` and the folder is git-ignored.
  - Measured on the RTX 3050 Ti: embedding a 1080p frame takes 0.15 s on the GPU, and each click takes 15 ms. Peak VRAM is 511 MB.
  - On the CPU, embedding takes 1.3 s and each click 45 ms.

**Studio package**
- `dist\CorridorKey2-Workbench-0.3.1.zip` is 3.84 GB and includes the weights. It was built and verified on 2026-10-29: 116 entries, with all weight files at their original sizes.
- **`Setup.bat` has never finished a full install.** The user asked us not to run it on the dev PC.
  - The test run got as far as uv, Python 3.12, the upstream download and the venv, then stopped.
  - Never ran: the torch/requirements install (utils3d comes from a GitHub archive), the app venv, the ffmpeg download, placing the weights and creating shortcuts.
  - If someone reports a failure, ask for their `setup.log`.
- Rebuild the package with: `powershell -ExecutionPolicy Bypass -File packaging\make_dist.ps1 -Models D:\CODE\CorridorKey2.0 -Zip`

**Still pending**
- [ ] Rename the folder `D:\CODE\corridorkey2webui` to `D:\CODE\corridorkey2-workbench`. Close the running app and engine first: they lock the folder.
- [ ] Commit and push the installer (0.3.1).
- [ ] Phase 3 and Phase 4 UI work (below).

**Rules for this machine**
- C: is nearly full. Point TMP, TEMP and HF_HOME at `D:\CODE\_tmp`.
- For manual runs of a new build, set `CK2WB_STATE` to a scratch folder. That keeps the user's real state in `%APPDATA%\CorridorKeyDesk` from being migrated or changed.
- Before any GPU test, check that the user's engine isn't busy. 4 GB of VRAM can't run two jobs at once.

## Done

### Phase 0: evaluate the existing GUI (2026-10-23)
- [x] Audit sceledrus/CorridorKey2.0-GUI: safe, engine identical to upstream; viewer CPU-bound
- [x] Install and test it (`D:\CODE\CorridorKey2.0-GUI`, test drive only)

### Phase 1: environment and engine runner (2026-10-23)
- [x] Unmodified upstream clone `D:\CODE\CorridorKey2.0` with its own venv; weights hardlinked
- [x] `ck_run.py`: frame-accurate in/out ranges without touching upstream files
- [x] Seek accuracy verified: H.264 with B-frames, HEVC, ProRes

### Phase 2: the app (2026-10-23)
- [x] Engine process: job queue, REST + SSE, token auth, whole-tree cancel, job history
- [x] Renders continue when the app is closed and show up on relaunch
- [x] GPU viewer: plate / composite / matte / fg / checker; single, wipe, side by side; EXR
- [x] Cavalry-style timeline: frame field, ruler, playhead, in/out handles, filmstrip
- [x] Inspector, media bin, queue, status bar (GPU, disk, engine)
- [x] Real-time playback: 24 fps at 1080p and 4K
- [x] Automated tests (66 as of 2.4), plus a real-GPU smoke script with screenshots

### Phase 2.1: polish (2026-10-23)
- [x] Rename to **OpenDeck** (full name "OpenDeck for CorridorKey", as the license requires);
      settings move from `%APPDATA%\CorridorKeyStudio` to `%APPDATA%\OpenDeck` automatically
- [x] Slate-amber accent, warm graphite base; type: Bahnschrift with tabular figures for numerals and
      titles, Segoe UI Variable for controls
- [x] Transport: three fixed columns and a big amber frame readout; play/pause never shifts (tested)
- [x] Panel toggles in the top bar (Media, Queue, Inspector), Ctrl+1/2/3; panels can't collapse into a
      1 px handle; layout and panel visibility remembered
- [x] Deliver redesign: output folder row, elided path box, render name, Format and precision here,
      frame/disk status, Render
- [x] Inspector no longer clipped (outputs as a 2×2 grid, short combo labels, min width 300)
- [x] Zoom menu: "Fit" always present; "Custom" when off-preset; live zoom % beside it
- [x] Drop-down arrows on every combo box
- [x] Viewer text glitch fixed: GL unpack alignment and texture bindings restored for QPainter
- [x] Sentence-case panel titles and badges; no ALL-CAPS labels or middle-dot meta strings

### Phase 2.2: design pass (2026-10-23)
- [x] Darker blacks: chrome `#121214`, panels `#161718`, viewer `#0F1010`, so the picture is the deepest surface
- [x] Geist and Geist Mono bundled (`ckapp/app/assets/fonts`, SIL OFL); tabular figures for every number
- [x] Workbench icon set (media, queue, inspector, deliver, render, setting) plus Lucide icons for the
      rest (folder, import, remove), recoloured from the theme
- [x] Icon panel toggles in the top bar; icon panel headers; Render button and Deliver title with icons
- [x] VRAM bar: compact in the status bar, full with free / in use in the Inspector's GPU memory section;
      turns amber above 85% and red above 95%
- [x] Timeline zoom and pan stay on the clip (no zooming out past it, no panning off either end)
- [x] Timeline right-click: Fit to view, Zoom to in/out, Use entire clip
- [x] Drag the in/out bar to slide the whole range, clamped to the clip
- [x] Check marks and radio dots; leftover middle-dot and em-dash strings removed

### Phase 2.3: top bar and queue (2026-10-23)
- [x] Top-bar buttons show icon and label by default; right-click the top bar for "Icons only"
      (like Resolve's page tabs); the choice is remembered
- [x] Queue rows never scroll sideways: long names fade out at the edge (full name in the tooltip),
      while the frame range and the cancel/remove button stay pinned on the right
- [x] Long status and error lines fade the same way; rows highlight on hover

### Phase 2.4: export settings and the name (2026-10-29)
- [x] Inspector "Export" section: format, EXR precision, codec (H.264 / H.265), pixels (10-bit 4:4:4 /
      4:2:2 / 4:2:0, 8-bit 4:2:0), constant quality (CRF) or bitrate, speed preset; "Use CorridorKey defaults"
- [x] Says what each output really is (display-referred sRGB vs scene-linear EXR; cutout is always ProRes 4444)
      and warns when the pixel format won't play in common players
- [x] Deliver shows one line with exactly what the render writes, e.g. "H.264 10-bit 4:4:4, CRF 12, .mp4"
- [x] Defaults are upstream's own, checked by a test against `infer.py`
- [x] Verified on the GPU with non-default encoding settings
- [x] An idle engine from an older app version is replaced on start (it wouldn't know the new settings)
- [x] Drop-down highlight toned down (grey, not amber)
- [x] Renamed to **CorridorKey2 Workbench**; repo and folder `corridorkey2-workbench`; settings move from
      `%APPDATA%\OpenDeck` automatically

### Studio installer (2026-10-29)
- [x] `packaging/make_dist.ps1` builds a package folder (optionally with the weights and a .zip)
- [x] `Setup.bat`: private Python via uv, upstream at the tested commit, CUDA PyTorch, ffmpeg, shortcuts;
      no git or Python needed on the PC; re-runnable
- [x] Weights: download, or point at a folder you already have (hard-linked on the same drive), or shipped in `models\`
- [x] App icon; ffmpeg found in `tools\ffmpeg` when it isn't on PATH

## Next

Phase 3 and 4 work in progress is on the `phase-3-4` branch (engine side: held jobs, SAM 2.1 tiny worker).

### Phase 3: projects
- [ ] A project is a folder: `project.json` (it has its own version number), `renders/<clip folder>/render_NNN/` and `masks/<clip folder>/`
  - Each clip gets a render folder name once, stored on the clip and made unique. Two `plate.mp4` from different folders must not share one.
  - Render `out_dir` is stored relative to the project, so the project folder can be moved. Old absolute paths keep working, and existing render files are never moved.
- [ ] Project switcher in the top bar: New, Open, Recent and Show in Explorer. The window title shows the project. The recent list lives in the state dir.
- [ ] New Project dialog with a folder picker that shows free space.
  - **Never default to C: (Documents/AppData)**, because renders live inside the project.
  - Default to the last folder used. Otherwise use Documents only if its drive has at least 20 GB free, and else the fixed drive with the most free space.
- [ ] With no project open, show a start page (New, Open, Recent).
  - If an old `session.json` has clips, offer "Bring in my N clips (renders stay where they are)", then rename it to `session.migrated.json`.
- [ ] Jobs across projects:
  - The queue shows every engine job.
  - `JobSpec.project` (on the branch) records which project.json a job belongs to.
  - When a job finishes while another project is open, update that project's file.
  - Clicking that job in the queue opens its project.
  - When a project opens, reconcile its renders with the engine's job list, but only while the engine is connected.
- [ ] Engine "held" jobs (engine side done on the branch):
  - Deliver gets **Add to queue** (hold) and **Render** (Ctrl+Shift+R and Ctrl+R).
  - Queue rows get a Start button, and the panel header gets Start all.
  - The bin badge says "Held".
  - A clip with held jobs can't be removed.
- [ ] "Fits in GPU memory" estimate from upstream's README table, shown in the Inspector's GPU memory section and labelled as approximate.
  - Columns go by the clip's pixel count, rounded up to the next of 720p, 1080p, 1440p and 4K. Rows go by the GPU's total memory.
  - On a 4 GB card, 4K is "not enough memory": warn, don't block.
- [ ] Bump to 0.4.0, so an idle older engine gets replaced.

### Phase 4: click to mask (on-viewer hint)
- [x] SAM 2.1 tiny worker run by the engine (branch `phase-3-4`). It runs on the GPU between renders, is stopped before each render, and runs on the CPU while a render is going.
- [ ] Client calls: `/mask` status, `/mask/download` (an explicit button the user presses), and `/mask/predict` with `{image, points, box, out}`. Handle `mask` SSE events.
  - The app writes the displayed plate frame as an sRGB PNG for SAM, using `to_display_u8` at full width. Linear EXR is encoded to sRGB.
- [ ] Viewer mask tool:
  - A toggle in the viewer bar, with a hotkey.
  - Left-click keeps, right-click removes, a drag draws a box, and middle-drag pans while the tool is on.
  - Points are drawn as keep/remove dots.
  - The mask is a third texture in the shader, tinted over the plate.
  - The tool forces Single layout with the plate on side A, and restores the previous layout on exit.
  - Undo and Clear. Esc leaves the tool.
- [ ] "Use as hint": **a first-frame hint applies at the in-point**.
  - Using a mask drawn on frame F must set the in-point to F and say so.
  - Save it as a single-channel 8-bit PNG at clip resolution in `masks/<clip>/`, then set `hint_mode=first` and the hint path. Record the frame number too.
- [ ] One real-GPU check, then credit SAM 2.1 (Apache-2.0) in the README.
- [ ] Later, if VRAM allows: propagate through the clip as a full hint video (SAM 2 video / MatAnyone).

### Phase 5: LAN hosting
- [ ] Settings toggle: engine binds 0.0.0.0 (token already required)
- [ ] Connect to a remote engine; chunked clip upload; output download

### Later: more export and colour
- [ ] ProRes / DNxHR for every output (upstream always writes .mp4, so this needs a re-wrap or our own writer)
- [ ] Encoder threads (upstream default 2) in an advanced row
- [ ] Colour in: probe each clip's matrix, primaries, transfer and range (as EZ-CorridorKey does when
      extracting frames) and check how OpenCV decodes untagged and BT.709 footage. Expose upstream's
      `--linear_brightness`, `--linear_contrast` and `--linear_contrast_pivot`.
- [ ] OCIO / ACES input and output transforms (upstream has none; MarcelineVPQ/corridorkey-desktop ships OCIO 2.5)

## Backlog
- [ ] Cutout view with real alpha (OpenCV can't read ProRes 4444 alpha; decode through ffmpeg)
- [ ] 10/16-bit display of video plates (currently 8-bit)
- [ ] Despill color/method and "time awareness" from the official app: not in the open CLI, so revisit if upstream adds them
- [ ] Before going public: add a LICENSE (CorridorKey's terms: same CC BY-NC-SA 4.0-based license, free, keep the name)
