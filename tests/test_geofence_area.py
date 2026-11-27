import json
from pathlib import Path
from uuid import UUID, uuid4

from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction

from src.domain.missionplan import GroupKind, MissionPlan
from src.domain.tasks import (
    MovePathTask,
    MoveToTask,
    SearchAreaTask,
    SmarcStartGeofenceTask,
)
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
    return [feat.geometry() for feat in doc.layerBridge.areas.layer.getFeatures()]


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


def test_area_corners_have_no_tolerance_ring_or_column(qgis_app, tmp_path: Path):
    from qgis.core import NULL

    from src.ui.widgets.WaypointTableWidget import WaypointTableWidget

    corners = [_corner(59.0, 18.0), _corner(59.0, 18.1), _corner(59.1, 18.1)]
    plan, fence = _fenced_plan(corners)
    doc = MissionDocument(plan, tmp_path / "mission.json")
    layer = doc.layerBridge.waypointLayer

    def tolerance(waypointUuid) -> object:
        fid = doc.layerBridge.featureIdForWaypointUuid(waypointUuid)
        return layer.getFeature(fid).attribute("tolerance")

    # The ring is drawn from this attribute; NULL draws none
    for corner in corners:
        assert tolerance(corner.uuid) in (None, NULL)
    assert tolerance(plan.tasks[0].waypoint.uuid) == 10.0

    # A corner added by the map tool gets none either
    doc.startEditing()
    doc.addWaypoint(fence.uuid, "fence", 59.1, 18.0, fieldName="waypoints")
    assert tolerance(fence.waypoints[-1].uuid) in (None, NULL)

    context = MissionContext()
    columns = GeoPoint.schema().fields
    toleranceColumn = [f.name for f in columns].index("tolerance")
    fenceTable = WaypointTableWidget(SmarcStartGeofenceTask, "waypoints", GeoPoint, context)
    pathTable = WaypointTableWidget(MovePathTask, "waypoints", GeoPoint, context)
    assert fenceTable.ui.waypointTable.isColumnHidden(toleranceColumn)
    assert not pathTable.ui.waypointTable.isColumnHidden(toleranceColumn)


def test_a_search_area_is_drawn_as_an_area_and_keeps_its_json(qgis_app, tmp_path: Path):
    corners = [_corner(59.0, 18.0), _corner(59.0, 18.1), _corner(59.1, 18.1)]
    search = SearchAreaTask(description="search", uuid=uuid4(), area=corners)
    plan = MissionPlan(
        name=GroupKind.SEQ.value,
        description="search",
        tasks=[_move_to("before", 58.9), search, _move_to("after", 59.2)],
    )
    doc = MissionDocument(plan, tmp_path / "mission.json")

    assert len(_area_polygons(doc)) == 1
    assert _track_segments(doc) == 1
    params = search.toJson()["params"]
    assert [(p["latitude"], p["longitude"]) for p in params["area"]] == [
        (59.0, 18.0), (59.0, 18.1), (59.1, 18.1)]
    # UUIDs are not saved, so compare the saved form
    assert SearchAreaTask.fromJson(search.toJson()).toJson() == search.toJson()


def test_route_neighbours_skip_area_corners(qgis_app, tmp_path: Path):
    corners = [_corner(59.0, 18.0), _corner(59.0, 18.1), _corner(59.1, 18.1)]
    plan, fence = _fenced_plan(corners)
    before, after = plan.tasks[0].waypoint, plan.tasks[2].waypoint
    doc = MissionDocument(plan, tmp_path / "mission.json")

    assert doc.index.nextRouteWaypointByUuid(before.uuid) is after
    assert doc.index.previousRouteWaypointByUuid(after.uuid) is before
    assert doc.index.nextRouteWaypointByUuid(corners[0].uuid) is None
    assert doc.index.previousRouteWaypointByUuid(corners[1].uuid) is None


def _no_go_flags(doc: MissionDocument) -> dict[str, bool]:
    """The area kind per task description, as the area layer stores it."""
    return {
        doc.index.taskByUuid(UUID(feat.attribute("task-uuid"))).description:
            bool(feat.attribute("no-go"))
        for feat in doc.layerBridge.areas.layer.getFeatures()
    }


def test_each_area_feature_says_whether_it_is_a_no_go_zone(qgis_app, tmp_path: Path):
    def box() -> list[GeoPoint]:
        return [_corner(59.0, 18.0), _corner(59.0, 18.1), _corner(59.1, 18.1)]

    fence = _fence(box())
    zone = SmarcStartGeofenceTask(description="zone", uuid=uuid4(), stay_inside=False,
                                  waypoints=box())
    search = SearchAreaTask(description="search", uuid=uuid4(), area=box())
    plan = MissionPlan(name=GroupKind.SEQ.value, description="areas",
                       tasks=[fence, zone, search])
    doc = MissionDocument(plan, tmp_path / "mission.json")

    assert _no_go_flags(doc) == {"fence": False, "zone": True, "search": False}

    # Unticking StayInside turns the fence into a no-go zone, and undo turns it back
    doc.startEditing()
    stayInside = [f.name for f in SmarcStartGeofenceTask.schema().fields].index("stay_inside")
    doc.setTaskField(fence.uuid, stayInside, False)
    assert _no_go_flags(doc)["fence"] is True
    doc.layerBridge.waypointLayer.undoStack().undo()
    assert _no_go_flags(doc)["fence"] is False


def test_only_no_go_zones_are_drawn_with_diagonal_lines(qgis_app, tmp_path: Path):
    from qgis.core import QgsLinePatternFillSymbolLayer, QgsRuleBasedRenderer

    plan, _ = _fenced_plan([])
    doc = MissionDocument(plan, tmp_path / "mission.json")
    renderer = doc.layerBridge.areas.layer.renderer()
    assert isinstance(renderer, QgsRuleBasedRenderer)

    hatchedRules = {}
    for rule in renderer.rootRule().children():
        layers = rule.symbol().symbolLayers()
        hatched = any(isinstance(layer, QgsLinePatternFillSymbolLayer) for layer in layers)
        hatchedRules[rule.filterExpression()] = hatched
        if hatched:
            # The hatch lines run at 45 degrees
            [hatch] = [layer for layer in layers if isinstance(layer, QgsLinePatternFillSymbolLayer)]
            assert hatch.lineAngle() == 45
    assert hatchedRules == {'NOT "no-go"': False, '"no-go"': True}
