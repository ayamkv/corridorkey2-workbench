"""Left-hand panels: media bin (clip thumbnails) and render queue; async thumbnail loading."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMenu, QProgressBar,
                               QScrollArea, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from . import icons
from . import theme as T
from .media import open_source, thumbnail, to_display_u8
from .widgets import FadeLabel, hline, icon_button, label, panel_header

CLIP_ID = Qt.UserRole + 1


def qimage(arr: np.ndarray) -> QImage:
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class ThumbLoader(QObject):
    """Decodes thumbnails and filmstrips off the GUI thread."""
    thumbReady = Signal(str, QImage)              # clip id, image
    stripReady = Signal(str, list)                # clip id, [(frame, QImage)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbs")

    def thumb(self, clip_id: str, path: str, linear: bool = False) -> None:
        def work():
            arr = thumbnail(path, at=0.5, width=240, linear=linear)
            if arr is not None:
                self.thumbReady.emit(clip_id, qimage(arr))
        self.pool.submit(work)

    def strip(self, clip_id: str, path: str, frames: int, count: int = 24, linear: bool = False) -> None:
        def work():
            try:
                src = open_source(path, linear=linear)
            except ValueError:
                return
            out = []
            try:
                idx = sorted(set(int(i) for i in np.linspace(0, max(0, frames - 1), num=min(count, max(1, frames)))))
                for i in idx:
                    fr = src.read(i)
                    if fr is not None:
                        out.append((i, qimage(to_display_u8(fr, 96))))
            finally:
                src.close()
            if out:
                self.stripReady.emit(clip_id, out)
        self.pool.submit(work)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


class ClipDelegate(QStyledItemDelegate):
    THUMB_H = 78

    def __init__(self, bin_: "MediaBin"):
        super().__init__(bin_)
        self.bin = bin_

    def sizeHint(self, option, index) -> QSize:
        return self.bin.cell_size()

    def paint(self, p: QPainter, option, index) -> None:
        cid = index.data(CLIP_ID)
        info = self.bin.info.get(cid, {})
        r = option.rect.adjusted(4, 4, -4, -4)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if selected or hover:
            p.setPen(QPen(T.qc("ACCENT") if selected else T.qc("BORDER"), 1.5))
            p.setBrush(T.qc("PANEL_2"))
            p.drawRoundedRect(QRectF(r).adjusted(-2, -2, 2, 2), 5, 5)
        thumb = QRectF(r.x(), r.y(), r.width(), self.THUMB_H)
        p.setPen(Qt.NoPen)
        p.setBrush(T.qc("VIEWER_BG"))
        p.drawRoundedRect(thumb, 4, 4)
        img: Optional[QImage] = self.bin.thumbs.get(cid)
        if img is not None and not img.isNull():
            s = min(thumb.width() / img.width(), thumb.height() / img.height())
            w, h = img.width() * s, img.height() * s
            p.drawImage(QRectF(thumb.center().x() - w / 2, thumb.center().y() - h / 2, w, h), img)
        status, frac = info.get("status", "ready"), info.get("fraction", 0.0)
        text = f"{int(frac * 100)}%" if status == "running" else status.capitalize()
        f = T.num_font(8.0, QFont.DemiBold)
        p.setFont(f)
        fm = QFontMetrics(f)
        badge = QRectF(thumb.x() + 5, thumb.y() + 5, fm.horizontalAdvance(text) + 12, 16)
        p.setBrush(QColor(0, 0, 0, 175))
        p.drawRoundedRect(badge, 3, 3)
        p.setPen(T.qc(T.STATUS_COLORS.get(status, "TEXT_DIM")))
        p.drawText(badge, Qt.AlignCenter, text)
        if status == "running":
            p.fillRect(QRectF(thumb.x(), thumb.bottom() - 3, thumb.width() * frac, 3), T.qc("ACCENT"))
        f = T.ui_font(8.5, bold=True)
        p.setFont(f)
        p.setPen(T.qc("TEXT"))
        name_r = QRectF(r.x() + 1, thumb.bottom() + 4, r.width() - 2, 16)
        p.drawText(name_r, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(f).elidedText(info.get("name", ""), Qt.ElideMiddle, int(name_r.width())))
        f = T.num_font(8.0)
        p.setFont(f)
        p.setPen(T.qc("TEXT_DIM"))
        sub_r = QRectF(r.x() + 1, name_r.bottom(), r.width() - 2, 15)
        p.drawText(sub_r, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(f).elidedText(info.get("sub", ""), Qt.ElideRight, int(sub_r.width())))
        p.restore()


class MediaBin(QWidget):
    clipSelected = Signal(str)
    importRequested = Signal()
    renderRequested = Signal(str)
    removeRequested = Signal(str)
    revealRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.info: dict[str, dict] = {}
        self.thumbs: dict[str, QImage] = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        b = QToolButton()
        b.setObjectName("Flat")
        b.setText("Import")
        b.setIcon(icons.svg("plus", "TEXT_DIM", 14, hover="TEXT"))
        b.setIconSize(QSize(14, 14))
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setToolTip("Import clips or image-sequence folders (Ctrl+O). You can also drop files on the window.")
        b.clicked.connect(self.importRequested)
        v.addWidget(panel_header("media", "Media", b))
        v.addWidget(hline())
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(0)
        self.list.setMouseTracking(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setItemDelegate(ClipDelegate(self))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.currentItemChanged.connect(lambda cur, _: cur and self.clipSelected.emit(cur.data(CLIP_ID)))
        self.empty = label("Drop clips or image-sequence folders here,\nor choose Import.", "Faint")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.list, 1)
        v.addWidget(self.empty, 1)
        self._update_empty()

    def cell_size(self) -> QSize:
        w = max(120, (self.list.viewport().width() - 4) // 2)
        return QSize(w, ClipDelegate.THUMB_H + 46)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.list.setGridSize(self.cell_size())

    def _update_empty(self) -> None:
        has = self.list.count() > 0
        self.list.setVisible(has)
        self.empty.setVisible(not has)

    def add(self, clip_id: str, name: str, sub: str) -> None:
        self.info[clip_id] = {"name": name, "sub": sub, "status": "ready", "fraction": 0.0}
        it = QListWidgetItem()
        it.setData(CLIP_ID, clip_id)
        it.setToolTip(name)
        self.list.addItem(it)
        self.list.setGridSize(self.cell_size())
        self._update_empty()

    def remove(self, clip_id: str) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(CLIP_ID) == clip_id:
                self.list.takeItem(i)
                break
        self.info.pop(clip_id, None)
        self.thumbs.pop(clip_id, None)
        self._update_empty()

    def select(self, clip_id: str) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(CLIP_ID) == clip_id:
                self.list.setCurrentRow(i)
                return

    def set_thumb(self, clip_id: str, img: QImage) -> None:
        self.thumbs[clip_id] = img
        self.list.viewport().update()

    def set_status(self, clip_id: str, status: str, fraction: float = 0.0) -> None:
        if clip_id in self.info:
            self.info[clip_id].update(status=status, fraction=fraction)
            self.list.viewport().update()

    def _menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if it is None:
            return
        cid = it.data(CLIP_ID)
        m = QMenu(self)
        m.addAction("Render", lambda: self.renderRequested.emit(cid))
        m.addAction("Show renders in Explorer", lambda: self.revealRequested.emit(cid))
        m.addSeparator()
        m.addAction("Remove from project", lambda: self.removeRequested.emit(cid))
        m.exec(self.list.viewport().mapToGlobal(pos))


class JobRow(QWidget):
    """Name (fades out when long), frame range and the cancel/remove button stay visible at any width."""

    def __init__(self, job: dict, queue: "QueuePanel"):
        super().__init__()
        self.setObjectName("JobRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.job_id = job["id"]
        self.queue = queue
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 7, 6, 7)
        v.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.name = FadeLabel("", "TEXT", bold=True)
        self.range = QLabel()
        self.range.setFont(T.num_font(8.5))
        self.range.setObjectName("Dim")
        self.btn = icon_button("x", "", 14)
        self.btn.clicked.connect(self._button)
        top.addWidget(self.name, 1)
        top.addWidget(self.range)
        top.addWidget(self.btn)
        v.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        self.stage = FadeLabel("", "TEXT_FAINT", size=8.5)
        v.addWidget(self.stage)
        self.job = job
        self.update_job(job)

    def update_job(self, job: dict) -> None:
        self.job = job
        st = job["status"]
        spec = job.get("spec", {})
        rng = ""
        if spec.get("frame_in") is not None or spec.get("frame_out") is not None:
            out = spec.get("frame_out")
            rng = f"{spec.get('frame_in') or 0}–{out if out is not None else 'end'}"
        self.name.setText(job.get("name", ""))
        self.range.setText(rng)
        self.range.setVisible(bool(rng))
        self.bar.setValue(int(job.get("fraction", 0) * 1000))
        self.bar.setVisible(st in ("running", "queued"))
        text = job.get("stage", "")
        if st == "running" and job.get("eta") is not None:
            text += f",  about {_fmt_eta(job['eta'])} left"
        elif st == "done" and job.get("started"):
            text = f"Done in {_fmt_eta(job['finished'] - job['started'])}"
        elif st == "error":
            text = "Failed: " + (job.get("error") or "")[:300]
        self.stage.setText(text)
        self.stage.set_color(T.STATUS_COLORS.get(st, "TEXT_DIM") if st in ("error", "done", "interrupted")
                             else "TEXT_FAINT")
        self.btn.setToolTip("Cancel" if st in ("running", "queued") else "Remove from the list")

    def _button(self) -> None:
        if self.job["status"] in ("running", "queued"):
            self.queue.cancelRequested.emit(self.job_id)
        else:
            self.queue.removeRequested.emit(self.job_id)

    def mousePressEvent(self, e) -> None:
        self.queue.jobActivated.emit(self.job_id)
        super().mousePressEvent(e)


def _fmt_eta(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


class QueuePanel(QWidget):
    """Rows in a vertical-only scroll area: they always take the panel's width, never scroll sideways."""
    cancelRequested = Signal(str)
    removeRequested = Signal(str)
    jobActivated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.rows: dict[str, JobRow] = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.clear_btn = QToolButton()
        self.clear_btn.setObjectName("Flat")
        self.clear_btn.setText("Clear finished")
        self.clear_btn.setToolTip("Remove finished, failed and cancelled renders from this list (files stay)")
        self.clear_btn.clicked.connect(self._clear_finished)
        v.addWidget(panel_header("queue", "Queue", self.clear_btn))
        v.addWidget(hline())
        self.scroll = QScrollArea()
        self.scroll.setObjectName("Panel")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.list = QVBoxLayout(body)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(0)
        self.list.addStretch(1)
        self.scroll.setWidget(body)
        v.addWidget(self.scroll, 1)
        self.empty = label("Renders you start appear here.", "Faint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        v.addWidget(self.empty, 1)
        self._update_empty()

    def _update_empty(self) -> None:
        has = bool(self.rows)
        self.scroll.setVisible(has)
        self.empty.setVisible(not has)

    def reset(self, jobs: list[dict]) -> None:
        for jid in list(self.rows):
            self._drop(jid)
        for j in jobs:
            self.update_job(j)
        self._update_empty()

    def update_job(self, job: dict) -> None:
        jid = job["id"]
        if jid in self.rows:
            self.rows[jid].update_job(job)
        else:
            row = JobRow(job, self)
            self.list.insertWidget(self.list.count() - 1, row)      # above the stretch
            self.rows[jid] = row
        self._update_empty()

    def _drop(self, jid: str) -> None:
        row = self.rows.pop(jid, None)
        if row is not None:
            self.list.removeWidget(row)
            row.deleteLater()

    def remove_job(self, jid: str) -> None:
        self._drop(jid)
        self._update_empty()

    def _clear_finished(self) -> None:
        for jid, row in list(self.rows.items()):
            if row.job["status"] not in ("running", "queued"):
                self.removeRequested.emit(jid)

    def active_count(self) -> int:
        return sum(1 for r in self.rows.values() if r.job["status"] in ("running", "queued"))