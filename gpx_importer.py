"""
GPX Appender Pro v4
- QGIS 4 compatible (PyQt6 + qgis.PyQt compatibility shim)
- Dockable drag-and-drop panel
- Destination layer picker (point or line layers)
- Auto-detects GPX sublayer and imports appropriately:
    • Target is Point  → imports all waypoints/track-points as individual points
    • Target is Line   → imports tracks as a single LineString per file
"""

import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication

from .gpx_panel import GPXDockPanel


class GPXImporter:

    def __init__(self, iface):
        self.iface = iface
        self.dock = None

    # ------------------------------------------------------------------
    # QGIS plugin lifecycle
    # ------------------------------------------------------------------

    def initGui(self):
        self.action = QAction("GPX Appender", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self._toggle_panel)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("GPX Appender", self.action)

        self._create_dock()

    def unload(self):
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("GPX Appender", self.action)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_dock(self):
        from qgis.PyQt.QtCore import Qt
        self.dock = GPXDockPanel(self.iface)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self.action.setChecked)

    def _toggle_panel(self, checked):
        if self.dock:
            self.dock.setVisible(checked)
