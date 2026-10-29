"""The main window: wires media bin, viewer, timeline, inspector, queue and the engine client."""
from __future__ import annotations

import os
from dataclasses import asdict
from typing import Optional

from PySide6.QtCore import QSettings, QSize, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QCursor, QDesktopServices, QFont, QFontMetrics, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
                               QSplitter, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..config import Settings, load_settings, save_settings, state_dir
from . import icons
from . import theme as T
from .client import EngineClient
from .frames import FrameProvider
from .inspector import Inspector
from .media import is_media, probe
from .model import Clip, Render, Session
from .panels import MediaBin, QueuePanel, ThumbLoader
from .timeline import Timeline
from .viewer import MODE_COLOR, MODE_COMPOSITE, MODE_MATTE, GLViewer, Side
from .widgets import Segmented, VramMeter, combo, hline, icon_button, label, styled_popup, vline

VIEWS = [("plate", "Plate"), ("composite", "Composite"), ("matte", "Matte"), ("fg", "Foreground"),
         ("checker", "Checker")]
VIEW_LABEL = dict(VIEWS)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__} (unofficial)")
        self.resize(1500, 900)
        self.setAcceptDrops(True)
        self.settings = load_settings().resolved()
        self.session = Session(state_dir() / "session.json")
        self.frames = FrameProvider(parent=self)
        self.thumbs = ThumbLoader(self)
        self.client = EngineClient(self)
        self.clip: Optional[Clip] = None
        self.render: Optional[Render] = None
        self.frame = 0
        self.playing = False
        self.job_fraction: dict[str, float] = {}
        self.strips: dict[str, list] = {}
        self._shown: dict[str, object] = {}        # last frame shown per (side, role): no flicker while decoding
        self._gpu_total_mb = 0

        self._build_ui()
        self._wire()
        self._shortcuts()
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self.session.save)
        self._play_timer = QTimer(self, timeout=self._tick)
        self._play_timer.setTimerType(Qt.PreciseTimer)

        self.session.load()
        for c in self.session.clips:
            self._add_to_bin(c)
        if self.session.clips:
            self.bin.select(self.session.clips[0].id)
        else:
            self._select_clip(None)
        self.restore_layout()
        self._sync_zoom_box()

    # ================================================================== layout
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._top_bar())
        v.addWidget(hline())

        self.bin = MediaBin()
        self.queue = QueuePanel()
        self.bin.setMinimumSize(220, 160)
        self.queue.setMinimumSize(220, 120)
        left = self.left_split = QSplitter(Qt.Vertical)
        left.setChildrenCollapsible(False)      # panels hide via the top-bar toggles, never into a 1 px handle
        left.addWidget(self.bin)
        left.addWidget(self.queue)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 2)

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._viewer_bar())
        cv.addWidget(hline())
        self.viewer = GLViewer()
        cv.addWidget(self.viewer, 1)
        cv.addWidget(hline())
        cv.addWidget(self._transport())
        self.timeline = Timeline()
        cv.addWidget(self.timeline)

        self.inspector = Inspector()
        center.setMinimumWidth(420)
        main = self.main_split = QSplitter(Qt.Horizontal)
        main.setChildrenCollapsible(False)
        main.addWidget(left)
        main.addWidget(center)
        main.addWidget(self.inspector)
        main.setStretchFactor(1, 1)
        main.setSizes([300, 900, 340])
        v.addWidget(main, 1)
        self.setCentralWidget(root)

        sb = self.statusBar()
        self.st_engine = QLabel("Engine: starting…")
        self.st_gpu = VramMeter(compact=True)
        self.st_disk = QLabel("")
        self.st_msg = QLabel("")
        sb.addWidget(self.st_msg, 1)
        sb.addPermanentWidget(self.st_gpu)
        sb.addPermanentWidget(self.st_disk)
        sb.addPermanentWidget(self.st_engine)

    def _top_bar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("TopBar")
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 5, 8, 5)
        h.setSpacing(8)
        # one rich-text label so both parts share a baseline
        h.addWidget(label(f"{APP_NAME}&nbsp;&nbsp;<span style='font-size:8.5pt; font-weight:400; "
                          f"color:{T.c('TEXT_FAINT')}'>unofficial</span>", "Brand"))
        h.addStretch(1)
        self.title = label("", "Title")
        h.addWidget(self.title)
        h.addStretch(1)
        self.panel_toggles: dict[str, QToolButton] = {}
        for key, text, keys in (("media", "Media", "Ctrl+1"), ("queue", "Queue", "Ctrl+2"),
                                ("inspector", "Inspector", "Ctrl+3")):
            b = QToolButton()
            b.setObjectName("Toggle")
            b.setText(text)
            b.setIcon(icons.svg(key, "TEXT", 16, hover="TEXT", off="TEXT_FAINT"))
            b.setCheckable(True)
            b.setChecked(True)
            b.setToolTip(f"Show or hide the {text.lower()} panel ({keys})")
            b.toggled.connect(lambda on, k=key: self._show_panel(k, on))
            h.addWidget(b)
            self.panel_toggles[key] = b
        h.addWidget(vline())
        b = QToolButton()
        b.setObjectName("Toggle")
        b.setProperty("plain", True)
        b.setText("Settings")
        b.setIcon(icons.svg("setting", "TEXT_DIM", 16, hover="TEXT"))
        b.setToolTip("Settings: CorridorKey folder, python, cache, ffmpeg")
        b.clicked.connect(self._open_settings)
        h.addWidget(b)
        self.top_buttons = [*self.panel_toggles.values(), b]
        for b in self.top_buttons:
            b.setIconSize(QSize(16, 16))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(self._top_menu)
        w.setContextMenuPolicy(Qt.CustomContextMenu)
        w.customContextMenuRequested.connect(self._top_menu)
        self.set_top_labels(True)
        return w

    def set_top_labels(self, on: bool) -> None:
        """Top-bar buttons show 'icon + label' (default) or icons only; right-click them to switch."""
        self.top_labels = on
        for b in self.top_buttons:
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if on else Qt.ToolButtonIconOnly)
            b.setProperty("iconOnly", not on)
            b.style().unpolish(b)
            b.style().polish(b)

    def _top_menu(self, _pos=None) -> None:
        m = QMenu(self)
        for text, on in (("Icons and labels", True), ("Icons only", False)):
            a = m.addAction(text, lambda v=on: self.set_top_labels(v))
            a.setCheckable(True)
            a.setChecked(self.top_labels == on)
        m.exec(QCursor.pos())

    def _show_panel(self, key: str, on: bool) -> None:
        {"media": self.bin, "queue": self.queue, "inspector": self.inspector}[key].setVisible(on)
        self.left_split.setVisible(self.panel_toggles["media"].isChecked() or self.panel_toggles["queue"].isChecked())

    def _viewer_bar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Panel")
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(8)
        self.seg_layout = Segmented([(GLViewer.SINGLE, "Single"), (GLViewer.WIPE, "Wipe"),
                                     (GLViewer.SIDE, "Side by side")])
        h.addWidget(self.seg_layout)
        h.addWidget(vline())
        self.cb_a, self.cb_b = combo([(t, k, "") for k, t in VIEWS]), combo([(t, k, "") for k, t in VIEWS])
        for cb in (self.cb_a, self.cb_b):
            cb.setMinimumContentsLength(8)
            cb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.cb_a.setCurrentIndex(1)
        self.cb_b.setCurrentIndex(0)
        self.lb_a = label("A", "Dim")
        self.lb_b = label("B", "Dim")
        for wdg in (self.lb_a, self.cb_a, self.lb_b, self.cb_b):
            h.addWidget(wdg)
        h.addStretch(1)
        h.addWidget(label("Render", "Dim"))
        self.cb_render = combo([])
        self.cb_render.setMinimumContentsLength(10)
        self.cb_render.setMaximumWidth(240)
        self.cb_render.setToolTip("Which render of this clip the viewer shows")
        h.addWidget(self.cb_render)
        self.bt_folder = icon_button("folder-open", "Open this render's folder")
        self.bt_folder.clicked.connect(self._open_render_folder)
        h.addWidget(self.bt_folder)
        h.addWidget(vline())
        self.lb_zoom = QLabel("")
        self.lb_zoom.setObjectName("Dim")
        self.lb_zoom.setFont(T.num_font(9))
        self.lb_zoom.setMinimumWidth(QFontMetrics(self.lb_zoom.font()).horizontalAdvance("0000%"))
        self.lb_zoom.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lb_zoom.setToolTip("Current zoom")
        h.addWidget(self.lb_zoom)
        self.cb_zoom = styled_popup(QComboBox())
        self.cb_zoom.setPlaceholderText("Custom")
        self.cb_zoom.addItem("Fit", 0)
        for z in (25, 50, 100, 200, 400):
            self.cb_zoom.addItem(f"{z}%", z)
        self.cb_zoom.setToolTip("Fit, or a fixed zoom. Scroll on the viewer to zoom at the cursor.")
        h.addWidget(self.cb_zoom)
        return w

    def _transport(self) -> QWidget:
        """Three columns; the outer two have the same fixed width so the buttons never move."""
        w = QWidget()
        w.setObjectName("Panel")
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 4, 12, 2)
        side_w = 200
        left = QWidget()
        left.setFixedWidth(side_w)
        lh = QHBoxLayout(left)
        lh.setContentsMargins(0, 0, 0, 0)
        lh.setSpacing(8)
        self.lb_frame = QLabel("")
        self.lb_frame.setFont(T.num_font(17, QFont.DemiBold))
        self.lb_frame.setStyleSheet(f"color: {T.c('ACCENT')};")
        self.lb_frame.setToolTip("Current frame")
        self.lb_range = QLabel("")
        self.lb_range.setObjectName("Dim")
        self.lb_range.setFont(T.num_font(9.5))
        self.lb_range.setToolTip("Frame range (in to out)")
        lh.addWidget(self.lb_frame)
        lh.addWidget(self.lb_range, 0, Qt.AlignBottom)
        lh.addStretch(1)
        h.addWidget(left)
        h.addStretch(1)
        self.tr_buttons = {}
        self._icon_play, self._icon_pause = icons.play(), icons.pause()
        for key, icon, tip in (("first", icons.to_in(), "Go to in-point (Home)"),
                               ("prev", icons.step_back(), "Previous frame (←, Shift = 10)"),
                               ("play", self._icon_play, "Play / pause (Space)"),
                               ("next", icons.step_fwd(), "Next frame (→, Shift = 10)"),
                               ("last", icons.to_out(), "Go to out-point (End)")):
            b = QToolButton()
            b.setObjectName("Flat")
            b.setIcon(icon)
            b.setIconSize(QSize(16, 16))
            b.setToolTip(tip)
            b.setMinimumWidth(32)
            h.addWidget(b)
            self.tr_buttons[key] = b
        h.addStretch(1)
        self.lb_fps = label("", "Dim")
        self.lb_fps.setFont(T.num_font(9.5))
        self.lb_fps.setFixedWidth(side_w)
        self.lb_fps.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.lb_fps)
        return w

    # ================================================================== wiring
    def _wire(self) -> None:
        self.bin.clipSelected.connect(lambda cid: self._select_clip(self.session.find(cid)))
        self.bin.importRequested.connect(self._import_dialog)
        self.bin.renderRequested.connect(lambda cid: self._render(self.session.find(cid)))
        self.bin.removeRequested.connect(self._remove_clip)
        self.bin.revealRequested.connect(self._reveal_clip)
        self.thumbs.thumbReady.connect(self.bin.set_thumb)
        self.thumbs.stripReady.connect(self._strip_ready)

        self.timeline.frameChanged.connect(self.set_frame)
        self.timeline.rangeChanged.connect(self._timeline_range)
        self.inspector.changed.connect(self._settings_changed)
        self.inspector.rangeEdited.connect(self._sync_range_to_timeline)
        self.inspector.renderRequested.connect(lambda: self._render(self.clip))
        self.inspector.setInRequested.connect(lambda: self._set_point("in"))
        self.inspector.setOutRequested.connect(lambda: self._set_point("out"))

        self.seg_layout.changed.connect(self._layout_changed)
        self.cb_a.currentIndexChanged.connect(self.update_viewer)
        self.cb_b.currentIndexChanged.connect(self.update_viewer)
        self.cb_render.currentIndexChanged.connect(self._render_chosen)
        self.cb_zoom.activated.connect(self._zoom_chosen)
        self.viewer.viewChanged.connect(self._sync_zoom_box)
        self.viewer.glFailed.connect(lambda msg: self._message(f"OpenGL problem: {msg}", error=True))
        self.frames.frameReady.connect(self._frame_ready)
        self.frames.sourceError.connect(lambda p, e: self._message(f"Cannot read {os.path.basename(p)}: {e}", True))

        self.tr_buttons["first"].clicked.connect(lambda: self._go_point("in"))
        self.tr_buttons["last"].clicked.connect(lambda: self._go_point("out"))
        self.tr_buttons["prev"].clicked.connect(lambda: self.step(-1))
        self.tr_buttons["next"].clicked.connect(lambda: self.step(1))
        self.tr_buttons["play"].clicked.connect(self.toggle_play)

        self.queue.cancelRequested.connect(self.client.cancel)
        self.queue.removeRequested.connect(self.client.remove)
        self.queue.jobActivated.connect(self._job_activated)
        self.client.connectedChanged.connect(self._engine_connected)
        self.client.jobsReset.connect(self._jobs_reset)
        self.client.jobUpdated.connect(self._job_updated)
        self.client.jobRemoved.connect(self.queue.remove_job)
        self.client.system.connect(self._system)
        self.client.requestFailed.connect(lambda m: self._message(m, error=True))
        self._layout_changed(GLViewer.SINGLE)

    def _shortcuts(self) -> None:
        def sc(keys, fn):
            s = QShortcut(QKeySequence(keys), self)
            s.setContext(Qt.WindowShortcut)
            s.activated.connect(fn)
        sc("Space", self.toggle_play)
        sc("Left", lambda: self.step(-1))
        sc("Right", lambda: self.step(1))
        sc("Shift+Left", lambda: self.step(-10))
        sc("Shift+Right", lambda: self.step(10))
        sc("Home", lambda: self._go_point("in"))
        sc("End", lambda: self._go_point("out"))
        sc("I", lambda: self._set_point("in"))
        sc("O", lambda: self._set_point("out"))
        sc("Alt+I", lambda: self._clear_point("in"))
        sc("Alt+O", lambda: self._clear_point("out"))
        sc("F", self.viewer.fit_view)
        sc("1", lambda: self.seg_layout.set_current(GLViewer.SINGLE, emit=True))
        sc("2", lambda: self.seg_layout.set_current(GLViewer.WIPE, emit=True))
        sc("3", lambda: self.seg_layout.set_current(GLViewer.SIDE, emit=True))
        sc("Ctrl+O", self._import_dialog)
        sc("Ctrl+R", lambda: self._render(self.clip))
        for keys, name in (("Ctrl+1", "media"), ("Ctrl+2", "queue"), ("Ctrl+3", "inspector")):
            sc(keys, lambda n=name: self.panel_toggles[n].toggle())
        act = QAction(self)
        act.setShortcut(QKeySequence.Delete)
        act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        act.triggered.connect(lambda: self.clip and self._remove_clip(self.clip.id))
        self.bin.list.addAction(act)

    # ================================================================== clips
    def _import_dialog(self) -> None:
        start = os.path.dirname(self.clip.path) if self.clip else ""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Import clips", start,
            "Video (*.mp4 *.mov *.mkv *.avi *.mxf *.m4v *.webm);;All files (*)")
        if not files:
            d = QFileDialog.getExistingDirectory(self, "...or an image-sequence folder (EXR/PNG/JPG)", start)
            files = [d] if d else []
        self.import_paths(files)

    def import_paths(self, paths: list[str]) -> list[Clip]:
        added, skipped = [], []
        known = {os.path.normcase(os.path.abspath(c.path)) for c in self.session.clips}
        for p in paths:
            p = os.path.normpath(p)
            if os.path.normcase(os.path.abspath(p)) in known:
                continue
            if not is_media(p):
                skipped.append(os.path.basename(p))
                continue
            try:
                clip = Clip.from_info(probe(p))
            except ValueError as e:
                skipped.append(f"{os.path.basename(p)} ({e})")
                continue
            self.session.clips.append(clip)
            known.add(os.path.normcase(os.path.abspath(p)))
            self._add_to_bin(clip)
            added.append(clip)
        if added:
            self.bin.select(added[0].id)
            self._save_timer.start()
        if skipped:
            self._message("Not imported: " + ", ".join(skipped[:5]), error=True)
        return added

    def _add_to_bin(self, clip: Clip) -> None:
        self.bin.add(clip.id, clip.name, clip.label if not clip.error else "file missing")
        if not clip.error:
            self.thumbs.thumb(clip.id, clip.path, clip.settings.frame_dir_linear)
        self._refresh_clip_status(clip)

    def _remove_clip(self, clip_id: str) -> None:
        clip = self.session.find(clip_id)
        if clip is None:
            return
        if any(r.status in ("queued", "running") for r in clip.renders):
            self._message("This clip is still rendering; cancel its job first.", error=True)
            return
        self.session.clips.remove(clip)
        self.bin.remove(clip_id)
        self.strips.pop(clip_id, None)
        if self.clip is clip:
            nxt = self.session.clips[0] if self.session.clips else None
            if nxt:
                self.bin.select(nxt.id)
            else:
                self._select_clip(None)
        self._save_timer.start()

    def _reveal_clip(self, clip_id: str) -> None:
        clip = self.session.find(clip_id)
        if clip:
            folder = clip.render_root() if os.path.isdir(clip.render_root()) else os.path.dirname(clip.path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _select_clip(self, clip: Optional[Clip]) -> None:
        self.stop()
        self.clip = clip
        self._shown.clear()
        self.inspector.set_clip(clip)
        if clip is None:
            self.title.setText("")
            self.timeline.set_clip(1)
            self.render = None
            self._fill_render_box()
            self.update_viewer()
            return
        self.title.setText(clip.name)
        self.timeline.set_clip(clip.frames)
        self.timeline.set_filmstrip(self.strips.get(clip.id, []))
        if clip.id not in self.strips and not clip.error:
            self.thumbs.strip(clip.id, clip.path, clip.frames, linear=clip.settings.frame_dir_linear)
        self.lb_fps.setText(f"{clip.fps:g} fps")
        self.client.disk_path = clip.render_root()
        self.client.poll_system()
        self._sync_range_to_timeline()
        self.render = clip.latest_render()
        self._fill_render_box()
        first, _ = clip.frame_range()
        self.set_frame(first if self.render is None else max(first, self.render.frame_in))

    def _strip_ready(self, clip_id: str, items: list) -> None:
        self.strips[clip_id] = items
        if self.clip and self.clip.id == clip_id:
            self.timeline.set_filmstrip(items)

    def _settings_changed(self) -> None:
        self._save_timer.start()
        if self.clip:
            self.client.disk_path = self.clip.render_root()

    # ================================================================== range
    def _sync_range_to_timeline(self) -> None:
        if self.clip:
            self.timeline.set_range(*self.clip.frame_range())

    def _timeline_range(self, first: int, last: int) -> None:
        if self.clip:
            whole = first == 0 and last == self.clip.last_frame
            self.inspector.set_range(first, last, custom=not whole)
            self._save_timer.start()

    def _set_point(self, which: str) -> None:
        if not self.clip:
            return
        first, last = self.clip.frame_range()
        if which == "in":
            first, last = self.frame, max(last, self.frame)
        else:
            first, last = min(first, self.frame), self.frame
        self.inspector.set_range(first, last, custom=True)
        self._sync_range_to_timeline()
        self._save_timer.start()

    def _clear_point(self, which: str) -> None:
        if not self.clip:
            return
        first, last = self.clip.frame_range()
        if which == "in":
            first = 0
        else:
            last = self.clip.last_frame
        whole = first == 0 and last == self.clip.last_frame
        self.inspector.set_range(first, last, custom=not whole)
        self._sync_range_to_timeline()
        self._save_timer.start()

    def _go_point(self, which: str) -> None:
        if self.clip:
            first, last = self.clip.frame_range()
            self.set_frame(first if which == "in" else last)

    # ================================================================== playback
    def set_frame(self, f: int) -> None:
        if self.clip is None:
            return
        f = max(0, min(int(f), self.clip.last_frame))
        self.frame = f
        self.timeline.set_frame(f)
        first, last = self.clip.frame_range()
        self.lb_frame.setText(str(f))
        self.lb_range.setText(f"{first}–{last}")
        self.update_viewer()

    def step(self, d: int) -> None:
        self.stop()
        self.set_frame(self.frame + d)

    def toggle_play(self) -> None:
        if self.playing:
            self.stop()
        elif self.clip:
            first, last = self.clip.frame_range()
            if not first <= self.frame < last:
                self.set_frame(first)
            self.playing = True
            self.tr_buttons["play"].setIcon(self._icon_pause)
            self._play_timer.start(max(5, int(1000 / max(1.0, self.clip.fps))))
            self.update_viewer()

    def stop(self) -> None:
        if self.playing:
            self.playing = False
            self._play_timer.stop()
            self.tr_buttons["play"].setIcon(self._icon_play)

    def _tick(self) -> None:
        if not self.clip:
            return self.stop()
        first, last = self.clip.frame_range()
        nxt = self.frame + 1 if self.frame < last else first
        if all(self._cached(src, nxt) for src in self._needed_sources()):
            self.set_frame(nxt)
        else:
            self._request_all(nxt)       # wait for the decoders rather than skipping frames

    # ================================================================== viewer
    def _layout_changed(self, mode: str) -> None:
        self.viewer.set_layout(mode)
        two = mode != GLViewer.SINGLE
        for w in (self.lb_b, self.cb_b):
            w.setVisible(two)
        self.lb_a.setVisible(two)
        self.update_viewer()

    def _sources_for(self, view: str, f: int) -> list[tuple[str, str, int, bool, bool]]:
        """[(role, path, frame_index_in_source, gray, linear)] needed to show `view` at frame f."""
        c, r = self.clip, self.render
        if c is None:
            return []
        if view == "plate":
            return [("color", c.path, f, False, c.kind == "sequence" and c.settings.frame_dir_linear)]
        if r is None or not (r.frame_in <= f <= r.frame_out):
            return []
        idx = f - r.frame_in

        def out(key, role, gray=False):
            p = r.outputs.get(key)
            if not p:
                return None
            exr = os.path.isdir(p)
            return (role, p, f if exr else idx, gray, exr)
        items = {"composite": [out("fg", "color"), out("alpha", "alpha", True)],
                 "matte": [out("alpha", "color", True)],
                 "fg": [out("fg", "color")],
                 "checker": [out("checker", "color")]}[view]
        return [i for i in items if i is not None]

    def _resolve(self, view: str, f: int) -> tuple[str, list, str]:
        """(view actually shown, sources, reason). Views that need a render fall back to the plate."""
        srcs = self._sources_for(view, f)
        if srcs or view == "plate":
            return view, srcs, ""
        r = self.render
        if r is None:
            reason = "no render yet"
        elif not (r.frame_in <= f <= r.frame_out):
            reason = f"outside render {r.frame_in}–{r.frame_out}"
        else:
            reason = f"render has no {VIEW_LABEL[view].lower()}"
        return "plate", self._sources_for("plate", f), reason

    def _needed_sources(self) -> list[tuple]:
        views = [self.cb_a.currentData()]
        if self.viewer.layout_mode != GLViewer.SINGLE:
            views.append(self.cb_b.currentData())
        out = []
        for v in views:
            for role, path, idx, gray, lin in self._resolve(v, self.frame)[1]:
                out.append((path, idx - self.frame, gray, lin))   # offset relative to the frame
        return out

    def _cached(self, src: tuple, f: int) -> bool:
        path, off, gray, lin = src
        return self.frames.get(path, f + off, gray=gray, linear=lin) is not None

    def _request_all(self, f: int) -> None:
        last = self.clip.frame_range()[1] if self.clip else None
        for path, off, gray, lin in self._needed_sources():
            self.frames.request(path, f + off, gray=gray, linear=lin, ahead=12 if self.playing else 2,
                                last=None if last is None else last + off)

    def _side(self, key: str, view: str) -> Side:
        side = Side(label=VIEW_LABEL[view])
        c = self.clip
        if c is None:
            side.note = "Import a clip to start"
            return side
        if c.error:
            side.note = f"File missing:\n{c.path}"
            return side
        shown, srcs, reason = self._resolve(view, self.frame)
        if reason:
            side.label = f"Plate   ({VIEW_LABEL[view].lower()}: {reason})"
        view = shown
        if not srcs:
            side.note = "Cannot read this clip"
            return side
        frames = {}
        last = c.frame_range()[1]
        for role, path, idx, gray, lin in srcs:
            fr = self.frames.request(path, idx, gray=gray, linear=lin, ahead=12 if self.playing else 2,
                                     last=last + (idx - self.frame))
            memo = (key, role, path)
            if fr is None:
                fr = self._shown.get(memo)           # keep the previous frame until the new one decodes
            else:
                self._shown[memo] = fr
            frames[role] = fr
            if fr is None:
                err = self.frames.error(path)
                side.note = f"Cannot read {os.path.basename(path)}" if err else "Loading…"
        side.color, side.alpha = frames.get("color"), frames.get("alpha")
        side.mode = {"composite": MODE_COMPOSITE, "matte": MODE_MATTE}.get(view, MODE_COLOR)
        return side

    def update_viewer(self) -> None:
        a = self._side("a", self.cb_a.currentData())
        b = self._side("b", self.cb_b.currentData()) if self.viewer.layout_mode != GLViewer.SINGLE else Side()
        self.viewer.set_sides(a, b)

    def _frame_ready(self, path: str, idx: int) -> None:
        if self.clip is None:
            return
        for p, off, _, _ in self._needed_sources():
            if p == path and idx == self.frame + off:
                self.update_viewer()
                return

    def _zoom_chosen(self, i: int) -> None:
        z = self.cb_zoom.itemData(i)
        if z:
            self.viewer.set_zoom_percent(z)
        else:
            self.viewer.fit_view()

    def _sync_zoom_box(self) -> None:
        """The menu shows Fit, the matching preset, or 'Custom'; the label beside it shows the live %."""
        pct = self.viewer.zoom_percent()
        self.lb_zoom.setText(f"{pct:.0f}%")
        if self.viewer.fit:
            idx = 0
        else:
            idx = next((i for i in range(1, self.cb_zoom.count())
                        if abs(self.cb_zoom.itemData(i) - pct) < 0.5), -1)
        self.cb_zoom.blockSignals(True)
        self.cb_zoom.setCurrentIndex(idx)
        self.cb_zoom.blockSignals(False)

    # ================================================================== renders
    def _fill_render_box(self) -> None:
        self.cb_render.blockSignals(True)
        self.cb_render.clear()
        c = self.clip
        if c:
            for r in reversed(c.renders):
                state = "" if r.status == "done" else f"  ({r.status})"
                self.cb_render.addItem(f"{r.label}    {r.frame_in}–{r.frame_out}{state}", r.job_id)
        if self.cb_render.count() == 0:
            self.cb_render.addItem("No renders yet", "")
        elif self.render is not None:
            self.cb_render.setCurrentIndex(max(0, self.cb_render.findData(self.render.job_id)))
        self.cb_render.blockSignals(False)
        self.bt_folder.setEnabled(self.render is not None)
        self.timeline.set_rendered((self.render.frame_in, self.render.frame_out) if self.render else None)

    def _render_chosen(self, i: int) -> None:
        if not self.clip:
            return
        jid = self.cb_render.itemData(i)
        self.render = next((r for r in self.clip.renders if r.job_id == jid), None)
        self._shown.clear()
        self._fill_render_box()
        self.update_viewer()

    def _open_render_folder(self) -> None:
        if self.render:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.render.out_dir))

    def _render(self, clip: Optional[Clip]) -> None:
        if clip is None:
            return
        if not self.client.connected:
            self._message("The render engine is not connected yet.", error=True)
            return
        if not clip.settings.outputs:
            self._message("Pick at least one output.", error=True)
            return
        out_dir, label_ = clip.next_render_dir()
        spec = clip.to_spec(out_dir)
        first, last = clip.frame_range()

        def done(job: dict) -> None:
            r = Render(job_id=job["id"], out_dir=out_dir, frame_in=first, frame_out=last,
                       output_format=spec.output_format, status=job["status"], label=label_)
            clip.renders.append(r)
            self._save_timer.start()
            self._refresh_clip_status(clip)
            if clip is self.clip:
                self._fill_render_box()
                self.inspector.set_clip(clip)          # next render number in the summary
            self._message(f"Queued {clip.name} ({label_}, frames {first}–{last})")
        self.client.submit(asdict(spec), done)

    def _jobs_reset(self, jobs: list) -> None:
        self.queue.reset(jobs)
        by_id = {j["id"]: j for j in jobs}
        for c in self.session.clips:
            for r in c.renders:
                j = by_id.get(r.job_id)
                if j:
                    self._apply_job(c, r, j)
                elif r.status in ("queued", "running"):
                    r.status = "interrupted"
            self._refresh_clip_status(c)
        self._save_timer.start()
        # renders may have finished while the app was closed: show the newest one
        if self.clip is not None:
            latest = self.clip.latest_render()
            if latest is not None and latest is not self.render:
                self.render = latest
                self._shown.clear()
                self._fill_render_box()
                if not latest.frame_in <= self.frame <= latest.frame_out:
                    self.set_frame(latest.frame_in)
                self.update_viewer()

    def _job_updated(self, job: dict) -> None:
        self.queue.update_job(job)
        clip, r = self.session.find_job(job["id"])
        if clip and r:
            was = r.status
            self._apply_job(clip, r, job)
            self._refresh_clip_status(clip)
            if r.status != was:
                self._save_timer.start()
                if r.status == "done":
                    self._message(f"Finished {clip.name} ({r.label})")
                    if clip is self.clip:
                        self.render = r
                        self._shown.clear()
                        self._fill_render_box()
                        if not r.frame_in <= self.frame <= r.frame_out:
                            self.set_frame(r.frame_in)
                        self.update_viewer()
                elif r.status == "error":
                    self._message(f"{clip.name} failed: {job.get('error', '')}", error=True)
                if clip is self.clip and r.status != "done":
                    self._fill_render_box()

    def _apply_job(self, clip: Clip, r: Render, job: dict) -> None:
        r.status = job["status"]
        self.job_fraction[r.job_id] = job.get("fraction", 0.0)
        if job.get("outputs"):
            r.outputs = dict(job["outputs"])

    def _refresh_clip_status(self, clip: Clip) -> None:
        if clip.error:
            return self.bin.set_status(clip.id, "missing")
        running = next((r for r in clip.renders if r.status == "running"), None)
        if running:
            return self.bin.set_status(clip.id, "running", self.job_fraction.get(running.job_id, 0.0))
        if any(r.status == "queued" for r in clip.renders):
            return self.bin.set_status(clip.id, "queued")
        last = clip.renders[-1] if clip.renders else None
        if last and last.status == "error":
            return self.bin.set_status(clip.id, "error")
        self.bin.set_status(clip.id, "done" if clip.latest_render() else "ready")

    def _job_activated(self, job_id: str) -> None:
        clip, r = self.session.find_job(job_id)
        if clip is None:
            return
        if clip is not self.clip:
            self.bin.select(clip.id)
        if r and r.status == "done":
            self.render = r
            self._shown.clear()
            self._fill_render_box()
            self.set_frame(r.frame_in)
        elif r and r.status == "error":
            self.client.fetch_log(job_id, self._show_log)

    def _show_log(self, job: dict) -> None:
        d = QDialog(self)
        d.setWindowTitle(f"Log: {job.get('name', '')}")
        d.resize(900, 500)
        v = QVBoxLayout(d)
        t = QPlainTextEdit("\n".join(job.get("log", [])))
        t.setReadOnly(True)
        t.setFont(T.mono_font(9))
        v.addWidget(t)
        t.moveCursor(QTextCursor.End)
        d.exec()

    # ================================================================== engine / status
    def _engine_connected(self, on: bool) -> None:
        self.st_engine.setText("● Engine connected" if on else "○ Engine offline, reconnecting…")
        self.st_engine.setStyleSheet(f"color: {T.c('OK' if on else 'WARN')};")

    def _system(self, info: dict) -> None:
        g = info.get("gpu")
        if g:
            self._gpu_total_mb = g["total_mb"]
            self.inspector.small_gpu = g["total_mb"] < 6000
        self.st_gpu.set_info(g)
        self.inspector.set_gpu(g)
        d = info.get("disk")
        if d:
            drive = os.path.splitdrive(d["path"])[0] or d["path"]
            self.st_disk.setText(f"{drive} {d['free_gb']:.1f} GB free")
            self.st_disk.setStyleSheet(f"color: {T.c('ERROR')};" if d["free_gb"] < 5 else "")
            self.inspector.set_disk(f"{drive} {d['free_gb']:.1f} GB free")

    def _message(self, text: str, error: bool = False) -> None:
        self.st_msg.setText(text)
        self.st_msg.setStyleSheet(f"color: {T.c('ERROR')};" if error else "")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(load_settings(), self)
        if dlg.exec() == QDialog.Accepted:
            save_settings(dlg.result_settings())
            self.settings = load_settings().resolved()
            QMessageBox.information(self, "Settings saved",
                                    "Saved. The render engine picks up path changes the next time it starts "
                                    "(it stops on its own 10 minutes after the last render with the app closed).")

    # ================================================================== window events
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        self.import_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ================================================================== layout memory
    def _ui_settings(self) -> QSettings:
        return QSettings(str(state_dir() / "ui.ini"), QSettings.IniFormat)

    def restore_layout(self) -> None:
        q = self._ui_settings()
        if q.value("geometry") is not None:
            self.restoreGeometry(q.value("geometry"))
        for split, key in ((self.main_split, "main_split"), (self.left_split, "left_split")):
            if q.value(key) is not None:
                split.restoreState(q.value(key))
        for name, b in self.panel_toggles.items():
            b.setChecked(str(q.value(f"panel_{name}", "true")).lower() == "true")
        self.set_top_labels(str(q.value("top_labels", "true")).lower() == "true")

    def save_layout(self) -> None:
        q = self._ui_settings()
        q.setValue("geometry", self.saveGeometry())
        q.setValue("main_split", self.main_split.saveState())
        q.setValue("left_split", self.left_split.saveState())
        for name, b in self.panel_toggles.items():
            q.setValue(f"panel_{name}", b.isChecked())
        q.setValue("top_labels", self.top_labels)

    def closeEvent(self, e) -> None:
        self.stop()
        self.save_layout()
        self.session.save()
        self.client.close()
        self.frames.shutdown()
        self.thumbs.shutdown()
        super().closeEvent(e)


class SettingsDialog(QDialog):
    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(640, 0)
        self.s = s
        res = s.resolved()
        form = QFormLayout(self)
        self.fields = {}
        for key, title, is_dir in (("ck_root", "CorridorKey folder", True), ("ck_python", "CorridorKey python", False),
                                   ("cache_dir", "Cache / staging folder", True), ("ffmpeg", "ffmpeg", False)):
            row = QHBoxLayout()
            ed = QLineEdit(getattr(s, key))
            ed.setPlaceholderText(f"auto: {getattr(res, key)}")
            b = QPushButton("…")
            b.setFixedWidth(30)
            b.clicked.connect(lambda _=False, e=ed, d=is_dir: self._browse(e, d))
            row.addWidget(ed, 1)
            row.addWidget(b)
            form.addRow(title, row)
            self.fields[key] = ed
        note = label("Leave a field empty to use the automatic value shown in grey.", "Faint")
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _browse(self, ed: QLineEdit, is_dir: bool) -> None:
        if is_dir:
            p = QFileDialog.getExistingDirectory(self, "Choose folder", ed.text() or ed.placeholderText()[6:])
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Choose program", ed.text())
        if p:
            ed.setText(os.path.normpath(p))

    def result_settings(self) -> Settings:
        s = Settings(**asdict(self.s))
        for key, ed in self.fields.items():
            setattr(s, key, ed.text().strip())
        return s
