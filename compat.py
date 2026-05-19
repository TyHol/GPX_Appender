"""
Qt5 (PyQt5/QGIS3) vs Qt6 (PyQt6/QGIS4) enum compatibility.

In PyQt5 enums are flat:  QFrame.HLine
In PyQt6 they're namespaced: QFrame.Shape.HLine

Import everything from here instead of accessing enums directly.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QFrame, QSizePolicy, QHeaderView, QAbstractItemView
)


def _get(obj, pyqt5_name, pyqt6_path):
    """Try PyQt5 flat form first, fall back to PyQt6 namespaced form."""
    try:
        return getattr(obj, pyqt5_name)
    except AttributeError:
        result = obj
        for part in pyqt6_path.split('.'):
            result = getattr(result, part)
        return result


# Qt.DockWidgetArea
Qt_LeftDock = _get(Qt, 'LeftDockWidgetArea', 'DockWidgetArea.LeftDockWidgetArea')
Qt_RightDock = _get(Qt, 'RightDockWidgetArea', 'DockWidgetArea.RightDockWidgetArea')
Qt_BottomDock = _get(Qt, 'BottomDockWidgetArea', 'DockWidgetArea.BottomDockWidgetArea')

# Qt.AlignmentFlag
Qt_AlignCenter = _get(Qt, 'AlignCenter', 'AlignmentFlag.AlignCenter')

# Qt.CursorShape
Qt_PointingHand = _get(Qt, 'PointingHandCursor', 'CursorShape.PointingHandCursor')

# Qt.ItemFlag
Qt_ItemIsEnabled = _get(Qt, 'ItemIsEnabled', 'ItemFlag.ItemIsEnabled')

# QFrame
QFrame_HLine = _get(QFrame, 'HLine', 'Shape.HLine')
QFrame_Sunken = _get(QFrame, 'Sunken', 'Shadow.Sunken')

# QSizePolicy
QSizePolicy_Expanding = _get(QSizePolicy, 'Expanding', 'Policy.Expanding')

# QHeaderView
QHeaderView_ResizeToContents = _get(QHeaderView, 'ResizeToContents', 'ResizeMode.ResizeToContents')
QHeaderView_Stretch = _get(QHeaderView, 'Stretch', 'ResizeMode.Stretch')

# QAbstractItemView
QAbstractItemView_NoEditTriggers = _get(QAbstractItemView, 'NoEditTriggers', 'EditTrigger.NoEditTriggers')
QAbstractItemView_NoSelection = _get(QAbstractItemView, 'NoSelection', 'SelectionMode.NoSelection')
