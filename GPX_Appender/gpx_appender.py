import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt

from .gpx_panel import GPXDockPanel

# Qt enum compatibility: PyQt5 (QGIS 3) vs PyQt6 (QGIS 4)
try:
    _Qt_RightDock = Qt.RightDockWidgetArea
except AttributeError:
    _Qt_RightDock = Qt.DockWidgetArea.RightDockWidgetArea


class GPXAppender:

    def __init__(self, iface):
        self.iface = iface
        self.dock = None

    def initGui(self):
        self.action = QAction("GPX Appender", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self._toggle_panel)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu("GPX Appender", self.action)
        self._create_dock()

    def unload(self):
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginVectorMenu("GPX Appender", self.action)

    def _create_dock(self):
        self.dock = GPXDockPanel(self.iface)
        self.iface.addDockWidget(_Qt_RightDock, self.dock)
        self.dock.visibilityChanged.connect(self.action.setChecked)

    def _toggle_panel(self, checked):
        if self.dock:
            self.dock.setVisible(checked)
