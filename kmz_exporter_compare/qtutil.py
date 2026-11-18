# -*- coding: utf-8 -*-
"""Small call-name differences between QGIS 3 (Qt 5) and QGIS 4 (Qt 6)."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QHeaderView


def _window_flag(*names):
    """Resolve Qt5 / Qt6 window flag enums."""
    window_type = getattr(Qt, "WindowType", None)
    for name in names:
        if window_type is not None and hasattr(window_type, name):
            return getattr(window_type, name)
        if hasattr(Qt, name):
            return getattr(Qt, name)
    return 0


def apply_taskbar_window(widget):
    """Top-level window with minimize, independent of the QGIS main window."""
    if widget is None:
        return widget
    flags = (
        _window_flag("Window")
        | _window_flag("WindowTitleHint")
        | _window_flag("WindowSystemMenuHint")
        | _window_flag("WindowMinMaxButtonsHint")
        | _window_flag("WindowCloseButtonHint")
    )
    widget.setWindowFlags(flags)
    return widget


def run_dialog(widget):
    from qgis.PyQt.QtWidgets import QMessageBox

    if not isinstance(widget, QMessageBox):
        apply_taskbar_window(widget)
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
