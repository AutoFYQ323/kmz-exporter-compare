# -*- coding: utf-8 -*-

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .dialog import MainDialog
from .i18n import language_changed, tr
from .icons import tool_icon


def _plugin_icon():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    icon = QIcon(path)
    if icon.isNull():
        return tool_icon("mActionFileSave.svg", "K", "#2e7d32")
    return icon


class Plugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        self.action = QAction(
            _plugin_icon(),
            tr("KMZ Exporter & Compare"),
            self.iface.mainWindow(),
        )
        self.action.setToolTip(tr("KMZ Exporter & Compare"))
        self.action.triggered.connect(self.run)
        self._menu = tr("&KMZ Exporter & Compare")
        self.iface.addPluginToMenu(self._menu, self.action)
        self.iface.addToolBarIcon(self.action)
        language_changed().connect(self._on_language)

    def _on_language(self, *_args):
        if self.action is None:
            return
        self.iface.removePluginMenu(self._menu, self.action)
        self.action.setText(tr("KMZ Exporter & Compare"))
        self.action.setToolTip(tr("KMZ Exporter & Compare"))
        self._menu = tr("&KMZ Exporter & Compare")
        self.iface.addPluginToMenu(self._menu, self.action)

    def unload(self):
        try:
            language_changed().disconnect(self._on_language)
        except Exception:
            pass
        if self.action is not None:
            self.iface.removePluginMenu(self._menu, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    def run(self):
        if self.dialog is None:
            self.dialog = MainDialog(self.iface.mainWindow())
        self.dialog.open_page("home")
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
