from dataclasses import dataclass, field

from qgis.core import QgsApplication

from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import QColor

from ..domain.waraps import WaraPsExecutingTask
from .MqttService import (
    MqttService,
    VehicleHeartbeatEvent,
    VehicleSensorEvent,
    VehicleTaskStateEvent,
)


@dataclass
class VehicleState:
    latitude  : float | None = None
    longitude : float | None = None
    heading   : float | None = None
    course    : float | None = None
    depth     : float | None = None
    altitude  : float | None = None
    speed     : float | None = None
    roll      : float | None = None
    pitch     : float | None = None
    mode      : str   | None = ""

    executingTasks: list[WaraPsExecutingTask] | None = None

    # Internal use parameters
    mapColor: QColor = field(default_factory =
        lambda: QgsApplication.colorSchemeRegistry().fetchRandomStyleColor()
    )

class FleetState(QObject):
    vehicleDiscovered = pyqtSignal(str)
    vehicleExpired = pyqtSignal(str)
    vehicleUpdated = pyqtSignal(str)
    vehicleHeartbeat = pyqtSignal(str)
    
    _vehicles: dict[str, VehicleState]

    def __init__(self, mqttService: MqttService, parent: QObject | None):
        super().__init__(parent)

        self._vehicles = {}

        mqttService.vehicleHeartbeat.connect(self.onVehicleHeartbeat)
        mqttService.vehicleSensorEvent.connect(self.onVehicleSensorEvent)
        mqttService.vehicleTaskStateEvent.connect(self.onVehicleTaskStateEvent)

    def vehicleState(self, vehicleTopic: str) -> VehicleState | None:
        return self._vehicles.get(vehicleTopic)

    def _ensureVehicle(self, vehicleTopic: str):
        if vehicleTopic not in self._vehicles:
            print(f'FleetState._ensureVehicle: vehicle discovered: {vehicleTopic}')

            self._vehicles[vehicleTopic] = VehicleState()
            self.vehicleDiscovered.emit(vehicleTopic)

    @pyqtSlot(VehicleHeartbeatEvent)
    def onVehicleHeartbeat(self, event: VehicleHeartbeatEvent):
        self._ensureVehicle(event.vehicleTopic)

        state = self._vehicles[event.vehicleTopic]
        state.mode = event.mode
      
        # TODO: propagate vehicle heartbeat in some way?
        self.vehicleHeartbeat.emit(event.vehicleTopic)
        
    @pyqtSlot(VehicleSensorEvent)
    def onVehicleSensorEvent(self, event: VehicleSensorEvent):
        self._ensureVehicle(event.vehicleTopic)

        state = self._vehicles[event.vehicleTopic]
        if event.position is not None:
            state.latitude = event.position.latitude
            state.longitude = event.position.longitude
            state.altitude = event.position.altitude
        if event.heading is not None:
            state.heading = event.heading
        if event.course is not None:
            state.course = event.course
        if event.depth is not None:
            state.depth = event.depth
        if event.speed is not None:
            state.speed = event.speed
        if event.roll is not None:
            state.roll = event.roll
        if event.pitch is not None:
            state.pitch = event.pitch

        self.vehicleUpdated.emit(event.vehicleTopic)

    def onVehicleTaskStateEvent(self, event: VehicleTaskStateEvent):
        self._ensureVehicle(event.vehicleTopic)

        state = self._vehicles[event.vehicleTopic]

        if event.tasksExecuting != state.executingTasks:
            state.executingTasks = event.tasksExecuting
            self.vehicleUpdated.emit(event.vehicleTopic)
