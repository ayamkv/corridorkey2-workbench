# CorridorKey2 Workbench roadmap

CorridorKey2 Workbench: an unofficial native desktop app for
[CorridorKey 2.0](https://github.com/nikopueringer/CorridorKey2.0).
Check items off as they land. Decisions and the reasons for them live in `PLAN.md`.

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

## Next

### Phase 3: projects
- [ ] A project is a folder: `project.json` + `renders/<clip>/render_NNN/`
- [ ] Project switcher in the top bar: New, Open, Recent; per-project media, settings, render history
- [ ] Migrate the current session into a first project
- [ ] Engine "held" jobs: **Add to queue** holds, **Render** starts
- [ ] "Fits in GPU memory" estimate from upstream's measured VRAM table

### Phase 4: click to mask (on-viewer hint)
- [ ] SAM 2.1 tiny in the CorridorKey venv, run by the engine between renders (4 GB GPU)
- [ ] Viewer mask tool: left-click keep, right-click remove, drag a box; mask tinted over the plate
- [ ] "Use as hint": saves the mask as the first-frame hint at the in-point
- [ ] Later, if VRAM allows: propagate through the clip as a full hint video (SAM 2 video / MatAnyone)

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
