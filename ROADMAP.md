# CorridorKey2 Workbench roadmap

CorridorKey2 Workbench: an unofficial native desktop app for
[CorridorKey 2.0](https://github.com/nikopueringer/CorridorKey2.0).
Check items off as they land. Decisions and the reasons for them live in `PLAN.md`.

## Where we left off (2026-10-30)

Read this first when picking the work back up.

**State of the code**
- `main` is 0.3.1, pushed to the private repo https://github.com/ayamkv/corridorkey2-workbench. 0.3.1 is the studio installer:
  - `packaging/`: `setup.ps1`, `Setup.bat`, `make_dist.ps1` and `INSTALL.txt`.
  - The app icon `ckapp/app/assets/app.ico`.
  - ffmpeg detection in `tools\ffmpeg`.
  - `dist/` is in `.gitignore`.
- Branch **`phase-3-4`** is local only and not pushed. It was rebased onto `main` (0.3.1) on 2026-10-30 and holds:
  - The engine WIP commit: held jobs (`HELD`, `submit(hold=)`, `start()`, a `before_run` hook), the SAM 2.1 tiny
    worker (`sam_worker.py`), `MaskService` (`masks.py`), the `/jobs/start`, `/jobs/{id}/start` and `/mask*` endpoints.
  - **Phase 3 (0.4.0)**: projects, the start page, held jobs in the UI, jobs across projects and the GPU memory guide.
    97 tests pass. Not yet tried in the real windowed app or on the GPU: do one real-app pass (with `CK2WB_STATE` set
    to a scratch folder) before merging to `main`.
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
- [ ] A real-app check of Phase 3, then merge `phase-3-4` into `main`.
- [ ] Phase 4 UI work (below).

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

### Phase 3: projects (2026-10-30, on branch `phase-3-4`)
- [x] A project is a folder: `project.json` (format version 1; a newer file is refused, never overwritten),
      `renders/<clip folder>/render_NNN/` and `masks/<clip folder>/`
  - Each clip gets a folder name once (Windows-safe, unique case-insensitively against other clips and folders
    already on disk). Two `plate.mp4` get `plate` and `plate_2`.
  - Render `out_dir` and `outputs` are stored relative when inside the project, so it can be moved. Paths outside
    it (old renders, custom output folders, other drives) stay absolute. Render files are never moved.
- [x] Project button in the top bar: New, Open, Recent, Show in Explorer, Close. The window title shows the project.
      `recent.json` in the state dir. The last project reopens on launch.
- [x] New Project dialog with free space. Default: the last parent folder; else Documents if its drive has 20 GB
      free; else the fixed drive with the most room (D: on this PC).
- [x] Start page (New, Open, Recent). An old `session.json` with clips offers "Bring in my N clips"; the file is
      renamed to `session.migrated.json` only after the project is written.
- [x] Importing, dropping or passing clips on the command line with no project open asks for a new project first.
- [x] Jobs across projects: `JobSpec.project` is set on every render. A job finishing for a project that isn't open
      updates that project's file. Clicking it in the queue opens its project. Opening a project reconciles it with
      `GET /jobs` (only while connected).
- [x] Held jobs: Deliver has **Add to queue** (Ctrl+Shift+R) and **Render** (Ctrl+R); queue rows have Start, the
      header has Start all; the bin badge says Held; clips with held jobs can't be removed; Clear finished skips them.
      An older engine (which would ignore "hold" and start at once) is refused with a message.
- [x] Inspector GPU memory: "what Auto picks" from upstream's README table, labelled approximate; rows match with
      10% slack; warns (doesn't block) for "not enough memory", under 4 GB and above-4K clips. A test checks the
      table against upstream's README.
- [x] Version 0.4.0, so an idle older engine is replaced.

## Next

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
