import json
from types import SimpleNamespace

import pytest
from qgis.core import Qgis, QgsApplication, QgsDistanceArea, QgsPointXY, QgsProject

from src.context.FleetMapManager import FleetMapManager
from src.context.MapObjectLayers import MapObjectLayers
from src.context.MqttService import MqttService
from src.domain.mapobjects import MapObjectShape, parseMapObject

BASE_TOPIC = "waraps/general/generic/real/c2/target/positions"


def _payload(**fields) -> bytes:
    return json.dumps(fields).encode()


LINE = _payload(
    name="transit-R",
    type="polyline",
    line=[[58.25, 11.45], [58.26, 11.46]],
    color="#00AA00",
)
POLYGON = _payload(
    name="survey-A",
    type="area",
    area=[[58.25, 11.45], [58.25, 11.46], [58.26, 11.46]],
)
CIRCLE = _payload(name="dive-A", type="circle", lat=58.25, lon=11.45, radius=50)
POINT = _payload(name="buoy-P", type="point", lat=58.25, lon=11.45)


@pytest.fixture
def mapObjects(qgis_app):
    layers = MapObjectLayers(None)
    yield layers
    layers.cleanup()


def _drawn(layerName: str) -> dict[str, object]:
    [layer] = QgsProject.instance().mapLayersByName(layerName)
    return {f["name"]: f for f in layer.getFeatures()}


@pytest.fixture
def warnings(qgis_app):
    """Messages this plugin logged as warnings."""
    logged: list[str] = []

    def keep(message: str, tag: str, level: Qgis.MessageLevel) -> None:
        if level == Qgis.MessageLevel.Warning:
            logged.append(message)

    log = QgsApplication.messageLog()
    log.messageReceived.connect(keep)
    yield logged
    log.messageReceived.disconnect(keep)


def test_each_shape_is_read():
    line = parseMapObject("transit-R", LINE)
    assert line.shape == MapObjectShape.PATH
    assert line.latLons == [(58.25, 11.45), (58.26, 11.46)]
    assert line.color == "#00AA00"
    assert line.duration == 0

    polygon = parseMapObject("survey-A", POLYGON)
    assert polygon.shape == MapObjectShape.POLYGON
    assert len(polygon.latLons) == 3

    circle = parseMapObject("dive-A", CIRCLE)
    assert circle.shape == MapObjectShape.CIRCLE
    assert circle.latLons == [(58.25, 11.45)]
    assert circle.radius == 50

    point = parseMapObject("buoy-P", POINT)
    assert point.shape == MapObjectShape.POINT


def test_each_shape_is_drawn_on_its_layer(mapObjects):
    for name, payload in (
        ("transit-R", LINE),
        ("survey-A", POLYGON),
        ("dive-A", CIRCLE),
        ("buoy-P", POINT),
    ):
        mapObjects.onMapObjectMessage(name, payload)

    assert set(_drawn("Map paths")) == {"transit-R"}
    assert set(_drawn("Map areas")) == {"survey-A", "dive-A"}
    assert set(_drawn("Map points")) == {"buoy-P"}
    assert _drawn("Map paths")["transit-R"]["color"] == "#00AA00"

    # The circle is drawn 50 m out from its centre, all the way round.
    ring = _drawn("Map areas")["dive-A"].geometry().asPolygon()[0]
    ellipsoid = QgsDistanceArea()
    ellipsoid.setEllipsoid("WGS84")
    centre = QgsPointXY(11.45, 58.25)
    for corner in ring:
        assert ellipsoid.measureLine(centre, corner) == pytest.approx(50, abs=0.01)


def test_same_name_replaces_and_new_name_adds(mapObjects):
    mapObjects.onMapObjectMessage("survey-A", POLYGON)
    mapObjects.onMapObjectMessage("survey-A", _payload(
        name="survey-A",
        type="circle",
        lat=58.3,
        lon=11.5,
        radius=20,
    ))
    mapObjects.onMapObjectMessage("dive-A", CIRCLE)

    areas = _drawn("Map areas")
    assert set(areas) == {"survey-A", "dive-A"}
    assert areas["survey-A"].geometry().centroid().asPoint().y() == pytest.approx(58.3)


def test_duration_runs_out(mapObjects):
    shortLived = parseMapObject("buoy-P", _payload(
        name="buoy-P",
        type="point",
        lat=58.25,
        lon=11.45,
        duration=5,
    ))
    forever = parseMapObject("transit-R", LINE)
    mapObjects.showMapObject(shortLived, receivedAt=100.0)
    mapObjects.showMapObject(forever, receivedAt=100.0)

    mapObjects.removeExpired(now=104.9)
    assert set(_drawn("Map points")) == {"buoy-P"}

    mapObjects.removeExpired(now=105.0)
    assert _drawn("Map points") == {}
    mapObjects.removeExpired(now=1e9)
    assert set(_drawn("Map paths")) == {"transit-R"}


def test_empty_message_clears_one_and_clear_removes_all(mapObjects):
    mapObjects.onMapObjectMessage("survey-A", POLYGON)
    mapObjects.onMapObjectMessage("dive-A", CIRCLE)
    mapObjects.onMapObjectMessage("transit-R", LINE)

    mapObjects.onMapObjectMessage("dive-A", b"")
    assert set(_drawn("Map areas")) == {"survey-A"}

    mapObjects.clearMapObjects()
    assert _drawn("Map areas") == {}
    assert _drawn("Map paths") == {}


@pytest.mark.parametrize("name, payload", [
    ("junk-A", b"{not json"),
    ("junk-A", _payload(type="hexagon", area=[[0, 0], [0, 1], [1, 1]])),
    ("junk-A", _payload(type="area", area=[[0, 0], [0, 1]])),
    ("junk-A", _payload(type="circle", lat=58.25, lon=11.45)),
    ("junk-A", _payload(type="circle", lat=58.25, lon=11.45, radius=-1)),
    ("junk-R", _payload(type="polyline", line=[[95, 0], [0, 0]])),
    ("junk-P", _payload(type="area", area=[[0, 0], [0, 1], [1, 1]])),
    ("junk-P", _payload(type="point", lat=58.25, lon=11.45, color="red")),
    ("junk-P", _payload(type="point", lat=58.25, lon=11.45, duration=-1)),
    ("junk-P", b'{"type": "point", "lat": 58.25, "lon": 11.45, "duration": NaN}'),
    ("junk-P", b'{"type": "point", "lat": NaN, "lon": 11.45}'),
    ("junk-A", b'{"type": "circle", "lat": 58.25, "lon": 11.45, "radius": Infinity}'),
    ("junk-A", b'{"type": "circle", "lat": 58.25, "lon": 11.45, "radius": NaN}'),
])
def test_bad_message_is_ignored_with_a_warning(mapObjects, warnings, name, payload):
    mapObjects.onMapObjectMessage("buoy-P", POINT)
    mapObjects.onMapObjectMessage(name, payload)

    assert set(_drawn("Map points")) == {"buoy-P"}
    assert set(_drawn("Map areas")) == set()
    assert len(warnings) == 1
    assert name in warnings[0]


def test_map_object_topics_reach_the_layers(qgis_app):
    mqtt = MqttService(None)
    heard: list[tuple[str, bytes]] = []
    mqtt.mapObjectMessage.connect(lambda name, payload: heard.append((name, payload)))

    for topic, payload in (
        (f"{BASE_TOPIC}/dive-A", CIRCLE),
        (f"{BASE_TOPIC}/dive-A", b""),
        # Not map objects: a vehicle's sensor and a name without a shape suffix.
        ("waraps/unit/subsurface/real/sam1/sensor/heading", b"12.5"),
        (f"{BASE_TOPIC}/dive", CIRCLE),
    ):
        mqtt.onMqttMessage(None, None, SimpleNamespace(topic=topic, payload=payload))

    assert heard == [("dive-A", CIRCLE), ("dive-A", b"")]


def test_name_without_a_shape_suffix_is_a_value_error():
    with pytest.raises(ValueError, match="cannot be sent"):
        parseMapObject("buoy", POINT)


def _group():
    return QgsProject.instance().layerTreeRoot().findGroup(MapObjectLayers.GROUP_NAME)


def test_user_removed_layer_is_made_again(mapObjects):
    mapObjects.onMapObjectMessage("buoy-P", POINT)
    mapObjects.onMapObjectMessage("survey-A", POLYGON)
    [areas] = QgsProject.instance().mapLayersByName("Map areas")
    QgsProject.instance().removeMapLayer(areas.id())

    # Replacing and clearing an object on the removed layer must not raise.
    mapObjects.onMapObjectMessage("survey-A", b"")
    mapObjects.onMapObjectMessage("dive-A", CIRCLE)

    assert set(_drawn("Map areas")) == {"dive-A"}
    assert len(QgsProject.instance().mapLayersByName("Map points")) == 1
    assert len(_group().findLayers()) == 3


def test_new_project_and_removed_group_are_survived(mapObjects):
    mapObjects.onMapObjectMessage("buoy-P", POINT)
    QgsProject.instance().clear()
    mapObjects.onMapObjectMessage("transit-R", LINE)
    assert set(_drawn("Map paths")) == {"transit-R"}

    root = QgsProject.instance().layerTreeRoot()
    root.removeChildNode(_group())
    mapObjects.onMapObjectMessage("buoy-P", POINT)
    assert set(_drawn("Map points")) == {"buoy-P"}
    assert _drawn("Map paths") == {}


def test_unload_after_user_removed_one_layer_leaves_nothing(qgis_app):
    mapObjects = MapObjectLayers(None)
    mapObjects.onMapObjectMessage("buoy-P", POINT)
    [points] = QgsProject.instance().mapLayersByName("Map points")
    QgsProject.instance().removeMapLayer(points.id())

    mapObjects.cleanup()

    assert _group() is None
    for name in ("Map points", "Map paths", "Map areas"):
        assert QgsProject.instance().mapLayersByName(name) == []


def test_group_sits_just_below_the_vehicles(qgis_app):
    from qgis.core import QgsVectorLayer
    QgsProject.instance().clear()
    root = QgsProject.instance().layerTreeRoot()
    root.insertGroup(0, "SMaRCMissions")
    vehicles = QgsVectorLayer("point?crs=epsg:4326", FleetMapManager.LAYER_NAME, "memory")
    QgsProject.instance().addMapLayer(vehicles, False)
    root.insertLayer(0, vehicles)

    mapObjects = MapObjectLayers(None)
    mapObjects.onMapObjectMessage("buoy-P", POINT)
    try:
        assert [node.name() for node in root.children()] == [
            FleetMapManager.LAYER_NAME,
            MapObjectLayers.GROUP_NAME,
            "SMaRCMissions",
        ]
    finally:
        mapObjects.cleanup()
        QgsProject.instance().clear()
