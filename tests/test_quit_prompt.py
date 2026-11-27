import qgis.utils
from qgis.core import QgsProject, QgsVectorLayer

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QMainWindow

from src.context.FleetMapManager import FleetMapManager

LAYER = "SMaRCVehiclePositionLayer"


class _Fleet(QObject):
    vehicleDiscovered = pyqtSignal(str)
    vehicleUpdated = pyqtSignal(str)

    def vehicleState(self, topic):
        return None


def _start(monkeypatch):
    window = QMainWindow()
    window.show()
    monkeypatch.setattr(qgis.utils.iface, "mainWindow", lambda: window, raising=False)
    return FleetMapManager(_Fleet(), None), window


def test_adding_the_vehicle_layer_leaves_an_untouched_project_clean(qgis_app, monkeypatch):
    project = QgsProject.instance()
    project.setDirty(False)

    manager, window = _start(monkeypatch)
    try:
        assert not project.isDirty()
        [layer] = project.mapLayersByName(LAYER)
        # QGIS skips its "temporary scratch layers will be lost" warning for this layer.
        assert layer.customProperty("skipMemoryLayersCheck")
    finally:
        manager.cleanup()
        window.close()


def test_an_already_changed_project_stays_changed(qgis_app, monkeypatch):
    project = QgsProject.instance()
    mine = QgsVectorLayer("point?crs=epsg:4326", "my own layer", "memory")
    project.addMapLayer(mine)
    # In the QGIS app the main window marks the project changed on that add.
    project.setDirty(True)

    manager, window = _start(monkeypatch)
    try:
        assert project.isDirty()
    finally:
        manager.cleanup()
        project.removeMapLayer(mine.id())
        window.close()
