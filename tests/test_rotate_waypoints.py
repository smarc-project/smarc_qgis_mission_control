import math
from pathlib import Path
from uuid import uuid4

import qgis.utils
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
)
from qgis.gui import QgsMapToolPan
from test_waypoint_table import _open, _select

from qgis.PyQt.QtCore import QEvent, QItemSelectionModel, QPoint, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent
from qgis.PyQt.QtWidgets import QApplication

from src.mission.RotateWaypointsTool import RotateWaypointsMapTool, WaypointRotation

# A lawnmower at Stockholm's latitude, where a degree of longitude is about half a
# degree of latitude: turning it in degrees would stretch it.
LAWNMOWER = [(18.110, 59.3240), (18.114, 59.3240), (18.114, 59.3255),
             (18.110, 59.3255), (18.110, 59.3270), (18.114, 59.3270)]


def _metres():
    d = QgsDistanceArea()
    d.setEllipsoid("WGS84")
    d.setSourceCrs(QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance().transformContext())
    return d


def _legs(points):
    d = _metres()
    return [d.measureLine(a, b) for a, b in zip(points, points[1:])]


def test_turning_keeps_every_distance_and_turns_by_the_angle(qgis_app):
    positions = {uuid4(): QgsPointXY(lon, lat) for lon, lat in LAWNMOWER}
    rotation = WaypointRotation(positions)

    turned = rotation.turned(60.0)

    before, after = list(positions.values()), [turned[u] for u in positions]
    for a, b in zip(_legs(before), _legs(after)):
        assert math.isclose(a, b, abs_tol=0.05)
    for p, q in zip(before, after):
        assert math.isclose((rotation.angleTo(q) - rotation.angleTo(p)) % 360, 60.0, abs_tol=0.01)


def _canvasOn(points):
    canvas = qgis.utils.iface.mapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    canvas.resize(800, 600)
    lons, lats = [p[1] for p in points], [p[0] for p in points]
    extent = QgsRectangle(min(lons), min(lats), max(lons), max(lats))
    extent.grow(0.02)  # the test task's waypoints share one longitude
    canvas.setExtent(extent)
    return canvas


def _click(canvas, lon, lat, button=Qt.LeftButton):
    p = canvas.getCoordinateTransform().transform(QgsPointXY(lon, lat))
    pos = QPointF(p.x(), p.y())
    vp = canvas.viewport()
    glob = QPointF(vp.mapToGlobal(QPoint(round(pos.x()), round(pos.y()))))
    for kind, b, bs in ((QEvent.MouseMove, Qt.NoButton, Qt.NoButton),
                        (QEvent.MouseButtonPress, button, button),
                        (QEvent.MouseButtonRelease, button, Qt.NoButton)):
        QApplication.sendEvent(vp, QMouseEvent(kind, pos, glob, b, bs, Qt.NoModifier))


def _rotate(table):
    return table.ui.buttonRotateWaypoints.defaultAction()


def _positions(task):
    return [(w.latitude, w.longitude) for w in task.waypoints]


def test_click_move_click_turns_the_task_as_one_undo_step(qgis_app, tmp_path: Path):
    context, doc, table, task = _open(tmp_path)
    before = _positions(task)
    canvas = _canvasOn(before)
    lat0 = sum(p[0] for p in before) / len(before)
    lon0 = sum(p[1] for p in before) / len(before)

    pan = QgsMapToolPan(canvas)
    canvas.setMapTool(pan)
    _rotate(table).setChecked(True)
    assert isinstance(canvas.mapTool(), RotateWaypointsMapTool)
    _click(canvas, lon0 + 0.01, lat0)   # start east of the centre
    _click(canvas, lon0, lat0 + 0.01)   # drop north of it

    after = _positions(task)
    assert after != before
    assert not _rotate(table).isChecked()
    assert canvas.mapTool() is pan  # back to the tool from before, once
    a = _legs([QgsPointXY(lon, lat) for lat, lon in before])
    b = _legs([QgsPointXY(lon, lat) for lat, lon in after])
    assert all(math.isclose(x, y, abs_tol=0.05) for x, y in zip(a, b))

    doc.layerBridge.waypointLayer.undoStack().undo()
    assert _positions(task) == before


def test_right_click_cancels_without_moving_anything(qgis_app, tmp_path: Path):
    context, doc, table, task = _open(tmp_path)
    before = _positions(task)
    canvas = _canvasOn(before)

    _rotate(table).setChecked(True)
    _click(canvas, before[0][1] + 0.01, before[0][0])
    _click(canvas, before[0][1], before[0][0] + 0.01, Qt.RightButton)

    assert _positions(task) == before
    assert not _rotate(table).isChecked()


def test_rotate_takes_only_the_selected_rows(qgis_app, tmp_path: Path):
    context, doc, table, task = _open(tmp_path)
    before = _positions(task)
    canvas = _canvasOn(before)
    selection = table.ui.waypointTable.selectionModel()
    model = table.ui.waypointTable.model()
    for row in (0, 2):
        selection.select(model.index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)

    _rotate(table).setChecked(True)
    _click(canvas, 18.08, 59.31)
    _click(canvas, 18.07, 59.32)

    after = _positions(task)
    assert after[1] == before[1]
    assert after[0] != before[0] and after[2] != before[2]


def test_rotate_is_off_when_it_would_turn_a_single_point(qgis_app, tmp_path: Path):
    context, doc, table, task = _open(tmp_path)

    _select(table, 1)
    assert not _rotate(table).isEnabled()

    table.ui.waypointTable.clearSelection()
    assert _rotate(table).isEnabled()

    doc.deleteWaypoint(task.waypoints[0].uuid)
    doc.deleteWaypoint(task.waypoints[0].uuid)
    assert not _rotate(table).isEnabled()
