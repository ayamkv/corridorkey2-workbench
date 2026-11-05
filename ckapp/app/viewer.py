"""GPU image viewer: frames are textures, display transforms run in a shader.

Layouts: single, wipe (A left of the divider, B right) and side by side. Each
side shows a View: plate / foreground / checker output (one color texture),
composite (foreground over a checkerboard through the alpha texture) or matte.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import OpenGL
OpenGL.ERROR_CHECKING = False      # per-call glGetError is slow; shaders are checked at link time
from OpenGL import GL  # noqa: E402

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QSurfaceFormat  # noqa: E402
from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: E402

from . import theme as T  # noqa: E402
from .media import Frame  # noqa: E402

MODE_COLOR, MODE_COMPOSITE, MODE_MATTE, MODE_EMPTY = 0, 1, 2, 3

VERT = """#version 330 core
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

FRAG = """#version 330 core
out vec4 outColor;
uniform sampler2D uColor;
uniform sampler2D uAlpha;
uniform int uMode;            // 0 color, 1 composite, 2 matte, 3 empty
uniform bool uColorLinear;
uniform vec4 uViewport;       // x, y, w, h in framebuffer pixels (bottom-left origin)
uniform vec2 uImgSize;        // image size in pixels
uniform vec2 uCenter;         // image coords (top-left origin) shown at the viewport centre
uniform float uZoom;          // framebuffer pixels per image pixel
uniform float uCheck;         // checker size in framebuffer pixels
uniform vec3 uBg;
uniform float uDespill;       // composite only: CorridorKey's average despill, 0..1
uniform sampler2D uMask;      // click-to-mask result, 1 = keep
uniform bool uMaskOn;
uniform vec3 uTint;

vec3 srgbEncode(vec3 x) {
    x = max(x, vec3(0.0));
    vec3 lo = x * 12.92;
    vec3 hi = 1.055 * pow(x, vec3(1.0 / 2.4)) - 0.055;
    return mix(lo, hi, step(vec3(0.0031308), x));
}
// corridorkey/runtime.py _despill_average_srgb_torch: green above the red/blue average moves into red and blue.
// Upstream applies it to sRGB foregrounds (video) and to linear ones (EXR); here it runs before the sRGB encode,
// so it matches both.
vec3 despill(vec3 c, float s) {
    float spill = max(c.g - (c.r + c.b) * 0.5, 0.0);
    vec3 full = vec3(c.r + spill * 0.5, c.g - spill, c.b + spill * 0.5);
    return mix(c, full, clamp(s, 0.0, 1.0));
}
vec3 checker(vec2 p) {
    vec2 c = floor(p / uCheck);
    return mix(vec3(0.24), vec3(0.36), mod(c.x + c.y, 2.0));
}
void main() {
    vec2 p = gl_FragCoord.xy - uViewport.xy;
    vec2 q = vec2(p.x, uViewport.w - p.y);                 // top-left origin
    vec2 img = (q - 0.5 * uViewport.zw) / uZoom + uCenter;
    vec2 uv = img / uImgSize;
    if (uMode == 3 || any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) {
        outColor = vec4(uBg, 1.0);
        return;
    }
    vec3 c = texture(uColor, uv).rgb;
    if (uMode == 1 && uDespill > 0.0) c = despill(c, uDespill);
    if (uColorLinear) c = srgbEncode(c);
    if (uMode == 2) {
        outColor = vec4(vec3(clamp(c.r, 0.0, 1.0)), 1.0);
    } else if (uMode == 1) {
        float a = clamp(texture(uAlpha, uv).r, 0.0, 1.0);
        outColor = vec4(mix(checker(q), clamp(c, 0.0, 1.0), a), 1.0);
    } else {
        outColor = vec4(clamp(c, 0.0, 1.0), 1.0);
    }
    if (uMaskOn) {
        // tint what's kept, dim the rest a little, and outline the edge about 1.5 screen pixels wide
        float m = texture(uMask, uv).r;
        vec2 d = vec2(1.5 / uZoom) / uImgSize;
        float lo = min(min(texture(uMask, uv + vec2(d.x, 0.0)).r, texture(uMask, uv - vec2(d.x, 0.0)).r),
                       min(texture(uMask, uv + vec2(0.0, d.y)).r, texture(uMask, uv - vec2(0.0, d.y)).r));
        float hi = max(max(texture(uMask, uv + vec2(d.x, 0.0)).r, texture(uMask, uv - vec2(d.x, 0.0)).r),
                       max(texture(uMask, uv + vec2(0.0, d.y)).r, texture(uMask, uv - vec2(0.0, d.y)).r));
        vec3 rgb = mix(outColor.rgb * 0.55, mix(outColor.rgb, uTint, 0.35), m);
        float edge = step(0.5, hi) * (1.0 - step(0.5, lo));
        outColor = vec4(mix(rgb, uTint, edge), 1.0);
    }
}
"""


def default_surface_format() -> QSurfaceFormat:
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSwapInterval(1)
    return fmt


@dataclass
class Side:
    """What one side of the viewer shows."""
    label: str = ""
    mode: int = MODE_EMPTY
    color: Optional[Frame] = None
    alpha: Optional[Frame] = None
    note: str = ""                   # shown when there is nothing to draw
    despill: float = 0.0             # composite: despill the foreground, as the checker and cutout outputs are


class _Tex:
    def __init__(self):
        self.id = GL.glGenTextures(1)
        self.key = None
        self.shape = None
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.id)
        for p, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                     (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, p, v)

    def upload(self, fr: Frame, key=None) -> None:
        """`key` names the content; by default the Frame object (fine while frames live in the cache)."""
        key = id(fr) if key is None else key
        if self.key is not None and self.key == key:
            return
        a = fr.data
        h, w, c = a.shape
        is_f = a.dtype != np.uint8
        fmt = GL.GL_RED if c == 1 else GL.GL_BGR          # frames keep OpenCV's BGR order
        ifmt = {(1, False): GL.GL_R8, (3, False): GL.GL_RGB8, (1, True): GL.GL_R16F, (3, True): GL.GL_RGB16F}[(c, is_f)]
        typ = GL.GL_HALF_FLOAT if is_f else GL.GL_UNSIGNED_BYTE
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.id)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        shape = (w, h, ifmt)
        if shape == self.shape:
            GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, w, h, fmt, typ, a)
        else:
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, ifmt, w, h, 0, fmt, typ, a)
            self.shape = shape
            sw = GL.GL_RED if c == 1 else None
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_SWIZZLE_G, sw or GL.GL_GREEN)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_SWIZZLE_B, sw or GL.GL_BLUE)
        self.key = key

    def set_nearest(self, on: bool) -> None:
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.id)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST if on else GL.GL_LINEAR)


class GLViewer(QOpenGLWidget):
    viewChanged = Signal()
    glFailed = Signal(str)
    maskClicked = Signal(float, float, bool)            # image x, y; True = keep, False = remove
    maskBoxed = Signal(float, float, float, float)      # image x0, y0, x1, y1 (any order)

    SINGLE, WIPE, SIDE = "single", "wipe", "side"
    DRAG_PX = 4                                         # a press that moves less than this is a click

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 200)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.layout_mode = self.SINGLE
        self.a, self.b = Side(), Side()
        self.wipe = 0.5                 # divider position, fraction of width
        self.fit = True
        self.zoom = 1.0                 # framebuffer px per image px (when not fit)
        self.center: Optional[QPointF] = None   # image coords at viewport centre
        self.img_size = (1920, 1080)
        self._drag = None
        self._prog = None
        self._tex: dict[str, _Tex] = {}
        self._ok = True
        # click to mask: the tool, the mask shown over side A (single layout), and the prompts drawn on top
        self.mask_tool = False
        self.mask: Optional[Frame] = None
        self.mask_key = 0
        self.mask_points: list = []
        self.mask_box: Optional[list] = None
        self._box_drag: Optional[tuple[QPointF, QPointF]] = None

    # -- content ---------------------------------------------------------------------------
    def set_mask_tool(self, on: bool) -> None:
        self.mask_tool = on
        self._drag = self._box_drag = None
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        self.update()

    def set_mask(self, mask: Optional[Frame], key: int = 0, points: Optional[list] = None,
                 box: Optional[list] = None) -> None:
        """The mask (HxWx1 uint8, 255 = keep) and its prompts; `key` changes whenever the mask does."""
        self.mask, self.mask_key = mask, key
        self.mask_points, self.mask_box = list(points or []), box
        self.update()
    def set_sides(self, a: Side, b: Side) -> None:
        self.a, self.b = a, b
        for s in (a, b):
            if s.color is not None:
                w, h = s.color.size
                if (w, h) != self.img_size:
                    self.img_size = (w, h)
                    self.center = None
                break
        self.update()

    def set_layout(self, mode: str) -> None:
        self.layout_mode = mode
        self.update()

    def fit_view(self) -> None:
        self.fit, self.center = True, None
        self.update()
        self.viewChanged.emit()

    def set_zoom_percent(self, pct: float) -> None:
        self.fit = False
        self.zoom = pct / 100.0 * self.devicePixelRatioF()
        self.update()
        self.viewChanged.emit()

    def zoom_percent(self) -> float:
        vp = self._viewports()[0]
        z = self._fit_zoom(vp) if self.fit else self.zoom
        return 100.0 * z / self.devicePixelRatioF()

    # -- GL ----------------------------------------------------------------------------------
    def initializeGL(self) -> None:
        try:
            vs = self._shader(GL.GL_VERTEX_SHADER, VERT)
            fs = self._shader(GL.GL_FRAGMENT_SHADER, FRAG)
            prog = GL.glCreateProgram()
            GL.glAttachShader(prog, vs)
            GL.glAttachShader(prog, fs)
            GL.glLinkProgram(prog)
            if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
                raise RuntimeError(GL.glGetProgramInfoLog(prog).decode(errors="replace"))
            self._prog = prog
            self._vao = GL.glGenVertexArrays(1)
            self._u = {n: GL.glGetUniformLocation(prog, n) for n in (
                "uColor", "uAlpha", "uMode", "uColorLinear", "uViewport", "uImgSize", "uCenter",
                "uZoom", "uCheck", "uBg", "uMask", "uMaskOn", "uTint", "uDespill")}
            self._tex = {k: _Tex() for k in ("a_color", "a_alpha", "b_color", "b_alpha", "mask")}
        except Exception as e:  # no GL 3.3: report and draw nothing
            self._ok = False
            self.glFailed.emit(str(e))

    @staticmethod
    def _shader(kind, src):
        sh = GL.glCreateShader(kind)
        GL.glShaderSource(sh, src)
        GL.glCompileShader(sh)
        if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
            raise RuntimeError(GL.glGetShaderInfoLog(sh).decode(errors="replace"))
        return sh

    def resizeGL(self, w: int, h: int) -> None:
        self.viewChanged.emit()          # "Fit" zoom % depends on the widget size

    def _viewports(self) -> list[tuple[int, int, int, int]]:
        dpr = self.devicePixelRatioF()
        w, h = int(self.width() * dpr), int(self.height() * dpr)
        if self.layout_mode == self.SIDE:
            half = w // 2
            return [(0, 0, half - 1, h), (half + 1, 0, w - half - 1, h)]
        return [(0, 0, w, h)]

    def _fit_zoom(self, vp) -> float:
        iw, ih = self.img_size
        return max(1e-3, min(vp[2] / iw, vp[3] / ih) * 0.97)

    def _view_for(self, vp) -> tuple[float, float, float]:
        z = self._fit_zoom(vp) if self.fit else self.zoom
        c = self.center or QPointF(self.img_size[0] / 2, self.img_size[1] / 2)
        return z, c.x(), c.y()

    def paintGL(self) -> None:
        p = QPainter(self)
        p.beginNativePainting()
        bg = QColor(T.c("VIEWER_BG"))
        GL.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if self._ok and self._prog:
            GL.glUseProgram(self._prog)
            GL.glBindVertexArray(self._vao)
            GL.glUniform1i(self._u["uColor"], 0)
            GL.glUniform1i(self._u["uAlpha"], 1)
            GL.glUniform1i(self._u["uMask"], 2)
            tint = QColor(T.c("ACCENT"))
            GL.glUniform3f(self._u["uTint"], tint.redF(), tint.greenF(), tint.blueF())
            GL.glUniform3f(self._u["uBg"], bg.redF(), bg.greenF(), bg.blueF())
            GL.glUniform1f(self._u["uCheck"], 12.0 * self.devicePixelRatioF())
            vps = self._viewports()
            if self.layout_mode == self.SIDE:
                self._draw(self.a, "a", vps[0])
                self._draw(self.b, "b", vps[1])
            elif self.layout_mode == self.WIPE:
                vp = vps[0]
                split = int(vp[2] * self.wipe)
                GL.glEnable(GL.GL_SCISSOR_TEST)
                GL.glScissor(0, 0, split, vp[3])
                self._draw(self.a, "a", vp)
                GL.glScissor(split, 0, vp[2] - split, vp[3])
                self._draw(self.b, "b", vp)
                GL.glDisable(GL.GL_SCISSOR_TEST)
            else:
                self._draw(self.a, "a", vps[0])
            GL.glBindVertexArray(0)
            GL.glUseProgram(0)
            # Give QPainter back the state it expects. Its glyph cache uploads text with the
            # default 4-byte unpack alignment; leaving ours at 1 garbles letters in the overlay.
            for unit in (GL.GL_TEXTURE2, GL.GL_TEXTURE1, GL.GL_TEXTURE0):     # ends with unit 0 active
                GL.glActiveTexture(unit)
                GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 4)
        p.endNativePainting()
        self._overlay(p)
        p.end()

    def _draw(self, side: Side, slot: str, vp) -> None:
        mode = side.mode if side.color is not None else MODE_EMPTY
        if mode == MODE_COMPOSITE and side.alpha is None:
            mode = MODE_COLOR
        z, cx, cy = self._view_for(vp)
        GL.glViewport(*vp)
        GL.glUniform4f(self._u["uViewport"], *vp)
        GL.glUniform2f(self._u["uImgSize"], *self.img_size)
        GL.glUniform2f(self._u["uCenter"], cx, cy)
        GL.glUniform1f(self._u["uZoom"], z)
        GL.glUniform1i(self._u["uMode"], mode)
        GL.glUniform1f(self._u["uDespill"], side.despill if mode == MODE_COMPOSITE else 0.0)
        mask_on = (slot == "a" and self.layout_mode == self.SINGLE and self.mask is not None
                   and side.color is not None and self.mask.size == side.color.size)
        GL.glUniform1i(self._u["uMaskOn"], int(mask_on))
        if mask_on:
            tm = self._tex["mask"]
            GL.glActiveTexture(GL.GL_TEXTURE2)
            tm.upload(self.mask, key=self.mask_key)
            tm.set_nearest(z >= 2.0)
            GL.glActiveTexture(GL.GL_TEXTURE0)
        if mode != MODE_EMPTY:
            t = self._tex[f"{slot}_color"]
            GL.glActiveTexture(GL.GL_TEXTURE0)
            t.upload(side.color)
            t.set_nearest(z >= 2.0)
            GL.glUniform1i(self._u["uColorLinear"], int(side.color.linear))
            if mode == MODE_COMPOSITE:
                ta = self._tex[f"{slot}_alpha"]
                GL.glActiveTexture(GL.GL_TEXTURE1)
                ta.upload(side.alpha)
                ta.set_nearest(z >= 2.0)
                GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, t.id)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)

    def _overlay(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(T.ui_font(8.5, bold=True))
        w, h = self.width(), self.height()

        def tag(x, y, text, right=False):
            if not text:
                return
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(text) + 12
            r = QRectF(x - tw if right else x, y, tw, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QColor(T.c("TEXT")))
            p.drawText(r, Qt.AlignCenter, text)

        def note(rect: QRectF, side: Side):
            if side.color is None and side.note:
                p.setPen(QColor(T.c("TEXT_DIM")))
                p.drawText(rect, Qt.AlignCenter, side.note)

        if self.layout_mode == self.SIDE:
            note(QRectF(0, 0, w / 2, h), self.a)
            note(QRectF(w / 2, 0, w / 2, h), self.b)
            tag(10, 10, self.a.label)
            tag(w / 2 + 10, 10, self.b.label)
            p.setPen(QPen(QColor(T.c("BORDER")), 2))
            p.drawLine(QPointF(w / 2, 0), QPointF(w / 2, h))
        elif self.layout_mode == self.WIPE:
            x = w * self.wipe
            note(QRectF(0, 0, x, h), self.a)
            note(QRectF(x, 0, w - x, h), self.b)
            tag(10, 10, self.a.label)
            tag(w - 10, 10, self.b.label, right=True)
            p.setPen(QPen(QColor(T.c("ACCENT")), 2))
            p.drawLine(QPointF(x, 0), QPointF(x, h))
            p.setBrush(QColor(T.c("ACCENT")))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, h / 2), 7, 7)
        else:
            note(QRectF(0, 0, w, h), self.a)
            tag(10, 10, self.a.label)
            self._mask_overlay(p)
        if not self._ok:
            p.setPen(QColor(T.c("ERROR")))
            p.drawText(self.rect(), Qt.AlignCenter, "OpenGL 3.3 is not available - the viewer is disabled")

    def _mask_overlay(self, p: QPainter) -> None:
        """Keep (green) and remove (red) dots, the box, and the box being dragged."""
        if not (self.mask_tool or self.mask_points or self.mask_box):
            return
        accent = QColor(T.c("ACCENT"))
        for box, dashed in ((self.mask_box, False),
                            ((self._box_drag[0].x(), self._box_drag[0].y(), self._box_drag[1].x(),
                              self._box_drag[1].y()) if self._box_drag else None, True)):
            if not box:
                continue
            r = QRectF(self.widget_at(QPointF(box[0], box[1])), self.widget_at(QPointF(box[2], box[3]))).normalized()
            pen = QPen(accent, 1.5, Qt.DashLine if dashed else Qt.SolidLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        for x, y, keep in self.mask_points:
            c = self.widget_at(QPointF(x, y))
            p.setPen(QPen(QColor(0, 0, 0, 200), 2))
            p.setBrush(QColor(T.c("OK" if keep else "ERROR")))
            p.drawEllipse(c, 5.5, 5.5)
            p.setPen(QPen(QColor(255, 255, 255, 230), 1.6))
            p.drawLine(QPointF(c.x() - 2.5, c.y()), QPointF(c.x() + 2.5, c.y()))
            if keep:
                p.drawLine(QPointF(c.x(), c.y() - 2.5), QPointF(c.x(), c.y() + 2.5))

    # -- interaction -------------------------------------------------------------------------
    def widget_at(self, img: QPointF) -> QPointF:
        """Image pixel -> widget position (single / wipe layout); the inverse of _img_at."""
        dpr = self.devicePixelRatioF()
        vp = self._viewports()[0]
        z, cx, cy = self._view_for(vp)
        return QPointF(((img.x() - cx) * z + vp[2] / 2 + vp[0]) / dpr, ((img.y() - cy) * z + vp[3] / 2) / dpr)

    def _img_at(self, pos: QPointF, vp_index: int = 0) -> QPointF:
        dpr = self.devicePixelRatioF()
        vp = self._viewports()[vp_index]
        z, cx, cy = self._view_for(vp)
        qx = pos.x() * dpr - vp[0]
        qy = pos.y() * dpr
        return QPointF((qx - vp[2] / 2) / z + cx, (qy - vp[3] / 2) / z + cy)

    def _vp_index(self, pos: QPointF) -> int:
        return 1 if self.layout_mode == self.SIDE and pos.x() > self.width() / 2 else 0

    def _freeze_fit(self) -> None:
        if self.fit:
            vp = self._viewports()[0]
            self.zoom = self._fit_zoom(vp)
            self.fit = False
        if self.center is None:
            self.center = QPointF(self.img_size[0] / 2, self.img_size[1] / 2)

    def wheelEvent(self, e) -> None:
        pos = e.position()
        idx = self._vp_index(pos)
        before = self._img_at(pos, idx)
        self._freeze_fit()
        factor = 1.0 + 0.0015 * e.angleDelta().y()
        self.zoom = float(np.clip(self.zoom * max(0.2, factor), 0.02, 64.0))
        after = self._img_at(pos, idx)
        self.center += before - after
        self.update()
        self.viewChanged.emit()

    def mousePressEvent(self, e) -> None:
        pos = e.position()
        if self.mask_tool and e.button() in (Qt.LeftButton, Qt.RightButton):
            self._drag = ("mask", pos, e.button())          # click (point) or, for left, a drag (box)
            e.accept()
            return
        if self.layout_mode == self.WIPE and e.button() == Qt.LeftButton and abs(pos.x() - self.width() * self.wipe) < 12:
            self._drag = ("wipe", pos)
        elif e.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._freeze_fit()
            self._drag = ("pan", pos, QPointF(self.center))
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if self._drag and self._drag[0] == "mask":
            start, button = self._drag[1], self._drag[2]
            moved = (pos - start).manhattanLength() >= self.DRAG_PX
            if button == Qt.LeftButton and (moved or self._box_drag):
                self._box_drag = (self._img_at(start), self._img_at(pos))
                self.update()
            return
        if self._drag and self._drag[0] == "wipe":
            self.wipe = float(np.clip(pos.x() / max(1, self.width()), 0.0, 1.0))
            self.update()
        elif self._drag and self._drag[0] == "pan":
            dpr = self.devicePixelRatioF()
            d = (pos - self._drag[1]) * dpr / self.zoom
            self.center = self._drag[2] - d
            self.update()
        elif self.layout_mode == self.WIPE:
            near = abs(pos.x() - self.width() * self.wipe) < 12
            self.setCursor(Qt.SplitHCursor if near else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e) -> None:
        if self._drag and self._drag[0] == "mask":
            start, button = self._drag[1], self._drag[2]
            if e.button() != button:
                return
            box, self._box_drag, self._drag = self._box_drag, None, None
            if box is not None:
                self.maskBoxed.emit(box[0].x(), box[0].y(), box[1].x(), box[1].y())
            else:
                img = self._img_at(start)
                if 0 <= img.x() < self.img_size[0] and 0 <= img.y() < self.img_size[1]:
                    self.maskClicked.emit(img.x(), img.y(), button == Qt.LeftButton)
            self.update()
            return
        if self._drag and self._drag[0] == "pan":
            self.viewChanged.emit()
        self._drag = None

    def mouseDoubleClickEvent(self, e) -> None:
        if self.mask_tool:                  # quick clicks are two points, not "fit"
            self.mousePressEvent(e)
            return
        self.fit_view()

    def grab_rgb(self) -> np.ndarray:
        """Rendered viewer as an RGB array (tests / screenshots)."""
        img = self.grabFramebuffer().convertToFormat(QImage.Format_RGB888)
        arr = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).reshape(img.height(), img.bytesPerLine())
        return arr[:, : img.width() * 3].reshape(img.height(), img.width(), 3).copy()
