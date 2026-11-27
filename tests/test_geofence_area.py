import json
from pathlib import Path
from uuid import uuid4

from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction

from src.domain.missionplan import GroupKind, MissionPlan
from src.domain.tasks import MoveToTask, SmarcStartGeofenceTask
from src.domain.waypoints import GeoPoint
from src.mission.MissionContext import MissionContext
from src.mission.MissionDocument import MissionDocument

FENCE_UUID = "0b7f3c1e-2a6d-4f3b-9a51-7d2c8e4f6a10"

#: A geofence task as a mission file from before #79 holds it
OLD_GEOFENCE_FILE: dict = {
    "name": "seq",
    "description": "fenced",
    "tst-uuid": "6a1d2b4c-8e3f-4a5b-9c7d-1e2f3a4b5c6d",
    "params": {"timeout": 300.0},
    "common-params": {},
    "children": [{
        "description": "fence",
        "task-uuid": FENCE_UUID,
        "name": "smarc-start-geofence",
        "params": {
            "ceiling-altitude": -1.0,
            "floor-altitude": 1.0,
            "stay-inside": True,
            "waypoints": [
                {"latitude": 59.0, "longitude": 18.0, "altitude": 0.0,
                 "tolerance": 10.0, "rostype": "GeoPoint"},
                {"latitude": 59.0, "longitude": 18.1, "altitude": 0.0,
                 "tolerance": 10.0, "rostype": "GeoPoint"},
                {"latitude": 59.1, "longitude": 18.1, "altitude": 0.0,
                 "tolerance": 10.0, "rostype": "GeoPoint"},
            ],
        },
    }],
}


def _corner(latitude: float, longitude: float) -> GeoPoint:
    return GeoPoint(latitude=latitude, longitude=longitude, uuid=uuid4())


def _move_to(description: str, latitude: float) -> MoveToTask:
    return MoveToTask(description=description, uuid=uuid4(),
                      waypoint=_corner(latitude, 18.05))


def _fence(corners: list[GeoPoint]) -> SmarcStartGeofenceTask:
    return SmarcStartGeofenceTask(description="fence", uuid=uuid4(), waypoints=corners)


def _fenced_plan(corners: list[GeoPoint]) -> tuple[MissionPlan, SmarcStartGeofenceTask]:
    """A route through a fence task, so a corner wrongly on the route would show in the tracks."""
    fence = _fence(corners)
    plan = MissionPlan(
        name=GroupKind.SEQ.value,
        description="fenced",
        tasks=[_move_to("before", 58.9), fence, _move_to("after", 59.2)],
    )
    return plan, fence


def _area_polygons(doc: MissionDocument) -> list[QgsGeometry]:
    return [feat.geometry() for feat in doc.layerBridge.areas.layer().getFeatures()]


def _track_segments(doc: MissionDocument) -> int:
    return doc.layerBridge.tracks._layer.featureCount()


def test_an_old_geofence_file_loads_and_saves_the_same_waypoints(qgis_app):
    plan = MissionPlan.fromJson(OLD_GEOFENCE_FILE)

    fence = plan.tasks[0]
    assert isinstance(fence, SmarcStartGeofenceTask)
    assert [(c.latitude, c.longitude) for c in fence.waypoints] == [
        (59.0, 18.0), (59.0, 18.1), (59.1, 18.1)]
    # Same keys out as in: the geofence server reads "waypoints" with latitude/longitude
    assert plan.toJson()["children"] == OLD_GEOFENCE_FILE["children"]


def test_the_fence_is_one_closed_polygon_and_not_on_the_route(qgis_app, tmp_path: Path):
    plan, fence = _fenced_plan([_corner(59.0, 18.0), _corner(59.0, 18.1),
                                _corner(59.1, 18.1), _corner(59.1, 18.0)])
    doc = MissionDocument(plan, tmp_path / "mission.json")

    (polygon,) = _area_polygons(doc)
    assert QgsWkbTypes.geometryType(polygon.wkbType()) == QgsWkbTypes.PolygonGeometry
    ring = polygon.asPolygon()[0]
    assert len(ring) == 5 and ring[0] == ring[-1]
    assert ring[2] == QgsPointXY(18.1, 59.1)
    # before -> after directly; the corners are not stops on the way
    assert _track_segments(doc) == 1
    # The corners are still waypoints on the map, so the usual tools move them
    for corner in fence.waypoints:
        assert doc.layerBridge.featureIdForWaypointUuid(corner.uuid) is not None


def test_a_map_click_adds_a_corner_and_undo_takes_it_away(qgis_app, tmp_path: Path):
    plan, fence = _fenced_plan([_corner(59.0, 18.0), _corner(59.0, 18.1)])
    path = tmp_path / "mission.json"
    path.write_text(json.dumps(plan.toJson()))
    context = MissionContext()
    context.loadMissionFromFile(path)
    context.changeActiveMission(plan.uuid)
    doc = context.activeDocument()
    doc.startEditing()
    fence = doc.index.taskByUuid(fence.uuid)
    assert _area_polygons(doc) == []

    # The waypoint table's Add Waypoint button, then a click on the map
    action = QAction()
    context.mapManager.onAddWaypointRequested(action, 2, fence.uuid, "waypoints", True)
    context.mapManager.onAddWaypointToolMapClicked(
        QgsPointXY(18.1, 59.1),
        Qt.MouseButton.LeftButton,
    )
    context.mapManager.onAddWaypointRequested(action, 3, fence.uuid, "waypoints", False)

    assert len(fence.waypoints) == 3
    (polygon,) = _area_polygons(doc)
    assert len(polygon.asPolygon()[0]) == 4
    assert _track_segments(doc) == 1

    stack = doc.layerBridge.waypointLayer.undoStack()
    stack.undo()
    assert len(fence.waypoints) == 2
    assert _area_polygons(doc) == []
    stack.redo()
    assert len(_area_polygons(doc)) == 1


def test_undoing_a_corner_move_puts_the_polygon_back(qgis_app, tmp_path: Path):
    corners = [_corner(59.0, 18.0), _corner(59.0, 18.1), _corner(59.1, 18.1)]
    plan, fence = _fenced_plan(corners)
    doc = MissionDocument(plan, tmp_path / "mission.json")
    doc.startEditing()
    stack = doc.layerBridge.waypointLayer.undoStack()

    doc.setWaypointPosition(corners[2].uuid, 59.2, 18.2)
    assert _area_polygons(doc)[0].asPolygon()[0][2] == QgsPointXY(18.2, 59.2)

    stack.undo()
    assert _area_polygons(doc)[0].asPolygon()[0][2] == QgsPointXY(18.1, 59.1)


def test_deleting_the_fence_task_removes_its_polygon_and_undo_restores_it(qgis_app, tmp_path: Path):
    plan, fence = _fenced_plan([_corner(59.0, 18.0), _corner(59.0, 18.1),
                                _corner(59.1, 18.1)])
    doc = MissionDocument(plan, tmp_path / "mission.json")
    doc.startEditing()

    doc.deleteTask(fence)
    assert _area_polygons(doc) == []
    assert _track_segments(doc) == 1

    doc.layerBridge.waypointLayer.undoStack().undo()
    assert len(_area_polygons(doc)) == 1
    assert _track_segments(doc) == 1
