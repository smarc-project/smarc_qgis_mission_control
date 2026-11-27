import time
from collections.abc import Callable
from dataclasses import dataclass, field

from qgis.core import QgsApplication

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot
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
    # When any message from the vehicle last arrived, on FleetState's clock.
    lastHeard: float = 0.0
    # False while the vehicle has been silent longer than the inactive timeout.
    active: bool = True

# Seconds without any message before a vehicle counts as inactive.
DEFAULT_INACTIVE_TIMEOUT = 60
# How often silent vehicles are looked for.
INACTIVE_CHECK_INTERVAL = 1000 # ms


class FleetState(QObject):
    vehicleDiscovered = pyqtSignal(str)
    # Heard nothing for the inactive timeout.
    vehicleExpired = pyqtSignal(str)
    # Heard again after vehicleExpired.
    vehicleReturned = pyqtSignal(str)
    vehicleUpdated = pyqtSignal(str)
    vehicleHeartbeat = pyqtSignal(str)
    
    _vehicles: dict[str, VehicleState]

    def __init__(self, mqttService: MqttService, parent: QObject | None,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__(parent)

        self._vehicles = {}
        self._clock = clock
        self._inactiveTimeout = DEFAULT_INACTIVE_TIMEOUT

        self._inactiveTimer = QTimer(self)
        self._inactiveTimer.setInterval(INACTIVE_CHECK_INTERVAL)
        self._inactiveTimer.timeout.connect(self._updateActivity)
        self._inactiveTimer.start()

        mqttService.vehicleHeartbeat.connect(self.onVehicleHeartbeat)
        mqttService.vehicleSensorEvent.connect(self.onVehicleSensorEvent)
        mqttService.vehicleTaskStateEvent.connect(self.onVehicleTaskStateEvent)
        mqttService.vehicleHeard.connect(self.onVehicleHeard)

    def vehicleState(self, vehicleTopic: str) -> VehicleState | None:
        return self._vehicles.get(vehicleTopic)

    def isActive(self, vehicleTopic: str) -> bool:
        state = self._vehicles.get(vehicleTopic)
        return state is None or state.active

    def setInactiveTimeout(self, seconds: float) -> None:
        """Expire vehicles silent for `seconds`; 0 never expires them."""
        self._inactiveTimeout = max(0.0, float(seconds))
        self._updateActivity()

    @pyqtSlot()
    def _updateActivity(self) -> None:
        now = self._clock()
        for vehicleTopic, state in self._vehicles.items():
            active = (self._inactiveTimeout == 0
                      or now - state.lastHeard < self._inactiveTimeout)
            if active == state.active:
                continue
            state.active = active
            if active:
                self.vehicleReturned.emit(vehicleTopic)
            else:
                self.vehicleExpired.emit(vehicleTopic)

    def _ensureVehicle(self, vehicleTopic: str):
        if vehicleTopic not in self._vehicles:
            print(f'FleetState._ensureVehicle: vehicle discovered: {vehicleTopic}')

            self._vehicles[vehicleTopic] = VehicleState(lastHeard=self._clock())
            self.vehicleDiscovered.emit(vehicleTopic)
            return
        self.onVehicleHeard(vehicleTopic)

    @pyqtSlot(str)
    def onVehicleHeard(self, vehicleTopic: str):
        """Any message counts, so a vehicle whose sensors are relayed stays active."""
        state = self._vehicles.get(vehicleTopic)
        if state is None:
            return
        state.lastHeard = self._clock()
        if not state.active:
            state.active = True
            self.vehicleReturned.emit(vehicleTopic)

    @pyqtSlot(VehicleHeartbeatEvent)
    def onVehicleHeartbeat(self, event: VehicleHeartbeatEvent):
        self._ensureVehicle(event.vehicleTopic)

        state = self._vehicles[event.vehicleTopic]
        if state.mode != event.mode:
            state.mode = event.mode
            # The cards show the mode, and they redraw on vehicleUpdated.
            self.vehicleUpdated.emit(event.vehicleTopic)

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
