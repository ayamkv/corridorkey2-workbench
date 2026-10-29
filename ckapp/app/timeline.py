"""Cavalry-style timeline: frame field, numbered ruler, playhead, in/out handles, filmstrip."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QMenu, QSizePolicy, QSpinBox, QWidget

from . import theme as T

MAJOR_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000)


def tick_steps(ppf: float, min_label_px: float = 56.0, min_minor_px: float = 6.0) -> tuple[int, int]:
    """(major, minor) frame steps for `ppf` pixels per frame. minor == 0 means none."""
    major = next((s for s in MAJOR_STEPS if s * ppf >= min_label_px), MAJOR_STEPS[-1])
    minor = 0
    for div in (10, 5, 2):
        if major % div == 0 and (major // div) * ppf >= min_minor_px:
            minor = major // div
            break
    if minor == 0 and major > 1 and ppf >= min_minor_px:
        minor = 1
    return major, minor


class Ruler(QWidget):
    frameScrubbed = Signal(int)
    rangeEdited = Signal(int, int)

    RULER_H, TRACK_Y, TRACK_H, STRIP_Y, STRIP_H = 26, 30, 12, 46, 34
    MARGIN = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(self.STRIP_Y + self.STRIP_H + 4)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.last = 0                  # last frame index
        self.frame = 0
        self.rin, self.rout = 0, 0
        self.view_start = 0.0          # frame at the left margin
        self.ppf = 1.0                 # pixels per frame
        self.fitted = True
        self.strip: list[tuple[int, QImage]] = []
        self.rendered: Optional[tuple[int, int]] = None   # range covered by the shown render
        self._drag = None
        self._hover = None

    # -- model ------------------------------------------------------------------------------
    def set_clip(self, frames: int) -> None:
        self.last = max(0, frames - 1)
        self.frame = min(self.frame, self.last)
        self.rin, self.rout = 0, self.last
        self.strip = []
        self.fit()

    MAX_PPF = 80.0

    def _usable(self) -> float:
        return max(10, self.width() - 2 * self.MARGIN)

    def fit_ppf(self) -> float:
        return self._usable() / max(1, self.last)

    def fit(self) -> None:
        self.fitted = True
        self.ppf = self.fit_ppf()
        self.view_start = 0.0
        self.update()

    def zoom_to_range(self) -> None:
        self.ppf = self._usable() / max(1, self.rout - self.rin)
        self.view_start = float(self.rin)
        self.fitted = False
        self._clamp()

    def _clamp(self) -> None:
        """The clip always fills the ruler: no zooming out past it, no panning off either end."""
        fit = self.fit_ppf()
        self.ppf = min(max(self.ppf, fit), max(fit, self.MAX_PPF))
        if self.ppf <= fit * 1.0001:
            return self.fit()
        self.view_start = min(max(self.view_start, 0.0), max(0.0, self.last - self._usable() / self.ppf))
        self.update()

    def resizeEvent(self, e) -> None:
        if self.fitted:
            self.fit()
        else:
            self._clamp()
        super().resizeEvent(e)

    def x_of(self, f: float) -> float:
        return self.MARGIN + (f - self.view_start) * self.ppf

    def f_of(self, x: float) -> int:
        return int(round(min(max((x - self.MARGIN) / self.ppf + self.view_start, 0), self.last)))

    # -- paint ------------------------------------------------------------------------------
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), T.qc("PANEL"))
        x0, x1 = self.x_of(0), self.x_of(self.last)
        xin, xout = self.x_of(self.rin), self.x_of(self.rout)

        # ruler
        p.setFont(T.num_font(8.5))
        major, minor = tick_steps(self.ppf)
        first_vis = max(0, int(self.view_start) - 1)
        last_vis = min(self.last, int(self.view_start + w / self.ppf) + 1)
        p.setPen(QPen(T.qc("TEXT_FAINT"), 1))
        if minor:
            start = first_vis - first_vis % minor
            for fr in range(start, last_vis + 1, minor):
                if fr % major:
                    x = round(self.x_of(fr)) + 0.5
                    p.drawLine(QPointF(x, self.RULER_H - 6), QPointF(x, self.RULER_H))
        start = first_vis - first_vis % major
        for fr in range(start, last_vis + 1, major):
            x = round(self.x_of(fr)) + 0.5
            p.setPen(QPen(T.qc("TEXT_DIM"), 1))
            p.drawLine(QPointF(x, self.RULER_H - 11), QPointF(x, self.RULER_H))
            p.setPen(T.qc("TEXT"))
            p.drawText(QRectF(x + 3, 0, 60, 14), Qt.AlignLeft | Qt.AlignVCenter, str(fr))
        if self.last not in range(start, last_vis + 1, major) and first_vis <= self.last <= last_vis:
            x = round(self.x_of(self.last)) + 0.5
            p.setPen(QPen(T.qc("TEXT_FAINT"), 1))
            p.drawLine(QPointF(x, self.RULER_H - 11), QPointF(x, self.RULER_H))

        # range track
        ty = self.TRACK_Y
        p.fillRect(QRectF(x0, ty, max(1, x1 - x0), self.TRACK_H), T.qc("PANEL_3"))
        moving = self._hover == "move" or (self._drag and self._drag[0] == "move")
        p.fillRect(QRectF(xin, ty, max(1, xout - xin), self.TRACK_H), T.qc("ACCENT", 110 if moving else 70))
        if self.rendered:
            rx0, rx1 = self.x_of(self.rendered[0]), self.x_of(self.rendered[1])
            p.fillRect(QRectF(rx0, ty + self.TRACK_H - 3, max(1, rx1 - rx0), 3), T.qc("OK", 200))
        for x, which in ((xin, "in"), (xout, "out")):
            active = self._hover == which or (self._drag and self._drag[0] == which)
            col = T.qc("ACCENT_HI") if active else T.qc("ACCENT")
            hx = x - 4 if which == "in" else x
            p.fillRect(QRectF(hx, ty - 2, 4, self.TRACK_H + 4), col)

        # filmstrip
        sy = self.STRIP_Y
        p.fillRect(QRectF(x0, sy, max(1, x1 - x0), self.STRIP_H), T.qc("PANEL_2"))
        if self.strip:
            p.setClipRect(QRectF(x0, sy, max(1, x1 - x0), self.STRIP_H))
            for i, (fr, img) in enumerate(self.strip):
                nxt = self.strip[i + 1][0] if i + 1 < len(self.strip) else self.last + 1
                xa, xb = self.x_of(fr), self.x_of(nxt)
                if xb < 0 or xa > w:
                    continue
                tw = img.width() * self.STRIP_H / max(1, img.height())
                x = xa
                while x < xb:
                    p.drawImage(QRectF(x, sy, tw, self.STRIP_H), img)
                    x += tw
            p.setClipping(False)

        # dim outside the range
        dim = QColor(0, 0, 0, 140)
        if xin > x0:
            p.fillRect(QRectF(x0, 0, xin - x0, h), dim)
        if xout < x1:
            p.fillRect(QRectF(xout, 0, x1 - xout, h), dim)

        # playhead
        px = round(self.x_of(self.frame)) + 0.5
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(T.qc("ACCENT"), 1))
        p.drawLine(QPointF(px, self.RULER_H - 8), QPointF(px, h))
        p.setPen(Qt.NoPen)
        p.setBrush(T.qc("ACCENT"))
        tri = QPolygonF([QPointF(px - 6, self.RULER_H - 13), QPointF(px + 6, self.RULER_H - 13),
                         QPointF(px, self.RULER_H - 5)])
        p.drawPolygon(tri)
        p.end()

    # -- interaction ------------------------------------------------------------------------
    def _handle_at(self, pos: QPointF) -> Optional[str]:
        """'in' / 'out' near a handle, 'move' on the bar between them, else None."""
        if not (self.TRACK_Y - 4 <= pos.y() <= self.TRACK_Y + self.TRACK_H + 4):
            return None
        xin, xout = self.x_of(self.rin), self.x_of(self.rout)
        din, dout = abs(pos.x() - xin), abs(pos.x() - xout)
        if min(din, dout) <= 7:
            return "in" if din < dout or (din == dout and pos.x() < xin) else "out"
        whole = self.rin == 0 and self.rout == self.last
        if xin < pos.x() < xout and not whole:
            return "move"
        return None

    def contextMenuEvent(self, e) -> None:
        m = QMenu(self)
        m.addAction("Fit to view", self.fit).setEnabled(not self.fitted)
        whole = self.rin == 0 and self.rout == self.last
        m.addAction("Zoom to in/out", self.zoom_to_range).setEnabled(not whole)
        m.addSeparator()
        m.addAction("Use entire clip", lambda: self._set_range(0, self.last)).setEnabled(not whole)
        m.exec(e.globalPos())

    def _set_range(self, rin: int, rout: int) -> None:
        self.rin, self.rout = rin, rout
        self.update()
        self.rangeEdited.emit(rin, rout)

    def mousePressEvent(self, e) -> None:
        pos = e.position()
        if e.button() == Qt.MiddleButton:
            self._drag = ("pan", pos.x(), self.view_start)
            return
        if e.button() != Qt.LeftButton:
            return
        which = self._handle_at(pos)
        if which == "move":
            self._drag = ("move", pos.x(), self.rin, self.rout)
            self.setCursor(Qt.ClosedHandCursor)
        elif which:
            self._drag = (which,)
        else:
            self._drag = ("scrub",)
            self._scrub(pos.x())

    def _scrub(self, x: float) -> None:
        f = self.f_of(x)
        if f != self.frame:
            self.frame = f
            self.update()
            self.frameScrubbed.emit(f)

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if not self._drag:
            hov = self._handle_at(pos)
            if hov != self._hover:
                self._hover = hov
                self.setCursor({"move": Qt.OpenHandCursor, None: Qt.ArrowCursor}.get(hov, Qt.SizeHorCursor))
                self.update()
            return
        kind = self._drag[0]
        if kind == "pan":
            if not self.fitted:
                self.view_start = self._drag[2] - (pos.x() - self._drag[1]) / self.ppf
                self._clamp()
        elif kind == "move":
            _, x0, rin0, rout0 = self._drag
            d = int(round((pos.x() - x0) / self.ppf))
            d = min(max(d, -rin0), self.last - rout0)
            if (rin0 + d, rout0 + d) != (self.rin, self.rout):
                self._set_range(rin0 + d, rout0 + d)
        elif kind == "scrub":
            self._scrub(pos.x())
        else:
            f = self.f_of(pos.x())
            if kind == "in":
                self.rin = min(f, self.rout)
            else:
                self.rout = max(f, self.rin)
            self.update()
            self.rangeEdited.emit(self.rin, self.rout)

    def mouseReleaseEvent(self, e) -> None:
        if self._drag and self._drag[0] == "move":
            self.setCursor(Qt.OpenHandCursor if self._handle_at(e.position()) == "move" else Qt.ArrowCursor)
        self._drag = None

    def mouseDoubleClickEvent(self, e) -> None:
        if self._handle_at(e.position()) is None and e.position().y() < self.TRACK_Y - 4:
            self.fit()

    def wheelEvent(self, e) -> None:
        x = e.position().x()
        anchor = (x - self.MARGIN) / self.ppf + self.view_start
        factor = 1.0 + 0.0015 * e.angleDelta().y()
        self.ppf *= max(0.2, factor)
        self.view_start = anchor - (x - self.MARGIN) / self.ppf
        self.fitted = False
        self._clamp()

    def leaveEvent(self, e) -> None:
        self._hover = None
        self.update()


class FrameField(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPrefix("F  ")
        self.setRange(0, 0)
        self.setFixedWidth(92)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setFont(T.num_font(10.5))
        self.setKeyboardTracking(False)


class Timeline(QWidget):
    """Frame field + ruler. Signals carry 0-based frame numbers."""
    frameChanged = Signal(int)          # user scrubbed or typed a frame
    rangeChanged = Signal(int, int)     # user dragged an in/out handle

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)
        self.field = FrameField()
        self.ruler = Ruler()
        lay.addWidget(self.field, 0, Qt.AlignTop)
        lay.addWidget(self.ruler, 1)
        self.field.valueChanged.connect(self._typed)
        self.ruler.frameScrubbed.connect(self._scrubbed)
        self.ruler.rangeEdited.connect(self.rangeChanged)

    def set_clip(self, frames: int) -> None:
        self.field.blockSignals(True)
        self.field.setRange(0, max(0, frames - 1))
        self.field.blockSignals(False)
        self.ruler.set_clip(frames)

    def set_frame(self, f: int) -> None:
        self.ruler.frame = f
        self.ruler.update()
        self.field.blockSignals(True)
        self.field.setValue(f)
        self.field.blockSignals(False)

    def set_range(self, rin: int, rout: int) -> None:
        self.ruler.rin, self.ruler.rout = rin, rout
        self.ruler.update()

    def set_rendered(self, rng: Optional[tuple[int, int]]) -> None:
        self.ruler.rendered = rng
        self.ruler.update()

    def set_filmstrip(self, items: list[tuple[int, QImage]]) -> None:
        self.ruler.strip = items
        self.ruler.update()

    def _typed(self, f: int) -> None:
        self.ruler.frame = f
        self.ruler.update()
        self.frameChanged.emit(f)

    def _scrubbed(self, f: int) -> None:
        self.field.blockSignals(True)
        self.field.setValue(f)
        self.field.blockSignals(False)
        self.frameChanged.emit(f)
