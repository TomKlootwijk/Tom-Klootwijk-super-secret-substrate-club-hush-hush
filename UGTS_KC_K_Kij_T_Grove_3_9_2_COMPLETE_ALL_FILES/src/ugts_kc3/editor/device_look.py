"""Desktop reference presentation for the packed polar/Bayer substrate.

The editor still composes polar motion on the CPU from the exact binary16
UGLUT2 payload.  This module only adds the native Bayer presentation formula
as an optional OpenGL post pass.  It deliberately does not claim Android GPU
or performance parity.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import math
from typing import Sequence

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QGuiApplication, QOpenGLContext, QSurfaceFormat
from PySide6.QtOpenGL import (
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ..renderpack import RenderSubstrateConfig


# Canonical order from shaders/grove_post.frag.  A focused source-contract
# test prevents this pure reference oracle from drifting away from that asset.
BAYER8: tuple[int, ...] = (
    0,
    48,
    12,
    60,
    3,
    51,
    15,
    63,
    32,
    16,
    44,
    28,
    35,
    19,
    47,
    31,
    8,
    56,
    4,
    52,
    11,
    59,
    7,
    55,
    40,
    24,
    36,
    20,
    43,
    27,
    39,
    23,
    2,
    50,
    14,
    62,
    1,
    49,
    13,
    61,
    34,
    18,
    46,
    30,
    33,
    17,
    45,
    29,
    10,
    58,
    6,
    54,
    9,
    57,
    5,
    53,
    42,
    26,
    38,
    22,
    41,
    25,
    37,
    21,
)

_SHADER_RESOURCE_PARTS = (
    "project",
    "app",
    "src",
    "main",
    "assets",
    "shaders",
)


def native_post_shader_source(filename: str) -> str:
    """Read one packaged native post shader without maintaining a desktop copy."""

    if filename not in {"grove_post.vert", "grove_post.frag"}:
        raise ValueError(f"Unsupported post shader resource: {filename}")
    shader = resources.files("ugts_kc3.android_template").joinpath(
        *_SHADER_RESOURCE_PARTS, filename
    )
    return shader.read_text(encoding="utf-8")


def shader_source_for_context(source: str, *, is_gles: bool) -> str:
    """Adapt only the GLSL dialect preamble for a desktop core context."""

    lines = source.splitlines()
    if not lines or lines[0].strip() != "#version 300 es":
        raise ValueError("The shared post shader must use GLSL ES 3.00")
    if is_gles:
        return source
    adapted = ["#version 330 core"]
    adapted.extend(
        line for line in lines[1:] if not line.lstrip().startswith("precision ")
    )
    return "\n".join(adapted) + "\n"


def bayer_reference_rgb(
    rgb: Sequence[float],
    *,
    physical_x: int,
    physical_y_top: int,
    config: RenderSubstrateConfig | None,
) -> tuple[float, float, float]:
    """Evaluate shared Bayer formula/phase semantics for one physical pixel.

    Python arithmetic makes this a semantic oracle, not a claim that every
    intermediate is bit-identical to a particular GPU's float operations.
    """

    if config is None or not config.bayer_enabled:
        # Native Off returns before clamp/quantization. Preserve the input
        # components exactly, including values outside the display range.
        return rgb[0], rgb[1], rgb[2]

    threshold_index = (int(physical_y_top) & 7) * 8 + (int(physical_x) & 7)
    threshold = (BAYER8[threshold_index] + 0.5) / 64.0 - 0.5
    level_span = float(config.levels - 1)
    strength = float(config.strength)
    result: list[float] = []
    for component in rgb[:3]:
        source = max(0.0, min(1.0, float(component)))
        quantized = math.floor(source * level_span + 0.5 + threshold) / level_span
        result.append(source * (1.0 - strength) + quantized * strength)
    return result[0], result[1], result[2]


def bayer_reference_fragment_rgb(
    rgb: Sequence[float],
    *,
    fragment_x: float,
    fragment_y_bottom: float,
    output_height: int,
    config: RenderSubstrateConfig | None,
) -> tuple[float, float, float]:
    """Evaluate the shared bottom-to-top ``gl_FragCoord`` phase conversion."""

    if output_height <= 0:
        raise ValueError("output_height must be positive")
    y_top = (int(output_height) - 1 - int(fragment_y_bottom)) & 7
    return bayer_reference_rgb(
        rgb,
        physical_x=int(fragment_x) & 7,
        physical_y_top=y_top,
        config=config,
    )


@dataclass(frozen=True)
class DeviceLookSupport:
    """Result of the non-widget OpenGL capability probe."""

    available: bool
    reason: str = ""


def device_look_surface_format() -> QSurfaceFormat:
    """Return the non-multisampled format required by the shared post shader."""

    result = QSurfaceFormat()
    result.setAlphaBufferSize(8)
    result.setDepthBufferSize(24)
    result.setStencilBufferSize(8)
    result.setSamples(0)
    if (
        QOpenGLContext.openGLModuleType()
        == QOpenGLContext.OpenGLModuleType.LibGLES
    ):
        result.setRenderableType(QSurfaceFormat.RenderableType.OpenGLES)
        result.setVersion(3, 0)
        result.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
    else:
        result.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        result.setVersion(3, 3)
        result.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    return result


def probe_device_look_gl() -> DeviceLookSupport:
    """Check GL availability before replacing the dependable raster viewport."""

    application = QGuiApplication.instance()
    if application is None:
        return DeviceLookSupport(False, "no GUI application")
    platform = QGuiApplication.platformName().lower()
    if platform in {"offscreen", "minimal", "minimalegl"}:
        return DeviceLookSupport(False, f"the {platform} Qt platform has no preview GL")

    # Importing here keeps the pure Bayer functions usable in headless tests.
    from PySide6.QtGui import QOffscreenSurface

    requested = device_look_surface_format()
    surface = QOffscreenSurface()
    surface.setFormat(requested)
    surface.create()
    if not surface.isValid():
        return DeviceLookSupport(False, "OpenGL probe surface creation failed")

    context = QOpenGLContext()
    context.setFormat(requested)
    if not context.create() or not context.isValid():
        return DeviceLookSupport(False, "OpenGL 3 shader context creation failed")
    if not context.makeCurrent(surface):
        return DeviceLookSupport(False, "OpenGL probe context could not become current")
    try:
        actual = context.format()
        required = (3, 0) if context.isOpenGLES() else (3, 3)
        version = (actual.majorVersion(), actual.minorVersion())
        if version < required:
            return DeviceLookSupport(
                False,
                f"OpenGL {required[0]}.{required[1]} is required; got "
                f"{version[0]}.{version[1]}",
            )
    finally:
        context.doneCurrent()
    return DeviceLookSupport(True)


class _BayerPostProcessor:
    """Context-bound copy-and-post resources owned by one viewport widget."""

    _GL_NO_ERROR = 0
    _GL_TEXTURE0 = 0x84C0
    _GL_TEXTURE_2D = 0x0DE1
    _GL_FRAMEBUFFER = 0x8D40
    _GL_TRIANGLES = 0x0004
    _GL_DEPTH_TEST = 0x0B71
    _GL_STENCIL_TEST = 0x0B90
    _GL_BLEND = 0x0BE2
    _GL_CULL_FACE = 0x0B44
    _GL_SCISSOR_TEST = 0x0C11

    def __init__(self) -> None:
        self._context: QOpenGLContext | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._texture: QOpenGLTexture | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._texture_size = (0, 0)

    def _build_program(self, context: QOpenGLContext) -> QOpenGLShaderProgram:
        program = QOpenGLShaderProgram()
        vertex = shader_source_for_context(
            native_post_shader_source("grove_post.vert"),
            is_gles=context.isOpenGLES(),
        )
        fragment = shader_source_for_context(
            native_post_shader_source("grove_post.frag"),
            is_gles=context.isOpenGLES(),
        )
        if not program.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Vertex, vertex
        ):
            raise RuntimeError(f"post vertex shader failed: {program.log().strip()}")
        if not program.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Fragment, fragment
        ):
            raise RuntimeError(f"post fragment shader failed: {program.log().strip()}")
        if not program.link():
            raise RuntimeError(f"post shader link failed: {program.log().strip()}")
        return program

    def _ensure_resources(
        self, context: QOpenGLContext, width: int, height: int
    ) -> None:
        if self._context is not None and self._context is not context:
            raise RuntimeError("the OpenGL viewport context changed without cleanup")
        if self._context is None:
            self._context = context
            self._program = self._build_program(context)
            self._vao = QOpenGLVertexArrayObject()
            if not self._vao.create():
                raise RuntimeError("fullscreen vertex-array creation failed")
        if self._texture is not None and self._texture_size != (width, height):
            self._texture.destroy()
            self._texture = None
        if self._texture is None:
            texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
            texture.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
            texture.setSize(width, height)
            texture.allocateStorage(
                QOpenGLTexture.PixelFormat.RGBA,
                QOpenGLTexture.PixelType.UInt8,
            )
            texture.setMinMagFilters(
                QOpenGLTexture.Filter.Linear,
                QOpenGLTexture.Filter.Linear,
            )
            texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            if not texture.isCreated():
                raise RuntimeError("frame-copy texture creation failed")
            self._texture = texture
            self._texture_size = (width, height)

    @staticmethod
    def _location(program: QOpenGLShaderProgram, name: str) -> int:
        return program.uniformLocation(name.encode("ascii"))

    def render(
        self,
        *,
        framebuffer: int,
        width: int,
        height: int,
        config: RenderSubstrateConfig,
    ) -> None:
        context = QOpenGLContext.currentContext()
        if context is None:
            raise RuntimeError("no current OpenGL context")
        gl = context.extraFunctions()

        # Qt painting can leave an unrelated diagnostic queued. Only errors
        # produced by this pass should trigger the visible raster fallback.
        for _ in range(16):
            if gl.glGetError() == self._GL_NO_ERROR:
                break

        self._ensure_resources(context, width, height)
        assert self._program is not None
        assert self._texture is not None
        assert self._vao is not None

        gl.glBindFramebuffer(self._GL_FRAMEBUFFER, int(framebuffer))
        gl.glActiveTexture(self._GL_TEXTURE0)
        self._texture.bind(0)
        gl.glCopyTexSubImage2D(
            self._GL_TEXTURE_2D,
            0,
            0,
            0,
            0,
            0,
            width,
            height,
        )
        gl.glViewport(0, 0, width, height)
        gl.glDisable(self._GL_DEPTH_TEST)
        gl.glDisable(self._GL_STENCIL_TEST)
        gl.glDisable(self._GL_BLEND)
        gl.glDisable(self._GL_CULL_FACE)
        gl.glDisable(self._GL_SCISSOR_TEST)
        gl.glColorMask(True, True, True, True)

        if not self._program.bind():
            raise RuntimeError("post shader could not be bound")
        try:
            gl.glUniform1i(self._location(self._program, "uColor"), 0)
            gl.glUniform1f(self._location(self._program, "uTime"), 0.0)
            gl.glUniform1f(self._location(self._program, "uBloom"), 0.0)
            gl.glUniform1f(self._location(self._program, "uFlash"), 0.0)
            gl.glUniform1f(self._location(self._program, "uAberration"), 0.0)
            gl.glUniform1f(self._location(self._program, "uVignette"), 0.0)
            gl.glUniform1f(self._location(self._program, "uSaturation"), 1.0)
            gl.glUniform1f(self._location(self._program, "uContrast"), 1.0)
            gl.glUniform1f(self._location(self._program, "uShock"), 0.0)
            gl.glUniform1f(self._location(self._program, "uJuicePulse"), 0.0)
            gl.glUniform2f(self._location(self._program, "uShockCenter"), 0.5, 0.5)
            gl.glUniform1i(
                self._location(self._program, "uBayerMode"),
                config.bayer_mode_code,
            )
            gl.glUniform1i(
                self._location(self._program, "uBayerLevels"), config.levels
            )
            gl.glUniform1f(
                self._location(self._program, "uBayerStrength"), config.strength
            )
            gl.glUniform1i(
                self._location(self._program, "uOutputHeight"), height
            )
            self._vao.bind()
            try:
                gl.glDrawArrays(self._GL_TRIANGLES, 0, 3)
            finally:
                self._vao.release()
        finally:
            self._program.release()
            self._texture.release()

        error = gl.glGetError()
        if error != self._GL_NO_ERROR:
            raise RuntimeError(f"Bayer post pass failed with GL error 0x{error:04x}")

    def release(self) -> None:
        """Release resources while their owning context is current."""

        if self._texture is not None:
            self._texture.destroy()
        if self._vao is not None:
            self._vao.destroy()
        if self._program is not None:
            self._program.release()
            self._program.removeAllShaders()
        self._texture = None
        self._vao = None
        self._program = None
        self._context = None
        self._texture_size = (0, 0)


class DeviceLookOpenGLViewport(QOpenGLWidget):
    """QGraphicsView viewport that owns the optional reference post pass."""

    postFailed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DeviceLookOpenGLViewport")
        self.setFormat(device_look_surface_format())
        self.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.NoPartialUpdate)
        self.setAutoFillBackground(False)
        self._post = _BayerPostProcessor()
        self._connected_context: QOpenGLContext | None = None
        self._failed = False

    def initializeGL(self) -> None:  # noqa: N802 - Qt virtual name
        context = self.context()
        if context is not None and context is not self._connected_context:
            context.aboutToBeDestroyed.connect(self._context_about_to_be_destroyed)
            self._connected_context = context

    def apply_bayer_reference(
        self, painter, config: RenderSubstrateConfig
    ) -> bool:
        """Apply the post pass at the end of QGraphicsView foreground drawing."""

        if self._failed:
            return False
        if not config.bayer_enabled:
            return True
        if not self.isValid():
            self._failed = True
            self.postFailed.emit("the OpenGL viewport is invalid")
            return False
        physical_size = self.size() * self.devicePixelRatioF()
        width = max(0, physical_size.width())
        height = max(0, physical_size.height())
        if width == 0 or height == 0:
            return True
        painter.beginNativePainting()
        try:
            self._post.render(
                framebuffer=self.defaultFramebufferObject(),
                width=width,
                height=height,
                config=config,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._failed = True
            self.postFailed.emit(str(exc))
            return False
        finally:
            painter.endNativePainting()
        return True

    @Slot()
    def _context_about_to_be_destroyed(self) -> None:
        try:
            self.makeCurrent()
            self._post.release()
            self.doneCurrent()
        except RuntimeError:
            # A failed/invalid context has no live resources worth preserving.
            pass
        self._connected_context = None

    def shutdown(self) -> None:
        """Release GL objects before QGraphicsView replaces this viewport."""

        if self.context() is None or not self.isValid():
            return
        try:
            self.makeCurrent()
            self._post.release()
        finally:
            self.doneCurrent()


__all__ = [
    "BAYER8",
    "DeviceLookOpenGLViewport",
    "DeviceLookSupport",
    "bayer_reference_fragment_rgb",
    "bayer_reference_rgb",
    "native_post_shader_source",
    "probe_device_look_gl",
    "shader_source_for_context",
]
