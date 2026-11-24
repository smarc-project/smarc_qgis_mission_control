import json
from pathlib import Path
from uuid import uuid4

import qgis.utils
from qgis.core import QgsPointXY
from qgis.gui import QgsMapToolPan
from qgis.PyQt.QtCore import QItemSelectionModel, Qt

from src.domain.missionplan import MissionPlan
from src.domain.tasks import MovePathTask
from src.domain.waypoints import GeoPoint
from src.mission.MissionContext import MissionContext
from src.ui.widgets.WaypointTableWidget import WaypointTableWidget


def _open(tmp_path: Path):
    path_task = MovePathTask(description="survey", uuid=uuid4(), waypoints=[
        GeoPoint(latitude=lat, longitude=18.07, uuid=uuid4()) for lat in (59.30, 59.31, 59.32)])
    plan = MissionPlan(name="seq", description="out", tasks=[path_task])
    path = tmp_path / "mission.json"
    path.write_text(json.dumps(plan.toJson()))
    context = MissionContext()
    context.loadMissionFromFile(path)
    context.changeActiveMission(plan.uuid)
    doc = context.activeDocument()
    doc.startEditing()
    table = WaypointTableWidget(MovePathTask, "waypoints", GeoPoint, context)
    table.bind(doc, path_task.uuid)
    table.onEditModeChanged(True)
    return context, doc, table, doc.plan.tasks[0]


def _select(table: WaypointTableWidget, row: int) -> None:
    table.ui.waypointTable.selectionModel().select(
        table.ui.waypointTable.model().index(row, 0),
        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)


def test_move_waypoint_moves_the_selected_one_not_the_first(qgis_app, tmp_path: Path):
    context, doc, table, task = _open(tmp_path)
    second = task.waypoints[1]
    _select(table, 1)
    action = table.ui.buttonMoveWaypoint.defaultAction()
    assert table.ui.buttonMoveWaypoint.isEnabled()

    action.setChecked(True)
    context.mapManager.onSelectLocationToolMapClicked(QgsPointXY(18.2, 59.5), Qt.LeftButton)

    assert (second.latitude, second.longitude) == (59.5, 18.2)
    assert (task.waypoints[0].latitude, task.waypoints[0].longitude) == (59.30, 18.07)
    action.setChecked(False)


def test_selecting_another_waypoint_stops_the_move(qgis_app, tmp_path: Path):
    context, doc, table, task = _open(tmp_path)
    canvas = qgis.utils.iface.mapCanvas()
    before = QgsMapToolPan(canvas)
    canvas.setMapTool(before)
    _select(table, 1)
    action = table.ui.buttonMoveWaypoint.defaultAction()
    action.setChecked(True)
    assert canvas.mapTool() is not before

    _select(table, 2)

    assert not action.isChecked()
    assert canvas.mapTool() is before


def test_without_one_selected_waypoint_the_button_does_nothing(qgis_app, tmp_path: Path):
    context, doc, table, task = _open(tmp_path)
    canvas = qgis.utils.iface.mapCanvas()
    before = canvas.mapTool()
    action = table.ui.buttonMoveWaypoint.defaultAction()
    assert not table.ui.buttonMoveWaypoint.isEnabled()

    action.setChecked(True)

    assert not action.isChecked()
    assert canvas.mapTool() is before

    _select(table, 0)
    table.ui.waypointTable.selectionModel().select(
        table.ui.waypointTable.model().index(1, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert not table.ui.buttonMoveWaypoint.isEnabled()


def test_leaving_edit_mode_or_switching_task_stops_the_move(qgis_app, tmp_path: Path):
    context, doc, table, task = _open(tmp_path)
    canvas = qgis.utils.iface.mapCanvas()
    before = QgsMapToolPan(canvas)
    canvas.setMapTool(before)
    action = table.ui.buttonMoveWaypoint.defaultAction()

    _select(table, 1)
    action.setChecked(True)
    table.onEditModeChanged(False)
    assert not action.isChecked() and canvas.mapTool() is before

    table.onEditModeChanged(True)
    _select(table, 1)
    action.setChecked(True)
    table.bind(doc, task.uuid)
    assert not action.isChecked() and canvas.mapTool() is before
