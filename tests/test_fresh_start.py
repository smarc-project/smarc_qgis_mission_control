import qgis.utils
from qgis.core import QgsProject

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QMainWindow

from src.context.FleetMapManager import FleetMapManager


class _Fleet(QObject):
    vehicleDiscovered = pyqtSignal(str)
    vehicleUpdated = pyqtSignal(str)

    def vehicleState(self, topic):
        return None


class _Startup(QObject):
    initializationCompleted = pyqtSignal()


def test_loads_before_qgis_has_finished_starting(qgis_app, monkeypatch):
    # On a normal start the plugin loads while the main window is still hidden,
    # and the vehicle layer only appears once QGIS reports it has finished.
    hiddenWindow = QMainWindow()
    startup = _Startup()
    monkeypatch.setattr(qgis.utils.iface, "mainWindow", lambda: hiddenWindow, raising=False)
    monkeypatch.setattr(qgis.utils.iface, "initializationCompleted",
                        startup.initializationCompleted, raising=False)

    manager = FleetMapManager(_Fleet(), None)
    try:
        assert not QgsProject.instance().mapLayersByName("SMaRCVehiclePositionLayer")

        startup.initializationCompleted.emit()

        [layer] = QgsProject.instance().mapLayersByName("SMaRCVehiclePositionLayer")
        assert "Heading" in layer.mapTipTemplate()
    finally:
        manager.cleanup()
