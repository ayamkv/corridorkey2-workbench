"""Icons: the Workbench set and a few Lucide icons (assets/icons, SVG), plus transport glyphs drawn
with QPainter. All are recoloured from the theme, so they follow it."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtSvg import QSvgRenderer

from . import theme as T

# Workbench set (drawn for this app): media, queue, inspector, deliver, render, setting.
# Lucide (ISC): folder-open, plus, x, trash-2, scan, circle-alert, hard-drive, cpu.
_SOURCE_GREY = "#9E9E9E"          # the colour the Workbench set is drawn in


@lru_cache(maxsize=None)
def _svg(name: str) -> str:
    return (T.ASSETS / "icons" / f"{name}.svg").read_text(encoding="utf-8")


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    data = _svg(name).replace(_SOURCE_GREY, color).replace("currentColor", color)
    pm = QPixmap(size * 3, size * 3)
    pm.setDevicePixelRatio(3.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(data.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def svg(name: str, color: str = "TEXT", size: int = 16, hover: str = "", off: str = "") -> QIcon:
    """Theme-coloured icon. `hover` colours the Active mode; `off` colours a checkable button's
    unchecked state (On uses `color`)."""
    icon = QIcon()
    icon.addPixmap(_pixmap(name, T.c(color), size), QIcon.Normal, QIcon.On)
    icon.addPixmap(_pixmap(name, T.c(off or color), size), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_pixmap(name, T.c(hover or color), size), QIcon.Active, QIcon.On)
    icon.addPixmap(_pixmap(name, T.c(hover or off or color), size), QIcon.Active, QIcon.Off)
    for state in (QIcon.On, QIcon.Off):
        icon.addPixmap(_pixmap(name, T.c("TEXT_FAINT"), size), QIcon.Disabled, state)
    return icon


def _icon(draw, size: int = 16) -> QIcon:
    icon = QIcon()
    for mode, col in ((QIcon.Normal, T.c("TEXT")), (QIcon.Active, T.c("ACCENT")), (QIcon.Disabled, T.c("TEXT_FAINT"))):
        pm = QPixmap(size * 3, size * 3)
        pm.setDevicePixelRatio(3.0)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(col))
        draw(p, size)
        p.end()
        icon.addPixmap(pm, mode)
    return icon


def _tri(p: QPainter, x0: float, x1: float, s: float, right: bool = True) -> None:
    top, bot, mid = s * 0.2, s * 0.8, s * 0.5
    pts = [QPointF(x0, top), QPointF(x1, mid), QPointF(x0, bot)] if right else \
          [QPointF(x1, top), QPointF(x0, mid), QPointF(x1, bot)]
    p.drawPolygon(QPolygonF(pts))


def play() -> QIcon:
    return _icon(lambda p, s: _tri(p, s * 0.3, s * 0.8, s))


def pause() -> QIcon:
    def d(p, s):
        p.drawRoundedRect(QRectF(s * 0.28, s * 0.2, s * 0.15, s * 0.6), 1, 1)
        p.drawRoundedRect(QRectF(s * 0.57, s * 0.2, s * 0.15, s * 0.6), 1, 1)
    return _icon(d)


def step_back() -> QIcon:
    def d(p, s):
        p.drawRect(QRectF(s * 0.25, s * 0.22, s * 0.1, s * 0.56))
        _tri(p, s * 0.38, s * 0.78, s, right=False)
    return _icon(d)


def step_fwd() -> QIcon:
    def d(p, s):
        _tri(p, s * 0.22, s * 0.62, s)
        p.drawRect(QRectF(s * 0.65, s * 0.22, s * 0.1, s * 0.56))
    return _icon(d)


def to_in() -> QIcon:
    def d(p, s):
        p.drawRect(QRectF(s * 0.14, s * 0.2, s * 0.09, s * 0.6))
        _tri(p, s * 0.25, s * 0.55, s, right=False)
        _tri(p, s * 0.52, s * 0.82, s, right=False)
    return _icon(d)


def to_out() -> QIcon:
    def d(p, s):
        _tri(p, s * 0.18, s * 0.48, s)
        _tri(p, s * 0.45, s * 0.75, s)
        p.drawRect(QRectF(s * 0.77, s * 0.2, s * 0.09, s * 0.6))
    return _icon(d)
