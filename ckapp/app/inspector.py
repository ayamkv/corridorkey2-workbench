"""Right-hand panel: per-clip settings (Inspector) and the Deliver box."""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QRadioButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from . import theme as T
from .model import PIX_NAMES, VIDEO_DEFAULTS, Clip, describe_export
from . import icons
from .widgets import ElidedLabel, Section, SliderRow, VramMeter, combo, hline, label, panel_header

HINT_TIP = ("A matte where white is the subject and black the background.\n"
            "First frame: one image for the in-point frame; the model carries it forward.\n"
            "Hint video: one matte per frame (a video or a folder of images).")
MIN_WIDTH = 300


class Inspector(QWidget):
    changed = Signal()                      # any setting edited
    rangeEdited = Signal()                  # range edited here (timeline must follow)
    renderRequested = Signal()
    setInRequested = Signal()
    setOutRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setMinimumWidth(MIN_WIDTH)
        self.clip: Optional[Clip] = None
        self._loading = False
        self.small_gpu = False
        self._disk = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(panel_header("inspector", "Inspector"))
        outer.addWidget(hline())

        scroll = QScrollArea()
        scroll.setObjectName("Panel")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self._build_range()
        self._build_memory()
        self._build_hint()
        self._build_despill()
        self._build_input()
        self._build_output()
        self._build_export()
        self.body.addStretch(1)

        outer.addWidget(hline())
        self._build_deliver(outer)
        self.set_clip(None)

    # ------------------------------------------------------------------------- sections
    def _build_range(self) -> None:
        s = Section("Frame range")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        self.rb_all = QRadioButton("Entire clip")
        self.rb_custom = QRadioButton("In to out")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_all)
        grp.addButton(self.rb_custom)
        h.addWidget(self.rb_all)
        h.addWidget(self.rb_custom)
        h.addStretch(1)
        s.full(row)
        self.sp_in, self.sp_out = QSpinBox(), QSpinBox()
        for sp in (self.sp_in, self.sp_out):
            sp.setKeyboardTracking(False)
            sp.setFixedWidth(72)
            sp.setFont(T.num_font(9.5))
        b_in, b_out = QPushButton("Set at playhead"), QPushButton("Set at playhead")
        b_in.setToolTip("Set the in-point to the playhead (I). Alt+I clears it.")
        b_out.setToolTip("Set the out-point to the playhead (O). Alt+O clears it.")
        b_in.clicked.connect(self.setInRequested)
        b_out.clicked.connect(self.setOutRequested)
        for text, sp, b in (("In", self.sp_in, b_in), ("Out", self.sp_out, b_out)):
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(sp)
            hl.addWidget(b, 1)
            s.row(text, w)
        self.lb_dur = label("", "Faint")
        s.full(self.lb_dur)
        self.rb_all.toggled.connect(self._range_ui)
        self.sp_in.valueChanged.connect(self._range_ui)
        self.sp_out.valueChanged.connect(self._range_ui)
        self.body.addWidget(s)

    def _build_memory(self) -> None:
        s = Section("GPU memory")
        self.vram = VramMeter(compact=False)
        s.full(self.vram)
        self.cb_mem = combo([
            ("Auto", "auto", "CorridorKey picks a window size from free GPU memory, per clip."),
            ("Low VRAM", "low", "Stages work through the cache folder on disk: slower, but fits small GPUs."),
            ("Manual", "manual", "Set the temporal window yourself.")])
        s.row("Memory", self.cb_mem)
        self.sp_chunk, self.sp_stride = QSpinBox(), QSpinBox()
        for sp in (self.sp_chunk, self.sp_stride):
            sp.setRange(1, 200)
            sp.setFixedWidth(72)
            sp.setFont(T.num_font(9.5))
        self.lb_chunk = s.row("Window", self.sp_chunk, "Frames per temporal window (hann_chunk)")
        self.lb_stride = s.row("Stride", self.sp_stride, "Frames between windows (hann_stride)")
        self.ck_manual_low = QCheckBox("Stage through disk (low VRAM)")
        s.full(self.ck_manual_low)
        self.lb_mem_tip = label("", "Faint")
        self.lb_mem_tip.setWordWrap(True)
        s.full(self.lb_mem_tip)
        self.cb_mem.currentIndexChanged.connect(self._edited)
        for w in (self.sp_chunk, self.sp_stride):
            w.valueChanged.connect(self._edited)
        self.ck_manual_low.toggled.connect(self._edited)
        self.body.addWidget(s)

    def _build_hint(self) -> None:
        s = Section("Alpha hint")
        self.cb_hint = combo([
            ("None", "none", "The model picks the subject on its own."),
            ("First frame", "first", "One matte for the in-point frame; carried forward."),
            ("Hint video", "video", "A matte for every frame (video or image folder).")])
        s.row("Hint", self.cb_hint, HINT_TIP)
        pick = QWidget()
        h = QHBoxLayout(pick)
        h.setContentsMargins(0, 0, 0, 0)
        self.lb_hint = ElidedLabel("None attached", "PathBox")
        self.bt_hint = QPushButton("Choose…")
        self.bt_hint_clear = QPushButton("Clear")
        h.addWidget(self.lb_hint, 1)
        h.addWidget(self.bt_hint)
        h.addWidget(self.bt_hint_clear)
        self.lb_hint_row = s.row("Matte", pick)
        self.sl_hint_q = SliderRow(0.0, 1.0, 0.95)
        self.lb_hint_q = s.row("Strength", self.sl_hint_q, "How much to trust the hint (hint_quality)")
        self.ck_carry = QCheckBox("Carry the hint between frames")
        self.ck_carry.setToolTip("Off: use the hint video literally on every frame (--no_carry_hint)")
        s.full(self.ck_carry)
        self.sl_carry_q = SliderRow(0.0, 1.0, 0.95)
        self.lb_carry_q = s.row("Carry", self.sl_carry_q, "Trust in the carried hint (carry_hint_quality)")
        self.cb_hint.currentIndexChanged.connect(self._edited)
        self.bt_hint.clicked.connect(self._choose_hint)
        self.bt_hint_clear.clicked.connect(self._clear_hint)
        self.sl_hint_q.valueChanged.connect(self._edited)
        self.sl_carry_q.valueChanged.connect(self._edited)
        self.ck_carry.toggled.connect(self._edited)
        self.body.addWidget(s)

    def _build_despill(self) -> None:
        s = Section("Despill")
        self.sl_despill = SliderRow(0.0, 1.0, 0.5)
        s.row("Amount", self.sl_despill, "Green/blue spill removal on the checker and cutout outputs")
        self.sl_despill.valueChanged.connect(self._edited)
        self.body.addWidget(s)

    def _build_input(self) -> None:
        s = self.sec_input = Section("Image sequence")
        self.ck_linear = QCheckBox("Frames are scene-linear (EXR plates)")
        s.full(self.ck_linear)
        self.sp_fps = SliderRow(1.0, 120.0, 24.0, decimals=3)
        s.row("FPS", self.sp_fps)
        self.ck_linear.toggled.connect(self._edited)
        self.sp_fps.valueChanged.connect(self._edited)
        self.body.addWidget(s)

    def _build_output(self) -> None:
        s = Section("Outputs")
        grid_w = QWidget()
        g = QGridLayout(grid_w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(6)
        self.ck_out = {}
        for i, (key, text, tip) in enumerate((
                ("alpha", "Matte", "Alpha matte"),
                ("fg", "Foreground", "Predicted foreground colour"),
                ("checker", "Checker preview", "Despilled foreground over a checkerboard"),
                ("cutout", "Cutout", "Foreground × alpha with an alpha channel (ProRes 4444 or EXR)"))):
            cb = QCheckBox(text)
            cb.setToolTip(tip)
            cb.toggled.connect(self._edited)
            g.addWidget(cb, i // 2, i % 2)
            self.ck_out[key] = cb
        s.full(grid_w)
        self.ck_cutout_lin = QCheckBox("Cutout in linear colour")
        s.full(self.ck_cutout_lin)
        self.ck_cutout_lin.toggled.connect(self._edited)
        self.body.addWidget(s)

    def _build_export(self) -> None:
        s = Section("Export")
        self.cb_fmt = combo([("Video", "video", "Display-referred previews you can play: sRGB, clipped to 0–1"),
                             ("EXR sequence", "exr", "Unclamped scene-linear OpenEXR, one folder per output")])
        s.row("Format", self.cb_fmt)
        self.cb_exr = combo([("Half float", "half", "16-bit float (VFX standard)"),
                             ("Full float", "float", "32-bit float")])
        self.lb_exr = s.row("Precision", self.cb_exr)
        self.cb_codec = combo([("H.264", "libx264", "Widest support. CorridorKey's default."),
                               ("H.265 (HEVC)", "libx265", "Smaller files at the same quality; slower to encode")])
        self.lb_codec = s.row("Codec", self.cb_codec)
        self.cb_pix = combo([
            ("10-bit 4:4:4", "yuv444p10le", "Full colour resolution. CorridorKey's default. Many players can't open it."),
            ("10-bit 4:2:2", "yuv422p10le", "Half horizontal colour resolution"),
            ("10-bit 4:2:0", "yuv420p10le", "Quarter colour resolution, 10-bit"),
            ("8-bit 4:2:0", "yuv420p", "Plays everywhere: browsers, phones, QuickTime, chat apps")])
        self.lb_pix = s.row("Pixels", self.cb_pix)
        rate = QWidget()
        h = QHBoxLayout(rate)
        h.setContentsMargins(0, 0, 0, 0)
        self.cb_rate = combo([("Constant quality", "crf", "CRF: the encoder keeps quality steady; size varies"),
                              ("Bitrate", "bitrate", "A target data rate; quality varies")])
        self.sp_crf = QSpinBox()
        self.sp_crf.setRange(0, 51)
        self.sp_crf.setPrefix("CRF ")
        self.sp_crf.setToolTip("Lower is better and bigger. 12 (default) is near-lossless; 18 is visually lossless"
                               " for most footage; 23 is the x264 everyday default.")
        self.sp_mbps = QDoubleSpinBox()
        self.sp_mbps.setRange(1, 2000)
        self.sp_mbps.setDecimals(0)
        self.sp_mbps.setSuffix(" Mb/s")
        for sp in (self.sp_crf, self.sp_mbps):
            sp.setFixedWidth(86)
            sp.setFont(T.num_font(9.5))
            sp.setKeyboardTracking(False)
        h.addWidget(self.cb_rate, 1)
        h.addWidget(self.sp_crf)
        h.addWidget(self.sp_mbps)
        self.lb_rate = s.row("Quality", rate)
        self.cb_preset = combo([(p.capitalize() + (" (default)" if p == "medium" else ""), p,
                                 "Slower presets make smaller files at the same quality; output quality is set above")
                                for p in ("ultrafast", "veryfast", "faster", "fast", "medium", "slow", "slower",
                                          "veryslow")])
        self.lb_preset = s.row("Speed", self.cb_preset)
        self.lb_export_info = QLabel("")
        self.lb_export_info.setObjectName("Faint")
        self.lb_export_info.setWordWrap(True)
        s.full(self.lb_export_info)
        self.lb_compat = QLabel("")
        self.lb_compat.setWordWrap(True)
        self.lb_compat.setStyleSheet(f"color: {T.c('WARN')}; font-size: 8.5pt;")
        s.full(self.lb_compat)
        self.bt_defaults = QPushButton("Use CorridorKey defaults")
        self.bt_defaults.setToolTip("H.264, 10-bit 4:4:4, CRF 12, medium: what infer.py uses on its own")
        self.bt_defaults.clicked.connect(self._video_defaults)
        s.full(self.bt_defaults)
        for cb in (self.cb_fmt, self.cb_exr, self.cb_codec, self.cb_pix, self.cb_rate, self.cb_preset):
            cb.currentIndexChanged.connect(self._edited)
        self.sp_crf.valueChanged.connect(self._edited)
        self.sp_mbps.valueChanged.connect(self._edited)
        self.body.addWidget(s)

    def _video_defaults(self) -> None:
        if self.clip is None:
            return
        for k, v in VIDEO_DEFAULTS.items():
            setattr(self.clip.settings, k, v)
        self.set_clip(self.clip)
        self.changed.emit()

    def _build_deliver(self, outer: QVBoxLayout) -> None:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 8, 12, 12)
        v.setSpacing(7)
        title = QHBoxLayout()
        title.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(icons.svg("deliver", "TEXT_DIM", 15).pixmap(15, 15))
        title.addWidget(ic)
        title.addWidget(label("Deliver", "SectionTitle"))
        title.addStretch(1)
        v.addLayout(title)

        head = QHBoxLayout()
        head.addWidget(label("Output folder", "Dim"))
        head.addStretch(1)
        self.bt_outdir = QPushButton("Choose…")
        self.bt_outdir.setToolTip("Where renders go. Default: next to the clip. Right-click to reset.")
        self.bt_outdir.clicked.connect(self._choose_outdir)
        self.bt_outdir.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bt_outdir.customContextMenuRequested.connect(self._reset_outdir)
        head.addWidget(self.bt_outdir)
        v.addLayout(head)
        self.lb_outdir = ElidedLabel("", "PathBox")
        v.addWidget(self.lb_outdir)
        self.lb_saveas = label("", "Faint")
        v.addWidget(self.lb_saveas)

        self.lb_export = QLabel("")
        self.lb_export.setObjectName("Dim")
        self.lb_export.setWordWrap(True)
        self.lb_export.setToolTip("Change these in Export, above")
        v.addWidget(self.lb_export)

        self.lb_summary = QLabel("")
        self.lb_summary.setObjectName("Faint")
        self.lb_summary.setWordWrap(True)
        v.addWidget(self.lb_summary)
        self.bt_render = QPushButton("Render")
        self.bt_render.setObjectName("Primary")
        self.bt_render.setIcon(icons.svg("render", "ACCENT_FG", 16))
        self.bt_render.setIconSize(QSize(16, 16))
        self.bt_render.setMinimumHeight(34)
        self.bt_render.setToolTip("Queue this clip with these settings (Ctrl+R)")
        self.bt_render.clicked.connect(self.renderRequested)
        v.addWidget(self.bt_render)
        outer.addWidget(box)

    # ------------------------------------------------------------------------- binding
    def set_clip(self, clip: Optional[Clip]) -> None:
        self.clip = clip
        self.setEnabled(clip is not None)
        if clip is None:
            self.lb_outdir.set_full_text("")
            self.lb_saveas.setText("")
            self.lb_summary.setText("Import a clip to start.")
            return
        s = clip.settings
        self._loading = True
        try:
            self.sp_in.setRange(0, clip.last_frame)
            self.sp_out.setRange(0, clip.last_frame)
            first, last = clip.frame_range()
            (self.rb_custom if s.range_mode == "custom" else self.rb_all).setChecked(True)
            self.sp_in.setValue(first)
            self.sp_out.setValue(last)
            self.cb_mem.setCurrentIndex(max(0, self.cb_mem.findData(s.memory)))
            self.sp_chunk.setValue(s.hann_chunk)
            self.sp_stride.setValue(s.hann_stride)
            self.ck_manual_low.setChecked(s.manual_low_vram)
            self.cb_hint.setCurrentIndex(max(0, self.cb_hint.findData(s.hint_mode)))
            self.sl_hint_q.set_value(s.hint_quality)
            self.ck_carry.setChecked(s.carry_hint)
            self.sl_carry_q.set_value(s.carry_hint_quality)
            self.sl_despill.set_value(s.despill)
            self.ck_linear.setChecked(s.frame_dir_linear)
            self.sp_fps.set_value(s.frame_dir_fps)
            for k, cb in self.ck_out.items():
                cb.setChecked(k in s.outputs)
            self.cb_fmt.setCurrentIndex(max(0, self.cb_fmt.findData(s.output_format)))
            self.cb_exr.setCurrentIndex(max(0, self.cb_exr.findData(s.exr_dtype)))
            self.ck_cutout_lin.setChecked(s.cutout_linear)
            self.cb_codec.setCurrentIndex(max(0, self.cb_codec.findData(s.video_codec)))
            self.cb_pix.setCurrentIndex(max(0, self.cb_pix.findData(s.pix_fmt)))
            self.cb_rate.setCurrentIndex(max(0, self.cb_rate.findData(s.rate_mode)))
            self.sp_crf.setValue(s.crf)
            self.sp_mbps.setValue(s.bitrate_mbps)
            self.cb_preset.setCurrentIndex(max(0, self.cb_preset.findData(s.preset)))
        finally:
            self._loading = False
        self._refresh()

    def set_range(self, first: int, last: int, custom: bool = True) -> None:
        """Called when the timeline handles move."""
        if self.clip is None:
            return
        self._loading = True
        (self.rb_custom if custom else self.rb_all).setChecked(True)
        self.sp_in.setValue(first)
        self.sp_out.setValue(last)
        self._loading = False
        self._store()
        self._refresh()

    def set_gpu(self, gpu: Optional[dict]) -> None:
        self.vram.set_info(gpu)

    def set_disk(self, text: str) -> None:
        if text != self._disk:
            self._disk = text
            self._refresh()

    def _range_ui(self, *_) -> None:
        if self._loading:
            return
        if self.sender() in (self.sp_in, self.sp_out):
            self._loading = True
            self.rb_custom.setChecked(True)
            if self.sp_out.value() < self.sp_in.value():
                if self.sender() is self.sp_in:
                    self.sp_out.setValue(self.sp_in.value())
                else:
                    self.sp_in.setValue(self.sp_out.value())
            self._loading = False
        self._store()
        self._refresh()
        self.rangeEdited.emit()
        self.changed.emit()

    def _edited(self, *_) -> None:
        if self._loading or self.clip is None:
            return
        self._store()
        self._refresh()
        self.changed.emit()

    def _store(self) -> None:
        c = self.clip
        if c is None:
            return
        s = c.settings
        s.range_mode = "custom" if self.rb_custom.isChecked() else "all"
        s.frame_in, s.frame_out = self.sp_in.value(), self.sp_out.value()
        if s.range_mode == "all":
            s.frame_in, s.frame_out = 0, -1
        s.memory = self.cb_mem.currentData()
        s.hann_chunk, s.hann_stride = self.sp_chunk.value(), self.sp_stride.value()
        s.manual_low_vram = self.ck_manual_low.isChecked()
        s.hint_mode = self.cb_hint.currentData()
        s.hint_quality = self.sl_hint_q.value()
        s.carry_hint = self.ck_carry.isChecked()
        s.carry_hint_quality = self.sl_carry_q.value()
        s.despill = self.sl_despill.value()
        s.frame_dir_linear = self.ck_linear.isChecked()
        s.frame_dir_fps = self.sp_fps.value()
        s.outputs = [k for k, cb in self.ck_out.items() if cb.isChecked()]
        s.output_format = self.cb_fmt.currentData()
        s.exr_dtype = self.cb_exr.currentData()
        s.cutout_linear = self.ck_cutout_lin.isChecked()
        s.video_codec = self.cb_codec.currentData()
        s.pix_fmt = self.cb_pix.currentData()
        s.rate_mode = self.cb_rate.currentData()
        s.crf = self.sp_crf.value()
        s.bitrate_mbps = self.sp_mbps.value()
        s.preset = self.cb_preset.currentData()

    def _refresh(self) -> None:
        """Show/hide dependent rows and update the Deliver text."""
        c = self.clip
        if c is None:
            return
        s = c.settings
        first, last = c.frame_range()
        dur = last - first + 1
        self.lb_dur.setText(f"{dur} frames, {dur / max(1e-6, c.fps):.2f} s"
                            + ("" if s.range_mode == "custom" else ", entire clip"))
        manual = s.memory == "manual"
        for w in (self.sp_chunk, self.sp_stride, self.lb_chunk, self.lb_stride, self.ck_manual_low):
            w.setVisible(manual)
        tip = ""
        if self.small_gpu and s.memory == "auto":
            tip = "Small GPU: Auto switches to low-VRAM staging by itself when needed."
        elif s.memory == "low":
            tip = "Staged through the cache folder on disk: slower, but exact."
        self.lb_mem_tip.setText(tip)
        self.lb_mem_tip.setVisible(bool(tip))
        has_hint = s.hint_mode != "none"
        for w in (self.lb_hint_row, self.lb_hint.parentWidget(), self.lb_hint_q, self.sl_hint_q):
            w.setVisible(has_hint)
        video_hint = s.hint_mode == "video"
        self.ck_carry.setVisible(video_hint)
        show_carry = s.hint_mode == "first" or (video_hint and s.carry_hint)
        self.sl_carry_q.setVisible(show_carry)
        self.lb_carry_q.setVisible(show_carry)
        self.lb_hint.set_full_text(s.hint_path or "None attached")
        self.bt_hint_clear.setEnabled(bool(s.hint_path))
        self.sec_input.setVisible(c.kind == "sequence")
        exr = s.output_format == "exr"
        self.cb_exr.setVisible(exr)
        self.lb_exr.setVisible(exr)
        self.ck_cutout_lin.setVisible(not exr and "cutout" in s.outputs)
        for w in (self.cb_codec, self.lb_codec, self.cb_pix, self.lb_pix, self.cb_rate.parentWidget(), self.lb_rate,
                  self.cb_preset, self.lb_preset, self.bt_defaults):
            w.setVisible(not exr)
        self.sp_crf.setVisible(s.rate_mode == "crf")
        self.sp_mbps.setVisible(s.rate_mode == "bitrate")
        is_default = all(getattr(s, k) == v for k, v in VIDEO_DEFAULTS.items())
        self.bt_defaults.setEnabled(not is_default)
        if exr:
            self.lb_export_info.setText("Scene-linear and unclamped: values above 1.0 survive. Matte is single "
                                        "channel; cutout is RGBA. Frames are numbered by source frame.")
            compat = ""
        else:
            cut = (" Cutout is always ProRes 4444 with alpha in a .mov"
                   + (", linear." if s.cutout_linear else ", sRGB.")) if "cutout" in s.outputs else ""
            self.lb_export_info.setText("Display-referred sRGB, clipped to 0–1, tagged BT.709 primaries with an "
                                        "sRGB curve. For compositing, use EXR." + cut)
            compat = ""
            if s.pix_fmt != "yuv420p":
                compat = (f"{PIX_NAMES[s.pix_fmt]} won't play in browsers, phones, QuickTime or many editors. "
                          "Choose 8-bit 4:2:0 for files you share.")
        self.lb_compat.setText(compat)
        self.lb_compat.setVisible(bool(compat))
        self.lb_export.setText(describe_export(s))

        out_dir, label_ = c.next_render_dir()
        self.lb_outdir.set_full_text(c.render_root())
        self.lb_saveas.setText(f"Saves as {label_}, in {os.path.basename(out_dir)}.")
        problems = []
        if not s.outputs:
            problems.append("choose at least one output")
        if has_hint and not s.hint_path:
            problems.append("attach a hint matte, or set Hint to None")
        if c.error:
            problems.append("the clip file is missing")
        if problems:
            self.lb_summary.setText("Can't render yet: " + "; ".join(problems) + ".")
            self.lb_summary.setStyleSheet(f"color: {T.c('ERROR')};")
        else:
            facts = [f"Frames {first}–{last} ({dur})"]
            if self._disk:
                facts.append(self._disk)
            self.lb_summary.setText("    ".join(facts))
            self.lb_summary.setStyleSheet("")
        self.bt_render.setEnabled(not problems)

    # ------------------------------------------------------------------------- pickers
    def _choose_hint(self) -> None:
        if self.clip is None:
            return
        start = os.path.dirname(self.clip.settings.hint_path or self.clip.path)
        if self.clip.settings.hint_mode == "video":
            path, _ = QFileDialog.getOpenFileName(self, "Hint video", start,
                                                  "Matte video (*.mp4 *.mov *.mkv *.avi);;All files (*)")
            if not path:
                path = QFileDialog.getExistingDirectory(self, "Or a folder of hint frames", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Hint matte for the in-point frame", start,
                                                  "Images (*.png *.jpg *.jpeg *.exr *.tif *.tiff)")
        if path:
            self.clip.settings.hint_path = os.path.normpath(path)
            if self.clip.settings.hint_mode == "none":
                self.cb_hint.setCurrentIndex(self.cb_hint.findData("first"))
            self._edited()

    def _clear_hint(self) -> None:
        if self.clip is not None:
            self.clip.settings.hint_path = ""
            self._edited()

    def _choose_outdir(self) -> None:
        if self.clip is None:
            return
        d = QFileDialog.getExistingDirectory(self, "Output folder", os.path.dirname(self.clip.render_root()))
        if d:
            self.clip.settings.output_root = os.path.normpath(d)
            self._edited()

    def _reset_outdir(self, *_) -> None:
        if self.clip is not None:
            self.clip.settings.output_root = ""
            self._edited()
