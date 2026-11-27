import pytest
import qgis.utils
from qgis.core import QgsProject
from qgis.gui import QgsRubberBand

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QMainWindow

from src.context.FleetMapManager import FleetMapManager
from src.context.FleetState import VehicleState

SAM = "waraps/unit/subsurface/simulation/sam1"
LOLO = "waraps/unit/subsurface/simulation/lolo1"


class _Fleet(QObject):
    vehicleDiscovered = pyqtSignal(str)
    vehicleUpdated = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._states: dict[str, VehicleState] = {}

    def vehicleState(self, topic):
        return self._states.get(topic)

    def move(self, topic, lon, lat):
        if topic not in self._states:
            self._states[topic] = VehicleState()
            self.vehicleDiscovered.emit(topic)
        state = self._states[topic]
        state.longitude, state.latitude, state.heading = 11.0 + lon, lat, 0.0
        self.vehicleUpdated.emit(topic)


@pytest.fixture
def fleet(qgis_app, monkeypatch):
    window = QMainWindow()
    window.show()
    monkeypatch.setattr(qgis.utils.iface, "mainWindow", lambda: window, raising=False)
    fleet = _Fleet()
    manager = FleetMapManager(fleet, None)
    yield fleet, manager
    manager.cleanup()
    # The plugin's unload takes the track lines off the canvas; do the same here.
    scene = qgis.utils.iface.mapCanvas().scene()
    for item in scene.items():
        if isinstance(item, QgsRubberBand):
            scene.removeItem(item)
    window.close()


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


def _visibleBands() -> int:
    """Track lines on the canvas that are drawn."""
    scene = qgis.utils.iface.mapCanvas().scene()
    return sum(1 for i in scene.items() if isinstance(i, QgsRubberBand) and i.isVisible())


def _markersShown(topic: str) -> bool:
    [layer] = QgsProject.instance().mapLayersByName("SMaRCVehiclePositionLayer")
    renderer = layer.renderer()
    return renderer.categories()[renderer.categoryIndexForLabel(topic)].renderState()


def test_unchecking_a_vehicle_hides_its_track_and_checking_brings_it_back(fleet):
    states, manager = fleet
    for lon in range(3):
        states.move(SAM, float(lon), 59.0)

    manager.onShowOnMapChanged(SAM, False)
    assert not _markersShown(SAM)
    assert _visibleBands() == 0

    manager.onShowOnMapChanged(SAM, True)
    assert _markersShown(SAM)
    assert _visibleBands() == 1


def test_an_unchecked_vehicle_that_moves_keeps_its_track_hidden(fleet):
    states, manager = fleet
    states.move(SAM, 0.0, 59.0)
    states.move(LOLO, 0.0, 58.0)

    manager.onShowOnMapChanged(SAM, False)
    states.move(SAM, 1.0, 59.0)
    states.move(LOLO, 1.0, 58.0)

    # Only LOLO's line is drawn.
    assert _visibleBands() == 1
    manager.clearAllVehicleMarkers()
    states.move(SAM, 2.0, 59.0)
    assert _visibleBands() == 0
