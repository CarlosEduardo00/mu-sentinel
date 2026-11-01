"""Ícone do MU Sentinel: escudo com um olho (o vigia), desenhado em código.

O mesmo desenho gera o ícone do .exe (assets/musentinel.ico, ver tools/make_icon.py), o da janela e o da bandeja.
Na bandeja ele ganha uma bolinha com o estado: verde (tudo certo), amarela (atenção), vermelha (alerta) ou
cinza (alertas pausados). Sem janelas do jogo abertas, fica sem bolinha.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

NAVY_TOP = "#2f5596"
NAVY_BOTTOM = "#14264a"
GOLD = "#e9b949"
GOLD_DARK = "#b9831f"
EYE_WHITE = "#f6f2e7"
PUPIL = "#0e1830"

# estado da bandeja -> cor da bolinha
STATUS_COLOR = {
    "ok": "#2ea043",
    "atencao": "#e3a008",
    "critico": "#e5484d",
    "pausado": "#8b949e",
}


def _shield_path() -> QPainterPath:
    """Escudo com o topo em bico, numa grade de 256x256."""
    p = QPainterPath()
    p.moveTo(128, 14)
    p.cubicTo(160, 32, 196, 40, 226, 40)
    p.lineTo(226, 118)
    p.cubicTo(226, 178, 184, 222, 128, 246)
    p.cubicTo(72, 222, 30, 178, 30, 118)
    p.lineTo(30, 40)
    p.cubicTo(60, 40, 96, 32, 128, 14)
    p.closeSubpath()
    return p


def _eye_path(cx: float, cy: float, w: float, h: float) -> QPainterPath:
    p = QPainterPath()
    p.moveTo(cx - w / 2, cy)
    p.quadTo(cx, cy - h, cx + w / 2, cy)
    p.quadTo(cx, cy + h, cx - w / 2, cy)
    p.closeSubpath()
    return p


def draw_brand(size: int) -> QImage:
    """Escudo azul com borda dourada e um olho no meio, sem fundo."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256
    p.scale(s, s)
    small = size <= 24
    shield = _shield_path()

    g = QLinearGradient(0, 14, 0, 246)
    g.setColorAt(0, QColor(NAVY_TOP))
    g.setColorAt(1, QColor(NAVY_BOTTOM))
    rim = 22 if small else 16  # borda mais grossa no tamanho pequeno, para não sumir
    p.setPen(QPen(QColor(GOLD), rim, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(g))
    p.drawPath(shield)

    cx, cy = 128, 124
    eye_w, eye_h = (168, 96) if small else (150, 84)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(EYE_WHITE))
    p.drawPath(_eye_path(cx, cy, eye_w, eye_h))

    iris_r = 40 if small else 33
    ig = QLinearGradient(0, cy - iris_r, 0, cy + iris_r)
    ig.setColorAt(0, QColor(GOLD))
    ig.setColorAt(1, QColor(GOLD_DARK))
    p.setBrush(QBrush(ig))
    p.drawEllipse(QPointF(cx, cy), iris_r, iris_r)
    p.setBrush(QColor(PUPIL))
    pupil_r = 20 if small else 16
    p.drawEllipse(QPointF(cx, cy), pupil_r, pupil_r)
    if not small:
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawEllipse(QPointF(cx + 11, cy - 11), 7, 7)
    p.end()
    return img


def draw_status(size: int, status: str | None) -> QImage:
    """Ícone com a bolinha de estado no canto de baixo à direita (recortada, para aparecer em qualquer fundo)."""
    img = draw_brand(size)
    color = STATUS_COLOR.get(status or "")
    if not color:
        return img
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    d = size * (0.50 if size <= 24 else 0.42)
    gap = max(1.0, size * 0.07)
    r = QRectF(size - d, size - d, d, d)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(Qt.GlobalColor.black)
    p.drawEllipse(r.adjusted(-gap, -gap, gap, gap))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    p.setBrush(QColor(color))
    p.drawEllipse(r)
    if size >= 32:  # símbolo dentro da bolinha só onde dá para ver
        p.setPen(QPen(QColor("white"), max(1.5, d * 0.14), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c = r.center()
        k = d * 0.22
        if status == "critico":
            p.drawLine(QPointF(c.x(), c.y() - k * 1.1), QPointF(c.x(), c.y() + k * 0.3))
            p.drawPoint(QPointF(c.x(), c.y() + k * 1.1))
        elif status == "pausado":
            p.drawLine(QPointF(c.x() - k * 0.5, c.y() - k), QPointF(c.x() - k * 0.5, c.y() + k))
            p.drawLine(QPointF(c.x() + k * 0.5, c.y() - k), QPointF(c.x() + k * 0.5, c.y() + k))
        elif status == "ok":
            path = QPainterPath(QPointF(c.x() - k, c.y()))
            path.lineTo(c.x() - k * 0.25, c.y() + k * 0.75)
            path.lineTo(c.x() + k, c.y() - k * 0.7)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
    p.end()
    return img


def app_icon(status: str | None = None) -> QIcon:
    icon = QIcon()
    for sz in SIZES:
        icon.addPixmap(QPixmap.fromImage(draw_status(sz, status)))
    return icon


def png_bytes(img: QImage) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data)


def ico_bytes(sizes: tuple[int, ...] = SIZES) -> bytes:
    """Arquivo .ico com uma imagem PNG por tamanho (formato aceito pelo Windows desde o Vista)."""
    import struct

    images = [(sz, png_bytes(draw_brand(sz))) for sz in sizes]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for sz, data in images:
        dim = 0 if sz >= 256 else sz
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return head + entries + blobs
