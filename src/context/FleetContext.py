from qgis.PyQt.QtCore import QObject

from .FleetMapManager import FleetMapManager
from .FleetState import FleetState
from .MqttService import MqttService


class FleetContext(QObject):
    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self.mqtt = MqttService(self)
        self.state = FleetState(self.mqtt, self)
        self.mapManager = FleetMapManager(self.state, self)
