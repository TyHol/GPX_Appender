"""
FieldMappingWidget
==================
A table widget where each row represents one field on the destination layer.
The user configures where the value comes from via a "source type" combo:

  Source type        | What the user configures
  -------------------|--------------------------------------------------
  (ignore)           | Field is left empty / not written
  From GPX           | Value copied from matching-name GPX attribute
  Layer pick         | Pick a layer, then a field, then a specific value
  Expression         | Free QGIS expression (opens the expression builder)

Mappings are serialised as a list of dicts and stored in QSettings keyed
by destination layer ID so each layer remembers its own mapping.

Public API
----------
  widget.load_for_layer(layer)   – populate table rows from layer fields
                                   and restore any saved mapping
  widget.save_for_layer(layer)   – persist current table state to QSettings
  widget.get_mappings()          – return list[dict] for the importer to use
"""

import json

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QComboBox, QLineEdit, QPushButton, QLabel, QHeaderView, QSizePolicy,
    QAbstractItemView
)
from qgis.PyQt.QtCore import Qt, QSettings
from .compat import (
    Qt_ItemIsEnabled,
    QHeaderView_ResizeToContents, QHeaderView_Stretch,
    QAbstractItemView_NoEditTriggers, QAbstractItemView_NoSelection,
    QSizePolicy_Expanding,
)


from qgis.PyQt.QtGui import QColor, QFont

from qgis.core import QgsProject, QgsVectorLayer, QgsExpression
from qgis.gui import QgsExpressionBuilderDialog

# Standard OGR GPX attribute fields (lat/lon/ele are geometry, not fields,
# but ele is also exposed as a regular field on track_points and waypoints)
GPX_FIELDS_WAYPOINTS = [
    "name", "ele", "time", "desc", "cmt", "src", "sym", "type",
    "fix", "sat", "hdop", "vdop", "pdop",
    "magvar", "geoidheight", "ageofdgpsdata", "dgpsid",
    "link1_href", "link1_text", "link1_type",
    "link2_href", "link2_text", "link2_type",
]
GPX_FIELDS_TRACK_POINTS = [
    "track_fid", "track_seg_id", "track_seg_point_id",
    "ele", "time", "name", "desc", "cmt", "src", "sym", "type",
    "fix", "sat", "hdop", "vdop", "pdop",
    "magvar", "geoidheight", "ageofdgpsdata", "dgpsid",
    "link1_href", "link1_text", "link1_type",
    "link2_href", "link2_text", "link2_type",
]
GPX_FIELDS_ALL = list(dict.fromkeys(
    GPX_FIELDS_TRACK_POINTS + GPX_FIELDS_WAYPOINTS
))

# Source-type identifiers (stored in settings)
SRC_IGNORE   = "ignore"
SRC_GPX      = "gpx"
SRC_LAYER    = "layer"
SRC_EXPR     = "expression"
SRC_FOLDER   = "folder"
SRC_FILENAME = "gpx_filename"

_SRC_LABELS = {
    SRC_IGNORE:   "(ignore)",
    SRC_GPX:      "From GPX",
    SRC_LAYER:    "Layer pick",
    SRC_EXPR:     "Expression",
    SRC_FOLDER:   "Parent folder",
    SRC_FILENAME: "GPX filename",
}

SETTINGS_KEY = "gpx_importer/field_mappings"


# ---------------------------------------------------------------------------
# Per-row source widget (the compound widget in column 2)
# ---------------------------------------------------------------------------

class _SourceWidget(QWidget):
    """
    Embeds inside a table cell.  Shows different sub-widgets depending on
    which source type is selected.
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(3)

        # Source type combo
        self.type_cb = QComboBox()
        for key, label in _SRC_LABELS.items():
            self.type_cb.addItem(label, key)
        self.type_cb.setFixedWidth(100)
        layout.addWidget(self.type_cb)

        # --- From GPX: field name picker ---
        self.gpx_field_cb = QComboBox()
        self.gpx_field_cb.setEditable(True)
        self.gpx_field_cb.setMinimumWidth(150)
        self.gpx_field_cb.setToolTip(
            "GPX attribute to read. These are the standard fields the OGR "
            "GPX driver exposes. Geometry coordinates (lat/lon) are not "
            "listed — they become the point geometry automatically."
        )
        for f in GPX_FIELDS_ALL:
            self.gpx_field_cb.addItem(f)
        layout.addWidget(self.gpx_field_cb)

        # --- Layer-pick sub-widgets ---
        self.lyr_cb = QComboBox()   # layer picker
        self.lyr_cb.setMinimumWidth(90)
        self._populate_layer_combo()
        layout.addWidget(self.lyr_cb)

        self.fld_cb = QComboBox()   # field picker (updates when layer changes)
        self.fld_cb.setMinimumWidth(80)
        layout.addWidget(self.fld_cb)

        self.val_cb = QComboBox()   # value picker (updates when field changes)
        self.val_cb.setMinimumWidth(80)
        layout.addWidget(self.val_cb)

        self.lyr_cb.currentIndexChanged.connect(self._on_layer_changed)
        self.fld_cb.currentIndexChanged.connect(self._on_field_changed)

        # --- Expression sub-widget ---
        self.expr_edit = QLineEdit()
        self.expr_edit.setPlaceholderText("expression…")
        self.expr_edit.setMinimumWidth(130)
        layout.addWidget(self.expr_edit)

        self.expr_btn = QPushButton("…")
        self.expr_btn.setFixedWidth(24)
        self.expr_btn.setToolTip("Open expression builder")
        self.expr_btn.clicked.connect(self._open_expr_builder)
        layout.addWidget(self.expr_btn)

        layout.addStretch()

        self.type_cb.currentIndexChanged.connect(self._on_type_changed)
        self._on_type_changed()

    # ------------------------------------------------------------------
    # Layer/field/value cascades
    # ------------------------------------------------------------------

    def _populate_layer_combo(self):
        self.lyr_cb.blockSignals(True)
        self.lyr_cb.clear()
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer):
                self.lyr_cb.addItem(lyr.name(), lyr.id())
        self.lyr_cb.blockSignals(False)

    def _on_layer_changed(self):
        self.fld_cb.blockSignals(True)
        self.fld_cb.clear()
        lyr = self._picked_layer()
        if lyr:
            for f in lyr.fields():
                self.fld_cb.addItem(f.name())
        self.fld_cb.blockSignals(False)
        self._on_field_changed()

    def _on_field_changed(self):
        self.val_cb.blockSignals(True)
        self.val_cb.clear()
        lyr = self._picked_layer()
        fld = self.fld_cb.currentText()
        if lyr and fld:
            seen = set()
            for feat in lyr.getFeatures():
                v = str(feat[fld]) if feat[fld] is not None else ""
                if v not in seen:
                    seen.add(v)
                    self.val_cb.addItem(v)
        self.val_cb.blockSignals(False)

    def _picked_layer(self):
        lid = self.lyr_cb.currentData()
        return QgsProject.instance().mapLayer(lid) if lid else None

    # ------------------------------------------------------------------
    # Expression builder
    # ------------------------------------------------------------------

    def _open_expr_builder(self):
        dlg = QgsExpressionBuilderDialog(
            None,                        # no context layer needed
            self.expr_edit.text(),
            self.iface.mainWindow(),
            "generic"
        )
        dlg.setWindowTitle("Build expression for field value")
        # exec_() = Qt5/QGIS3, exec() = Qt6/QGIS4; qgis.PyQt shim provides both
        exec_fn = getattr(dlg, "exec", None) or dlg.exec_
        if exec_fn():
            self.expr_edit.setText(dlg.expressionText())

    # ------------------------------------------------------------------
    # Visibility switching
    # ------------------------------------------------------------------

    def _on_type_changed(self):
        src = self.type_cb.currentData()
        layer_vis = src == SRC_LAYER
        expr_vis  = src == SRC_EXPR
        gpx_vis   = src == SRC_GPX

        self.gpx_field_cb.setVisible(gpx_vis)
        self.lyr_cb.setVisible(layer_vis)
        self.fld_cb.setVisible(layer_vis)
        self.val_cb.setVisible(layer_vis)
        self.expr_edit.setVisible(expr_vis)
        self.expr_btn.setVisible(expr_vis)
        # SRC_FOLDER and SRC_IGNORE need no sub-widgets

        if src == SRC_LAYER and self.lyr_cb.count() == 0:
            self._populate_layer_combo()

    # ------------------------------------------------------------------
    # Serialise / deserialise
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        src = self.type_cb.currentData()
        d = {"src": src}
        if src == SRC_GPX:
            d["gpx_field"] = self.gpx_field_cb.currentText()
        elif src == SRC_LAYER:
            d["layer_id"]  = self.lyr_cb.currentData()
            d["layer_name"] = self.lyr_cb.currentText()
            d["field"]     = self.fld_cb.currentText()
            d["value"]     = self.val_cb.currentText()
        elif src == SRC_EXPR:
            d["expression"] = self.expr_edit.text()
        return d

    def from_dict(self, d: dict):
        src = d.get("src", SRC_IGNORE)
        idx = self.type_cb.findData(src)
        if idx >= 0:
            self.type_cb.setCurrentIndex(idx)
        self._on_type_changed()

        if src == SRC_GPX:
            gf = d.get("gpx_field", "")
            if gf:
                idx = self.gpx_field_cb.findText(gf)
                if idx >= 0:
                    self.gpx_field_cb.setCurrentIndex(idx)
                else:
                    self.gpx_field_cb.setCurrentText(gf)
        elif src == SRC_LAYER:
            self._populate_layer_combo()
            lid = d.get("layer_id", "")
            idx = self.lyr_cb.findData(lid)
            if idx < 0:
                # layer might have been renamed — try by name
                idx = self.lyr_cb.findText(d.get("layer_name", ""))
            if idx >= 0:
                self.lyr_cb.setCurrentIndex(idx)
            self._on_layer_changed()
            self.fld_cb.setCurrentText(d.get("field", ""))
            self._on_field_changed()
            self.val_cb.setCurrentText(d.get("value", ""))
        elif src == SRC_EXPR:
            self.expr_edit.setText(d.get("expression", ""))

    def summary(self) -> str:
        """Short human-readable description shown in the Source column."""
        src = self.type_cb.currentData()
        if src == SRC_IGNORE:
            return "(ignore)"
        if src == SRC_GPX:
            return "From GPX"
        if src == SRC_LAYER:
            return (f"{self.lyr_cb.currentText()}."
                    f"{self.fld_cb.currentText()} = "
                    f"{self.val_cb.currentText()!r}")
        if src == SRC_EXPR:
            return self.expr_edit.text() or "(empty expression)"
        return ""


# ---------------------------------------------------------------------------
# Main mapping table widget
# ---------------------------------------------------------------------------

class FieldMappingWidget(QWidget):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._current_layer = None
        self._settings = QSettings()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hdr = QLabel("Field mappings")
        hdr.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(hdr)

        hint = QLabel(
            "For each destination field, choose where its value comes from."
        )
        hint.setStyleSheet("color: #666; font-size: 10px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Destination field", "Source"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView_ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView_Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView_NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView_NoSelection)
        self.table.setSizePolicy(QSizePolicy_Expanding, QSizePolicy_Expanding)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save mappings")
        save_btn.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def load_for_layer(self, layer: QgsVectorLayer):
        """Rebuild the table for the given layer and restore saved mappings."""
        self._current_layer = layer
        self.table.setRowCount(0)

        if not layer:
            return

        saved = self._load_raw(layer.id())

        for field in layer.fields():
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Column 0 — field name (read-only)
            item = QTableWidgetItem(field.name())
            item.setFlags(Qt_ItemIsEnabled)
            font = QFont()
            font.setFamily("Consolas, monospace")
            item.setFont(font)
            self.table.setItem(row, 0, item)

            # Column 1 — source widget
            src_widget = _SourceWidget(self.iface)
            if field.name() in saved:
                src_widget.from_dict(saved[field.name()])
            elif field.name() in GPX_FIELDS_ALL:
                # Destination field name matches a standard GPX attribute —
                # auto-select "From GPX" so the user doesn't have to wire
                # every field manually on a layer that already mirrors the GPX schema.
                src_widget.from_dict({"src": SRC_GPX, "gpx_field": field.name()})
            self.table.setCellWidget(row, 1, src_widget)
            self.table.setRowHeight(row, 34)

    def save_for_layer(self, layer: QgsVectorLayer = None):
        self._save(layer or self._current_layer)

    def get_mappings(self) -> list:
        """
        Return the current mapping as a list of dicts, one per field.
        Each dict has at minimum: {field_name, src, ...src-specific keys}
        """
        mappings = []
        for row in range(self.table.rowCount()):
            field_name = self.table.item(row, 0).text()
            src_widget = self.table.cellWidget(row, 1)
            d = src_widget.to_dict()
            d["field_name"] = field_name
            mappings.append(d)
        return mappings

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _settings_key(self, layer_id: str) -> str:
        return f"{SETTINGS_KEY}/{layer_id}"

    def _load_raw(self, layer_id: str) -> dict:
        """Returns {field_name: source_dict} or {}."""
        raw = self._settings.value(self._settings_key(layer_id), "")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _save(self, layer=None):
        target = layer or self._current_layer
        if not target:
            return
        data = {
            self.table.item(row, 0).text():
                self.table.cellWidget(row, 1).to_dict()
            for row in range(self.table.rowCount())
        }
        self._settings.setValue(
            self._settings_key(target.id()),
            json.dumps(data)
        )
