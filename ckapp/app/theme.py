"""CorridorKey2 Workbench look: near-black stage, slate-amber accent, Geist type.

Surfaces step down in darkness toward the picture: chrome #121214, panels #161718, viewer #0F1010,
so the image is always the deepest, calmest thing on screen.
Type roles (all Geist, bundled in assets/fonts, SIL OFL):
  ui_font()   controls and body text
  num_font()  the same face with tabular figures: frame numbers, the ruler, sizes.
              Tabular figures mean numbers never change width while they count.
  mono_font() Geist Mono, logs only
Amber is spent in few places: playhead, frame readout, primary action, selection.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen, QPixmap, QPolygonF

ASSETS = Path(__file__).resolve().parent / "assets"

COLORS = {
    "BG": "#121214",          # window chrome: top bar, status bar
    "PANEL": "#161718",
    "PANEL_2": "#1e1f21",     # raised: fields, buttons
    "PANEL_3": "#28292c",     # hover
    "BORDER": "#26272a",      # rules
    "VIEWER_BG": "#0f1010",
    "TEXT": "#ebe9e4",
    "TEXT_DIM": "#9b9992",
    "TEXT_FAINT": "#5f5e5a",
    "ACCENT": "#f0b429",      # slate amber
    "ACCENT_HI": "#ffc94d",
    "ACCENT_DIM": "#8a6a1f",
    "ACCENT_FG": "#1d1604",   # ink on amber
    "WARN": "#d9a033",
    "ERROR": "#e7735a",
    "OK": "#93c48b",
    "RUN": "#f0b429",
}

UI_FAMILY = "Geist"
NUM_FAMILY = "Geist"
MONO_FAMILY = "Geist Mono"
_fonts_loaded = False


def load_fonts() -> None:
    """Register the bundled Geist files once (needs a QGuiApplication)."""
    global _fonts_loaded
    if not _fonts_loaded:
        for f in sorted((ASSETS / "fonts").glob("*.ttf")):
            QFontDatabase.addApplicationFont(str(f))
        _fonts_loaded = True


def c(name: str) -> str:
    return COLORS[name]


def qc(name: str, alpha: int = 255) -> QColor:
    col = QColor(COLORS[name])
    col.setAlpha(alpha)
    return col


STATUS_COLORS = {"ready": "TEXT_DIM", "queued": "WARN", "running": "RUN", "done": "OK",
                 "error": "ERROR", "cancelled": "TEXT_DIM", "interrupted": "WARN", "missing": "ERROR"}


def ui_font(size: float = 9.0, bold: bool = False) -> QFont:
    f = QFont(UI_FAMILY)
    f.setPointSizeF(size)
    if bold:
        f.setWeight(QFont.DemiBold)
    return f


def num_font(size: float = 9.0, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont(NUM_FAMILY)
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setFeature(QFont.Tag("tnum"), 1)
    return f


def mono_font(size: float = 9.0) -> QFont:
    """Render logs only."""
    f = QFont(MONO_FAMILY)
    f.setStyleHint(QFont.Monospace)
    f.setPointSizeF(size)
    return f


def palette() -> QPalette:
    p = QPalette()
    for role, key in ((QPalette.Window, "PANEL"), (QPalette.Base, "PANEL_2"), (QPalette.AlternateBase, "PANEL_3"),
                      (QPalette.Button, "PANEL_2"), (QPalette.Text, "TEXT"), (QPalette.WindowText, "TEXT"),
                      (QPalette.ButtonText, "TEXT"), (QPalette.Highlight, "ACCENT"),
                      (QPalette.HighlightedText, "ACCENT_FG"), (QPalette.ToolTipBase, "PANEL_3"),
                      (QPalette.ToolTipText, "TEXT"), (QPalette.PlaceholderText, "TEXT_FAINT")):
        p.setColor(role, QColor(COLORS[key]))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, QColor(COLORS["TEXT_FAINT"]))
    return p


def _arrow(path: Path, color: str, up: bool = False) -> str:
    """Small chevron PNG for combo boxes / spin boxes. Returns a QSS-safe url path."""
    pm = QPixmap(30, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    pts = [QPointF(4, 4), QPointF(26, 4), QPointF(15, 15)] if not up else \
          [QPointF(4, 14), QPointF(26, 14), QPointF(15, 3)]
    p.drawPolygon(QPolygonF(pts))
    p.end()
    pm.save(str(path))
    return path.as_posix()


def _mark(folder: Path, name: str, kind: str) -> str:
    """Check mark / radio dot in ink-on-amber, at 1x and @2x (Qt picks @2x on high-DPI screens)."""
    for scale, suffix in ((1, ""), (2, "@2x")):
        s = 13 * scale
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        if kind == "check":
            pen = QPen(QColor(COLORS["ACCENT_FG"]), 1.8 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            p.drawPolyline(QPolygonF([QPointF(3.2 * scale, 6.8 * scale), QPointF(5.6 * scale, 9.2 * scale),
                                      QPointF(9.8 * scale, 4.2 * scale)]))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(COLORS["ACCENT_FG"]))
            p.drawEllipse(QPointF(6.5 * scale, 6.5 * scale), 2.4 * scale, 2.4 * scale)
        p.end()
        pm.save(str(folder / f"{name}{suffix}.png"))
    return (folder / f"{name}.png").as_posix()


def write_assets(folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    return {"check": _mark(folder, "check", "check"), "dot": _mark(folder, "dot", "dot"),
            "down": _arrow(folder / "down.png", COLORS["TEXT_DIM"]),
            "down_hover": _arrow(folder / "down_hover.png", COLORS["TEXT"]),
            "down_off": _arrow(folder / "down_off.png", COLORS["TEXT_FAINT"])}


def stylesheet(assets: dict) -> str:
    k = COLORS
    # No catch-all "* {font}" rule: it would override every setFont() (the frame readout, numerals).
    # The base UI font comes from app.setFont(ui_font()) in apply().
    return f"""
QMainWindow, QWidget#Root {{ background: {k['BG']}; }}
QWidget#Panel, QScrollArea#Panel > QWidget > QWidget {{ background: {k['PANEL']}; }}
QWidget#TopBar {{ background: {k['BG']}; }}
QLabel#PanelTitle {{ font-family: "{UI_FAMILY}"; font-size: 9.5pt; font-weight: 600; color: {k['TEXT']}; }}
QWidget#PanelHead {{ background: {k['PANEL']}; }}
QLabel#SectionTitle {{ font-family: "{UI_FAMILY}"; font-size: 9.5pt; font-weight: 600; color: {k['TEXT']}; }}
QLabel#Dim {{ color: {k['TEXT_DIM']}; }}
QLabel#Faint {{ color: {k['TEXT_FAINT']}; font-size: 8.5pt; }}
QLabel#Brand {{ font-family: "{UI_FAMILY}"; font-size: 11pt; font-weight: 600; color: {k['TEXT']}; }}
QLabel#Title {{ color: {k['TEXT']}; font-weight: 600; }}
QLabel#PathBox {{ background: {k['PANEL_2']}; border: 1px solid {k['BORDER']}; border-radius: 3px;
    padding: 4px 7px; color: {k['TEXT']}; }}
QFrame#HLine {{ background: {k['BORDER']}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#VLine {{ background: {k['BORDER']}; max-width: 1px; min-width: 1px; border: none; }}
QSplitter::handle {{ background: {k['BORDER']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QToolTip {{ background: {k['PANEL_3']}; color: {k['TEXT']}; border: 1px solid {k['BORDER']}; padding: 4px; }}

QPushButton, QToolButton {{
    background: {k['PANEL_2']}; color: {k['TEXT']}; border: 1px solid {k['BORDER']};
    border-radius: 3px; padding: 4px 10px; }}
QPushButton:hover, QToolButton:hover {{ background: {k['PANEL_3']}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {k['BORDER']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {k['TEXT_FAINT']}; }}
QPushButton:focus, QToolButton:focus {{ border-color: {k['ACCENT_DIM']}; }}
QPushButton#Primary {{ background: {k['ACCENT']}; color: {k['ACCENT_FG']}; border: none; font-weight: 600;
    padding: 6px 14px; }}
QPushButton#Primary:hover {{ background: {k['ACCENT_HI']}; }}
QPushButton#Primary:disabled {{ background: {k['PANEL_3']}; color: {k['TEXT_FAINT']}; }}
QToolButton#Seg {{ border-radius: 0; padding: 3px 9px; border: none; background: transparent; color: {k['TEXT_DIM']}; }}
QToolButton#Seg:checked {{ color: {k['TEXT']}; background: {k['PANEL_3']}; }}
QToolButton#Flat {{ border: none; background: transparent; padding: 3px 6px; }}
QToolButton#Flat:hover {{ background: {k['PANEL_3']}; }}
QToolButton#Icon {{ border: none; background: transparent; padding: 4px; border-radius: 4px; }}
QToolButton#Icon:hover {{ background: {k['PANEL_3']}; }}
QToolButton#Toggle {{ border: none; background: transparent; padding: 5px 9px 5px 7px; border-radius: 4px;
    color: {k['TEXT_FAINT']}; }}
QToolButton#Toggle[iconOnly="true"] {{ padding: 5px; }}
QToolButton#Toggle[plain="true"] {{ color: {k['TEXT_DIM']}; }}
QToolButton#Toggle[plain="true"]:hover {{ color: {k['TEXT']}; }}
QToolButton#Toggle:checked {{ background: {k['PANEL_2']}; color: {k['TEXT']}; }}
QWidget#JobRow {{ border-bottom: 1px solid {k['BORDER']}; }}
QWidget#JobRow:hover {{ background: {k['PANEL_2']}; }}
QToolButton#Toggle:hover {{ background: {k['PANEL_3']}; }}
QToolButton#Section {{ border: none; background: transparent; font-family: "{UI_FAMILY}"; font-size: 9.5pt;
    font-weight: 600; padding: 7px 4px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {k['PANEL_2']}; color: {k['TEXT']}; border: 1px solid {k['BORDER']};
    border-radius: 3px; padding: 3px 6px; selection-background-color: {k['ACCENT']};
    selection-color: {k['ACCENT_FG']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {k['ACCENT_DIM']}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0; border: none; }}
QComboBox {{ padding-right: 22px; }}
QComboBox:hover {{ background: {k['PANEL_3']}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; border: none; width: 20px; }}
QComboBox::down-arrow {{ image: url("{assets['down']}"); width: 10px; height: 6px; }}
QComboBox::down-arrow:hover, QComboBox::down-arrow:on {{ image: url("{assets['down_hover']}"); }}
QComboBox::down-arrow:disabled {{ image: url("{assets['down_off']}"); }}
QComboBox QAbstractItemView {{ background: {k['PANEL_2']}; border: 1px solid {k['BORDER']}; padding: 2px;
    selection-background-color: {k['PANEL_3']}; selection-color: {k['TEXT']}; outline: none; }}
QComboBox QAbstractItemView::item {{ padding: 4px 8px; min-height: 18px; border-radius: 3px; }}
QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {{
    background: {k['PANEL_3']}; color: {k['TEXT']}; }}
QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 13px; height: 13px; border: 1px solid {k['TEXT_FAINT']};
    background: {k['PANEL_2']}; border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {k['ACCENT']}; border-color: {k['ACCENT']}; }}
QCheckBox::indicator:checked {{ image: url("{assets['check']}"); }}
QRadioButton::indicator:checked {{ image: url("{assets['dot']}"); }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {k['TEXT_DIM']}; }}
QCheckBox::indicator:checked:hover, QRadioButton::indicator:checked:hover {{ border-color: {k['ACCENT_HI']}; }}

QSlider::groove:horizontal {{ height: 3px; background: {k['BORDER']}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {k['ACCENT_DIM']}; border-radius: 1px; }}
QSlider::handle:horizontal {{ background: {k['TEXT']}; width: 11px; height: 11px; margin: -5px 0; border-radius: 6px; }}
QSlider::handle:horizontal:hover {{ background: {k['ACCENT']}; }}

QProgressBar {{ background: {k['PANEL_3']}; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {k['ACCENT']}; border-radius: 2px; }}

QListWidget, QListView {{ background: {k['PANEL']}; border: none; outline: none; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 0; }}
QScrollBar::handle {{ background: {k['PANEL_3']}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {k['TEXT_FAINT']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; height: 0; width: 0; }}
QMenu {{ background: {k['PANEL_2']}; border: 1px solid {k['BORDER']}; padding: 4px; }}
QMenu::item {{ padding: 4px 18px; border-radius: 3px; }}
QMenu::item:selected {{ background: {k['PANEL_3']}; }}
QStatusBar {{ background: {k['BG']}; color: {k['TEXT_DIM']}; border-top: 1px solid {k['BORDER']}; }}
QStatusBar QLabel {{ color: {k['TEXT_DIM']}; padding: 0 8px; }}
QDialog {{ background: {k['PANEL']}; }}
"""


def apply(app) -> None:
    """Palette + stylesheet on a QApplication (call after it exists: assets are painted)."""
    from ..config import APP_ROOT
    load_fonts()
    app.setStyle("Fusion")
    app.setFont(ui_font())
    app.setPalette(palette())
    app.setStyleSheet(stylesheet(write_assets(APP_ROOT / ".cache" / "ui")))
