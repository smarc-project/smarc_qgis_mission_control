from pathlib import Path

import qgis.utils
from test_waypoint_table import _open, _select

from qgis.PyQt.QtCore import QItemSelectionModel
from qgis.PyQt.QtTest import QSignalSpy
from qgis.PyQt.QtWidgets import QAction, QMainWindow

from src.mission.MissionMapManager import QGIS_ROTATE_FEATURE_ACTION


def _qgisRotateAction(monkeypatch) -> QAction:
    """A main window holding QGIS's Rotate Feature(s) action, found by name as in QGIS."""
    window = QMainWindow()
    action = QAction(window)
    action.setObjectName(QGIS_ROTATE_FEATURE_ACTION)
    monkeypatch.setattr(qgis.utils.iface, "mainWindow", lambda: window, raising=False)
    monkeypatch.setattr(qgis.utils.iface, "_window", window, raising=False)  # keep it alive
    return action


def _rotate(table):
    return table.ui.buttonRotateWaypoints.defaultAction()


def test_rotate_hands_every_waypoint_of_the_task_to_qgis_rotate_tool(qgis_app, tmp_path: Path,
                                                                      monkeypatch):
    context, doc, table, task = _open(tmp_path)
    qgisRotate = _qgisRotateAction(monkeypatch)
    started = QSignalSpy(qgisRotate.triggered)
    layer = doc.layerBridge.waypointLayer

    assert _rotate(table).isEnabled()
    _rotate(table).trigger()

    assert len(started) == 1
    selected = {doc.layerBridge.waypointUuidForFeatureId(fid) for fid in layer.selectedFeatureIds()}
    assert selected == {w.uuid for w in task.waypoints}


def test_rotate_takes_only_the_selected_rows(qgis_app, tmp_path: Path, monkeypatch):
    context, doc, table, task = _open(tmp_path)
    _qgisRotateAction(monkeypatch)
    requested = QSignalSpy(table.rotateWaypointsRequested)
    selection = table.ui.waypointTable.selectionModel()
    model = table.ui.waypointTable.model()
    for row in (0, 2):
        selection.select(model.index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)

    _rotate(table).trigger()

    assert list(requested[0]) == [[task.waypoints[0].uuid, task.waypoints[2].uuid]]


def test_rotate_is_off_when_it_would_turn_a_single_point(qgis_app, tmp_path: Path):
    context, doc, table, task = _open(tmp_path)

    _select(table, 1)
    assert not _rotate(table).isEnabled()

    table.ui.waypointTable.clearSelection()
    assert _rotate(table).isEnabled()

    doc.deleteWaypoint(task.waypoints[0].uuid)
    doc.deleteWaypoint(task.waypoints[0].uuid)
    assert not _rotate(table).isEnabled()
