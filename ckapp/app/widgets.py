"""Small reusable widgets."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy,
                               QSlider, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from . import icons
from . import theme as T


def icon_button(name: str, tip: str, size: int = 16) -> QToolButton:
    b = QToolButton()
    b.setObjectName("Icon")
    b.setIcon(icons.svg(name, "TEXT_DIM", size, hover="TEXT"))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    return b


def panel_header(icon: str, title: str, *extras: QWidget) -> QWidget:
    """A panel's title row: icon, title, then right-aligned extras."""
    w = QWidget()
    w.setObjectName("PanelHead")
    h = QHBoxLayout(w)
    h.setContentsMargins(12, 0, 6, 0)
    h.setSpacing(8)
    w.setFixedHeight(34)
    ic = QLabel()
    ic.setPixmap(icons.svg(icon, "TEXT_DIM", 15).pixmap(15, 15))
    h.addWidget(ic)
    h.addWidget(label(title, "PanelTitle"))
    h.addStretch(1)
    for e in extras:
        h.addWidget(e)
    return w


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("HLine")
    return f


def vline() -> QFrame:
    f = QFrame()
    f.setObjectName("VLine")
    return f


def styled_popup(cb: QComboBox) -> QComboBox:
    """Without a styled delegate the popup ignores the stylesheet and paints the selection in loud amber."""
    cb.setItemDelegate(QStyledItemDelegate(cb))
    return cb


def combo(items: list[tuple[str, str, str]]) -> QComboBox:
    """(label, data, tooltip) items; may shrink below its longest item so panels never clip."""
    cb = QComboBox()
    styled_popup(cb)
    cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    cb.setMinimumContentsLength(6)
    cb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    for i, (text, data, tip) in enumerate(items):
        cb.addItem(text, data)
        if tip:
            cb.setItemData(i, tip, Qt.ToolTipRole)
    return cb


def label(text: str, name: str = "", tip: str = "") -> QLabel:
    l = QLabel(text)
    if name:
        l.setObjectName(name)
    if tip:
        l.setToolTip(tip)
    return l


class ElidedLabel(QLabel):
    """One line; long text (paths) is shortened in the middle to fit, full text in the tooltip."""

    def __init__(self, text: str = "", name: str = "", parent=None):
        super().__init__(parent)
        if name:
            self.setObjectName(name)
        self._full = ""
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._elide()

    def _elide(self) -> None:
        m = self.contentsMargins()
        avail = max(10, self.width() - m.left() - m.right() - 14)   # 14: QSS padding
        super().setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, avail))


class FadeLabel(QWidget):
    """One line of text that fades out at the right edge when it doesn't fit (full text in the
    tooltip). Takes no width of its own, so it never pushes neighbours off screen."""
    FADE = 28

    def __init__(self, text: str = "", color: str = "TEXT", bold: bool = False, size: float = 9.0, parent=None):
        super().__init__(parent)
        self._text = ""
        self._color = color
        self.setFont(T.ui_font(size, bold=bold))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(20)
        self.setFixedHeight(QFontMetrics(self.font()).height() + 2)
        self.setText(text)

    def setText(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.setToolTip(text)
            self.update()

    def text(self) -> str:
        return self._text

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def overflows(self) -> bool:
        return QFontMetrics(self.font()).horizontalAdvance(self._text) > self.width()

    def sizeHint(self) -> QSize:
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self._text), self.height())

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        col = T.qc(self._color)
        if self.overflows():
            g = QLinearGradient(w - self.FADE, 0, w, 0)
            g.setColorAt(0, col)
            g.setColorAt(1, T.qc(self._color, 0))
            pen = QPen(QBrush(g), 1)
        else:
            pen = QPen(col)
        p.setPen(pen)
        p.drawText(QRectF(0, 0, 100000, h), Qt.AlignLeft | Qt.AlignVCenter, self._text)
        p.end()


class Section(QWidget):
    """A titled block with a disclosure arrow; content is a two-column grid."""

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.head = QToolButton()
        self.head.setObjectName("Section")
        self.head.setText(title)
        self.head.setCheckable(True)
        self.head.setChecked(expanded)
        self.head.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.head.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.head.toggled.connect(self._toggle)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(16, 2, 10, 10)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(7)
        self.grid.setColumnStretch(1, 1)
        self.body.setVisible(expanded)
        lay.addWidget(self.head)
        lay.addWidget(self.body)
        lay.addWidget(hline())

    def _toggle(self, on: bool) -> None:
        self.head.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)

    def row(self, text: str, widget: QWidget, tip: str = "") -> QLabel:
        r = self.grid.rowCount()
        l = label(text, "Dim", tip)
        self.grid.addWidget(l, r, 0)
        self.grid.addWidget(widget, r, 1)
        if tip:
            widget.setToolTip(tip)
        return l

    def full(self, widget: QWidget) -> None:
        self.grid.addWidget(widget, self.grid.rowCount(), 0, 1, 2)


class SliderRow(QWidget):
    """Slider + numeric box. Middle-click resets to the default."""
    valueChanged = Signal(float)

    def __init__(self, lo: float, hi: float, default: float, decimals: int = 2, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self.default, self.scale = lo, hi, default, 10 ** decimals
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(lo * self.scale), int(hi * self.scale))
        self.box = QDoubleSpinBox()
        self.box.setRange(lo, hi)
        self.box.setDecimals(decimals)
        self.box.setSingleStep(1 / self.scale)
        self.box.setFixedWidth(64 if hi < 10 else 76)   # stepper buttons are hidden by the stylesheet
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.box)
        self.slider.valueChanged.connect(lambda v: self._set(v / self.scale, from_slider=True))
        self.box.valueChanged.connect(lambda v: self._set(v, from_slider=False))
        self.slider.installEventFilter(self)
        self.set_value(default)

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == ev.Type.MouseButtonPress and ev.button() == Qt.MiddleButton:
            self._set(self.default, from_slider=False)
            return True
        return False

    def value(self) -> float:
        return self.box.value()

    def set_value(self, v: float) -> None:
        for w in (self.slider, self.box):
            w.blockSignals(True)
        self.slider.setValue(int(round(v * self.scale)))
        self.box.setValue(v)
        for w in (self.slider, self.box):
            w.blockSignals(False)

    def _set(self, v: float, from_slider: bool) -> None:
        v = min(max(v, self.lo), self.hi)
        self.set_value(v)
        self.valueChanged.emit(v)


class VramMeter(QWidget):
    """GPU memory in use, as a bar. Compact: one line for the status bar. Full: bar over a
    'free / in use' line, for the Inspector."""
    BAR_W = 92

    def __init__(self, compact: bool = True, parent=None):
        super().__init__(parent)
        self.compact = compact
        self.used_mb: Optional[int] = None
        self.total_mb = 0
        if compact:
            fm = QFontMetrics(T.num_font(8.5))
            self.setFixedSize(fm.horizontalAdvance("VRAM") + self.BAR_W + fm.horizontalAdvance("00.0 / 00.0 GB") + 22,
                              20)
        else:
            self.setFixedHeight(34)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("GPU memory: no NVIDIA GPU found yet")

    def set_info(self, gpu: Optional[dict]) -> None:
        if gpu:
            self.used_mb, self.total_mb = gpu["used_mb"], max(1, gpu["total_mb"])
            self.setToolTip(f"{gpu['name']}\n{self.used_mb / 1024:.1f} GB of {self.total_mb / 1024:.1f} GB in use,"
                            f" {gpu.get('util', 0)}% busy")
        else:
            self.used_mb = None
        self.update()

    def fraction(self) -> float:
        return 0.0 if self.used_mb is None else min(1.0, self.used_mb / self.total_mb)

    def _fill(self) -> str:
        f = self.fraction()
        return "ERROR" if f >= 0.95 else "WARN" if f >= 0.85 else "TEXT_DIM"

    def _bar(self, p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(T.qc("PANEL_3"))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.used_mb is not None:
            p.setBrush(T.qc(self._fill()))
            p.drawRoundedRect(QRectF(r.x(), r.y(), max(r.height(), r.width() * self.fraction()), r.height()),
                              r.height() / 2, r.height() / 2)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        gb = (lambda mb: f"{mb / 1024:.1f}")
        if self.compact:
            f = T.num_font(8.5)
            p.setFont(f)
            fm = QFontMetrics(f)
            p.setPen(T.qc("TEXT_FAINT"))
            lw = fm.horizontalAdvance("VRAM")
            p.drawText(QRectF(0, 0, lw, h), Qt.AlignVCenter | Qt.AlignLeft, "VRAM")
            self._bar(p, QRectF(lw + 8, h / 2 - 3, self.BAR_W, 6))
            p.setPen(T.qc("TEXT_DIM"))
            text = "–" if self.used_mb is None else f"{gb(self.used_mb)} / {gb(self.total_mb)} GB"
            p.drawText(QRectF(lw + 16 + self.BAR_W, 0, w, h), Qt.AlignVCenter | Qt.AlignLeft, text)
        else:
            self._bar(p, QRectF(0, 2, w, 8))
            f = T.num_font(8.5)
            p.setFont(f)
            row = QRectF(0, 14, w, h - 14)
            if self.used_mb is None:
                p.setPen(T.qc("TEXT_FAINT"))
                p.drawText(row, Qt.AlignVCenter | Qt.AlignLeft, "No GPU reading yet")
            else:
                p.setPen(T.qc("TEXT"))
                p.drawText(row, Qt.AlignVCenter | Qt.AlignLeft,
                           f"{gb(self.total_mb - self.used_mb)} GB free")
                p.setPen(T.qc("TEXT_DIM"))
                p.drawText(row, Qt.AlignVCenter | Qt.AlignRight,
                           f"{gb(self.used_mb)} of {gb(self.total_mb)} GB in use")
        p.end()


class Segmented(QWidget):
    """A row of mutually exclusive flat buttons (Single / Wipe / Side by side)."""
    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}
        for key, text in items:
            b = QToolButton()
            b.setObjectName("Seg")
            b.setText(text)
            b.setCheckable(True)
            # QSS padding isn't in the tool button's size hint, so reserve the text width explicitly
            b.setMinimumWidth(b.fontMetrics().horizontalAdvance(text) + 24)
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, k=key: self.set_current(k, emit=True))
            lay.addWidget(b)
            self.buttons[key] = b
        self.current = items[0][0]
        self.buttons[self.current].setChecked(True)

    def set_current(self, key: str, emit: bool = False) -> None:
        self.current = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        if emit:
            self.changed.emit(key)
