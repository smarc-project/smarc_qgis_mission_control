"""Headless QGIS for the plugin tests.

Run from the plugin root:

    QT_QPA_PLATFORM=offscreen python3 -m pytest
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import pytest
from qgis.core import QgsApplication
from qgis.gui import QgsMapCanvas, QgsRubberBand
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtGui import QFont, QFontDatabase
from qgis.PyQt.QtWidgets import QMainWindow


class _Iface:
    def __init__(self, canvas: QgsMapCanvas):
        self._canvas = canvas

    def mapCanvas(self):
        return self._canvas

    def setActiveLayer(self, layer) -> bool:
        return True


# Plugin modules bind `from qgis.utils import iface` at import time, which is
# during test collection. The canvas has to exist before that import.
# QgsApplication finds its prefix from the interpreter, or from QGIS_PREFIX_PATH.
# initQgis writes symbology-style.db into the profile. Keep that out of the checkout.
_PROFILE = tempfile.mkdtemp(prefix="qgis-test-profile-")
atexit.register(shutil.rmtree, _PROFILE, True)
_APP = QgsApplication([], False, _PROFILE)
_APP.initQgis()
# A bare QgsApplication has no UI font, and Qt then picks Noto Color Emoji.
# That face's metrics shove Latin text into the top frame of a line edit.
_families = set(QFontDatabase().families())
for _family in ("Ubuntu", "Cantarell", "DejaVu Sans", "Liberation Sans", "Noto Sans"):
    if _family in _families:
        _APP.setFont(QFont(_family, 10))
        break
_CANVAS = QgsMapCanvas()
import qgis.utils
qgis.utils.iface = _Iface(_CANVAS)


@pytest.fixture(scope="session")
def qgis_app():
    yield _APP


# After the iface above: FleetMapManager binds it at import.
from src.context.FleetMapManager import FleetMapManager
from src.context.FleetState import VehicleState


class _Fleet(QObject):
    """FleetState's signals and states, moved by hand instead of by MQTT."""
    vehicleDiscovered = pyqtSignal(str)
    vehicleUpdated = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._states: dict[str, VehicleState] = {}

    def vehicleState(self, topic: str) -> VehicleState | None:
        return self._states.get(topic)

    def move(self, topic: str, lon: float, lat: float, heading: float = 0.0) -> None:
        """Put `topic` at longitude 11 + `lon`, discovering it on its first move."""
        if topic not in self._states:
            self._states[topic] = VehicleState()
            self.vehicleDiscovered.emit(topic)
        state = self._states[topic]
        state.longitude, state.latitude, state.heading = 11.0 + lon, lat, heading
        self.vehicleUpdated.emit(topic)


@pytest.fixture
def fleet(qgis_app, monkeypatch):
    """A FleetMapManager on the test canvas, fed by a hand-moved fleet."""
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
