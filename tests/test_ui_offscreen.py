"""Builds the real main window headless (no GPU, no engine) and drives its wiring."""
from __future__ import annotations

import os
import subprocess

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    from ckapp.app import theme as T
    a = QApplication.instance() or QApplication([])
    T.apply(a)
    return a


@pytest.fixture
def bare(app, tmp_path, monkeypatch):
    """The window as it first opens: no project yet."""
    monkeypatch.setenv("CK2WB_STATE", str(tmp_path / "state"))
    from ckapp.app.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 850)
    w.show()
    app.processEvents()
    yield w
    w.close()


@pytest.fixture
def win(bare, tmp_path, app):
    assert bare.new_project(str(tmp_path / "proj")) is not None
    app.processEvents()
    return bare


@pytest.fixture
def clip_path(tmp_path):
    p = tmp_path / "plate.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=5",
                    "-pix_fmt", "yuv420p", str(p)], check=True)
    return str(p)


def test_import_select_and_defaults(win, clip_path, app):
    added = win.import_paths([clip_path, clip_path, os.path.dirname(clip_path) + "/nope.txt"])
    assert len(added) == 1 and len(win.project.clips) == 1        # duplicate + non-media skipped
    app.processEvents()
    assert win.clip is added[0] and win.clip.frames == 120
    assert win.timeline.field.maximum() == 119
    assert win.inspector.rb_all.isChecked() and win.inspector.bt_render.isEnabled()


def test_timeline_handles_drive_inspector_and_spec(win, clip_path, app):
    win.import_paths([clip_path])
    win.timeline.rangeChanged.emit(20, 80)          # what dragging the handles emits
    app.processEvents()
    ins = win.inspector
    assert ins.rb_custom.isChecked() and (ins.sp_in.value(), ins.sp_out.value()) == (20, 80)
    spec = win.clip.to_spec("out")
    assert (spec.frame_in, spec.frame_out) == (20, 80)
    assert "Frames 20\u201380 (61)" in ins.lb_summary.text()


def test_set_in_out_at_playhead_and_clear(win, clip_path, app):
    win.import_paths([clip_path])
    win.set_frame(30)
    win._set_point("in")
    win.set_frame(90)
    win._set_point("out")
    assert win.clip.frame_range() == (30, 90)
    assert (win.timeline.ruler.rin, win.timeline.ruler.rout) == (30, 90)
    win.set_frame(10)
    win._set_point("out")                           # out before in drags the in-point along
    assert win.clip.frame_range() == (10, 10)
    win._clear_point("in")
    win._clear_point("out")
    assert win.clip.settings.range_mode == "all" and win.clip.frame_range() == (0, 119)


def test_inspector_spinboxes_update_timeline(win, clip_path, app):
    win.import_paths([clip_path])
    win.inspector.sp_in.setValue(15)
    win.inspector.sp_out.setValue(40)
    app.processEvents()
    assert (win.timeline.ruler.rin, win.timeline.ruler.rout) == (15, 40)
    assert win.clip.settings.range_mode == "custom"


def test_fallback_to_plate_without_render(win, clip_path, app):
    win.import_paths([clip_path])
    win.cb_a.setCurrentIndex(win.cb_a.findData("composite"))
    shown, srcs, reason = win._resolve("composite", 5)
    assert shown == "plate" and reason == "no render yet" and srcs[0][1] == win.clip.path


def test_render_outputs_map_to_source_frames(win, clip_path, app):
    from ckapp.app.model import Render
    win.import_paths([clip_path])
    r = Render("j", "out", 20, 80, "video", status="done",
               outputs={"fg": "fg.mp4", "alpha": "a.mp4", "checker": "c_exr"})
    os.makedirs("c_exr", exist_ok=True)
    try:
        win.clip.renders.append(r)
        win.render = r
        srcs = win._sources_for("composite", 25)
        assert [(s[0], s[1], s[2]) for s in srcs] == [("color", "fg.mp4", 5), ("alpha", "a.mp4", 5)]
        assert win._sources_for("checker", 25)[0][2] == 25          # EXR folders use source numbering
        assert win._resolve("matte", 90)[2].startswith("outside render")
    finally:
        os.rmdir("c_exr")


def test_panel_toggles(win, app):
    win.panel_toggles["inspector"].setChecked(False)
    assert not win.inspector.isVisible()
    win.panel_toggles["media"].setChecked(False)
    assert win.left_split.isVisible()                 # queue still shown
    win.panel_toggles["queue"].setChecked(False)
    assert not win.left_split.isVisible()
    for b in win.panel_toggles.values():
        b.setChecked(True)
    app.processEvents()
    assert win.inspector.isVisible() and win.bin.isVisible() and win.queue.isVisible()
    assert not win.main_split.childrenCollapsible() and not win.left_split.childrenCollapsible()


def test_zoom_menu_keeps_fit(win, app):
    assert win.cb_zoom.itemText(0) == "Fit"
    win.viewer.set_zoom_percent(37)
    win._sync_zoom_box()
    assert win.cb_zoom.itemText(0) == "Fit" and win.cb_zoom.currentIndex() == -1   # shows "Custom"
    assert win.lb_zoom.text() == "37%"
    win.viewer.set_zoom_percent(100)
    win._sync_zoom_box()
    assert win.cb_zoom.currentText() == "100%"
    win.viewer.fit_view()
    win._sync_zoom_box()
    assert win.cb_zoom.currentIndex() == 0


def test_frame_readout_width_is_constant(win, clip_path, app):
    win.import_paths([clip_path])
    widths = []
    for f in (1, 11, 88, 119):
        win.set_frame(f)
        widths.append(win.tr_buttons["play"].mapTo(win, win.tr_buttons["play"].rect().topLeft()).x())
    assert len(set(widths)) == 1, widths


def _wheel(widget, x, delta):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    pos = QPointF(x, 10)
    ev = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(), QPoint(0, delta),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


def test_timeline_zoom_and_pan_stay_on_the_clip(win, clip_path, app):
    win.import_paths([clip_path])
    app.processEvents()
    r = win.timeline.ruler
    fit = r.fit_ppf()
    _wheel(r, 200, -2400)                            # zoom far out: stops at fit
    assert r.fitted and r.ppf == pytest.approx(fit) and r.view_start == 0
    _wheel(r, 200, 1200)                             # zoom in, then pan hard both ways
    assert not r.fitted and r.ppf > fit
    for v in (-1e6, 1e6):
        r.view_start = v
        r._clamp()
        assert 0 <= r.view_start <= r.last - r._usable() / r.ppf + 1e-6
        assert r.x_of(0) <= r.MARGIN + 1e-6 and r.x_of(r.last) >= r.width() - r.MARGIN - 1e-6
    r.fit()
    assert r.view_start == 0 and r.x_of(r.last) == pytest.approx(r.width() - r.MARGIN)


def test_timeline_zoom_to_range_and_drag_range(win, clip_path, app):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    win.import_paths([clip_path])
    win.timeline.rangeChanged.emit(20, 40)
    win._sync_range_to_timeline()
    r = win.timeline.ruler
    r.zoom_to_range()
    assert r.x_of(20) == pytest.approx(r.MARGIN) and r.x_of(40) == pytest.approx(r.width() - r.MARGIN)
    r.fit()

    def mouse(kind, x, button=Qt.LeftButton):
        pos = QPointF(x, r.TRACK_Y + r.TRACK_H / 2)
        QApplication.sendEvent(r, QMouseEvent(kind, pos, r.mapToGlobal(pos), button,
                                              button if kind != QEvent.MouseButtonRelease else Qt.NoButton,
                                              Qt.NoModifier))
    x_mid = r.x_of(30)
    assert r._handle_at(QPointF(x_mid, r.TRACK_Y + 2)) == "move"
    mouse(QEvent.MouseButtonPress, x_mid)
    mouse(QEvent.MouseMove, x_mid + 10 * r.ppf)             # +10 frames
    assert win.clip.frame_range() == (30, 50)
    mouse(QEvent.MouseMove, x_mid + 500 * r.ppf)            # clamped at the clip end
    mouse(QEvent.MouseButtonRelease, x_mid + 500 * r.ppf)
    assert win.clip.frame_range() == (99, 119)
    r._set_range(0, r.last)                                      # "Use entire clip"
    assert win.clip.settings.range_mode == "all"


def test_vram_meter(win, app):
    g = {"name": "Test GPU", "used_mb": 1024, "total_mb": 4096, "util": 3}
    win._system({"gpu": g})
    assert win.st_gpu.fraction() == pytest.approx(0.25) and win.st_gpu._fill() == "TEXT_DIM"
    assert win.inspector.vram.fraction() == pytest.approx(0.25)
    win._system({"gpu": dict(g, used_mb=3990)})
    assert win.st_gpu._fill() == "ERROR"
    win._system({})
    assert win.st_gpu.used_mb is None


def test_top_bar_labels_switch_and_persist(win, app):
    from PySide6.QtCore import Qt
    b = win.panel_toggles["media"]
    assert win.top_labels and b.toolButtonStyle() == Qt.ToolButtonTextBesideIcon and b.text() == "Media"
    wide = b.sizeHint().width()
    win.set_top_labels(False)
    assert all(x.toolButtonStyle() == Qt.ToolButtonIconOnly for x in win.top_buttons)
    assert b.sizeHint().width() < wide
    win.save_layout()
    win.set_top_labels(True)
    win.restore_layout()
    assert not win.top_labels


def test_queue_row_keeps_button_visible_with_long_names(win, app):
    q = win.queue
    win.panel_toggles["media"].setChecked(True)
    win.panel_toggles["queue"].setChecked(True)
    win.main_split.setSizes([240, 900, 320])
    job = {"id": "j1", "status": "done", "name": "Kanye West  Wash Us In The Blood Music Video 4K remaster.mp4",
           "spec": {"frame_in": 4, "frame_out": 15}, "fraction": 1.0, "started": 100, "finished": 186}
    q.reset([job])
    app.processEvents()
    row = q.rows["j1"]
    assert not q.scroll.horizontalScrollBar().isVisible()
    right = row.btn.mapTo(q, row.btn.rect().topRight()).x()
    assert right <= q.width(), (right, q.width())
    assert row.name.overflows() and row.name.toolTip() == job["name"]
    assert row.range.text() == "4–15" and row.stage.text() == "Done in 1m 26s"
    q.remove_job("j1")
    assert not q.rows and q.empty.isVisibleTo(q)


def test_export_settings_reach_the_spec(win, clip_path, app):
    win.import_paths([clip_path])
    ins = win.inspector
    assert ins.lb_export.text() == "H.264 10-bit 4:4:4, CRF 12, .mp4" and not ins.bt_defaults.isEnabled()
    assert ins.lb_compat.isVisibleTo(ins)                         # 4:4:4 compatibility warning
    ins.cb_codec.setCurrentIndex(ins.cb_codec.findData("libx265"))
    ins.cb_pix.setCurrentIndex(ins.cb_pix.findData("yuv420p"))
    ins.cb_rate.setCurrentIndex(ins.cb_rate.findData("bitrate"))
    ins.sp_mbps.setValue(25)
    spec = win.clip.to_spec("o")
    assert (spec.video_codec, spec.pix_fmt, spec.bitrate) == ("libx265", "yuv420p", "25M")
    assert not ins.lb_compat.isVisibleTo(ins) and ins.sp_mbps.isVisibleTo(ins) and not ins.sp_crf.isVisibleTo(ins)
    assert ins.lb_export.text() == "H.265 8-bit 4:2:0, 25 Mb/s, .mp4"
    ins.bt_defaults.click()
    s = win.clip.to_spec("o")
    assert (s.video_codec, s.pix_fmt, s.crf, s.bitrate, s.preset) == ("libx264", "yuv444p10le", 12, "", "medium")
    ins.cb_fmt.setCurrentIndex(ins.cb_fmt.findData("exr"))
    assert not ins.cb_codec.isVisibleTo(ins) and ins.lb_export.text().startswith("OpenEXR half float")


def test_settings_dialog_round_trip(app):
    from ckapp.app.main_window import SettingsDialog
    from ckapp.config import Settings
    d = SettingsDialog(Settings(cache_dir="D:/cache"))
    d.fields["ffmpeg"].setText("C:/tools/ffmpeg.exe")
    s = d.result_settings()
    assert s.cache_dir == "D:/cache" and s.ffmpeg == "C:/tools/ffmpeg.exe" and s.ck_root == ""


# ------------------------------------------------------------------------- projects
def test_starts_on_the_start_page_and_reopens_the_last_project(bare, tmp_path, clip_path, app, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from ckapp.app.main_window import MainWindow
    assert bare.project is None and bare.pages.currentIndex() == 0
    assert bare.bt_project.text() == "No project" and not bare.panel_toggles["media"].isVisible()
    monkeypatch.setattr("ckapp.app.start.NewProjectDialog.exec", lambda self: QDialog.Rejected)
    assert bare.import_paths([clip_path]) == []                       # no project: cancelled the dialog
    p = bare.new_project(str(tmp_path / "Shoot day 1"))
    clip = bare.import_paths([clip_path])[0]
    assert bare.pages.currentIndex() == 1 and bare.windowTitle().startswith("Shoot day 1 - ")
    assert clip.render_root() == os.path.join(p.root, "renders", "plate")
    assert clip.next_render_dir()[0] == os.path.join(p.root, "renders", "plate", "render_001")
    bare.close()
    again = MainWindow()                                               # same state folder
    try:
        assert again.project is not None and again.project.path == p.path
        assert [c.id for c in again.project.clips] == [clip.id] and again.clip.id == clip.id
        again.close_project()
        assert again.pages.currentIndex() == 0 and again.start.recent.count() == 1
    finally:
        again.close()


def test_bring_in_old_session(bare, tmp_path, clip_path, app, monkeypatch):
    import dataclasses
    import json
    from ckapp.app.model import Clip, Render
    from ckapp.config import state_dir
    old = Clip(clip_path, "video", 120, 24, 320, 180)
    old.renders.append(Render("j1", str(tmp_path / "plate_ck2" / "render_001"), 0, 119, "video", status="done"))
    (state_dir() / "session.json").write_text(json.dumps({"version": 1, "clips": [dataclasses.asdict(old)]}))
    bare.close_project()
    assert bare.start.bring.isVisibleTo(bare.start) and "Bring in my 1 clip " in bare.start.bring.text()
    monkeypatch.setattr(bare, "_new_project_dialog", lambda: bare.new_project(str(tmp_path / "migrated")))
    bare._bring_in()
    assert len(bare.project.clips) == 1 and bare.clip.renders[0].out_dir == str(tmp_path / "plate_ck2" / "render_001")
    assert (state_dir() / "session.migrated.json").exists() and not (state_dir() / "session.json").exists()


def test_new_project_dialog_checks_the_name(app, tmp_path):
    from ckapp.app.project import Project
    from ckapp.app.start import NewProjectDialog
    d = NewProjectDialog(str(tmp_path))
    assert d.parent_dir() == str(tmp_path) and d.ed_name.text() == "Untitled project"
    Project.create(tmp_path / "Taken")
    for name, ok in (("", False), ("a:b", False), ("trailing.", False), ("Taken", False), ("Fine name", True)):
        d.ed_name.setText(name)
        assert (d.problem(name) is None) == ok, name
        assert d.bb.buttons()[0].isEnabled() == ok or d.bb.buttons()[1].isEnabled() == ok


def test_held_jobs_in_queue_and_bin(win, clip_path, app):
    win.import_paths([clip_path])
    clip = win.clip
    from ckapp.app.model import Render
    clip.renders.append(Render("h1", os.path.join(clip.render_root(), "render_001"), 0, 119, "video", status="held"))
    job = {"id": "h1", "status": "held", "name": clip.name, "stage": "Waiting for Start", "spec": {}, "fraction": 0}
    win.queue.reset([job])
    win._refresh_clip_status(clip)
    row = win.queue.rows["h1"]
    assert row.start.isVisibleTo(row) and win.queue.start_all_btn.isVisibleTo(win.queue)
    assert win.bin.info[clip.id]["status"] == "held"
    removed = []
    win.queue.removeRequested.connect(removed.append)
    win.queue._clear_finished()
    assert removed == []                                             # held jobs aren't finished
    win._remove_clip(clip.id)
    assert win.project.find(clip.id) is clip                         # can't remove a clip with held renders
    win._job_updated(dict(job, status="queued", stage="Queued"))
    assert not row.start.isVisibleTo(row) and not win.queue.start_all_btn.isVisibleTo(win.queue)
    assert clip.renders[0].status == "queued"


def test_add_to_queue_refused_by_an_older_engine(win, clip_path, app):
    win.import_paths([clip_path])
    sent = []
    win.client.connected = True
    win.client.info = {"host": "x", "port": 1, "token": "t", "version": "0.3.1"}
    win.client.submit = lambda spec, done, hold=False: sent.append((spec, hold))
    win._render(win.clip, hold=True)
    assert sent == [] and "can't hold" in win.st_msg.text()
    from ckapp import __version__
    win.client.info["version"] = __version__
    win._render(win.clip, hold=True)
    spec, hold = sent[0]
    assert hold and spec["project"] == str(win.project.path)
    assert spec["output_dir"] == os.path.join(win.project.root, "renders", "plate", "render_001")


def test_render_finishing_in_another_project_updates_its_file(win, tmp_path, clip_path, app):
    from ckapp.app.model import Render
    from ckapp.app.project import Project
    win.import_paths([clip_path])
    first = win.project
    out = os.path.join(win.clip.render_root(), "render_001")
    win.clip.renders.append(Render("r1", out, 0, 119, "video", status="running"))
    first.save()
    win.new_project(str(tmp_path / "second"))
    job = {"id": "r1", "status": "done", "name": "plate.mp4", "outputs": {"fg": os.path.join(out, "plate_fg.mp4")},
           "spec": {"project": str(first.path)}}
    win._job_updated(job)
    r = Project.open(first.path).clips[0].renders[0]
    assert r.status == "done" and r.outputs["fg"] == os.path.join(out, "plate_fg.mp4")
    win._job_activated("r1")                                        # clicking it opens its project
    assert win.project.path == first.path and win.render.job_id == "r1"


def test_gpu_fit_estimate_in_inspector(win, clip_path, app):
    win.import_paths([clip_path])
    win._system({"gpu": {"name": "GPU", "used_mb": 500, "total_mb": 4096, "util": 0}})
    assert "720p with 4 GB of GPU memory" in win.inspector.lb_fits.text()

def test_moved_project_keeps_its_outputs_when_the_engine_reports_old_paths(win, tmp_path, clip_path, app):
    import shutil
    from ckapp.app.model import Render
    win.import_paths([clip_path])
    old_root = win.project.root
    out = os.path.join(win.clip.render_root(), "render_001")
    win.clip.renders.append(Render("m1", out, 0, 119, "video", status="done",
                                   outputs={"fg": os.path.join(out, "plate_fg.mp4")}))
    win.close_project()
    shutil.move(old_root, str(tmp_path / "moved"))
    assert win.open_project(str(tmp_path / "moved"))
    job = {"id": "m1", "status": "done", "spec": {"output_dir": out, "project": os.path.join(old_root, "project.json")},
           "outputs": {"fg": os.path.join(out, "plate_fg.mp4"), "alpha": os.path.join(out, "plate_alpha.mp4")}}
    win._apply_job_list([job])
    new_out = os.path.join(str(tmp_path / "moved"), "renders", "plate", "render_001")
    r = win.clip.renders[0]
    assert r.out_dir == new_out and r.outputs == {"fg": os.path.join(new_out, "plate_fg.mp4"),
                                                  "alpha": os.path.join(new_out, "plate_alpha.mp4")}


def test_composite_view_previews_despill_live(win, clip_path, app):
    from ckapp.app.model import Render
    win.import_paths([clip_path])
    r = Render("j", "out", 0, 119, "video", status="done", outputs={"fg": clip_path, "alpha": clip_path})
    win.clip.renders.append(r)
    win.render = r
    win.cb_a.setCurrentIndex(win.cb_a.findData("composite"))
    win.inspector.sl_despill._set(0.8, from_slider=True)          # the user drags Despill
    app.processEvents()
    a = win.viewer.a
    assert a.despill == 0.8 and "despill 0.80" in a.label        # no re-render needed
    assert win._side("a", "fg").despill == 0.0                  # Foreground stays the raw output


def test_composite_despill_shader_matches_upstream(win, app):
    """Draw a known spill colour through the real shader and compare with upstream's formula."""
    import numpy as np
    from ckapp.app.media import Frame
    from ckapp.app.viewer import MODE_COMPOSITE, Side
    v = win.viewer
    app.processEvents()
    if not (v._ok and v._prog):
        pytest.skip("no OpenGL 3.3 here")
    rgb = np.array([0.30, 0.70, 0.20])
    color = Frame(np.ascontiguousarray(np.tile((rgb[::-1] * 255).round().astype(np.uint8), (64, 64, 1))))
    alpha = Frame(np.full((64, 64, 1), 255, np.uint8))
    v.set_sides(Side("c", MODE_COMPOSITE, color, alpha, despill=0.6), Side())
    v.set_layout("single")
    got = v.grab_rgb()[v.height() // 2, v.width() // 2] / 255.0
    c = (rgb * 255).round() / 255
    spill = max(c[1] - (c[0] + c[2]) / 2, 0)
    full = np.array([c[0] + spill / 2, c[1] - spill, c[2] + spill / 2])
    want = c * 0.4 + full * 0.6
    assert np.abs(got - want).max() < 2.5 / 255, (got, want)


# ------------------------------------------------------------------------- click to mask
class FakeMaskEngine:
    """Answers the client's mask calls at once: the 'mask' is a disc per keep-click, minus remove-clicks, or the
    box. Checks that every request names a plate frame the app really wrote at clip size."""

    def __init__(self, win, model=True, old=False, defer=False):
        self.win, self.calls, self.defer, self.pending = win, [], defer, []
        self.status = {"model": model, "downloading": False, "running": False, "device": None, "error": ""}
        c = win.client
        if old:                                                  # an engine from before masks
            c.mask_status = lambda done, fail: fail("Not Found", 404)
        else:
            c.mask_status = lambda done, fail: done(dict(self.status))
        c.mask_download = self.download
        c.mask_open = self.open
        c.mask_predict = self.predict
        c.mask_stop = lambda: self.calls.append(("stop",))

    def _emit(self):
        self.win.client.maskStatus.emit(dict(self.status))

    def download(self, done, fail):
        self.calls.append(("download",))
        self.status["model"] = True
        done(dict(self.status))

    def open(self, image, done, fail):
        self.calls.append(("open", image))
        if self.defer:                                           # still loading the model: answer later
            self.pending.append(lambda: done({"ok": True, "width": 320, "height": 180, "device": "cuda"}))
            return
        self.status["running"] = True
        self._emit()
        done({"ok": True, "width": 320, "height": 180, "device": "cuda"})

    def predict(self, image, points, box, out, done, fail):
        import cv2
        import numpy as np
        from ckapp.app.media import write_png
        assert cv2.imread(image).shape == (180, 320, 3)
        self.calls.append(("predict", [list(p) for p in points], box))
        m = np.zeros((180, 320), np.uint8)
        if box:
            x0, y0, x1, y1 = (int(v) for v in box)
            m[y0:y1, x0:x1] = 255
        for x, y, keep in points:
            cv2.circle(m, (int(x), int(y)), 20, 255 if keep else 0, -1)
        write_png(out, m)
        self.status["running"] = True
        self._emit()
        done({"ok": True, "score": 0.9, "device": "cuda", "width": 320, "height": 180})


def _settle(app, cond, timeout=10.0):
    import time
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return cond()


def _click(viewer, x, y, button=None):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(viewer, button or Qt.LeftButton, Qt.NoModifier, viewer.widget_at(QPointF(x, y)).toPoint())


def test_mask_tool_holds_single_plate_and_restores_the_layout(win, tmp_path, clip_path, app):
    win.import_paths([clip_path])
    win.masks.cache_dir = str(tmp_path / "cache")
    fake = FakeMaskEngine(win)
    win.seg_layout.set_current("wipe", emit=True)
    win.cb_a.setCurrentIndex(win.cb_a.findData("composite"))
    win.bt_mask.setChecked(True)
    assert win.viewer.mask_tool and win.viewer.layout_mode == "single" and win.cb_a.currentData() == "plate"
    assert not win.seg_layout.isEnabled() and not win.cb_a.isEnabled() and win.mask_bar.isVisible()
    assert all(s.isEnabled() for s in win.mask_shortcuts)
    win.mask_shortcuts[0].activated.emit()                         # Esc
    assert not win.viewer.mask_tool and not win.bt_mask.isChecked() and not win.mask_bar.isVisible()
    assert win.viewer.layout_mode == "wipe" and win.cb_a.currentData() == "composite" and win.seg_layout.isEnabled()
    assert not any(s.isEnabled() for s in win.mask_shortcuts)
    assert fake.calls[-1] == ("stop",)                             # the model's GPU memory is let go
    win._select_clip(None)
    win.bt_mask.setChecked(True)                                   # nothing to mask
    assert not win.bt_mask.isChecked() and not win.viewer.mask_tool


def test_mask_clicks_box_undo_and_use_as_hint(win, tmp_path, clip_path, app):
    import cv2
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    win.import_paths([clip_path])
    win.masks.cache_dir = str(tmp_path / "cache")
    fake = FakeMaskEngine(win)
    win.set_frame(30)
    win.bt_mask.setChecked(True)
    s = win.masks.current
    assert s is not None and s.frame == 30
    assert _settle(app, lambda: ("open", s.image) in fake.calls)     # frame written, embedded before any click
    v = win.viewer
    _click(v, 160, 90)
    assert s.points and abs(s.points[0][0] - 160) < 2 and abs(s.points[0][1] - 90) < 2 and s.points[0][2] == 1
    assert s.fresh() and s.mask[90, 160] == 255 and v.mask is not None and v.mask_points == s.points
    _click(v, 40, 40, Qt.RightButton)
    assert s.points[-1][2] == 0 and fake.calls[-1][1][-1][2] == 0
    a, b = v.widget_at(QPointF(200, 100)).toPoint(), v.widget_at(QPointF(300, 170)).toPoint()
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(v, b)
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, b)
    assert s.box and abs(s.box[0] - 200) < 2 and abs(s.box[3] - 170) < 2 and len(s.points) == 2   # a drag: no point
    assert fake.calls[-1][2] == s.box
    win.mask_shortcuts[1].activated.emit()                         # Ctrl+Z
    assert s.box is None and len(s.points) == 2 and s.fresh()
    assert "1 keep, 1 remove" in win.lb_mask.text() and win.bt_mask_use.isEnabled()

    win.bt_mask_use.click()
    st = win.clip.settings
    hint = os.path.join(win.project.root, "masks", "plate", "hint_f000030.png")
    assert (st.hint_mode, st.hint_path, st.hint_frame) == ("first", hint, 30)
    assert cv2.imread(hint, cv2.IMREAD_UNCHANGED).shape == (180, 320)     # one channel, clip size
    assert win.clip.frame_range() == (30, 119) and (win.timeline.ruler.rin, win.timeline.ruler.rout) == (30, 119)
    assert "in-point moved from 0 to 30" in win.st_msg.text()
    ins = win.inspector
    assert ins.lb_hint_at.text().startswith("Drawn on frame 30") and not ins.hint_warn.isVisibleTo(ins)
    spec = win.clip.to_spec("out")
    assert (spec.hint_mode, spec.hint_path, spec.frame_in) == ("first", hint, 30)
    win.bt_mask_use.click()                                        # again: a new file, the first is kept
    assert win.clip.settings.hint_path.endswith("hint_f000030_2.png") and os.path.isfile(hint)

    win.inspector.sp_in.setValue(10)                               # in-point moved off the hint's frame
    assert ins.hint_warn.isVisibleTo(ins) and "drawn on frame 30" in ins.lb_hint_warn.text()
    ins.bt_hint_frame.click()
    assert win.clip.frame_range()[0] == 30 and not ins.hint_warn.isVisibleTo(ins)
    win.bt_mask.setChecked(False)
    assert ("stop",) in fake.calls


def test_mask_edits_wait_for_the_model_download(win, tmp_path, clip_path, app):
    win.import_paths([clip_path])
    win.masks.cache_dir = str(tmp_path / "cache")
    fake = FakeMaskEngine(win, model=False)
    win.bt_mask.setChecked(True)
    assert win.bt_mask_dl.isVisibleTo(win.mask_bar) and "isn't downloaded" in win.lb_mask.text()
    s = win.masks.current
    assert _settle(app, lambda: s.image_ready)
    _click(win.viewer, 100, 60)
    assert s.points and not any(c[0] == "predict" for c in fake.calls)    # nothing to ask yet
    win.bt_mask_dl.click()
    assert fake.calls[0] == ("download",) and s.fresh() and not win.bt_mask_dl.isVisibleTo(win.mask_bar)


def test_leaving_while_the_model_loads_still_frees_it(win, tmp_path, clip_path, app):
    win.import_paths([clip_path])
    win.masks.cache_dir = str(tmp_path / "cache")
    fake = FakeMaskEngine(win, defer=True)
    win.bt_mask.setChecked(True)
    assert _settle(app, lambda: fake.pending)                     # the first open is out: the model is loading
    assert "Loading the mask model" in win.lb_mask.text()
    win.mask_shortcuts[0].activated.emit()                         # Esc before it finished
    assert fake.calls[-1] == ("stop",)
    fake.calls.clear()
    fake.pending.pop()()                                           # the load finishes after all
    assert fake.calls == [("stop",)] and not win.masks.busy()      # ...and is let go again


def test_old_mask_pngs_are_cleaned_from_the_cache(app, tmp_path):
    import time
    from ckapp.app.client import EngineClient
    from ckapp.app.masking import MaskController
    folder = tmp_path / "masks"
    folder.mkdir()
    old, new = folder / "c_f000001.png", folder / "c_f000002.png"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    t = time.time() - 13 * 3600
    os.utime(old, (t, t))
    MaskController(EngineClient(), None, str(tmp_path))
    assert not old.exists() and new.exists()


def test_mask_tool_on_an_engine_without_masks(win, tmp_path, clip_path, app):
    win.import_paths([clip_path])
    win.masks.cache_dir = str(tmp_path / "cache")
    fake = FakeMaskEngine(win, old=True)
    win.bt_mask.setChecked(True)
    _click(win.viewer, 100, 60)
    assert "can't make masks" in win.lb_mask.text() and not any(c[0] == "predict" for c in fake.calls)
    assert not win.bt_mask_use.isEnabled() and not win.bt_mask_dl.isVisibleTo(win.mask_bar)


def test_renders_finished_while_closed_reach_their_own_project(win, tmp_path, clip_path, app):
    from ckapp.app.model import Render
    from ckapp.app.project import Project
    win.import_paths([clip_path])
    a = win.project
    out = os.path.join(win.clip.render_root(), "render_001")
    win.clip.renders.append(Render("c1", out, 0, 119, "video", status="running"))
    a.save()
    win.new_project(str(tmp_path / "b"))
    job = {"id": "c1", "status": "done", "name": "plate.mp4", "stage": "", "fraction": 1,
           "spec": {"project": str(a.path), "output_dir": out}, "outputs": {"fg": os.path.join(out, "plate_fg.mp4")}}
    win._jobs_reset([job])                                           # the engine's hello after a relaunch
    r = Project.open(a.path).clips[0].renders[0]
    assert r.status == "done" and r.outputs == {"fg": os.path.join(out, "plate_fg.mp4")}