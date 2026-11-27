import qgis.utils
from qgis.core import QgsProject
from qgis.gui import QgsRubberBand

SAM = "waraps/unit/subsurface/simulation/sam1"
LOLO = "waraps/unit/subsurface/simulation/lolo1"


def _track(topic):
    [layer] = QgsProject.instance().mapLayersByName("SMaRCVehiclePositionLayer")
    feats = [f for f in layer.getFeatures() if f["vehicle-name"] == topic]
    feats.sort(key=lambda f: f.id())
    return [(f.geometry().asPoint().x() - 11.0, f["is-current"]) for f in feats]


def _bandPoints():
    """Vertices of the one vehicle's track line on the canvas."""
    scene = qgis.utils.iface.mapCanvas().scene()
    [band] = [i for i in scene.items() if isinstance(i, QgsRubberBand)]
    return band.numberOfVertices()


def test_track_keeps_only_the_newest_positions(fleet):
    states, manager = fleet
    manager.setTrackLength(3)
    for lon in range(5):
        states.move(SAM, float(lon), 59.0)

    assert _track(SAM) == [(2.0, False), (3.0, False), (4.0, True)]
    assert _bandPoints() == 3


def test_lowering_the_length_trims_existing_tracks_and_zero_keeps_all(fleet):
    states, manager = fleet
    manager.setTrackLength(0)
    for lon in range(6):
        states.move(SAM, float(lon), 59.0)
    assert len(_track(SAM)) == 6

    manager.setTrackLength(2)

    assert _track(SAM) == [(4.0, False), (5.0, True)]
    assert _bandPoints() == 2


def test_each_vehicle_has_its_own_limit(fleet):
    states, manager = fleet
    manager.setTrackLength(2)
    for lon in range(4):
        states.move(SAM, float(lon), 59.0)
    states.move(LOLO, 10.0, 58.0)

    assert [x for x, _ in _track(SAM)] == [2.0, 3.0]
    assert _track(LOLO) == [(10.0, True)]


def test_track_restarts_cleanly_after_clear(fleet):
    states, manager = fleet
    manager.setTrackLength(2)
    for lon in range(3):
        states.move(SAM, float(lon), 59.0)

    manager.clearAllVehicleMarkers()
    for lon in (7.0, 8.0, 9.0):
        states.move(SAM, lon, 59.0)

    assert _track(SAM) == [(8.0, False), (9.0, True)]
    assert _bandPoints() == 2
