"""
GPXDockPanel
============
Dockable widget that accepts GPX files dragged from the OS file manager
(or any drag source that provides file URLs).

Layout (two tabs)
-----------------
  [Import] tab
    Destination layer: [combo] [refresh]
    <type hint>
    Drop zone
    [log]

  [Field Mapping] tab
    Table: field name | source (ignore / From GPX / Layer pick / Expression)
    [Save mappings]

Import logic
------------
For each destination field, the saved mapping defines the value source:

  ignore     -> field is not written
  gpx        -> value copied from matching-name GPX attribute (default)
  layer      -> a specific value picked from another layer
  expression -> a QGIS expression evaluated per feature
                (@gpx_source = stem of GPX filename available as variable)
"""

import os

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QTextEdit, QFileDialog,
    QSizePolicy, QFrame, QTabWidget, QProgressBar
)
from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt.QtCore import Qt, QMimeData, pyqtSignal
from qgis.PyQt.QtGui import QDragEnterEvent, QDropEvent

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsCoordinateTransform, QgsWkbTypes,
    QgsPoint, QgsPointXY, QgsLineString,
    QgsExpression, QgsExpressionContext, QgsExpressionContextUtils,
    edit
)

from .field_mapping_widget import (
    FieldMappingWidget,
    SRC_IGNORE, SRC_GPX, SRC_LAYER, SRC_EXPR, SRC_FOLDER
)


# ---------------------------------------------------------------------------
# Drop zone
# ---------------------------------------------------------------------------

class _DropZone(QLabel):
    filesDropped = pyqtSignal(list)

    _STYLE_IDLE = (
        "QLabel {"
        "  border: 2px dashed #999;"
        "  border-radius: 8px;"
        "  color: #666;"
        "  font-size: 13px;"
        "  padding: 20px;"
        "  background: #f9f9f9;"
        "}"
    )
    _STYLE_HOVER = (
        "QLabel {"
        "  border: 2px dashed #0078d4;"
        "  border-radius: 8px;"
        "  color: #0078d4;"
        "  font-size: 13px;"
        "  padding: 20px;"
        "  background: #e8f4fd;"
        "}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("Drop GPX files or folders here\nor click to browse")
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(self._STYLE_IDLE)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(100)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        # Let user pick files or a folder
        from qgis.PyQt.QtWidgets import QMenu, QAction as QAct
        menu = QMenu(self)
        file_act = menu.addAction("Browse for GPX files...")
        folder_act = menu.addAction("Browse for folder(s)...")
        chosen = menu.exec_(self.mapToGlobal(event.pos()))
        if chosen == file_act:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Select GPX files", "", "GPX Files (*.gpx)"
            )
            if paths:
                self.filesDropped.emit(paths)
        elif chosen == folder_act:
            folder = QFileDialog.getExistingDirectory(
                self, "Select folder containing GPX files"
            )
            if folder:
                found = self._collect_gpx([folder])
                if found:
                    self.filesDropped.emit(found)

    def dragEnterEvent(self, event):
        if self._has_gpx_or_folder(event.mimeData()):
            self.setStyleSheet(self._STYLE_HOVER)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._STYLE_IDLE)

    def dropEvent(self, event):
        self.setStyleSheet(self._STYLE_IDLE)
        local_paths = [url.toLocalFile() for url in event.mimeData().urls()]
        found = self._collect_gpx(local_paths)
        if found:
            self.filesDropped.emit(found)
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def _collect_gpx(paths):
        """
        Given a list of paths (files or folders), return a flat sorted list
        of all .gpx files found — recursing into any folders.
        """
        import os
        result = []
        for p in paths:
            if os.path.isfile(p) and p.lower().endswith(".gpx"):
                result.append(p)
            elif os.path.isdir(p):
                for root, _dirs, files in os.walk(p):
                    for f in sorted(files):
                        if f.lower().endswith(".gpx"):
                            result.append(os.path.join(root, f))
        return result

    @staticmethod
    def _has_gpx_or_folder(mime):
        if not mime.hasUrls():
            return False
        for u in mime.urls():
            p = u.toLocalFile()
            if p.lower().endswith(".gpx"):
                return True
            if os.path.isdir(p):
                return True
        return False


# ---------------------------------------------------------------------------
# Dock panel
# ---------------------------------------------------------------------------

class GPXDockPanel(QDockWidget):

    def __init__(self, iface, parent=None):
        super().__init__("GPX Appender", parent)
        self.iface = iface
        self.setObjectName("GPXImporterDock")
        self.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self.setMinimumWidth(380)
        self._cancelled = False

        self._build_ui()
        self._refresh_layers()

        QgsProject.instance().layersAdded.connect(self._refresh_layers)
        QgsProject.instance().layersRemoved.connect(self._refresh_layers)
        QgsProject.instance().cleared.connect(self._refresh_layers)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Layer picker (above tabs, shared)
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Destination layer:"))

        self.layer_combo = QComboBox()
        self.layer_combo.setToolTip(
            "Select a Point or Line vector layer as the import target."
        )
        picker_row.addWidget(self.layer_combo, 1)

        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("Refresh layer list")
        refresh_btn.clicked.connect(self._refresh_layers)
        picker_row.addWidget(refresh_btn)

        outer.addLayout(picker_row)

        self.type_label = QLabel("")
        self.type_label.setStyleSheet("color: #555; font-size: 11px;")
        outer.addWidget(self.type_label)

        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        outer.addWidget(sep)

        # Tabs
        tabs = QTabWidget()
        outer.addWidget(tabs, 1)

        # Import tab
        import_tab = QWidget()
        import_layout = QVBoxLayout(import_tab)
        import_layout.setContentsMargins(4, 6, 4, 4)
        import_layout.setSpacing(6)

        self.drop_zone = _DropZone()
        self.drop_zone.filesDropped.connect(self._on_files_dropped)
        import_layout.addWidget(self.drop_zone, 1)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        import_layout.addWidget(sep2)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setStyleSheet("font-size: 11px;")
        import_layout.addWidget(self.log)

        # Progress bar (hidden when idle)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size: 11px; color: #555;")
        import_layout.addWidget(self.progress_label)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setVisible(False)
        progress_row.addWidget(self.progress_bar, 1)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedWidth(48)
        self.stop_btn.setFixedHeight(16)
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._request_stop)
        progress_row.addWidget(self.stop_btn)

        import_layout.addLayout(progress_row)

        tabs.addTab(import_tab, "Import")

        # Field Mapping tab
        self.mapping_widget = FieldMappingWidget(self.iface)
        tabs.addTab(self.mapping_widget, "Field Mapping")

        self.setWidget(root)

    # ------------------------------------------------------------------
    # Layer combo
    # ------------------------------------------------------------------

    def _refresh_layers(self, *_):
        current_id = self.layer_combo.currentData()
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()

        acceptable = {QgsWkbTypes.PointGeometry, QgsWkbTypes.LineGeometry}
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            gt = layer.geometryType()
            if gt not in acceptable:
                continue
            icon = "o" if gt == QgsWkbTypes.PointGeometry else "-"
            self.layer_combo.addItem(f"[{icon}]  {layer.name()}", layer.id())

        self.layer_combo.blockSignals(False)

        if current_id:
            idx = self.layer_combo.findData(current_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)

        self._on_layer_changed()

    def _current_layer(self):
        lid = self.layer_combo.currentData()
        return QgsProject.instance().mapLayer(lid) if lid else None

    def _on_layer_changed(self):
        layer = self._current_layer()
        if not layer:
            self.type_label.setText("No compatible layer selected")
            self.mapping_widget.load_for_layer(None)
            return

        gt = layer.geometryType()
        if gt == QgsWkbTypes.PointGeometry:
            self.type_label.setText(
                "Point layer - imports waypoints / track-points"
            )
        elif gt == QgsWkbTypes.LineGeometry:
            self.type_label.setText(
                "Line layer - imports tracks as linestrings"
            )

        self.mapping_widget.load_for_layer(layer)

    # ------------------------------------------------------------------
    # Import orchestration
    # ------------------------------------------------------------------

    def _on_files_dropped(self, paths):
        layer = self._current_layer()
        if not layer:
            self._log("Please select a destination layer first.", error=True)
            return

        # Auto-save mappings before importing
        self.mapping_widget.save_for_layer(layer)
        mappings = self.mapping_widget.get_mappings()

        total_files = len(paths)
        for i, path in enumerate(paths):
            if self._cancelled:
                self._log(f"Stopped before {os.path.basename(path)}", error=True)
                break
            self._progress_start(
                f"File {i+1}/{total_files}: {os.path.basename(path)}",
                total=0   # will be reset per-file inside import methods
            )
            try:
                self._import_gpx(path, layer, mappings)
            except Exception as exc:
                self._log(f"ERROR  {os.path.basename(path)}: {exc}", error=True)
        self._progress_done()

    def _import_gpx(self, gpx_path, target, mappings):
        gt = target.geometryType()
        fname = os.path.splitext(os.path.basename(gpx_path))[0]

        if gt == QgsWkbTypes.PointGeometry:
            # Pass full gpx_path so folder-name mapping can use it
            count = self._import_as_points(gpx_path, target, gpx_path, mappings)
            self._log(f"OK  {fname}: imported {count} point(s) into '{target.name()}'")
        elif gt == QgsWkbTypes.LineGeometry:
            count = self._import_as_lines(gpx_path, target, gpx_path, mappings)
            self._log(f"OK  {fname}: imported {count} line(s) into '{target.name()}'")
        else:
            self._log(f"WARNING  {fname}: unsupported geometry type.", error=True)

    # ------------------------------------------------------------------
    # Value resolution
    # ------------------------------------------------------------------

    def _resolve_value(self, mapping, gpx_feat, gpx_src_name):
        src = mapping.get("src", SRC_GPX)

        if src == SRC_IGNORE:
            return None

        if src == SRC_GPX:
            # Use explicitly chosen gpx_field if set, else fall back to
            # matching by destination field name (old behaviour)
            fn = mapping.get("gpx_field") or mapping["field_name"]
            try:
                return gpx_feat[fn]
            except Exception:
                return None

        if src == SRC_FOLDER:
            return os.path.basename(os.path.dirname(gpx_src_name))

        if src == SRC_LAYER:
            # The user already selected the exact value they want stored
            return mapping.get("value")

        if src == SRC_EXPR:
            expr_str = mapping.get("expression", "")
            if not expr_str:
                return None
            expr = QgsExpression(expr_str)
            ctx = QgsExpressionContext()
            ctx.appendScopes(
                QgsExpressionContextUtils.globalProjectLayerScopes(None)
            )
            ctx.setFeature(gpx_feat)
            from qgis.core import QgsExpressionContextScope
            scope = QgsExpressionContextScope()
            scope.setVariable("gpx_source", os.path.splitext(os.path.basename(gpx_src_name))[0])
            scope.setVariable("gpx_folder", os.path.basename(os.path.dirname(gpx_src_name)))
            ctx.appendScope(scope)
            result = expr.evaluate(ctx)
            if expr.hasEvalError():
                self._log(
                    f"  expr error ({mapping['field_name']}): "
                    f"{expr.evalErrorString()}",
                    error=True
                )
                return None
            return result

        return None

    def _apply_mappings(self, new_feat, gpx_feat, mappings, fname):
        mapping_index = {m["field_name"]: m for m in mappings}

        for field in new_feat.fields():
            fn = field.name()
            if fn in mapping_index:
                m = mapping_index[fn]
                if m.get("src") == SRC_IGNORE:
                    continue
                # Explicit mapping (expression, layer pick, or named GPX field)
                # — always honoured, even for fid
                val = self._resolve_value(m, gpx_feat, fname)
                if val is not None:
                    try:
                        new_feat[fn] = val
                    except Exception:
                        pass
            else:
                # No explicit mapping -> GPX pass-through by name.
                # Skip fid/primary-key fields here: the GPX driver assigns its
                # own negative internal IDs which clash with the target layer's
                # unique constraint. If you want fid populated, add an explicit
                # mapping (e.g. expression: epoch(now())).
                if fn.lower() in ("fid", "ogc_fid", "objectid", "gid"):
                    continue
                try:
                    new_feat[fn] = gpx_feat[fn]
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Point import
    # ------------------------------------------------------------------

    def _import_as_points(self, gpx_path, target, fname, mappings):
        gpx_layer = self._open_gpx_sublayer(gpx_path, ["waypoints", "track_points"])
        if gpx_layer is None:
            raise RuntimeError("No readable point sublayer found in GPX file.")

        transform = QgsCoordinateTransform(
            gpx_layer.crs(), target.crs(), QgsProject.instance()
        )

        target_wkb = target.wkbType()
        want_z = QgsWkbTypes.hasZ(target_wkb)
        want_m = QgsWkbTypes.hasM(target_wkb)

        total = gpx_layer.featureCount()
        self._progress_start(f"Importing {total} points...", total)

        count = 0
        with edit(target):
            for src_feat in gpx_layer.getFeatures():
                raw_geom = src_feat.geometry()
                if raw_geom.isEmpty():
                    count += 1
                    continue

                # GPX geometries are always Point or MultiPoint with Z from ele.
                # Extract a single QgsPoint so we can control Z/M explicitly.
                pt = None
                vx = raw_geom.vertices()
                if vx.hasNext():
                    pt = vx.next()   # QgsPoint with x, y, z (ele) if present

                if pt is None:
                    count += 1
                    continue

                # Build the correctly-dimensioned geometry for the target layer
                if want_z and want_m:
                    z = pt.z() if pt.is3D() else 0.0
                    out_pt = QgsPoint(pt.x(), pt.y(), z, 0.0)
                    geom = QgsGeometry(out_pt)
                elif want_z:
                    z = pt.z() if pt.is3D() else 0.0
                    out_pt = QgsPoint(pt.x(), pt.y(), z)
                    geom = QgsGeometry(out_pt)
                else:
                    # Plain 2D — drop Z entirely to avoid type mismatch
                    geom = QgsGeometry.fromPointXY(QgsPointXY(pt.x(), pt.y()))

                geom.transform(transform)

                new_feat = QgsFeature(target.fields())
                new_feat.setGeometry(geom)

                # If target has Z and GPX has ele, honour the mapping or
                # fall back to copying ele into any field named "ele"/"elevation"
                if want_z and pt.is3D():
                    ele_val = pt.z()
                    for fn in ("ele", "elevation", "elev", "altitude", "alt"):
                        if fn in {f.name() for f in target.fields()}:
                            # only set if not already covered by a mapping
                            mapped = {m["field_name"] for m in mappings
                                      if m.get("src") not in ("ignore",)}
                            if fn not in mapped:
                                try:
                                    new_feat[fn] = ele_val
                                except Exception:
                                    pass
                            break

                self._apply_mappings(new_feat, src_feat, mappings, fname)
                target.addFeature(new_feat)
                count += 1

                # Update progress every 100 features to avoid UI thrashing
                if count % 100 == 0:
                    self._progress_update(
                        count, f"Importing points... {count}/{total}"
                    )
                    if self._cancelled:
                        break

        return count

    # ------------------------------------------------------------------
    # Line import
    # ------------------------------------------------------------------

    def _import_as_lines(self, gpx_path, target, fname, mappings):
        gpx_layer = self._open_gpx_sublayer(gpx_path, ["tracks", "routes"])
        if gpx_layer is None:
            raise RuntimeError("No readable line sublayer found in GPX file.")

        transform = QgsCoordinateTransform(
            gpx_layer.crs(), target.crs(), QgsProject.instance()
        )

        target_wkb = target.wkbType()
        want_z = QgsWkbTypes.hasZ(target_wkb)
        want_m = QgsWkbTypes.hasM(target_wkb)

        total = gpx_layer.featureCount()
        self._progress_start(f"Importing {total} track(s)...", total)

        count = 0
        with edit(target):
            for feat_idx, src_feat in enumerate(gpx_layer.getFeatures()):
                if self._cancelled:
                    break
                self._progress_update(feat_idx + 1)
                geom = src_feat.geometry()
                if geom.isEmpty():
                    continue
                geom.transform(transform)

                # Collect part geometries as lists of QgsPoint vertices,
                # preserving Z from GPX (which always carries ele as Z).
                # We use constGet() to walk the underlying geometry tree so
                # we never lose Z via the lossy asMultiPolyline() path.
                raw = geom.constGet()
                if raw is None:
                    continue

                # Normalise to a list of vertex-lists, one per part
                from qgis.core import QgsAbstractGeometry, QgsLineString as QgsLS
                def parts_of(g):
                    """Yield each linestring part as a list of QgsPoint."""
                    if g is None:
                        return
                    wkt_type = QgsWkbTypes.flatType(g.wkbType())
                    if wkt_type == QgsWkbTypes.LineString:
                        yield [g.pointN(i) for i in range(g.numPoints())]
                    elif wkt_type == QgsWkbTypes.MultiLineString:
                        for pi in range(g.numGeometries()):
                            part = g.geometryN(pi)
                            yield [part.pointN(i) for i in range(part.numPoints())]

                for pts in parts_of(raw):
                    if not pts:
                        continue

                    # Build points with the right dimensionality for the target
                    if want_z and want_m:
                        out_pts = [
                            QgsPoint(p.x(), p.y(),
                                     p.z() if p.is3D() else 0.0, 0.0)
                            for p in pts
                        ]
                    elif want_z:
                        out_pts = [
                            QgsPoint(p.x(), p.y(),
                                     p.z() if p.is3D() else 0.0)
                            for p in pts
                        ]
                    else:
                        # 2D only — drop Z to avoid type mismatch
                        out_pts = [QgsPoint(p.x(), p.y()) for p in pts]

                    line_geom = QgsGeometry(QgsLineString(out_pts))

                    new_feat = QgsFeature(target.fields())
                    new_feat.setGeometry(line_geom)
                    self._apply_mappings(new_feat, src_feat, mappings, fname)
                    target.addFeature(new_feat)
                    count += 1

        return count

    # ------------------------------------------------------------------
    # GPX sublayer helper
    # ------------------------------------------------------------------

    @staticmethod
    def _open_gpx_sublayer(gpx_path, preferred):
        for sublayer in preferred:
            uri = f"{gpx_path}|layername={sublayer}"
            lyr = QgsVectorLayer(uri, sublayer, "ogr")
            if lyr.isValid() and lyr.featureCount() > 0:
                return lyr
        return None

    # ------------------------------------------------------------------
    # Progress helpers
    # ------------------------------------------------------------------

    def _request_stop(self):
        self._cancelled = True
        self.stop_btn.setEnabled(False)
        self.progress_label.setText("Stopping after current feature...")
        QApplication.processEvents()

    def _progress_start(self, label, total):
        self._cancelled = False
        self.progress_label.setText(label)
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        QApplication.processEvents()

    def _progress_update(self, value, label=None):
        self.progress_bar.setValue(value)
        if label:
            self.progress_label.setText(label)
        QApplication.processEvents()

    def _progress_done(self):
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.stop_btn.setVisible(False)
        self._cancelled = False
        QApplication.processEvents()

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def _log(self, msg, error=False):
        colour = "#c0392b" if error else "#27ae60"
        self.log.append(f'<span style="color:{colour};">{msg}</span>')
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())
