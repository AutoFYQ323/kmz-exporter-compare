# -*- coding: utf-8 -*-
"""Small call-name differences between QGIS 3 (Qt 5) and QGIS 4 (Qt 6)."""

from qgis.PyQt.QtWidgets import QHeaderView


def run_dialog(widget):
    runner = getattr(widget, "exec_", None)
    if not callable(runner):
        runner = widget.exec
    return runner()


def run_menu(menu, pos):
    runner = getattr(menu, "exec_", None)
    if not callable(runner):
        runner = menu.exec
    return runner(pos)


def pointer_pos(event):
    if hasattr(event, "position"):
        point = event.position()
        if hasattr(point, "toPoint"):
            return point.toPoint()
        return point
    return event.pos()


def header_mode(name):
    mode = getattr(QHeaderView, name, None)
    if mode is not None:
        return mode
    return getattr(QHeaderView.ResizeMode, name)
