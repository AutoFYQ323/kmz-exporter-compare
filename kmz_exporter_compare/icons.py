# -*- coding: utf-8 -*-
"""Toolbar icons. QGIS theme icons when they exist, otherwise a drawn mark."""

from qgis.PyQt.QtCore import Qt, QLineF, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap


def tool_icon(theme_name, letter, color):
    if theme_name:
        try:
            from qgis.core import QgsApplication

            icon = QgsApplication.getThemeIcon(theme_name)
            if icon is not None and not icon.isNull():
                return icon
        except Exception:  # nosec B110
            pass
    return _drawn(letter, color)


def glyph_icon(kind, color, size=16):
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    radius = max(2.0, size * 0.18)
    painter.drawRoundedRect(QRectF(0, 0, size - 1, size - 1), radius, radius)
    painter.save()
    painter.scale(size / 16.0, size / 16.0)
    _glyph(painter, kind, QColor(color))
    painter.restore()
    painter.end()
    return QIcon(pix)


def _stroke(painter, width):
    pen = QPen(QColor("#ffffff"), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _line(painter, x1, y1, x2, y2):
    painter.drawLine(QLineF(x1, y1, x2, y2))


def _glyph(painter, kind, background):
    white = QColor("#ffffff")
    if kind == "trash":
        _stroke(painter, 1.25)
        _line(painter, 6.3, 3.0, 9.7, 3.0)
        _line(painter, 6.6, 3.0, 6.6, 4.35)
        _line(painter, 9.4, 3.0, 9.4, 4.35)
        _line(painter, 3.5, 4.55, 12.5, 4.55)
        body = QPainterPath()
        body.moveTo(4.7, 5.7)
        body.lineTo(11.3, 5.7)
        body.lineTo(10.45, 13.15)
        body.lineTo(5.55, 13.15)
        body.closeSubpath()
        painter.drawPath(body)
        _line(painter, 7.15, 7.15, 7.15, 11.45)
        _line(painter, 8.85, 7.15, 8.85, 11.45)
        return
    if kind == "pencil":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(white)
        body = QPainterPath()
        body.moveTo(3.15, 10.35)
        body.lineTo(5.35, 12.55)
        body.lineTo(12.15, 5.75)
        body.lineTo(9.95, 3.55)
        body.closeSubpath()
        painter.drawPath(body)
        tip = QPainterPath()
        tip.moveTo(10.85, 4.45)
        tip.lineTo(13.55, 2.35)
        tip.lineTo(12.55, 6.15)
        tip.closeSubpath()
        painter.drawPath(tip)
        painter.setBrush(background)
        lead = QPainterPath()
        lead.moveTo(12.35, 3.55)
        lead.lineTo(13.55, 2.35)
        lead.lineTo(12.85, 4.25)
        lead.closeSubpath()
        painter.drawPath(lead)
        return
    if kind == "save":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(white)
        painter.drawRoundedRect(QRectF(3.05, 2.75, 9.9, 10.7), 1.15, 1.15)
        painter.setBrush(background)
        painter.drawRect(QRectF(5.55, 2.75, 4.7, 3.35))
        painter.drawRoundedRect(QRectF(4.35, 8.15, 7.3, 3.85), 0.45, 0.45)
        painter.setBrush(white)
        painter.drawRect(QRectF(5.35, 9.15, 5.3, 0.85))
        return
    if kind == "home":
        _stroke(painter, 1.2)
        roof = QPainterPath()
        roof.moveTo(2.8, 8.2)
        roof.lineTo(8.0, 3.2)
        roof.lineTo(13.2, 8.2)
        painter.drawPath(roof)
        painter.drawRect(QRectF(4.6, 8.0, 7.0, 5.5))
        return
    if kind == "cancel":
        _stroke(painter, 1.35)
        _line(painter, 4.5, 4.5, 11.5, 11.5)
        _line(painter, 11.5, 4.5, 4.5, 11.5)
        return
    if kind == "export":
        _stroke(painter, 1.2)
        painter.drawRect(QRectF(4.2, 9.0, 7.6, 3.2))
        _line(painter, 8.0, 3.0, 8.0, 9.0)
        _line(painter, 5.8, 5.2, 8.0, 3.0)
        _line(painter, 10.2, 5.2, 8.0, 3.0)
        return
    if kind == "run":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(white)
        play = QPainterPath()
        play.moveTo(5.0, 3.5)
        play.lineTo(12.0, 8.0)
        play.lineTo(5.0, 12.5)
        play.closeSubpath()
        painter.drawPath(play)
        return
    if kind == "folder":
        _stroke(painter, 1.1)
        painter.drawRoundedRect(QRectF(2.8, 5.0, 10.4, 7.5), 0.6, 0.6)
        painter.drawRoundedRect(QRectF(2.8, 3.4, 4.8, 2.2), 0.5, 0.5)
        return
    if kind == "refresh":
        _stroke(painter, 1.15)
        painter.drawArc(QRectF(3.0, 3.0, 10.0, 10.0), 30 * 16, 300 * 16)
        _line(painter, 10.8, 3.2, 12.8, 1.8)
        _line(painter, 10.8, 3.2, 9.4, 5.4)
        return
    if kind == "link":
        _stroke(painter, 1.15)
        painter.drawEllipse(QRectF(2.8, 5.5, 4.0, 4.0))
        painter.drawEllipse(QRectF(9.2, 5.5, 4.0, 4.0))
        _line(painter, 6.4, 7.5, 9.6, 7.5)
        return
    if kind == "doc":
        _stroke(painter, 1.1)
        painter.drawRoundedRect(QRectF(4.0, 2.5, 8.0, 11.0), 0.6, 0.6)
        _line(painter, 5.5, 5.5, 10.5, 5.5)
        _line(painter, 5.5, 7.5, 10.5, 7.5)
        _line(painter, 5.5, 9.5, 9.0, 9.5)
        return
    if kind == "reset":
        _stroke(painter, 1.1)
        painter.drawArc(QRectF(3.0, 3.0, 10.0, 10.0), 0, 360 * 16)
        _line(painter, 8.0, 2.0, 8.0, 4.2)
        _line(painter, 8.0, 2.0, 6.4, 3.4)
        return
    if kind == "compare":
        _stroke(painter, 1.1)
        painter.drawRect(QRectF(3.0, 4.0, 4.2, 8.0))
        painter.drawRect(QRectF(8.8, 4.0, 4.2, 8.0))
        _line(painter, 7.2, 8.0, 8.8, 8.0)
        return
    if kind == "select_all":
        _stroke(painter, 1.1)
        painter.drawRect(QRectF(3.0, 3.0, 10.0, 10.0))
        _line(painter, 4.5, 8.0, 7.0, 10.5)
        _line(painter, 7.0, 10.5, 11.5, 5.0)
        return
    if kind == "import_mode":
        _stroke(painter, 1.1)
        painter.drawRect(QRectF(3.0, 5.0, 10.0, 7.0))
        _line(painter, 8.0, 3.0, 8.0, 6.0)
        _line(painter, 6.0, 4.8, 8.0, 3.0)
        _line(painter, 10.0, 4.8, 8.0, 3.0)
        return
    if kind == "qgis_mode":
        _stroke(painter, 1.1)
        painter.drawEllipse(QRectF(3.0, 3.0, 10.0, 10.0))
        painter.drawEllipse(QRectF(6.0, 6.0, 4.0, 4.0))
        return
    if kind == "auto":
        _stroke(painter, 1.1)
        painter.drawEllipse(QRectF(2.5, 2.5, 11.0, 11.0))
        _line(painter, 8.0, 4.5, 8.0, 8.0)
        _line(painter, 8.0, 8.0, 10.8, 10.0)
        return
    if kind == "matched":
        _stroke(painter, 1.2)
        _line(painter, 3.5, 8.0, 6.5, 11.0)
        _line(painter, 6.5, 11.0, 12.5, 4.5)
        return
    if kind == "unmatched":
        _stroke(painter, 1.2)
        _line(painter, 4.0, 4.0, 12.0, 12.0)
        _line(painter, 12.0, 4.0, 4.0, 12.0)
        return
    if kind == "all":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(white)
        painter.drawEllipse(QRectF(3.0, 3.0, 4.0, 4.0))
        painter.drawEllipse(QRectF(9.0, 3.0, 4.0, 4.0))
        painter.drawEllipse(QRectF(6.0, 9.0, 4.0, 4.0))
        return
    if kind == "point":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(white)
        painter.drawEllipse(QRectF(5.0, 5.0, 6.0, 6.0))
        return
    if kind == "line":
        _stroke(painter, 1.3)
        _line(painter, 3.0, 11.0, 13.0, 5.0)
        return
    if kind == "polygon":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(white)
        tri = QPainterPath()
        tri.moveTo(8.0, 3.0)
        tri.lineTo(13.0, 12.0)
        tri.lineTo(3.0, 12.0)
        tri.closeSubpath()
        painter.drawPath(tri)
        return
    if kind == "field":
        _stroke(painter, 1.1)
        painter.drawRect(QRectF(3.0, 3.0, 10.0, 10.0))
        _line(painter, 3.0, 6.0, 13.0, 6.0)
        _line(painter, 6.0, 6.0, 6.0, 13.0)
        return
    _stroke(painter, 1.2)
    painter.drawRoundedRect(QRectF(6.15, 2.35, 7.15, 8.15), 0.7, 0.7)
    painter.setBrush(background)
    painter.drawRoundedRect(QRectF(2.55, 5.15, 7.35, 8.25), 0.7, 0.7)
    if kind == "copy":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        _line(painter, 4.0, 7.85, 8.45, 7.85)
        _line(painter, 4.0, 9.75, 8.45, 9.75)
        _line(painter, 4.0, 11.55, 6.7, 11.55)


def letter_icon(letter, color, size=16):
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(0, 0, size - 1, size - 1, 3, 3)
    painter.setPen(QColor("#ffffff"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(8, size - 6))
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    return QIcon(pix)


def _drawn(letter, color):
    return letter_icon(letter, color, 24)
